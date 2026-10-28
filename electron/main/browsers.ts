import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { IS_WINDOWS, pidsByName, run } from './win32'

/**
 * Зашифрованный DNS в браузерах.
 *
 * Системный DoH из диагностики («Dnscache») браузеры не использовали: у каждого
 * свой выключатель, и пока он не нажат, провайдер видит запросы. Здесь этот
 * выключатель — по одному на браузер.
 *
 * Способ зависит от браузера:
 *  - Firefox и «хромоподобные» Яндекс и Chrome понимают политики из реестра;
 *  - Opera GX политик не понимает вовсе (их вырезали из кода) — у неё настройка
 *    лежит в файле Local State, который браузер переписывает при выходе. Такой
 *    файл трогаем только когда браузер закрыт, иначе запись пропадёт, а мы
 *    соврём, что включили.
 *
 * Пишем в HKLM — на уровень компьютера, а не в куст пользователя. Яндекс
 * Браузер значения из HKCU видит, но помечает «политика заблокирована, её
 * значение не будет учтено»: во всех его документах политики задаются только в
 * HKLM, и уровень компьютера там старше пользовательского. Программа и так
 * работает с правами администратора, а настройка одна на всю машину — так же,
 * как служба и драйвер, которые она ставит.
 *
 * Режим везде с откатом на обычный DNS: если зашифрованный провайдер не
 * ответит, браузер спросит как обычно и не оставит человека без интернета.
 */

export type BrowserId = 'firefox' | 'chrome' | 'yandex' | 'operagx'

export interface BrowserDoh {
  id: BrowserId
  /** Как подписать браузер человеку — название бренда, перевод не нужен. */
  name: string
  /** Браузер найден на диске. */
  installed: boolean
  /** Браузер сейчас запущен. */
  running: boolean
  /** Зашифрованный DNS в браузере включён. */
  on: boolean
  /** Адрес провайдера, если задан. */
  template: string
  /**
   * Можно ли по записи судить, что браузер её принял.
   *
   * У Яндекс Браузера — нет: он подменяет DNS на свой и политику DoH
   * отвергает («Политика заблокирована. Её значение не будет учтено»). Из
   * реестра это не видно, поэтому такой браузер нельзя показывать включённым
   * только потому, что мы туда записали.
   */
  confirmed: boolean
}

/**
 * Режим «сначала шифрованный DNS, не вышло — обычный».
 *
 * Не «secure»: при нём браузер на отказ провайдера отвечает ошибкой, и человек
 * остаётся без интернета. Наша задача — обойти блокировку, а не отрезать сеть.
 */
const MODE = 'automatic'

/** Как браузер хранит настройку. */
type Storage =
  /** Политика «хромоподобных»: два строковых значения. */
  | { kind: 'chromium'; key: string }
  /** Политика Firefox: своя ветка и свои имена значений. */
  | { kind: 'firefox'; key: string }
  /** Файл Local State тех, кто политик не понимает. */
  | { kind: 'local-state'; file: () => string }

interface BrowserDef {
  id: BrowserId
  name: string
  /** Видно ли по записи, что браузер её принял. */
  confirmed: boolean
  /** Имя процесса — чтобы не переписывать настройку под запущенным браузером. */
  process: string
  /** Где искать исполняемый файл: установлен ли браузер вообще. */
  exe: () => string[]
  storage: Storage
}

const LOCAL_APP_DATA = () =>
  process.env.LOCALAPPDATA ?? path.join(os.homedir(), 'AppData', 'Local')
const ROAMING_APP_DATA = () => process.env.APPDATA ?? path.join(os.homedir(), 'AppData', 'Roaming')
const PROGRAM_FILES = () => process.env.ProgramFiles ?? 'C:\\Program Files'
const PROGRAM_FILES_X86 = () => process.env['ProgramFiles(x86)'] ?? 'C:\\Program Files (x86)'

