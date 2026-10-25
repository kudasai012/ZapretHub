/**
 * Компонент zapret-discord-youtube (winws.exe).
 *
 * Ключевая идея: стратегии из .bat-файлов не запускаются через cmd.exe, а
 * разбираются и преобразуются в прямой запуск bin/winws.exe дочерним
 * процессом нашего приложения. Так мы:
 *   * знаем PID и можем корректно остановить компонент;
 *   * не зависим от консольных окон и служебных проверок service.bat;
 *   * управляем всем из одного интерфейса.
 */
import fs from 'node:fs'
import path from 'node:path'
import type { ProcessStatus, ZapretSettings, ZapretState } from '@shared/contract'
import { findFileDeep, resolveWinws, resolveZapretBinDir, resolveZapretDir } from './paths'
import { configStore } from './config'
import { logger } from './logger'
import { ManagedProcess, STATUS_STOPPED } from './procman'
import { enableTcpTimestamps, isAdmin, killForeignProcesses, pidsByName, queryService, removeService } from './win32'

export const SERVICE_NAME = 'zapret'

export const IPSET_PLACEHOLDER = '203.0.113.113/32'
export const IPSET_URL =
  'https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/refs/heads/main/.service/ipset-service.txt'

/** Пользовательские списки, которые создаются сами, если их нет. */
export const USER_LISTS: Record<string, string> = {
  'list-general-user.txt': '# Never leave this file empty\ndomain.example.abc\n',
  'list-exclude-user.txt': 'domain.example.abc\n',
  'ipset-exclude-user.txt': '203.0.113.113/32\n'
}

/** Порядок списков в интерфейсе: основной список и его пользовательская часть сверху. */
const LIST_ORDER = ['list-general.txt', 'list-general-user.txt']

export class ZapretError extends Error {}

/** Естественная сортировка: general (ALT2) идёт раньше general (ALT10). */
export function naturalKey(name: string): (string | number)[] {
  return name.split(/(\d+)/).map((part) => (/^\d+$/.test(part) ? Number(part) : part.toLowerCase()))
}

function listSortKey(name: string): [number, number, string] {
  const index = LIST_ORDER.indexOf(name)
  return index === -1 ? [1, 0, name] : [0, index, name]
}

/** Разбор командной строки Windows: кавычки обрамляют токен и удаляются. */
export function tokenizeWindows(line: string): string[] {
  const tokens: string[] = []
  let current = ''
  let inQuotes = false
  let hasToken = false
  for (const ch of line) {
    if (ch === '"') {
      inQuotes = !inQuotes
      hasToken = true
      continue
    }
    if (!inQuotes && (ch === ' ' || ch === '\t')) {
      if (hasToken) {
        tokens.push(current)
        current = ''
        hasToken = false
      }
      continue
    }
    current += ch
    hasToken = true
  }
  if (hasToken) tokens.push(current)
  return tokens
}

/** Известные причины, по которым winws.exe умирает сразу после старта. */
const WINWS_KNOWN_FAILURES: [string, string][] = [
  [
    'A copy of winws is already running with the same filter',
    'уже запущена другая копия winws с тем же фильтром — выключите zapret (или снимите службу) и повторите'
  ],
  ['error opening filter', 'фильтр WinDivert занят предыдущей копией winws — подождите пару секунд и повторите'],
  ['could not read', 'winws не смог прочитать свои файлы — переустановите компонент zapret']
]

/**
 * Причины, после которых имеет смысл попробовать ещё раз.
 *
 * «Фильтр WinDivert занят предыдущей копией» — не поломка, а тормоза: ядро
 * удаляет фильтр не в тот же миг, когда убит процесс winws. Раньше программа
 * показывала эту ошибку и сдавалась, и человеку оставалось только перезагружать
 * компьютер. Теперь такие отзывы повторяются с паузой.
 */
const BUSY_FILTER = /фильтр WinDivert занят|другая копия winws|error opening filter|same filter/i

/** Сколько ждём, пока ядро отпустит фильтр убитой копии winws. */
const WINDIVERT_SETTLE_MS = 1200

/** Сколько ждём после убийства чужого winws.exe. */
const FOREIGN_KILL_SETTLE_MS = 900

