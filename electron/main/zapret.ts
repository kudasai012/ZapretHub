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
import {
  enableTcpTimestamps,
  holdsFilter,
  isAdmin,
  killForeignProcesses,
  killOrphanGuardians,
  pidsByName,
  queryService,
  releaseWinDivert,
  removeService,
  type ServiceState,
  WINDIVERT_SERVICES
} from './win32'

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

/**
 * Разбор командной строки Windows: кавычки обрамляют токен и удаляются.
 *
 * Попутно снимается экранирование cmd: в .bat-файлах `!` пишут как `^!`
 * (иначе cmd съест его сам — при включённой delayed expansion), `&` как `^&`,
 * `|` как `^|`, а сам `^` как `^^`. Мы запускаем winws напрямую, без cmd, и
 * раньше эти символы доходили до него буквально: `--dpi-desync-fake-tls=^!`
 * winws принимал за имя файла с фейковым TLS и падал с «could not read ^!».
 * Внутри кавычек `^` — обычный символ, так же как у cmd.
 */
export function tokenizeWindows(line: string): string[] {
  const tokens: string[] = []
  let current = ''
  let inQuotes = false
  let hasToken = false
  let escaped = false
  for (let at = 0; at < line.length; at += 1) {
    const ch = line[at]
    // Экранированный символ уходит в токен как есть: будь то кавычка, пробел,
    // скобка или &.
    if (escaped) {
      current += ch
      hasToken = true
      escaped = false
      continue
    }
    if (ch === '^' && !inQuotes) {
      const next = line[at + 1]
      // Каретка в конце строки — это перенос, а не экранирование: cmd съедает
      // перевод строки, а не первый символ следующей. Съесть символ — значит
      // склеить аргумент с чужой строкой и получить в аргументах текст справки
      // winws вместо значения.
      if (next === undefined) continue
      /**
       * Каретка перед процентом снимает его служебный смысл.
       *
       * cmd разбирает строку в два прохода: сначала подставляет переменные
       * (`%%` → `%`, `%NAME%` → значение), потом снимает каретки. Поэтому
       * `^%PATH^%` доезжает как `%PATH%`, а не разворачивается в путь.
       * У нас тот же порядок — подстановка идёт раньше разбора, — значит
       * снятая каретка ложной подстановки не вызовет.
       */
      escaped = true
      continue
    }
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
  ['error opening filter', 'фильтр WinDivert занят прежней копией winws']
]

/**
 * Код выхода winws, когда фильтр WinDivert занят прежней копией.
 *
 * winws не всегда пишет про это в журнал: иногда он просто выходит с десяткой.
 * Раньше такой выход показывался как «не удалось запустить» и повторов не
 * было, хотя причина та же, что у «error opening filter», — фильтр ещё не
 * отдали.
 */
export const WINDIVERT_BUSY_EXIT = 10

/** Так Windows сообщает, что процесс снят извне: нашим сторожем или человеком. */
const KILLED_EXIT_CODES = [0x40010004, 0xc000013a]

/** winws не нашёл файл: «could not read ^!», «cannot access ipset file 'x'». */
const MISSING_FILE = /(?:could not read|cannot (?:access|open)|could not open)\s+(.+?)\s*$/i

/**
 * Имя файла из жалобы winws.
 *
 * В кавычках — берём то, что в кавычках: «cannot access ipset file 'loaded'»
 * — это про файл loaded, а не про строку целиком. Без кавычек берём хвост
 * строки: «could not read ^!» — это про файл ^!.
 */
function missingFileName(line: string): string {
  const found = MISSING_FILE.exec(line.trim())
  if (!found) return ''
  const rest = found[1].trim()
  const quoted = /'([^']+)'/.exec(rest) ?? /"([^"]+)"/.exec(rest)
  return (quoted ? quoted[1] : rest).trim()
}

