/**
 * Диагностика системы: те же проверки, что делает `service.bat` пакета zapret.
 *
 * Зачем она в программе. Прежняя версия умела проверять только сайты, а причина
 * «почему обход не работает» чаще всего не в стратегии, а в системе: включён
 * системный прокси, стоит Adguard, в системе осталась служба WinDivert от другой
 * копии winws, пакет распакован в папку с кириллицей или в OneDrive. Человек
 * этого не видит и goes перезагружать компьютер.
 *
 * Устройство нарочно разделено на две части:
 *   • `collectFacts()` — собирает «сырые» факты командами Windows. Здесь ничего
 *     не решается, только факты, и проверить это в песочнице нельзя;
 *   • `evaluateFacts()` — превращает факты в список проверок. Чистая функция:
 *     она проверяется тестом на заранее заготовленных фактах, и её поведение не
 *     зависит от того, на какой машине запустили.
 *
 * Проверки названы по именам из service.bat, чтобы их можно было сверить.
 */
import fs from 'node:fs'
import path from 'node:path'
import { app } from 'electron'
import { IS_WINDOWS, pidsByName, powershell, queryService, removeService, run } from './win32'
import { DATA_ROOT, resolveZapretBinDir } from './paths'

/** Итог проверки. */
export type SysStatus = 'ok' | 'warn' | 'fail' | 'info'

/** Что можно починить кнопкой. */
export type SysFix = 'windivert' | 'conflicts' | 'zapret-service' | 'timestamps' | 'discord'

export interface SysCheck {
  /** Устойчивое имя: по нему интерфейс берёт подпись из своего словаря. */
  id: string
  status: SysStatus
  /** Данные проверки: что именно нашли. Показывается как есть. */
  detail: string
  /** Есть ли кнопка «починить». */
  fix?: SysFix
}

/** Сырые факты о системе — всё, что нужно знать, чтобы принять решение. */
export interface SysFacts {
  /** Вывод `sc query` — по нему ищем конфликтующие службы. */
  services: string
  bfe: string
  winDivert: string
  zapretService: string
  proxyEnable: string
  proxyServer: string
  timestamps: string
  adguard: boolean
  winwsPids: number[]
  dohCount: number
  hosts: string
  paths: string[]
  oneDrive: string
  winDivertSys: boolean
}

const EMPTY_FACTS: SysFacts = {
  services: '',
  bfe: 'NOT_FOUND',
  winDivert: 'NOT_FOUND',
  zapretService: 'NOT_FOUND',
  proxyEnable: '',
  proxyServer: '',
  timestamps: '',
  adguard: false,
  winwsPids: [],
  dohCount: 0,
  hosts: '',
  paths: [],
  oneDrive: '',
  winDivertSys: false
}

/** Службы, которые дерутся с zapret за WinDivert. */
export const CONFLICT_SERVICES = ['GoodbyeDPI', 'discordfix_zapret', 'winws1', 'winws2']

/** Папки кэша Discord: их чистят, когда Discord не открывается. */
const DISCORD_FOLDERS = ['discord', 'discordptb', 'discordcanary', 'discorddevelopment']
const DISCORD_PROCESSES = ['Discord.exe', 'DiscordPTB.exe', 'DiscordCanary.exe', 'DiscordDevelopment.exe']

/** Кириллица в пути: так выходит, когда пакет распакован в «Загрузки» и т.п. */
const CYRILLIC = /[а-яёА-ЯЁ]/

/** Включён ли системный прокси. */
function proxyOn(facts: SysFacts): boolean {
  return /0x1/.test(facts.proxyEnable)
}

/** Работает ли служба (не «нет такой» и не «остановлена»). */
function busy(state: string): boolean {
  return state !== '' && state !== 'NOT_FOUND' && state !== 'STOPPED'
}

/** Есть ли в выводе `sc query` служба с таким именем. */
function serviceNamed(services: string, name: string): boolean {
  return new RegExp(`SERVICE_NAME:\\s*${name}\\s*$`, 'im').test(services)
}