const BROWSERS: BrowserDef[] = [
  {
    id: 'firefox',
    confirmed: true,
    name: 'Firefox',
    process: 'firefox',
    exe: () => [
      path.join(PROGRAM_FILES(), 'Mozilla Firefox', 'firefox.exe'),
      path.join(PROGRAM_FILES_X86(), 'Mozilla Firefox', 'firefox.exe')
    ],
    storage: { kind: 'firefox', key: 'HKLM\\Software\\Policies\\Mozilla\\Firefox\\DNSOverHTTPS' }
  },
  {
    id: 'chrome',
    confirmed: true,
    name: 'Chrome',
    process: 'chrome',
    exe: () => [
      path.join(LOCAL_APP_DATA(), 'Google', 'Chrome', 'Application', 'chrome.exe'),
      path.join(PROGRAM_FILES(), 'Google', 'Chrome', 'Application', 'chrome.exe'),
      path.join(PROGRAM_FILES_X86(), 'Google', 'Chrome', 'Application', 'chrome.exe')
    ],
    storage: { kind: 'chromium', key: 'HKLM\\Software\\Policies\\Google\\Chrome' }
  },
  {
    // Яндекс Браузер сам подменяет DNS на свой и чужую политику DoH не
    // принимает — записать её можно, подтвердить нельзя.
    id: 'yandex',
    confirmed: false,
    name: 'Яндекс Браузер',
    process: 'browser',
    exe: () => [
      path.join(LOCAL_APP_DATA(), 'Yandex', 'YandexBrowser', 'Application', 'browser.exe'),
      path.join(PROGRAM_FILES(), 'Yandex', 'YandexBrowser', 'Application', 'browser.exe')
    ],
    storage: { kind: 'chromium', key: 'HKLM\\Software\\Policies\\YandexBrowser' }
  },
  {
    id: 'operagx',
    confirmed: true,
    name: 'Opera GX',
    process: 'opera',
    exe: () => [path.join(LOCAL_APP_DATA(), 'Programs', 'Opera GX', 'opera.exe')],
    storage: {
      kind: 'local-state',
      file: () => path.join(ROAMING_APP_DATA(), 'Opera Software', 'Opera GX Stable', 'Local State')
    }
  }
]

/**
 * Старые ключи в кусте пользователя.
 *
 * Раньше настройка писалась в HKCU. В Яндекс Браузере такие значения не
 * работали, но оставались в реестре и мешали: конфликт уровней — частая причина
 * «политика заблокирована». Поэтому перед записью убираем то, что могли
 * оставить прежние версии программы.
 */
const LEGACY_USER_KEYS: { key: string; values: string[] }[] = [
  {
    key: 'HKCU\\Software\\Policies\\Google\\Chrome',
    values: ['DnsOverHttpsMode', 'DnsOverHttpsTemplates']
  },
  {
    key: 'HKCU\\Software\\Policies\\YandexBrowser',
    values: ['DnsOverHttpsMode', 'DnsOverHttpsTemplates']
  },
  {
    key: 'HKCU\\Software\\Policies\\Mozilla\\Firefox\\DNSOverHTTPS',
    values: ['Enabled', 'ProviderURL', 'Fallback', 'Locked']
  }
]

/** Имена браузеров — по ним интерфейс подписывает список. */
export const BROWSER_NAMES: Record<BrowserId, string> = {
  firefox: 'Firefox',
  chrome: 'Chrome',
  yandex: 'Яндекс Браузер',
  operagx: 'Opera GX'
}

/** Готовые провайдеры: интерфейс предлагает выбрать, сюда приходит адрес. */
export const DOH_PROVIDERS: { id: string; name: string; url: string }[] = [
  { id: 'cloudflare', name: 'Cloudflare', url: 'https://cloudflare-dns.com/dns-query' },
  { id: 'google', name: 'Google', url: 'https://dns.google/dns-query' },
  { id: 'adguard', name: 'AdGuard DNS', url: 'https://dns.adguard.com/dns-query' }
]

// ------------------------------------------------------------------ реестр

async function regRead(key: string, value: string): Promise<string> {
  const result = await run('reg', ['query', key, '/v', value])
  if (result.code !== 0) return ''
  const match = new RegExp(`${value}\\s+REG_\\w+\\s+(.+)$`, 'im').exec(result.stdout)
  return match ? match[1].trim() : ''
}

async function regWrite(key: string, value: string, type: string, data: string): Promise<boolean> {
  const result = await run('reg', ['add', key, '/v', value, '/t', type, '/d', data, '/f'])
  return result.code === 0
}

async function regDrop(key: string, value: string): Promise<void> {
  await run('reg', ['delete', key, '/v', value, '/f'])
}

/** Значение политики — включён ли DoH. */
function modeOn(mode: string): boolean {
  return /^(automatic|secure)$/i.test(mode.trim())
}

// ---------------------------------------------------------------- Local State

/** Настройка DoH внутри Local State — узел dns_over_https. */
interface LocalState {
  dns_over_https?: { mode?: string; templates?: string }
}

function readLocalState(file: string): { state: LocalState | null; raw: string } {
  try {
    const raw = fs.readFileSync(file, 'utf8')
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') return { state: parsed as LocalState, raw }
    return { state: null, raw }
  } catch {
    // файла нет или он не читается — значит настройки нет, а не «выключено»
    return { state: null, raw: '' }
  }
}

// --------------------------------------------------------------- чтение/запись