/** Сколько раз пробуем запустить winws, если фильтр ещё занят. */
const START_ATTEMPTS = 4

/** Человеческая причина провала по тому, что написал сам winws. */
export function winwsFailureReason(output: string[]): string {
  for (const line of output) {
    for (const [needle, reason] of WINWS_KNOWN_FAILURES) {
      if (line.includes(needle)) return reason
    }
  }
  return ''
}

export const PROBE_SETTLE_SECONDS = 1500
export const START_CONFIRM_SECONDS = 800

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

export class ZapretComponent {
  private proc: ManagedProcess | null = null
  private reason = ''

  // ------------------------------------------------------------ пути

  /** Где лежит пакет: по правилам или там, где его нашли. */
  get dir(): string {
    return resolveZapretDir()
  }

  get binDir(): string {
    return resolveZapretBinDir()
  }

  get listsDir(): string {
    return path.join(this.dir, 'lists')
  }

  get utilsDir(): string {
    return path.join(this.dir, 'utils')
  }

  /**
   * Путь к winws.exe. Спрашиваем у paths каждый раз: пакет могли доставить
   * в папку с другим именем, и тогда жёсткий путь врал бы «не установлен».
   */
  get winws(): string {
    return resolveWinws() ?? path.join(this.binDir, 'winws.exe')
  }

  /**
   * Что именно лежит на диске: папка пакета, service.bat, winws.exe.
   *
   * Нужно и для вердикта «установлен», и для журнала: когда человек говорит
   * «компонент установлен, а программа пишет, что нет», по этой строке видно,
   * какой из файлов мы не нашли и в какой папке искали.
   */
  installFacts(): { dir: string; service: boolean; winws: string | null } {
    return {
      dir: this.dir,
      service: fs.existsSync(path.join(this.dir, 'service.bat')),
      winws: resolveWinws()
    }
  }

  /**
   * Компонент считается установленным, когда на диске есть и service.bat, и
   * winws.exe. Раньше оба файла искались по одному жёсткому пути, и пакет,
   * лежавший под другим именем папки, объявлялся не установленным.
   *
   * Работает — значит установлен, и спорить с этим нечего: winws.exe запущен,
   * пакет найден. Это правило закрывает главный случай, когда программа врала
   * «не установлен» живому обходу: «Компонент не установлен» — обвинение, и
   * показывать его работающему компоненту нельзя.
   */
  installed(): boolean {
    if (this.isRunning()) return true
    const facts = this.installFacts()
    if (facts.service && facts.winws !== null) return true
    // service.bat лежит не в корне пакета, а во вложенной папке: так выходит,
    // когда архив распакован целиком, вместе с папкой-контейнером. Ищем на
    // два уровня вглубь — иначе такой пакет объявлялся не установленным,
    // хотя на диске он был.
    return findFileDeep(this.dir, 'service.bat', 2) !== null && facts.winws !== null
  }