/** Все совпадения служб по подстроке — так service.bat ищет Killer и Check Point. */
function servicesMatching(services: string, needles: string[]): string[] {
  const names = new Set<string>()
  for (const line of services.split(/\r?\n/)) {
    const match = /SERVICE_NAME:\s*(.+)$/i.exec(line)
    if (!match) continue
    const name = match[1].trim()
    const lower = name.toLowerCase()
    if (needles.every((needle) => lower.includes(needle.toLowerCase()))) names.add(name)
  }
  return [...names]
}

/**
 * Факты → список проверок.
 *
 * Чистая функция: тест кормит ей заготовленные факты и сравнивает итог. Порядок
 * проверок — как в service.bat: сначала то, что ломает обход совсем, потом то,
 * что может мешать.
 */
export function evaluateFacts(facts: SysFacts): SysCheck[] {
  const checks: SysCheck[] = []

  // Base Filtering Engine — без него WinDivert не работает вовсе.
  checks.push(
    facts.bfe === 'RUNNING'
      ? { id: 'bfe', status: 'ok', detail: '' }
      : { id: 'bfe', status: 'fail', detail: facts.bfe }
  )

  // Системный прокси: часть стратегий уходит в него и не находит блокировку.
  checks.push(
    proxyOn(facts)
      ? {
          id: 'proxy',
          status: 'warn',
          detail: facts.proxyServer ? facts.proxyServer : ''
        }
      : { id: 'proxy', status: 'ok', detail: '' }
  )

  // TCP-метки времени: без них часть стратегий не заводится.
  checks.push(
    /timestamps/i.test(facts.timestamps) && /enabled/i.test(facts.timestamps)
      ? { id: 'timestamps', status: 'ok', detail: '' }
      : { id: 'timestamps', status: 'warn', detail: '', fix: 'timestamps' }
  )

  // Adguard: известный конфликт с Discord.
  checks.push(
    facts.adguard
      ? { id: 'adguard', status: 'fail', detail: 'AdguardSvc.exe' }
      : { id: 'adguard', status: 'ok', detail: '' }
  )

  // Killer, Intel Connectivity, Check Point, SmartByte: сетевое оборудование и
  // антивирусы, которые сами лезут в пакеты.
  const killer = servicesMatching(facts.services, ['killer'])
  checks.push(
    killer.length > 0
      ? { id: 'killer', status: 'fail', detail: killer.join(', ') }
      : { id: 'killer', status: 'ok', detail: '' }
  )

  const intel = servicesMatching(facts.services, ['intel', 'connectivity'])
  checks.push(
    intel.length > 0
      ? { id: 'intel', status: 'fail', detail: intel.join(', ') }
      : { id: 'intel', status: 'ok', detail: '' }
  )

  const checkpoint = servicesMatching(facts.services, ['tracsrvwrapper']).concat(
    servicesMatching(facts.services, ['epwd'])
  )
  checks.push(
    checkpoint.length > 0
      ? { id: 'checkpoint', status: 'fail', detail: checkpoint.join(', ') }
      : { id: 'checkpoint', status: 'ok', detail: '' }
  )

  const smartbyte = servicesMatching(facts.services, ['smartbyte'])
  checks.push(
    smartbyte.length > 0
      ? { id: 'smartbyte', status: 'fail', detail: smartbyte.join(', ') }
      : { id: 'smartbyte', status: 'ok', detail: '' }
  )

  // Кириллица в пути пакета: winws.exe с ней не всегда справляется.
  const cyrillicPaths = facts.paths.filter((dir) => CYRILLIC.test(dir))
  checks.push(
    cyrillicPaths.length > 0
      ? { id: 'cyrillic', status: 'warn', detail: cyrillicPaths.join(', ') }
      : { id: 'cyrillic', status: 'ok', detail: '' }
  )

  // OneDrive: файлы пакета оказываются в облаке, и winws читает их странно.
  const oneDrivePath =
    facts.oneDrive && facts.paths.find((dir) => dir.toLowerCase().startsWith(facts.oneDrive.toLowerCase()))
  checks.push(
    oneDrivePath
      ? { id: 'onedrive', status: 'fail', detail: oneDrivePath }
      : { id: 'onedrive', status: 'ok', detail: '' }
  )

  // WinDivert64.sys — драйвер, без которого не поедет ничего.
  checks.push(
    facts.winDivertSys
      ? { id: 'windivert-sys', status: 'ok', detail: '' }
      : { id: 'windivert-sys', status: 'fail', detail: '' }
  )

  // VPN: свой обход поверх чужого — источник странностей.
  const vpn = servicesMatching(facts.services, ['happservice'])
  checks.push(
    vpn.length > 0
      ? { id: 'vpn', status: 'warn', detail: vpn.join(', ') }
      : { id: 'vpn', status: 'ok', detail: '' }
  )

  // Зашифрованный DNS: без него провайдер видит запросы и режет их раньше.
  checks.push(
    facts.dohCount > 0
      ? { id: 'doh', status: 'ok', detail: '' }
      : { id: 'doh', status: 'info', detail: '' }
  )

  // hosts с записями про YouTube: сайт уходит по IP, и обход его не касается.
  checks.push(
    /youtube\.com|youtu\.be/i.test(facts.hosts)
      ? { id: 'hosts', status: 'warn', detail: '' }
      : { id: 'hosts', status: 'ok', detail: '' }
  )

  // Служба WinDivert есть, а winws не запущен — вот это и есть «фильтр занят»:
  // драйвер остался в системе от чужой копии и не отдаёт фильтр нашей.
  checks.push(
    facts.winwsPids.length === 0 && busy(facts.winDivert)
      ? { id: 'windivert', status: 'warn', detail: facts.winDivert, fix: 'windivert' }
      : { id: 'windivert', status: 'ok', detail: facts.winwsPids.length > 0 ? '' : facts.winDivert }
  )

  // Чужие обходы, зарегистрированные службами.
  const conflicts = CONFLICT_SERVICES.filter((name) => serviceNamed(facts.services, name))
  checks.push(
    conflicts.length > 0
      ? { id: 'conflicts', status: 'fail', detail: conflicts.join(', '), fix: 'conflicts' }
      : { id: 'conflicts', status: 'ok', detail: '' }
  )

  // Служба «zapret» от service.bat: она и наша программа дерутся за WinDivert.
  checks.push(
    busy(facts.zapretService)
      ? {
          id: 'zapret-service',
          status: 'fail',
          detail: facts.zapretService,
          fix: 'zapret-service'
        }
      : { id: 'zapret-service', status: 'ok', detail: '' }
  )

  // Сколько копий winws работает прямо сейчас — просто чтобы было видно.
  checks.push({
    id: 'winws',
    status: 'info',
    detail: facts.winwsPids.length > 0 ? facts.winwsPids.join(', ') : ''
  })

  return checks
}

