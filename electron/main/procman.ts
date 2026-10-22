/**
 * Управление дочерними процессами компонентов.
 *
 * ManagedProcess оборачивает child_process и:
 *  * читает stdout/stderr и отдаёт строки в интерфейс;
 *  * пишет вывод в лог-файл;
 *  * умеет мягко и жёстко (taskkill /T /F) останавливаться;
 *  * следит за процессом и сообщает о выходе.
 *
 * Процессы компонентов считаются «своими» только пока Hub ими управляет.
 * TgWsProxy_windows.exe — программа с графической подсистемой, она
 * распаковывает себя во временную папку и запускает второй процесс с тем же
 * именем. Поэтому держим не только главный PID, но и всё дерево, а при
 * остановке подчищаем процессы по имени образа — иначе распакованный остаётся
 * висеть отдельной программой и продолжает работать уже без Hub.
 *
 * И ещё одна забота: Windows не убивает дочерние процессы вслед за
 * родителем. Если снять задачу Zapret Hub (диспетчер задач), программа
 * исчезнет, а winws.exe продолжит работать — обход останется включённым без
 * всякого управления, да и файлы компонентов будут заняты. Поэтому рядом с
 * компонентом живёт «дозорный»: крошечный процесс, который гасит компонент,
 * как только исчезла программа.
 */
import { ChildProcess } from 'node:child_process'
import type { ProcessStatus } from '@shared/contract'
import { LOGS_DIR } from './paths'
import { configStore } from './config'
import {
  killForeignProcesses,
  killTree,
  pidsByName,
  powershell,
  spawnDetached,
  spawnGuardian
} from './win32'

export const STATUS_STOPPED: ProcessStatus = 'stopped'
export const STATUS_STARTING: ProcessStatus = 'starting'
export const STATUS_RUNNING: ProcessStatus = 'running'
export const STATUS_STOPPING: ProcessStatus = 'stopping'
export const STATUS_CRASHED: ProcessStatus = 'crashed'

const SWEEP_TIMEOUT_MS = 8000

export interface ManagedOptions {
  key: string
  command: string
  args: string[]
  cwd?: string
  logName?: string
  onStatus?: (status: ProcessStatus, reason?: string) => void
  onLog?: (line: string) => void
  onExit?: (code: number | null) => void
  restartOnCrash?: boolean
  restartDelayMs?: number
}

export class ManagedProcess {
  private proc: ChildProcess | null = null
  private status: ProcessStatus = STATUS_STOPPED
  private reason = ''
  private tree = new Set<number>()
  private restartTimer: NodeJS.Timeout | null = null
  private guardian: ChildProcess | null = null
  private stopping = false
  private readonly options: ManagedOptions

  constructor(options: ManagedOptions) {
    this.options = options
  }

  get currentStatus(): ProcessStatus {
    return this.status
  }

  get currentReason(): string {
    return this.reason
  }

  /** PID наших собственных процессов — их никогда не гасим как чужие. */
  ownPids(): Set<number> {
    return new Set(this.tree)
  }

  isRunning(): boolean {
    return this.status === STATUS_RUNNING || this.status === STATUS_STARTING
  }

  private setStatus(status: ProcessStatus, reason = ''): void {
    this.status = status
    this.reason = reason
    this.options.onStatus?.(status, reason)
  }

  private emit(line: string): void {
    this.options.onLog?.(line)
  }

  start(): void {
    if (this.isRunning()) return
    this.stopping = false
    this.reason = ''
    this.setStatus(STATUS_STARTING)

    const { command, args, cwd } = this.options
    this.emit(`[hub] запуск: ${command} ${args.join(' ')}`)

    let child: ChildProcess
    try {
      child = spawnDetached(command, args, { cwd })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.emit(`[hub] не удалось запустить: ${message}`)
      this.setStatus(STATUS_CRASHED, message)
      return
    }

    this.proc = child
    this.tree = new Set(child.pid ? [child.pid] : [])
    this.startGuardian()

    child.stdout?.setEncoding('utf8')
    child.stderr?.setEncoding('utf8')
    child.stdout?.on('data', (chunk: string) => this.emit(chunk.replace(/\r?\n$/, '')))
    child.stderr?.on('data', (chunk: string) => this.emit(chunk.replace(/\r?\n$/, '')))

    child.on('error', (error) => {
      this.emit(`[hub] ошибка процесса: ${error.message}`)
      this.setStatus(STATUS_CRASHED, error.message)
    })

    child.on('exit', (code) => {
      this.proc = null
      this.options.onExit?.(code)
      if (this.stopping) {
        this.setStatus(STATUS_STOPPED)
        return
      }
      this.emit(`[hub] процесс завершился с кодом ${code}`)
      this.setStatus(code === 0 ? STATUS_STOPPED : STATUS_CRASHED, `код выхода ${code}`)
      this.scheduleRestart()
    })

    this.setStatus(STATUS_RUNNING)
  }

  /** Имя образа компонента: winws, TgWsProxy_windows — без .exe и без пути. */
  private imageName(): string {
    return (
      this.options.command
        .split(/[\\/]/)
        .pop()
        ?.replace(/\.exe$/i, '') ?? ''
    )
  }

