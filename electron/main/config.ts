/**
 * Конфигурация приложения (data/config.json).
 *
 * Формат тот же, что был у прежней версии: миграция не нужна, программа
 * подхватит существующий файл как есть.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { CONFIG_FILE, MANIFEST_FILE, TEMP_DIR } from './paths'
import type {
  AppConfig,
  AutostartSettings,
  GeneralSettings,
  TgwsSettings,
  UpdateSettings,
  ZapretSettings
} from '@shared/contract'

export const CONFIG_VERSION = 2

/** Сайты и адреса для проверки стратегий. Дублирует targets.txt пакета. */
export const DEFAULT_DIAG_TARGETS: string[] = [
  'DiscordMain = "https://discord.com"',
  'DiscordGateway = "https://gateway.discord.gg"',
  'DiscordCDN = "https://cdn.discordapp.com"',
  'DiscordUpdates = "https://updates.discord.com"',
  'YouTubeWeb = "https://www.youtube.com"',
  'YouTubeShort = "https://youtu.be"',
  'YouTubeImage = "https://i.ytimg.com"',
  'YouTubeVideoRedirect = "https://redirector.googlevideo.com"',
  'GoogleMain = "https://www.google.com"',
  'GoogleGstatic = "https://www.gstatic.com"',
  'CloudflareWeb = "https://www.cloudflare.com"',
  'CloudflareCDN = "https://cdnjs.cloudflare.com"',
  'CloudflareDNS1111 = "PING:1.1.1.1"',
  'CloudflareDNS1001 = "PING:1.0.0.1"',
  'GoogleDNS8888 = "PING:8.8.8.8"',
  'GoogleDNS8844 = "PING:8.8.4.4"'
]

export function defaultConfig(): AppConfig {
  return {
    version: CONFIG_VERSION,
    general: {
      language: 'ru',
      minimizeToTray: true,
      startMinimized: false,
      sidebarCollapsed: false,
      checkUpdatesOnStart: true,
      // По умолчанию обходы гаснут вместе с программой: «снять задачу» в
      // диспетчере, падение, выход — winws.exe не остаётся висеть без хозяина.
      stopComponentsOnQuit: true
    },
    autostart: { enabled: false, startZapret: true, startTgws: true, delaySeconds: 0 },
    updates: { autoCheck: true, lastCheck: 0 },
    zapret: {
      strategy: 'general.bat',
      gameMode: 'disabled',
      gameTcpRange: '1024-65535',
      gameUdpRange: '1024-65535',
      ipsetMode: 'loaded',
      diagTargets: [...DEFAULT_DIAG_TARGETS],
      editTargets: false
    },
    tgws: defaultTgws()
  }
}

export function defaultTgws(): TgwsSettings {
  return {
    host: '127.0.0.1',
    port: 1443,
    secret: '',
    dcIp: ['2:149.154.167.220', '4:149.154.167.220'],
    bufKb: 256,
    poolSize: 4,
    verbose: false,
    cfproxy: true,
    forceTestDc: false,
    noSecure: false,
    checkUpdates: false,
    logMaxMb: 5
  }
}

const clampInt = (value: unknown, min: number, max: number, fallback: number): number => {
  const n = Math.trunc(Number(value))
  if (!Number.isFinite(n)) return fallback
  return Math.min(max, Math.max(min, n))
}

const str = (value: unknown, fallback: string): string =>
  typeof value === 'string' && value.length > 0 ? value : fallback

const bool = (value: unknown, fallback: boolean): boolean =>
  typeof value === 'boolean' ? value : fallback

