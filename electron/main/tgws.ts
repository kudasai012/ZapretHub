/**
 * Компонент TG WS Proxy (TgWsProxy_windows.exe).
 *
 * Это tray-программа на Python. Мы запускаем её дочерним процессом в
 * портативном режиме (--portable), поэтому её конфиг и логи лежат рядом с
 * ней в TgWsProxy_data/ и полностью управляются из Hub.
 */
import fs from 'node:fs'
import path from 'node:path'
import type { ProcessStatus, TgwsSettings, TgwsState } from '@shared/contract'
import { TGWS_DIR, resolveTgwsDir, resolveTgwsExe } from './paths'
import { configStore } from './config'
import { logger } from './logger'
import { ManagedProcess, STATUS_STOPPED } from './procman'
import { isAdmin } from './win32'

export const EXE_NAME = 'TgWsProxy_windows.exe'
const PORTABLE_DIR = 'TgWsProxy_data'
const CONFIG_NAME = 'config.json'
const LOG_NAME = 'proxy.log'

export class TgwsError extends Error {}

export class TgWsComponent {
  private proc: ManagedProcess | null = null
  private reason = ''

  /** Где лежит пакет: по правилам или там, где его нашли. */
  get dir(): string {
    return resolveTgwsDir()
  }

  /**
   * Путь к exe: спрашиваем у paths — релиз tg-ws-proxy кладёт файл с другим
   * именем (для других систем), и жёсткое имя врало бы «не установлен».
   */
  get exe(): string {
    return resolveTgwsExe() ?? path.join(TGWS_DIR, EXE_NAME)
  }

  get portableDir(): string {
    return path.join(this.dir, PORTABLE_DIR)
  }

  get configFile(): string {
    return path.join(this.portableDir, CONFIG_NAME)
  }

  get logFile(): string {
    return path.join(this.portableDir, LOG_NAME)
  }

  /** Что именно лежит на диске: папка пакета и путь к exe (или null). */
  installFacts(): { dir: string; exe: string | null } {
    return { dir: this.dir, exe: resolveTgwsExe() }
  }

  /**
   * Установлен, когда exe на диске. Работает — тем более: процесс запущен,
   * значит exe нашелся, и врать «не установлен» нельзя.
   */
  installed(): boolean {
    if (this.isRunning()) return true
    return resolveTgwsExe() !== null
  }

  /** Версия из имени рядом лежащего файла, иначе «—». */
  version(): string | null {
    try {
      const marker = path.join(this.dir, 'version.txt')
      if (fs.existsSync(marker)) return fs.readFileSync(marker, 'utf8').trim() || null
    } catch {
      /* нет файла — версия неизвестна */
    }
    return null
  }

  versionDisplay(): string {
    return this.version() ?? '—'
  }

  /**
   * Запоминает версию рядом с exe.
   *
   * Релиз tg-ws-proxy — это один файл TgWsProxy_windows.exe без версии в
   * имени, и самой программе версию не выпросить, поэтому установщик пишет
   * метку сам. Без неё плашка вечно показывала бы «Доступно», хотя компонент
   * только что поставлен.
   */
  recordVersion(version: string): void {
    try {
      fs.writeFileSync(path.join(this.dir, 'version.txt'), version.trim(), 'utf8')
    } catch (error) {
      logger.write(`[tgws] не записал версию ${version}: ${String(error)}`)
    }
  }

  /** Конфиг портативного режима из настроек Hub. */
  private portableConfig(): Record<string, unknown> {
    const t = configStore.get().tgws
    return {
      host: t.host,
      port: t.port,
      secret: t.secret,
      dc_ip: t.dcIp,
      verbose: t.verbose,
      buf_kb: t.bufKb,
      pool_size: t.poolSize,
      cfproxy: t.cfproxy,
      force_test_dc: t.forceTestDc,
      no_secure: t.noSecure,
      check_updates: t.checkUpdates,
      log_max_mb: t.logMaxMb,
      language: configStore.get().general.language
    }
  }