  /**
   * Ставит дозорного — страховку от смерти программы мимо штатного выхода.
   *
   * Дозорный нужен только тогда, когда обходы должны гаснуть вместе с
   * программой (настройка «Останавливать обходы при выходе»). Кто выключил
   * эту настройку, тот хочет, чтобы обход работал без программы — значит, и
   * дозорный ему не нужен.
   */
  private startGuardian(): void {
    const pid = this.proc?.pid
    if (!pid) return
    if (!configStore.get().general.stopComponentsOnQuit) return
    const image = this.imageName()
    this.guardian = spawnGuardian(process.pid, [pid], image ? [image] : [])
  }

  /** Снимает дозорного: компонент остаётся работать уже без программы. */
  releaseGuardian(): void {
    const guardian = this.guardian
    this.guardian = null
    if (!guardian) return
    try {
      guardian.kill()
    } catch {
      /* дозорный мог уйти сам */
    }
  }

  /**
   * Снимает дерево процессов компонента — один запрос, а не таймер.
   *
   * Раньше дерево переснималось каждые 500 мс, пока компонент работает. Каждый
   * пересчёт — отдельный запуск PowerShell и запрос CIM ко всем процессам
   * Windows: при двух работающих обходах это 240 запусков в минуту, и
   * программа постоянно ела процессор, даже когда человек просто смотрел в
   * открытое окно.
   *
   * Дерево нужно только затем, чтобы знать, какие процессы с тем же именем
   * образа свои: при остановке подчищаем по имени всё, кроме своих. Оба
   * случая, когда оно спрашивается, известны заранее, и ждать полсекунды
   * между ними незачем:
   *   * гасим мы всё дерево одним taskkill /T — дети умирают вместе с
   *     родителем, следить за ними всю работу не нужно;
   *   * список своих PID важен ровно в секунду остановки, поэтому снимок
   *     делается прямо перед ней.
   */
  private async sampleTree(): Promise<void> {
    const pid = this.proc?.pid
    if (!pid) return
    try {
      const result = await powershell(
        `Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq ${pid} } | Select-Object -ExpandProperty ProcessId`,
        // Короткий срок: снимок — уточнение для подчистки, а не обязательное
        // условие. Если PowerShell завис, остановка не должна ждать его.
        2000
      )
      for (const line of result.stdout.split(/\r?\n/)) {
        const child = Number(line.trim())
        if (Number.isFinite(child) && child > 0) this.tree.add(child)
      }
    } catch {
      /* дерево не снялось — подчистим по имени, это надёжнее догадок */
    }
  }

  private scheduleRestart(): void {
    if (!this.options.restartOnCrash) return
    if (this.status !== STATUS_CRASHED) return
    if (this.restartTimer) clearTimeout(this.restartTimer)
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null
      if (this.status === STATUS_CRASHED) {
        this.emit('[hub] перезапуск после сбоя')
        this.start()
      }
    }, this.options.restartDelayMs ?? 5000)
  }

  async stop(): Promise<void> {
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
    const pid = this.proc?.pid
    if (!pid) {
      this.setStatus(STATUS_STOPPED)
      return
    }
    this.stopping = true
    this.setStatus(STATUS_STOPPING)
    this.emit('[hub] остановка')

    // Снимок дерева идёт рядом с гашением, а не до него: гасим мы всё дерево
    // одним taskkill /T, поэтому ждать снимок незачем — он успеет, пока
    // taskkill работает. Подчистка по имени образа смотрит на него после.
    const sampled = this.sampleTree()

    try {
      await killTree(pid)
    } catch {
      /* процесс мог умереть сам */
    }

    await sampled

    // Распакованная копия остаётся висеть по имени образа — подчищаем её.
    const image = this.imageName()
    if (image) {
      const deadline = Date.now() + SWEEP_TIMEOUT_MS
      while (Date.now() < deadline) {
        const alive = await pidsByName(image)
        const foreign = alive.filter((p) => !this.ownPids().has(p))
        if (foreign.length === 0) break
        await killForeignProcesses(image, this.ownPids())
        await new Promise((r) => setTimeout(r, 400))
      }
    }

    // Дозорный снимаем в самом конце: пока он жив, он не даст компоненту
    // остаться на диске в одиночестве, даже если что-то в остановке сорвётся.
    this.releaseGuardian()

    this.proc = null
    this.setStatus(STATUS_STOPPED)
  }

  dispose(): void {
    if (this.restartTimer) clearTimeout(this.restartTimer)
    this.restartTimer = null
    this.releaseGuardian()
  }
}

/** Куда писать вывод компонента, если попросили отдельный файл. */
export function componentLogPath(logName: string): string {
  const fs = require('node:fs') as typeof import('node:fs')
  const path = require('node:path') as typeof import('node:path')
  const target = path.join(LOGS_DIR, logName)
  try {
    fs.mkdirSync(path.dirname(target), { recursive: true })
  } catch {
    /* не смогли — вернём путь всё равно */
  }
  return target
}