const num = (value: unknown, fallback: number): number => {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function sanitizeGeneral(raw: unknown, fallback: GeneralSettings): GeneralSettings {
  const r = (raw ?? {}) as Partial<GeneralSettings>
  const language = r.language === 'en' ? 'en' : 'ru'
  return {
    language,
    minimizeToTray: bool(r.minimizeToTray, fallback.minimizeToTray),
    startMinimized: bool(r.startMinimized, fallback.startMinimized),
    sidebarCollapsed: bool(r.sidebarCollapsed, fallback.sidebarCollapsed),
    checkUpdatesOnStart: bool(r.checkUpdatesOnStart, fallback.checkUpdatesOnStart),
    stopComponentsOnQuit: bool(r.stopComponentsOnQuit, fallback.stopComponentsOnQuit)
  }
}

function sanitizeAutostart(raw: unknown, fallback: AutostartSettings): AutostartSettings {
  const r = (raw ?? {}) as Partial<AutostartSettings>
  return {
    enabled: bool(r.enabled, fallback.enabled),
    startZapret: bool(r.startZapret, fallback.startZapret),
    startTgws: bool(r.startTgws, fallback.startTgws),
    delaySeconds: clampInt(r.delaySeconds, 0, 600, fallback.delaySeconds)
  }
}

/** Проверять GitHub чаще, чем раз в несколько часов, незачем. */
const CHECK_INTERVAL_SECONDS = 6 * 3600

function sanitizeUpdates(raw: unknown, fallback: UpdateSettings): UpdateSettings {
  const r = (raw ?? {}) as Partial<UpdateSettings>
  return {
    autoCheck: bool(r.autoCheck, fallback.autoCheck),
    lastCheck: num(r.lastCheck, fallback.lastCheck)
  }
}

/** Пора ли снова спрашивать GitHub. */
export function dueForCheck(lastCheck: number): boolean {
  return Date.now() / 1000 - lastCheck > CHECK_INTERVAL_SECONDS
}

function sanitizeZapret(raw: unknown, fallback: ZapretSettings): ZapretSettings {
  const r = (raw ?? {}) as Partial<ZapretSettings>
  const gameMode = (['disabled', 'tcp', 'udp', 'all'] as const).includes(r.gameMode as never)
    ? (r.gameMode as ZapretSettings['gameMode'])
    : fallback.gameMode
  const ipsetMode = (['loaded', 'none', 'any'] as const).includes(r.ipsetMode as never)
    ? (r.ipsetMode as ZapretSettings['ipsetMode'])
    : fallback.ipsetMode
  const targets = Array.isArray(r.diagTargets)
    ? r.diagTargets.map((item) => String(item).trim()).filter((item) => item.length > 0).slice(0, 48)
    : fallback.diagTargets
  return {
    strategy: str(r.strategy, fallback.strategy),
    gameMode,
    gameTcpRange: str(r.gameTcpRange, fallback.gameTcpRange),
    gameUdpRange: str(r.gameUdpRange, fallback.gameUdpRange),
    ipsetMode,
    diagTargets: targets.length > 0 ? targets : [...DEFAULT_DIAG_TARGETS],
    // правка целей по умолчанию выключена, даже если в файле её забыли
    editTargets: bool(r.editTargets, false)
  }
}

function sanitizeTgws(raw: unknown, fallback: TgwsSettings): TgwsSettings {
  const r = (raw ?? {}) as Partial<TgwsSettings>
  const dcIp = Array.isArray(r.dcIp)
    ? r.dcIp.map((item) => String(item).trim()).filter((item) => item.length > 0)
    : fallback.dcIp
  const secret = typeof r.secret === 'string' && r.secret.length > 0 ? r.secret : crypto.randomUUID().replace(/-/g, '').slice(0, 32)
  return {
    host: str(r.host, fallback.host),
    port: clampInt(r.port, 1, 65535, fallback.port),
    secret,
    dcIp: dcIp.length > 0 ? dcIp : fallback.dcIp,
    bufKb: clampInt(r.bufKb, 4, 4096, fallback.bufKb),
    poolSize: clampInt(r.poolSize, 0, 64, fallback.poolSize),
    verbose: bool(r.verbose, fallback.verbose),
    cfproxy: bool(r.cfproxy, fallback.cfproxy),
    forceTestDc: bool(r.forceTestDc, fallback.forceTestDc),
    noSecure: bool(r.noSecure, fallback.noSecure),
    checkUpdates: bool(r.checkUpdates, fallback.checkUpdates),
    logMaxMb: clampInt(r.logMaxMb, 1, 1024, fallback.logMaxMb)
  }
}

/** Приводит любой кусок данных к валидному конфигу, добивая пропуски значением по умолчанию. */
export function normalize(raw: unknown): AppConfig {
  const source = (raw ?? {}) as Record<string, unknown>
  const fallback = defaultConfig()
  return {
    version: CONFIG_VERSION,
    general: sanitizeGeneral(source.general, fallback.general),
    autostart: sanitizeAutostart(source.autostart, fallback.autostart),
    updates: sanitizeUpdates(source.updates, fallback.updates),
    zapret: sanitizeZapret(source.zapret, fallback.zapret),
    tgws: sanitizeTgws(source.tgws, fallback.tgws)
  }
}

/** Пишет атомарно: сначала временный файл рядом, потом подмена. */
function writeJsonAtomic(file: string, data: unknown): boolean {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true })
    const tmp = path.join(
      path.dirname(file),
      `.${path.basename(file)}.${process.pid}.${Date.now()}.tmp`
    )
    fs.writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8')
    fs.renameSync(tmp, file)
    return true
  } catch {
    return false
  }
}

function readJson(file: string): unknown {
  try {
    if (!fs.existsSync(file)) return null
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'))
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

/**
 * Конфиг в памяти. Хранится одним объектом: и главный процесс, и IPC-слой
 * читают его напрямую, без повторного чтения с диска.
 */
class ConfigStore {
  private current: AppConfig = defaultConfig()

  load(): AppConfig {
    this.current = normalize(readJson(CONFIG_FILE))
    if (!fs.existsSync(CONFIG_FILE)) this.save()
    return this.current
  }

  get(): AppConfig {
    return this.current
  }

  save(): boolean {
    return writeJsonAtomic(CONFIG_FILE, this.current)
  }

  /** Глубоко примешивает заплатку и пересанитизирует результат. */
  patch(patch: Record<string, unknown>): AppConfig {
    const merged: Record<string, unknown> = {}
    for (const [section, value] of Object.entries(this.current)) {
      merged[section] =
        value && typeof value === 'object' ? { ...(value as Record<string, unknown>), ...((patch[section] as object) ?? {}) } : (patch[section] ?? value)
    }
    this.current = normalize(merged)
    this.save()
    return this.current
  }
}

export const configStore = new ConfigStore()

/** Манифест установленных версий компонентов (data/components.json). */
export function loadManifest(): Record<string, unknown> {
  return (readJson(MANIFEST_FILE) as Record<string, unknown>) ?? {}
}

export function saveManifest(data: Record<string, unknown>): boolean {
  return writeJsonAtomic(MANIFEST_FILE, data)
}

export const tmpDir = (): string => {
  try {
    fs.mkdirSync(TEMP_DIR, { recursive: true })
  } catch {
    return os.tmpdir()
  }
  return TEMP_DIR
}