/** Читает значение из реестра пользователя. */
async function regQuery(value: string, key: string): Promise<string> {
  const result = await run('reg', ['query', key, '/v', value])
  if (result.code !== 0) return ''
  const match = new RegExp(`${value}\\s+REG_\\w+\\s+(.+)$`, 'im').exec(result.stdout)
  return match ? match[1].trim() : ''
}

/** Собирает факты о системе. Всё, что можно — параллельно. */
export async function collectFacts(): Promise<SysFacts> {
  if (!IS_WINDOWS) return { ...EMPTY_FACTS }

  const hostsFile = path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'drivers', 'etc', 'hosts')
  const dohScript =
    "Get-ChildItem -Recurse -Path 'HKLM:System\\CurrentControlSet\\Services\\Dnscache\\InterfaceSpecificParameters\\' " +
    '-ErrorAction SilentlyContinue | Get-ItemProperty -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.DohFlags -gt 0 } | Measure-Object | Select-Object -ExpandProperty Count'

  const [services, bfe, winDivert, zapretService, timestamps, adguardPids, winwsPids, doh] = await Promise.all([
    run('sc', ['query', 'type=', 'service', 'state=', 'all'], 25000),
    queryService('BFE'),
    queryService('WinDivert'),
    queryService('zapret'),
    run('netsh', ['interface', 'tcp', 'show', 'global'], 15000),
    pidsByName('AdguardSvc'),
    pidsByName('winws'),
    powershell(dohScript, 25000)
  ])

  let hosts = ''
  try {
    hosts = fs.readFileSync(hostsFile, 'utf8')
  } catch {
    /* hosts недоступен — не беда, проверка скажет «ок» */
  }

  let winDivertSys = false
  try {
    winDivertSys = fs.existsSync(path.join(resolveZapretBinDir(), 'WinDivert64.sys'))
  } catch {
    /* пакет не установлен — проверка честно скажет «файла нет» */
  }

  const dohCount = Number(doh.stdout.trim().split(/\r?\n/).pop() ?? '0')

  return {
    services: services.stdout,
    bfe,
    winDivert,
    zapretService,
    proxyEnable: await regQuery('ProxyEnable', 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings'),
    proxyServer: await regQuery('ProxyServer', 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings'),
    timestamps: timestamps.stdout,
    adguard: adguardPids.length > 0,
    winwsPids,
    dohCount: Number.isFinite(dohCount) ? dohCount : 0,
    hosts,
    paths: [path.dirname(app.getPath('exe')), DATA_ROOT],
    oneDrive: process.env.OneDrive ?? '',
    winDivertSys
  }
}

/** Полный прогон: собрать факты и разобрать их. */
export async function runSystemChecks(): Promise<SysCheck[]> {
  return evaluateFacts(await collectFacts())
}

/** Останавливает и удаляет службу WinDivert — она и держит фильтр. */
export async function fixWinDivert(): Promise<{ ok: boolean; message: string }> {
  for (const name of ['WinDivert', 'WinDivert14']) {
    await run('net', ['stop', name], 15000)
    await run('sc', ['delete', name], 15000)
  }
  const left = await queryService('WinDivert')
  if (left === 'NOT_FOUND') return { ok: true, message: 'WinDivert удалён' }
  return { ok: false, message: `служба WinDivert всё ещё на месте (${left})` }
}

/** Удаляет службы чужих обходов: GoodbyeDPI, discordfix_zapret, winws1, winws2. */
export async function fixConflicts(): Promise<{ ok: boolean; message: string }> {
  const facts = await collectFacts()
  const found = CONFLICT_SERVICES.filter((name) => serviceNamed(facts.services, name))
  if (found.length === 0) return { ok: true, message: 'конфликтующих служб нет' }
  for (const name of found) {
    await run('net', ['stop', name], 15000)
    await run('sc', ['delete', name], 15000)
  }
  return { ok: true, message: `удалено: ${found.join(', ')}` }
}

/** Удаляет службу «zapret», поставленную service.bat. */
export async function fixZapretService(): Promise<{ ok: boolean; message: string }> {
  const ok = await removeService('zapret')
  return ok
    ? { ok: true, message: 'служба «zapret» удалена' }
    : { ok: false, message: 'не удалось удалить службу «zapret»' }
}

/** Чистит кэш Discord: помогает, когда Discord не открывается при живом обходе. */
export async function fixDiscordCache(): Promise<{ ok: boolean; message: string }> {
  const root = process.env.APPDATA ?? ''
  const killed: string[] = []
  for (const image of DISCORD_PROCESSES) {
    const pids = await pidsByName(image.replace(/\.exe$/i, ''))
    for (const pid of pids) {
      const result = await run('taskkill', ['/PID', String(pid), '/F'], 8000)
      if (result.code === 0) killed.push(image)
    }
  }

  let cleaned = 0
  for (const folder of DISCORD_FOLDERS) {
    const base = path.join(root, folder)
    if (!fs.existsSync(base)) continue
    for (const cache of ['Cache', 'Code Cache', 'GPUCache']) {
      const target = path.join(base, cache)
      if (!fs.existsSync(target)) continue
      try {
        fs.rmSync(target, { recursive: true, force: true })
        cleaned += 1
      } catch {
        /* папка занята — покажем, что успели */
      }
    }
  }
  return {
    ok: true,
    message: `закрыто: ${killed.length > 0 ? killed.join(', ') : 'ничего'}, папок очищено: ${cleaned}`
  }
}