/**
 * Причины, после которых имеет смысл попробовать ещё раз.
 *
 * «Фильтр WinDivert занят предыдущей копией» — не поломка, а тормоза: ядро
 * удаляет фильтр не в тот же миг, когда убит процесс winws. Раньше программа
 * показывала эту ошибку и сдавалась, и человеку оставалось только перезагружать
 * компьютер. Теперь такие отзывы повторяются с паузой.
 */
const BUSY_FILTER = /фильтр WinDivert занят|другая копия winws|error opening filter|same filter/i

/**
 * Что сказать, если фильтр так и не отдали.
 *
 * К этому моменту программа уже убрала всё, что умеет убирать сама: чужие
 * копии winws, дозорных прежнего запуска и службу драйвера. Если и после
 * этого фильтр занят, его держит что-то чужое — другой обход или служба,
 * поставленная service.bat, — и об этом надо сказать прямо, а не советовать
 * подождать: ожидание тут не помогает.
 */
const FILTER_HINT =
  'Программа убрала всё, что могла. Фильтр держит чужой обход (GoodbyeDPI, служба zapret) — снимите его в Диагностике или перезагрузите компьютер'

/** Сколько ждём после убийства чужого winws.exe. */
const FOREIGN_KILL_SETTLE_MS = 900

/** Сколько раз пробуем запустить winws, если фильтр ещё занят. */
const START_ATTEMPTS = 4

/** На какой попытке снимаем службу драйвера, если процессы уже убраны. */
const DRIVER_RELEASE_ATTEMPT = 2

/**
 * Как часто спрашиваем, отдал ли драйвер фильтр.
 *
 * Процесс winws убит — но ядро снимает фильтр не в ту же миллисекунду:
 * объекты драйвера ещё живут, и новый winws, запущенный в эту паузу,
 * доходит до открытия фильтра и получает «error opening filter: The object
 * is referenced by other objects so cannot be deleted». Именно из-за этого
 * перезапуск при смене настройки (стоп, затем старт) падал всегда.
 */
const FILTER_POLL_MS = 400

/** Сколько ждём, что драйвер отдаст фильтр сам, уже после остановки winws. */
const FILTER_RELEASE_WAIT_MS = 3000

/** Сколько ждём освобождения фильтра перед повтором (по номеру попытки). */
const FILTER_RETRY_WAIT_MS = [1500, 3000, 6000]

/** Сколько ждать освобождения фильтра перед повтором: 1.5, 3, 6 с. */
function filterRetryWait(attempt: number): number {
  return (
    FILTER_RETRY_WAIT_MS[attempt - 1] ??
    FILTER_RETRY_WAIT_MS[FILTER_RETRY_WAIT_MS.length - 1] * 2
  )
}

/**
 * Человеческая причина провала: сначала по тому, что написал сам winws, потом
 * по коду выхода.
 *
 * Про «could not read ^!» раньше говорилось «переустановите компонент zapret».
 * Это неправда: компонент цел, просто в аргументах указан файл, которого нет
 * (чаще всего это cmd-экранирование, которое мы теперь снимаем сами). Поэтому
 * имя файла показываем как есть, а переустанавливать не советуем.
 */
export function winwsFailureReason(output: string[], code?: number | null): string {
  if (code === WINDIVERT_BUSY_EXIT) return 'фильтр WinDivert занят прежней копией winws'
  if (code != null && KILLED_EXIT_CODES.includes(code)) return 'процесс снят извне — это не падение'
  for (const line of output) {
    const missing = missingFileName(line)
    if (missing) return `winws не нашёл файл, указанный в стратегии: ${missing}`
    for (const [needle, reason] of WINWS_KNOWN_FAILURES) {
      if (line.includes(needle)) return reason
    }
  }
  return ''
}

export const PROBE_SETTLE_SECONDS = 1500