  /** LOCAL_VERSION из service.bat. */
  version(): string | null {
    try {
      const text = fs.readFileSync(path.join(this.dir, 'service.bat'), 'utf8')
      const match = /set\s+"LOCAL_VERSION=([^"]+)"/i.exec(text) ?? /LOCAL_VERSION=([\d.]+)/i.exec(text)
      return match ? match[1].trim() : null
    } catch {
      return null
    }
  }

  versionDisplay(): string {
    return this.version() ?? '—'
  }

  // ------------------------------------------------------------ стратегии

  strategies(): string[] {
    if (!fs.existsSync(this.dir)) return []
    const files = fs
      .readdirSync(this.dir)
      .filter((name) => name.toLowerCase().endsWith('.bat') && !name.toLowerCase().startsWith('service'))
    return files.sort((a, b) => (naturalKey(a).join('\u0000') < naturalKey(b).join('\u0000') ? -1 : 1))
  }

  private readBat(file: string): string[] {
    const raw = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')
    return raw.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')
  }

  /** Склеивает строки, продолженные символом ^, в одну команду. */
  private static joinContinuations(lines: string[]): string[] {
    const joined: string[] = []
    let buffer = ''
    for (const line of lines) {
      const stripped = line.replace(/\s+$/, '')
      if (stripped.endsWith('^')) {
        buffer += stripped.slice(0, -1) + ' '
        continue
      }
      buffer += stripped
      joined.push(buffer)
      buffer = ''
    }
    if (buffer) joined.push(buffer)
    return joined
  }

  /** Переменные из set-строк пакета; %~dp0 разворачивается в папку компонента. */
  private batVariables(lines: string[]): Record<string, string> {
    const variables: Record<string, string> = {}
    for (const line of lines) {
      const match = /^\s*set\s+"?([A-Za-z_][A-Za-z0-9_]*)=(.*?)"?\s*$/i.exec(line)
      if (!match) continue
      const name = match[1].toUpperCase()
      let value = match[2].trim().replace(/%~dp0/gi, `${this.dir}${path.sep}`)
      if (path.sep !== '\\') value = value.replace(/\\/g, path.sep)
      variables[name] = value
    }
    variables.BIN = `${this.binDir}${path.sep}`
    variables.LISTS = `${this.listsDir}${path.sep}`
    return variables
  }

  private static expand(text: string, variables: Record<string, string>): string {
    return text.replace(/%([A-Za-z_][A-Za-z0-9_]*)%/g, (whole, name: string) => {
      const upper = name.toUpperCase()
      return upper in variables ? variables[upper] : whole
    })
  }

  /** Значения %GameFilterTCP% / %GameFilterUDP% по логике service.bat. */
  gameFilterValues(): Record<string, string> {
    const z = configStore.get().zapret
    const disabled = '12'
    switch (z.gameMode) {
      case 'all':
        return { GAMEFILTERTCP: z.gameTcpRange, GAMEFILTERUDP: z.gameUdpRange }
      case 'tcp':
        return { GAMEFILTERTCP: z.gameTcpRange, GAMEFILTERUDP: disabled }
      case 'udp':
        return { GAMEFILTERTCP: disabled, GAMEFILTERUDP: z.gameUdpRange }
      default:
        return { GAMEFILTERTCP: disabled, GAMEFILTERUDP: disabled }
    }
  }

  /** Возвращает (путь к winws.exe, аргументы) для выбранной стратегии. */
  parseStrategy(name?: string): { exe: string; args: string[] } {
    const strategy = name ?? configStore.get().zapret.strategy
    const batPath = path.join(this.dir, strategy)
    if (!fs.existsSync(batPath)) throw new ZapretError(`Файл стратегии не найден: ${strategy}`)

    const lines = this.readBat(batPath)
    const variables = this.batVariables(lines)
    Object.assign(variables, this.gameFilterValues())
    const commands = ZapretComponent.joinContinuations(lines)

    for (const command of commands) {
      const stripped = command.trim()
      if (!stripped.toLowerCase().startsWith('start')) continue
      const expanded = ZapretComponent.expand(stripped, variables)
      const tokens = tokenizeWindows(expanded)
      const exeIndex = tokens.findIndex((token) => token.toLowerCase().endsWith('winws.exe'))
      if (exeIndex === -1) continue
      const exe = path.isAbsolute(tokens[exeIndex])
        ? tokens[exeIndex]
        : path.resolve(this.binDir, tokens[exeIndex])
      const args = tokens.slice(exeIndex + 1).filter(Boolean)
      return { exe, args }
    }

    throw new ZapretError(
      `Не удалось разобрать стратегию ${strategy}: команда запуска winws.exe не найдена`
    )
  }

  /** Командная строка для показа пользователю. */
  commandLineDisplay(name?: string): string {
    try {
      const { exe, args } = this.parseStrategy(name)
      const parts = [`"${exe}"`, ...args.map((arg) => (arg.includes(' ') || arg.includes('\t') ? `"${arg}"` : arg))]
      return parts.join(' ')
    } catch (error) {
      return `# ${error instanceof Error ? error.message : String(error)}`
    }
  }

  // ------------------------------------------------------------ game filter

  gameFilterFile(): string {
    return path.join(this.utilsDir, 'game_filter.enabled')
  }

  /** Текущее состояние из файла компонента — источник истины на диске. */
  gameFilterState(): { mode: string; tcp: string; udp: string } {
    const state = { mode: 'disabled', tcp: '1024-65535', udp: '1024-65535' }
    if (!fs.existsSync(this.gameFilterFile())) return state
    try {
      for (const raw of fs.readFileSync(this.gameFilterFile(), 'utf8').split(/\r?\n/)) {
        const line = raw.trim()
        if (!line) continue
        if (!line.includes('=')) {
          if (['all', 'tcp', 'udp'].includes(line.toLowerCase())) state.mode = line.toLowerCase()
          continue
        }
        const [key, value] = line.split('=', 2)
        const k = key.trim().toLowerCase()
        const v = value.trim()
        if (k === 'mode' && ['all', 'tcp', 'udp', 'disabled'].includes(v.toLowerCase())) state.mode = v.toLowerCase()
        else if (k === 'tcp' && v) state.tcp = v
        else if (k === 'udp' && v) state.udp = v
      }
    } catch {
      /* читаем что смогли */
    }
    return state
  }

  /** Записывает состояние Game Filter из конфига в файл компонента. */
  applyGameFilter(): void {
    const z = configStore.get().zapret
    if (z.gameMode === 'disabled') {
      try {
        fs.rmSync(this.gameFilterFile(), { force: true })
      } catch {
        /* файла и так нет */
      }
      return
    }
    try {
      fs.mkdirSync(this.utilsDir, { recursive: true })
      fs.writeFileSync(
        this.gameFilterFile(),
        `mode=${z.gameMode}\ntcp=${z.gameTcpRange}\nudp=${z.gameUdpRange}\n`,
        'utf8'
      )
    } catch (error) {
      throw new ZapretError(
        `Не удалось записать game_filter.enabled: ${error instanceof Error ? error.message : error}`
      )
    }
  }

  // ------------------------------------------------------------ ipset

  ipsetFile(): string {
    return path.join(this.listsDir, 'ipset-all.txt')
  }

  /** Состояние ipset-списка на диске. */
  ipsetState(): 'loaded' | 'none' | 'any' {
    const file = this.ipsetFile()
    if (!fs.existsSync(file)) return 'any'
    try {
      const lines = fs
        .readFileSync(file, 'utf8')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
      if (lines.length === 0) return 'any'
      if (lines.length === 1 && lines[0] === IPSET_PLACEHOLDER) return 'none'
      return 'loaded'
    } catch {
      return 'any'
    }
  }

  applyIpsetMode(mode?: string): void {
    const target = mode ?? configStore.get().zapret.ipsetMode
    const file = this.ipsetFile()
    const backup = `${file}.backup`
    try {
      fs.mkdirSync(this.listsDir, { recursive: true })
      const current = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : ''
      if (target === 'none') {
        const stripped = current
          .split(/\r?\n/)
          .filter((line) => line.trim() && line.trim() !== IPSET_PLACEHOLDER)
          .join('\n')
        if (stripped.trim() && !fs.existsSync(backup)) fs.writeFileSync(backup, current, 'utf8')
        fs.writeFileSync(file, `${IPSET_PLACEHOLDER}\n`, 'utf8')
      } else if (target === 'any') {
        if (current.trim() && !fs.existsSync(backup)) fs.writeFileSync(backup, current, 'utf8')
        fs.writeFileSync(file, '', 'utf8')
      } else {
        if (fs.existsSync(backup)) fs.writeFileSync(file, fs.readFileSync(backup, 'utf8'), 'utf8')
        else if (!fs.existsSync(file)) fs.writeFileSync(file, '', 'utf8')
      }
    } catch (error) {
      throw new ZapretError(
        `Не удалось применить IPSet-режим: ${error instanceof Error ? error.message : error}`
      )
    }
    configStore.get().zapret.ipsetMode = target as ZapretSettings['ipsetMode']
  }

  // ------------------------------------------------------------ списки

  ensureUserLists(): void {
    try {
      fs.mkdirSync(this.listsDir, { recursive: true })
      for (const [name, content] of Object.entries(USER_LISTS)) {
        const file = path.join(this.listsDir, name)
        if (!fs.existsSync(file)) fs.writeFileSync(file, content, 'utf8')
      }
    } catch {
      /* списки создадутся при первой записи */
    }
  }

  /** Все .txt-списки из lists/ — общие и пользовательские. */
  listFiles(): string[] {
    let names: string[] = []
    try {
      names = fs
        .readdirSync(this.listsDir)
        .filter((name) => name.toLowerCase().endsWith('.txt'))
    } catch {
      names = []
    }
    for (const name of Object.keys(USER_LISTS)) {
      if (!names.includes(name)) names.push(name)
    }
    return names.sort((a, b) => {
      const [pa, ia, na] = listSortKey(a)
      const [pb, ib, nb] = listSortKey(b)
      return pa - pb || ia - ib || (na < nb ? -1 : na > nb ? 1 : 0)
    })
  }

  readUserList(name: string): string {
    const file = path.join(this.listsDir, name)
    if (!fs.existsSync(file)) return ''
    return fs.readFileSync(file, 'utf8')
  }

  writeUserList(name: string, text: string): void {
    const file = path.join(this.listsDir, name)
    fs.mkdirSync(path.dirname(file), { recursive: true })
    const content = text && !text.endsWith('\n') ? `${text}\n` : text
    fs.writeFileSync(file, content, 'utf8')
  }

  // ------------------------------------------------------------ служба Windows

  async serviceState(): Promise<string | null> {
    const state = await queryService(SERVICE_NAME)
    return state === 'NOT_FOUND' ? null : state
  }

  async serviceConflict(): Promise<string | null> {
    const state = await queryService(SERVICE_NAME)
    return state !== 'STOPPED' && state !== 'NOT_FOUND' ? state : null
  }

  async removeService(): Promise<boolean> {
    return removeService(SERVICE_NAME)
  }

  // ------------------------------------------------------------ запуск

  ownPids(): Set<number> {
    return this.proc ? this.proc.ownPids() : new Set<number>()
  }

  get status(): ProcessStatus {
    return this.proc ? this.proc.currentStatus : STATUS_STOPPED
  }

  get statusReason(): string {
    return this.reason
  }

  isRunning(): boolean {
    return this.proc?.isRunning() ?? false
  }

  /** Название для меню трея и сообщений: у каждого компонента оно своё. */
  get title(): string {
    return 'Zapret'
  }

  private log(text: string): void {
    logger.write(`[zapret] ${text}`)
  }

  /** Гасит winws.exe, запущенный не Zapret Hub. */
  private async killForeign(): Promise<number[]> {
    const killed = await killForeignProcesses('winws', this.ownPids())
    if (killed.length > 0) {
      this.log(`остановлен сторонний winws.exe (PID ${killed.join(', ')}) — запускаю свой`)
      await sleep(FOREIGN_KILL_SETTLE_MS)
    }
    return killed
  }

  /**
   * Одна попытка запустить winws.
   *
   * Отдельно от start(), потому что при занятом фильтре WinDivert запуск нужно
   * повторить, а ManagedProcess одноразовый — зато его можно создать заново.
   */
  private async spawnWinws(parsed: { exe: string; args: string[] }): Promise<{ ok: boolean; reason: string }> {
    const output: string[] = []
    this.proc = new ManagedProcess({
      key: 'zapret',
      command: parsed.exe,
      args: parsed.args,
      cwd: this.dir,
      logName: 'zapret.log',
      onLog: (line) => {
        output.push(line)
        logger.writeTo('zapret.log', line)
      },
      onStatus: (status) => {
        if (status === 'crashed') {
          this.reason = this.proc?.currentReason || winwsFailureReason(output) || 'процесс завершился'
        } else if (status === 'running') {
          this.reason = ''
        }
      }
    })
    this.proc.start()

    // winws подтверждает работу через пару сотен миллисекунд: раньше этого
    // срока отказ «A copy of winws is already running» уже пришёл бы.
    await sleep(START_CONFIRM_SECONDS)
    if (this.proc.currentStatus === 'crashed') {
      return {
        ok: false,
        reason: winwsFailureReason(output) || this.proc.currentReason || 'процесс завершился'
      }
    }
    return { ok: true, reason: '' }
  }

  async start(): Promise<{ ok: boolean; reason: string }> {
    if (this.isRunning()) return { ok: true, reason: '' }
    this.reason = ''
    if (!this.installed()) {
      this.log('компонент не установлен')
      this.reason = 'компонент не установлен'
      return { ok: false, reason: this.reason }
    }
    if (process.platform !== 'win32') {
      this.reason = 'zapret работает только в Windows'
      return { ok: false, reason: this.reason }
    }
    if (!(await isAdmin())) {
      this.reason = 'нужны права администратора'
      this.log(this.reason)
      return { ok: false, reason: this.reason }
    }

    const conflict = await this.serviceConflict()
    if (conflict) {
      this.reason = `служба Windows «zapret» активна (${conflict})`
      this.log(`${this.reason} — уберите её, иначе winws.exe не запустится`)
      return { ok: false, reason: this.reason }
    }

    await this.killForeign()

    try {
      this.ensureUserLists()
      this.applyGameFilter()
      this.applyIpsetMode()
    } catch (error) {
      this.reason = error instanceof Error ? error.message : String(error)
      this.log(this.reason)
      return { ok: false, reason: this.reason }
    }

    await enableTcpTimestamps()

    let parsed: { exe: string; args: string[] }
    try {
      parsed = this.parseStrategy()
    } catch (error) {
      this.reason = error instanceof Error ? error.message : String(error)
      this.log(this.reason)
      return { ok: false, reason: this.reason }
    }

    // Запуск с повторами. «Фильтр WinDivert занят предыдущей копией» — это не
    // поломка, а тормоза ядра: процесс предыдущей копии уже убит, а фильтр за
    // ним держится ещё какой-то миг. Раньше программа показывала эту ошибку и
    // сдавалась, и человек шёл перезагружать компьютер. Теперь пробуем снова:
    // почти всегда хватает второй попытки, и обход включается сам.
    for (let attempt = 1; ; attempt += 1) {
      const started = await this.spawnWinws(parsed)
      if (started.ok) {
        this.reason = ''
        return { ok: true, reason: '' }
      }
      this.reason = started.reason
      this.log(`не запустился: ${started.reason}`)
      if (attempt >= START_ATTEMPTS || !BUSY_FILTER.test(started.reason)) {
        return { ok: false, reason: started.reason }
      }
      this.log(`фильтр WinDivert ещё занят — попытка ${attempt} из ${START_ATTEMPTS}, повторяю`)
      await this.killForeign()
      await sleep(WINDIVERT_SETTLE_MS)
    }
  }

  async stop(): Promise<{ ok: boolean; reason: string }> {
    await this.proc?.stop()
    this.proc = null
    this.reason = ''
    return { ok: true, reason: '' }
  }

  /**
   * Снимает дозорного, оставив обход работать.
   *
   * Нужен для собственного перезапуска программы: это не выход, обходы должны
   * продолжать работать, а новый экземпляр подхватит их как свои.
   */
  releaseGuardian(): void {
    this.proc?.releaseGuardian()
  }

  /** Снимок состояния для интерфейса. */
  snapshot(): ZapretState {
    const z = configStore.get().zapret
    return {
      status: this.status,
      installed: this.installed(),
      version: this.versionDisplay(),
      strategies: this.strategies(),
      strategy: z.strategy,
      gameMode: z.gameMode,
      gameTcpRange: z.gameTcpRange,
      gameUdpRange: z.gameUdpRange,
      ipsetMode: z.ipsetMode,
      ipsetState: this.ipsetState(),
      lists: this.listFiles(),
      reason: this.reason,
      serviceState: null,
      dir: this.dir
    }
  }

  /** Снимок с состоянием службы — службу спрашиваем отдельно и асинхронно. */
  async snapshotAsync(): Promise<ZapretState> {
    return { ...this.snapshot(), serviceState: await this.serviceState() }
  }

  /** Освобождает таймеры и дерево процессов. Зовётся при выходе из программы. */
  dispose(): void {
    this.proc?.dispose()
    this.proc = null
  }

  /** Доступен ли порт для пробного запуска: нет ли чужого winws. */
  async foreignWinws(): Promise<number[]> {
    const pids = await pidsByName('winws')
    return pids.filter((pid) => !this.ownPids().has(pid))
  }
}