async function readState(def: BrowserDef): Promise<{ on: boolean; template: string }> {
  if (def.storage.kind === 'chromium') {
    return {
      on: modeOn(await regRead(def.storage.key, 'DnsOverHttpsMode')),
      template: await regRead(def.storage.key, 'DnsOverHttpsTemplates')
    }
  }
  if (def.storage.kind === 'firefox') {
    const enabled = await regRead(def.storage.key, 'Enabled')
    return {
      on: /^0x0*1$/i.test(enabled.trim()) || enabled.trim() === '1',
      template: await regRead(def.storage.key, 'ProviderURL')
    }
  }
  const { state } = readLocalState(def.storage.file())
  return {
    on: modeOn(state?.dns_over_https?.mode ?? ''),
    template: state?.dns_over_https?.templates ?? ''
  }
}

async function writeState(def: BrowserDef, url: string | null): Promise<void> {
  if (def.storage.kind === 'chromium') {
    if (url === null) {
      await regDrop(def.storage.key, 'DnsOverHttpsMode')
      await regDrop(def.storage.key, 'DnsOverHttpsTemplates')
      return
    }
    await regWrite(def.storage.key, 'DnsOverHttpsMode', 'REG_SZ', MODE)
    await regWrite(def.storage.key, 'DnsOverHttpsTemplates', 'REG_SZ', url)
    return
  }
  if (def.storage.kind === 'firefox') {
    // Fallback — откат на обычный DNS, Locked — человек может выключить сам
    await regWrite(def.storage.key, 'Enabled', 'REG_DWORD', url === null ? '0' : '1')
    if (url === null) {
      await regDrop(def.storage.key, 'ProviderURL')
      return
    }
    await regWrite(def.storage.key, 'ProviderURL', 'REG_SZ', url)
    await regWrite(def.storage.key, 'Fallback', 'REG_DWORD', '1')
    await regWrite(def.storage.key, 'Locked', 'REG_DWORD', '0')
    return
  }

  const file = def.storage.file()
  const { state, raw } = readLocalState(file)
  if (!state) return
  if (url === null) {
    state.dns_over_https = { mode: 'off' }
  } else {
    state.dns_over_https = { mode: MODE, templates: url }
  }
  // пишем поверх, сохраняя остальное содержимое как есть
  fs.writeFileSync(file, JSON.stringify(state), 'utf8')
  void raw
}

// ------------------------------------------------------------------- наружу

/** Где стоит браузер: хоть один из известных путей есть на диске. */
function installed(def: BrowserDef): boolean {
  return def.exe().some((file) => fs.existsSync(file))
}

/** Состояние всех четырёх браузеров. */
export async function scanBrowsers(): Promise<BrowserDoh[]> {
  if (!IS_WINDOWS) return []
  return Promise.all(
    BROWSERS.map(async (def) => {
      const present = installed(def)
      const running = present && (await pidsByName(def.process)).length > 0
      const state = present ? await readState(def) : { on: false, template: '' }
      return {
        id: def.id,
        name: def.name,
        installed: present,
        running,
        on: state.on,
        template: state.template,
        confirmed: def.confirmed
      }
    })
  )
}

export interface DohApplyResult {
  /** Где включили или выключили, и это подтвердилось перечитыванием. */
  done: BrowserId[]
  /**
   * Записали, но подтвердить нельзя: браузер сам ведёт DNS и чужую настройку
   * может отвергнуть. Сюда попадает Яндекс Браузер.
   */
  unconfirmed: BrowserId[]
  /** Записали, а перечитывание этого не показало — говорим честно. */
  failed: BrowserId[]
  /** Запущенные браузеры: настройку не трогали. */
  busy: BrowserId[]
}

/**
 * Включает или выключает зашифрованный DNS во всех установленных браузерах.
 *
 * `url === null` — выключить.
 *
 * После записи настройка перечитывается: человеку показываем то, что вышло на
 * самом деле, а не то, что мы собирались сделать.
 */
export async function applyBrowsersDoh(url: string | null): Promise<DohApplyResult> {
  const result: DohApplyResult = { done: [], unconfirmed: [], failed: [], busy: [] }
  if (!IS_WINDOWS) return result

  // сначала снимаем то, что прежние версии писали в куст пользователя
  for (const legacy of LEGACY_USER_KEYS) {
    for (const value of legacy.values) await regDrop(legacy.key, value)
  }

  for (const def of BROWSERS) {
    if (!installed(def)) continue
    if (def.storage.kind === 'local-state' && (await pidsByName(def.process)).length > 0) {
      // запущенный Opera GX перепишет Local State на выходе — запись пропадёт
      result.busy.push(def.id)
      continue
    }
    await writeState(def, url)
    const after = await readState(def)
    const wantOn = url !== null
    const templateOk = url === null || after.template === url
    if (after.on !== wantOn || !templateOk) result.failed.push(def.id)
    else if (def.confirmed) result.done.push(def.id)
    else result.unconfirmed.push(def.id)
  }
  return result
}