/**
 * Сколько следим за свежезапущенным winws, прежде чем сказать «запущен».
 *
 * Раньше ждали 800 мс и рапортовали успех — но winws иногда умирает на второй
 * секунде (например, споткнувшись о файл из аргументов), и программа успевала
 * показать «обход работает» там, где он уже упал. Теперь смотрим полторы
 * секунды: отказ «A copy of winws is already running» приходит в первые сотни
 * миллисекунд, а живой процесс спокойно доживает до конца окна.
 */
export const START_WATCH_MS = 1500

/**
 * Окно наблюдения при загруженном ipset-списке.
 *
 * ipset-список — это сотни килобайт: на холодном диске и под антивирусом
 * winws читает его заметно дольше обычного и может написать про ошибку в
 * файле только на третьей-четвёртой секунде. Короткое окно здесь опасно не
 * тем, что объявит провалом рабочий запуск (живой процесс мы провалом не
 * считаем), а тем, что пропустит позднюю смерть: программа успеет показать
 * «обход работает» и тут же откатится.
 */
export const START_WATCH_LOADED_MS = 5000

/** Сколько следим за запуском при выбранном ipset-режиме. */
export function startWatchMs(ipsetMode?: string): number {
  return ipsetMode === 'loaded' ? START_WATCH_LOADED_MS : START_WATCH_MS
}

/** Как часто спрашиваем, жив ли процесс, пока следим. */
const WATCH_STEP_MS = 120

/** Сколько строк вывода winws показываем человеку. */
const OUTPUT_TAIL = 5

/**
 * Чем winws сообщает, что перехват пошёл.
 *
 * Эту строку он пишет последней — после загрузки всех списков и ipset:
 * «windivert initialized. capture is started.». То есть это признак не
 * «процесс стартовал», а «фильтры применены», и ждать надо именно её, а не
 * просто доживать окно.
 */
const READY_MARKER = /windivert initialized|capture is started/i