  /** Записывает конфиг портативного режима на диск. */
  writeConfig(): void {
    try {
      fs.mkdirSync(this.portableDir, { recursive: true })
      fs.writeFileSync(this.configFile, JSON.stringify(this.portableConfig(), null, 2), 'utf8')
    } catch (error) {
      throw new TgwsError(
        `Не удалось записать конфиг TG WS Proxy: ${error instanceof Error ? error.message : error}`
      )
    }
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
    return 'TG WS Proxy'
  }

  async start(): Promise<{ ok: boolean; reason: string }> {
    if (this.isRunning()) return { ok: true, reason: '' }
    this.reason = ''
    if (!this.installed()) {
      this.reason = 'компонент не установлен'
      return { ok: false, reason: this.reason }
    }
    if (!(await isAdminSafe())) {
      this.reason = 'нужны права администратора'
      return { ok: false, reason: this.reason }
    }

    try {
      this.writeConfig()
    } catch (error) {
      this.reason = error instanceof Error ? error.message : String(error)
      return { ok: false, reason: this.reason }
    }

    this.proc = new ManagedProcess({
      key: 'tgws',
      command: this.exe,
      args: ['--portable'],
      cwd: this.dir,
      logName: 'tgws.log',
      // TgWsProxy в портативном режиме распаковывает копию себя, и процесс,
      // который остаётся висеть в трее, называется не так, как файл, который
      // мы запустили. Раньше из-за этого «завершить задачу» гасило zapret, а
      // прокси продолжал висеть: и по имени образа его не взять, и по номеру —
      // запущенный нами процесс к тому времени уже вышел. Поэтому добиваем по
      // подстроке в пути («TgWsProxy») и по порту, который он слушает.
      killNeedle: 'TgWsProxy',
      killPort: configStore.get().tgws.port,
      onLog: (line) => logger.writeTo('tgws.log', line),
      onStatus: (status) => {
        if (status === 'crashed') this.reason = this.proc?.currentReason || 'процесс завершился'
        else if (status === 'running') this.reason = ''
      }
    })
    this.proc.start()
    await new Promise((resolve) => setTimeout(resolve, 500))
    if (this.proc.currentStatus === 'crashed') {
      this.reason = this.proc.currentReason || 'процесс завершился'
      return { ok: false, reason: this.reason }
    }
    this.reason = ''
    return { ok: true, reason: '' }
  }

  async stop(): Promise<{ ok: boolean; reason: string }> {
    await this.proc?.stop()
    this.proc = null
    this.reason = ''
    return { ok: true, reason: '' }
  }

  /** Как и у zapret: перезапуск программы не должен гасить обход. */
  releaseGuardian(): void {
    this.proc?.releaseGuardian()
  }

  /** Хвост лога прокси — он пишет свой собственный файл. */
  tailLog(lines = 60): string[] {
    try {
      if (!fs.existsSync(this.logFile)) return []
      const text = fs.readFileSync(this.logFile, 'utf8')
      return text.split(/\r?\n/).filter(Boolean).slice(-lines)
    } catch {
      return []
    }
  }

  /** Освобождает таймеры. Зовётся при выходе из программы. */
  dispose(): void {
    this.proc?.dispose()
    this.proc = null
  }

  snapshot(): TgwsState {
    return {
      status: this.status,
      installed: this.installed(),
      version: this.versionDisplay(),
      settings: { ...configStore.get().tgws },
      reason: this.reason,
      dir: this.dir
    }
  }
}

async function isAdminSafe(): Promise<boolean> {
  return isAdmin()
}

/** Настройки по умолчанию для TgWsProxy, если файла ещё нет. */
export function defaultPortableConfig(settings: TgwsSettings): Record<string, unknown> {
  return {
    host: settings.host,
    port: settings.port,
    secret: settings.secret,
    dc_ip: settings.dcIp,
    verbose: settings.verbose,
    buf_kb: settings.bufKb,
    pool_size: settings.poolSize,
    cfproxy: settings.cfproxy,
    force_test_dc: settings.forceTestDc,
    no_secure: settings.noSecure,
    check_updates: settings.checkUpdates,
    log_max_mb: settings.logMaxMb
  }
}