/** Подтвердил ли winws, что capture запущен. */
export function readySeen(lines: string[]): boolean {
  return lines.some((line) => READY_MARKER.test(line))
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

export class ZapretComponent {
  private proc: ManagedProcess | null = null
  private reason = ''
  /** Последние строки winws — их показываем человеку при провале. */
  private tail: string[] = []

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

  /**
   * Склеивает строки, продолженные символом ^, в одну команду.
   *
   * Каретка в конце строки гасит сам перевод строки, а не добавляет пробел:
   * `echo a^` + перенос + `b` в cmd печатает `ab`, а не `a b`. Поэтому
   * склеиваем без разделителя — иначе длинное значение, разорванное на две
   * строки, превратилось бы в два аргумента.
   */
  private static joinContinuations(lines: string[]): string[] {
    const joined: string[] = []
    let buffer = ''
    for (const line of lines) {
      const stripped = line.replace(/\s+$/, '')
      if (stripped.endsWith('^')) {
        buffer += stripped.slice(0, -1)
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
      // %% в батнике — это просто символ процента, и гасится он сразу, при
      // чтении самой строки set: `set "A=50%%"` кладёт в переменную 50%.
      let value = match[2]
        .trim()
        .replace(/%%/g, '%')
        .replace(/%~dp0/gi, `${this.dir}${path.sep}`)
      if (path.sep !== '\\') value = value.replace(/\\/g, path.sep)
      variables[name] = value
    }
    variables.BIN = `${this.binDir}${path.sep}`
    variables.LISTS = `${this.listsDir}${path.sep}`
    return variables
  }

  /**
   * Подстановка переменных: %BIN%, %LISTS% и прочие из пакета.
   *
   * Считаем слева направо, а не одной подстановкой: `%%` в батнике — это
   * просто символ процента, и его надо съесть раньше, чем он склеится с
   * соседней переменной (`%%BIN%%` — не переменная BIN, а `%BIN%` в тексте).
   *
   * Неизвестную переменную не трогаем: молча подставить пустоту — значит
   * потерять аргумент, и человек будет искать поломку там, где её нет. Такие
   * места называем в журнале.
   */
  private static expand(
    text: string,
    variables: Record<string, string>
  ): { text: string; unknown: string[] } {
    let out = ''
    const unknown: string[] = []
    let at = 0
    while (at < text.length) {
      const ch = text[at]
      if (ch !== '%') {
        out += ch
        at += 1
        continue
      }
      if (text[at + 1] === '%') {
        out += '%'
        at += 2
        continue
      }
      /**
       * Ссылка на параметр: `%~dp0`, `%~1`, `%~nx0`.
       *
       * Закрывающего процента у неё нет, поэтому её надо съесть всю сразу.
       * Иначе этот процент спарится со следующим в строке, и подстановка
       * поедет по всей команде: `--literal=100%%` останется с двумя
       * процентами, а `%LISTS%` не подставится вовсе.
       */
      const param = /^%~[a-z]*\d*/i.exec(text.slice(at))
      if (param) {
        out += param[0]
        at += param[0].length
        continue
      }
      const end = text.indexOf('%', at + 1)
      if (end === -1) {
        out += ch
        at += 1
        continue
      }
      const name = text.slice(at + 1, end).toUpperCase()
      if (name in variables) {
        out += variables[name]
      } else {
        out += text.slice(at, end + 1)
        if (!/^~/.test(name)) unknown.push(`%${name}%`)
      }
      at = end + 1
    }
    return { text: out, unknown: [...new Set(unknown)] }
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
      // %~dp0 разворачиваем заранее: в set-строках это делается при чтении,
      // а в строке запуска — здесь, до подстановки переменных.
      const expanded = ZapretComponent.expand(
        stripped.replace(/%~dp0/gi, `${this.dir}${path.sep}`),
        variables
      )
      for (const name of expanded.unknown) {
        this.log(`в стратегии ${strategy} осталась неизвестная переменная ${name} — оставил как есть`)
      }
      if (expanded.text.includes('%')) {
        this.log(`в стратегии ${strategy} после подстановки остался символ % — проверьте файл`)
      }
      const tokens = tokenizeWindows(expanded.text)
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
  /**
   * Убирает всё, что помешает новому winws.
   *
   * Кроме чужих копий winws это ещё и дозорные прежнего запуска программы.
   * Дозорный живёт дольше своей программы и гасит winws по имени образа: если
   * программу сняли задачей, он ещё какое-то время добивает чужое — и убивает
   * наш свежий запуск ровно в тот миг, когда тот открывает фильтр.
   */
  private async killForeign(): Promise<number[]> {
    const orphans = await killOrphanGuardians('zapret')
    if (orphans.length > 0) {
      this.log(`снят дозорный прежнего запуска (PID ${orphans.join(', ')}) — иначе он гасит наш winws`)
    }
    const killed = await killForeignProcesses('winws', this.ownPids())
    if (killed.length > 0) {
      this.log(`остановлен сторонний winws.exe (PID ${killed.join(', ')}) — запускаю свой`)
    }
    if (orphans.length > 0 || killed.length > 0) await sleep(FOREIGN_KILL_SETTLE_MS)
    return killed
  }

  /**
   * Одна попытка запустить winws.
   *
   * Отдельно от start(), потому что при занятом фильтре WinDivert запуск нужно
   * повторить, а ManagedProcess одноразовый — зато его можно создать заново.
   */
  /** Чужие копии winws: те, что живут в системе, но не наши. */
  private async strangeWinws(): Promise<number[]> {
    const own = this.ownPids()
    const pids = await pidsByName('winws')
    return pids.filter((pid) => !own.has(pid))
  }

  /**
   * Кто сейчас держит фильтр WinDivert: чужие копии winws и служба драйвера.
   */
  private async filterState(): Promise<{ pids: number[]; state: ServiceState }> {
    const own = this.ownPids()
    const pids = (await pidsByName('winws')).filter((pid) => !own.has(pid))
    const states = await Promise.all(WINDIVERT_SERVICES.map((name) => queryService(name)))
    return { pids, state: states.find(holdsFilter) ?? 'NOT_FOUND' }
  }

  /**
   * Ждём, пока драйвер отдаст фильтр.
   *
   * Нужны оба признака: чужих копий winws нет и служба драйвера не держит
   * фильтр (остановлена или её нет вовсе). Одного «процессов нет» мало —
   * драйвер остаётся в ядре и после смерти последнего владельца, и ровно в
   * этом зазоре новый winws натыкался на занятый фильтр.
   */
  private async waitForFilterFree(budgetMs: number): Promise<{ free: boolean; waited: number }> {
    const startedAt = Date.now()
    for (;;) {
      const { pids, state } = await this.filterState()
      if (pids.length === 0 && !holdsFilter(state)) {
        return { free: true, waited: Date.now() - startedAt }
      }
      const left = budgetMs - (Date.now() - startedAt)
      if (left <= 0) return { free: false, waited: Date.now() - startedAt }
      await sleep(Math.min(FILTER_POLL_MS, left))
    }
  }

  /**
   * Дожимаем фильтр сразу после остановки своего winws.
   *
   * Смена стратегии, списка или игрового фильтра перезапускает обход: стоп,
   * потом старт. Раньше старт начинался, едва исчезал процесс winws, — и
   * упирался в фильтр, который ядро ещё не отдало. Теперь ждём здесь, в
   * остановке: следующий запуск начинается на чистом фильтре, а не надеется
   * на повторы, каждый из которых стоит секунды и показывает ошибку.
   */
  private async releaseAfterStop(): Promise<void> {
    const quick = await this.waitForFilterFree(FILTER_POLL_MS)
    if (quick.free) return
    const before = await this.filterState()
    this.log(
      `фильтр WinDivert занят после остановки (служба ${before.state}, копий winws: ${before.pids.length}) — снимаю службу драйвера`
    )
    // Удалять службу нельзя: до тех пор, пока ядро не отдаст объекты, запись
    // остаётся «на удаление» (service marked for deletion), и создать её
    // заново уже не выйдет — обход не поднимется до перезагрузки компьютера.
    await releaseWinDivert(this.ownPids(), { stopTimeoutMs: 3000, settleMs: 2000 })
    const after = await this.waitForFilterFree(FILTER_RELEASE_WAIT_MS)
    if (after.free) {
      this.log(`фильтр WinDivert отпустил через ${after.waited} мс`)
    } else {
      const stuck = await this.filterState()
      this.log(`фильтр WinDivert не отдали: служба ${stuck.state}, копий winws: ${stuck.pids.length}`)
    }
  }

  private async spawnWinws(parsed: { exe: string; args: string[] }): Promise<{ ok: boolean; reason: string }> {
    const output: string[] = []
    const startedAt = Date.now()
    this.tail.length = 0
    // Код выхода запоминаем: по нему виден занятый фильтр и снятый извне
    // процесс — то, чего в журнале winws может и не быть.
    let exitCode: number | null = null
    this.proc = new ManagedProcess({
      key: 'zapret',
      command: parsed.exe,
      args: parsed.args,
      cwd: this.dir,
      logName: 'zapret.log',
      onLog: (line) => {
        output.push(line)
        this.tail.push(line)
        if (this.tail.length > OUTPUT_TAIL * 4) this.tail.shift()
        logger.writeTo('zapret.log', line)
      },
      // Причину падения разбираем по выводу winws: «A copy of winws is
      // already running» понятнее, чем «код выхода 1».
      crashReason: (lines, code) => winwsFailureReason(lines, code),
      onExit: (code) => {
        exitCode = code
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

    /**
     * Смотрим за процессом до конца окна, а не один раз через паузу.
     *
     * Умер — отвечаем сразу, не дожидаясь конца: отказ из-за занятого фильтра
     * приходит в первые сотни миллисекунд, и ждать остаток окна незачем.
     */
    const window = startWatchMs(configStore.get().zapret.ipsetMode)
    const deadline = Date.now() + window
    while (Date.now() < deadline) {
      const status = this.proc.currentStatus
      if (status === 'crashed') {
        return {
          ok: false,
          reason: winwsFailureReason(output, exitCode) || this.proc.currentReason || 'процесс завершился'
        }
      }
      if (status === 'stopped') return { ok: false, reason: 'процесс снят до подтверждения запуска' }
      // Маркер — основной сигнал: он приходит после загрузки всех списков.
      // Дожидать окна до конца незачем, и запуск подтверждается быстрее.
      if (readySeen(output)) {
        this.log(`фильтр поднят за ${Date.now() - startedAt} мс`)
        return { ok: true, reason: '' }
      }
      await sleep(Math.min(WATCH_STEP_MS, Math.max(0, deadline - Date.now())))
    }

    const status = this.proc.currentStatus
    if (status === 'crashed') {
      return {
        ok: false,
        reason: winwsFailureReason(output, exitCode) || this.proc.currentReason || 'процесс завершился'
      }
    }
    if (readySeen(output)) {
      this.log(`фильтр поднят за ${Date.now() - startedAt} мс`)
      return { ok: true, reason: '' }
    }
    /**
     * Живой, но без маркера.
     *
     * Процесс не упал — значит, провала нет и повторять запуск нельзя (две
     * копии дерутся за один фильтр). Но и «работает» говорить рано: winws не
     * дошёл до строки «windivert initialized», то есть либо не загрузил
     * списки, либо фильтр не поднялся. Это конкретная диагностика, а не
     * гадание, поэтому её показываем.
     */
    const silent = output.length === 0
    this.reason = silent
      ? `обход запущен, но winws не написал ни строки за ${Math.round(window / 1000)} с — списки, вероятно, не загрузились`
      : `обход запущен, но winws не подтвердил фильтр за ${Math.round(window / 1000)} с — перехват мог не начаться`
    this.log(`${this.reason} (последнее, что сказал: ${output.slice(-1)[0] ?? 'ничего'})`)
    return { ok: true, reason: this.reason }
  }

  /**
   * Последние строки, которые успел сказать winws.
   *
   * Человеку показываем сырой вывод: пересказ «переустановите компонент»
   * скрывал, что именно не так, и люди переустанавливали то, что не сломано.
   */
  outputTail(): string[] {
    return this.tail.slice(-OUTPUT_TAIL)
  }

  async start(): Promise<{ ok: boolean; reason: string }> {
    if (this.isRunning()) return { ok: true, reason: '' }
    const startedAt = Date.now()
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

    // Проверки идут вместе, а не гуськом: каждая раньше была отдельным
    // обращением к системе (свой PowerShell), и в сложении они давали секунды
    // ожидания на ровном месте — человек нажимал «запустить» и ждал.
    const [conflict] = await Promise.all([
      this.serviceConflict(),
      this.killForeign(),
      // Метки времени нужны до запуска winws, но готовить их можно заодно с
      // остальным: это независимые вещи.
      enableTcpTimestamps()
    ])
    if (conflict) {
      this.reason = `служба Windows «zapret» активна (${conflict})`
      this.log(`${this.reason} — уберите её, иначе winws.exe не запустится`)
      return { ok: false, reason: this.reason }
    }

    try {
      this.ensureUserLists()
      this.applyGameFilter()
      this.applyIpsetMode()
    } catch (error) {
      this.reason = error instanceof Error ? error.message : String(error)
      this.log(this.reason)
      return { ok: false, reason: this.reason }
    }

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
    let released = false
    for (let attempt = 1; attempt <= START_ATTEMPTS; attempt += 1) {
      const started = await this.spawnWinws(parsed)
      if (started.ok) {
        // Причина при удачном запуске бывает: процесс жив, но не подтвердил
        // фильтр. Молчать про это нельзя, поэтому причина едет дальше.
        this.reason = started.reason
        this.log(`запущен за ${Date.now() - startedAt} мс`)
        return { ok: true, reason: this.reason }
      }
      this.reason = started.reason
      this.log(`не запустился: ${started.reason}`)
      if (!BUSY_FILTER.test(started.reason)) return { ok: false, reason: started.reason }
      if (attempt >= START_ATTEMPTS) break

      // Сначала убираем владельцев фильтра: чужие копии winws и дозорных
      // прежнего запуска. Это дешёвое действие, и в половине случаев его
      // хватает — ядро отпускает фильтр само, как только убит последний, кто
      // его держал.
      await this.killForeign()

      // Твёрдое правило: пока в системе жив хоть один чужой winws, вторую
      // копию не запускаем. Две копии с одним фильтром — это как раз «exit
      // code 10» и та самая гонка, из-за которой обход не поднимался.
      const strangers = await this.strangeWinws()
      if (strangers.length > 0) {
        this.reason = `в системе уже работает winws (PID ${strangers.join(', ')}) — второй не запускаю`
        this.log(`${this.reason}: две копии дерутся за один фильтр`)
        return { ok: false, reason: this.reason }
      }

      if (released || attempt < DRIVER_RELEASE_ATTEMPT) {
        // Ждём не просто паузу, а освобождения: пока драйвер держит фильтр,
        // следующая попытка всё равно упрётся в ту же ошибку.
        const waited = await this.waitForFilterFree(filterRetryWait(attempt))
        this.log(
          `фильтр WinDivert ещё занят — попытка ${attempt} из ${START_ATTEMPTS}, ждал ${waited.waited} мс`
        )
        continue
      }

      // Процессов-владельцев нет, а фильтр занят — значит, его держит служба
      // драйвера от прежней копии. Снимаем её и пробуем снова: раньше на этом
      // месте программа сдавалась и отправляла человека перезагружать
      // компьютер, хотя всё чинилось одной командой.
      released = true
      this.log('фильтр WinDivert занят службой драйвера — снимаю её')
      const freed = await releaseWinDivert(this.ownPids(), { stopTimeoutMs: 4000, settleMs: 3000 })
      this.log(
        freed.freed
          ? `фильтр WinDivert освобождён (снято копий winws: ${freed.killed.length})`
          : `фильтр WinDivert не отдали: служба ${freed.state}`
      )
      const waited = await this.waitForFilterFree(filterRetryWait(attempt))
      this.log(`после снятия службы драйвера ждал ${waited.waited} мс`)
    }
    this.log(`запуск не удался за ${Date.now() - startedAt} мс: ${this.reason}`)
    /**
     * Что говорить, зависит от того, кто держит фильтр.
     *
     * Служба, застрявшая посреди остановки, — это не чужой обход: драйвер не
     * отдаёт свои объекты, и ждать бесполезно. Раньше на оба случая говорили
     * одно и то же («снимите чужой обход»), и человек искал GoodbyeDPI там,
     * где проблема была в собственном драйвере.
     */
    const last = await this.filterState()
    const hint =
      last.state === 'STOP_PENDING'
        ? 'Служба драйвера WinDivert застряла посреди остановки — поможет перезагрузка компьютера'
        : FILTER_HINT
    return { ok: false, reason: `${this.reason}. ${hint}` }
  }

  async stop(): Promise<{ ok: boolean; reason: string }> {
    const wasRunning = this.proc !== null
    await this.proc?.stop()
    this.proc = null
    this.reason = ''
    // Ждём только свой фильтр: чужой мы не гасили и гасить не должны.
    if (wasRunning) await this.releaseAfterStop()
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
