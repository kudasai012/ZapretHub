/**
 * Слой IPC: превращает контракт из shared/ в настоящие вызовы.
 *
 * Каждый метод контракта регистрируется здесь один раз. Интерфейс ничего не
 * знает о Node: он зовёт window.hub.config.save(...) и получает ответ —
 * точно так же, как звал бы обычный HTTP-эндпоинт.
 */
import { spawn } from 'node:child_process'
import { app, BrowserWindow, ipcMain, shell } from 'electron'
import type {
  AppUpdateInfo,
  ComponentKey,
  ComponentVersion,
  DiagnosticsTargetResult,
  ErrorNotice,
  HomeState,
  MainEvents,
  UpdateInfo
} from '@shared/contract'
import { markUiClose } from './close-intent'
import { configStore, DEFAULT_DIAG_TARGETS } from './config'
import { logger } from './logger'
import { openInFileManager, uninstallerPath } from './paths'
import { ZapretComponent } from './zapret'
import { TgWsComponent } from './tgws'
import { STATUS_STOPPED } from './procman'
import { checkAll, checkTarget, parseTarget, parseTargets, probeAll, targets } from './diagnostics'
import {
  fixConflicts,
  fixDiscordCache,
  fixWinDivert,
  fixZapretService,
  runSystemChecks,
  type SysFix
} from './sysdiag'
import { pickWinner } from '@shared/scoring'
import {
  checkApp,
  checkComponents,
  componentVersions,
  applyAppUpdate,
  applyComponentUpdate
} from './updater'
import type { BrowserId } from './browsers'
import { BROWSER_NAMES, DOH_PROVIDERS, applyBrowsersDoh } from './browsers'
import { enableTcpTimestamps, setAutostart, tcpTimestampsOpt, timestampsOn } from './win32'

export interface Services {
  zapret: ZapretComponent
  tgws: TgWsComponent
}

let services: Services

export function attachServices(next: Services): void {
  services = next
}

/**
 * Проверка обновлений с рассылкой результата в интерфейс.
 *
 * Зовётся и при запуске программы, и по кнопке «Проверить»: если обновление
 * нашлось, интерфейс узнаёт о нём сам и может показать плашку — незачем
 * заставлять человека искать её в настройках.
 */
export async function announceUpdates(
  force: boolean
): Promise<{ checked: UpdateInfo[]; versions: ComponentVersion[]; app: AppUpdateInfo | null }> {
  const checked = await checkComponents(services.zapret, services.tgws, force)
  for (const info of checked) emit('update:available', info)
  const app = await checkApp(force)
  if (app) emit('app-update:available', app)
  broadcastAll()
  return { checked, versions: componentVersions(services.zapret, services.tgws), app }
}

/** Рассылает событие во все окна. */
export function emit<K extends keyof MainEvents>(channel: K, payload: MainEvents[K]): void {
  for (const window of BrowserWindow.getAllWindows()) {
    window.webContents.send(channel, payload)
  }
}

const ok = (reason = ''): { ok: boolean; reason: string } => ({ ok: true, reason })
const fail = (reason: string): { ok: boolean; reason: string } => ({ ok: false, reason })

/**
 * Показывает ошибку в отдельном окне.
 *
 * Тост для этого не годится: он исчезает и не вмещает ни путь, ни стек.
 * Пишем и в журнал — окно закрывают, а запись остаётся.
 */
function notice(
  source: ErrorNotice['source'],
  title: string,
  message: string,
  detail?: string
): void {
  logger.write(`[ошибка/${source}] ${title}: ${message}${detail ? ` (${detail})` : ''}`)
  emit('error:notice', { source, title, message, detail })
}

function componentOf(key: ComponentKey): ZapretComponent | TgWsComponent {
  return key === 'zapret' ? services.zapret : services.tgws
}

/** Снимок главного экрана. */
function homeSnapshot(): HomeState {
  const z = services.zapret.snapshot()
  const t = services.tgws.snapshot()
  return {
    zapret: {
      key: 'zapret',
      status: z.status,
      installed: z.installed,
      version: z.version,
      reason: z.reason
    },
    tgws: { key: 'tgws', status: t.status, installed: t.installed, version: t.version, reason: t.reason },
    zapretState: z,
    tgwsState: t,
    anyRunning: services.zapret.isRunning() || services.tgws.isRunning()
  }
}

/** Оповещает интерфейс об изменении состояния того или иного компонента. */
export function broadcastAll(): void {
  emit('home:state', homeSnapshot())
  emit('zapret:state', services.zapret.snapshot())
  emit('tgws:state', services.tgws.snapshot())
}

export function registerIpc(): void {
  // ---------------------------------------------------------------- конфиг
  ipcMain.handle('config:get', () => configStore.get())
  ipcMain.handle('config:save', (_event, patch: Record<string, unknown>) => {
    const saved = configStore.patch(patch)
    // автозапуск — запись в реестре, поэтому применяем сразу
    if (patch && typeof patch === 'object' && 'autostart' in patch) {
      void setAutostart(saved.autostart.enabled, process.execPath).catch(() => {})
    }
    broadcastAll()
    // Интерфейс мог не быть тем, кто менял настройки: пусть узнает сам.
    emit('config:changed', saved)
    return saved
  })

  // ---------------------------------------------------------------- главная
  ipcMain.handle('home:snapshot', () => homeSnapshot())

  // ---------------------------------------------------------------- zapret
  ipcMain.handle('zapret:snapshot', () => services.zapret.snapshot())

  ipcMain.handle('zapret:setStrategy', (_event, name: string) => {
    configStore.get().zapret.strategy = name
    configStore.save()
    const snapshot = services.zapret.snapshot()
    emit('zapret:state', snapshot)
    return snapshot
  })

  ipcMain.handle('zapret:setGameFilter', (_event, patch: Record<string, unknown>) => {
    const z = configStore.get().zapret
    if (typeof patch.mode === 'string') z.gameMode = patch.mode as typeof z.gameMode
    if (typeof patch.tcp === 'string') z.gameTcpRange = patch.tcp
    if (typeof patch.udp === 'string') z.gameUdpRange = patch.udp
    configStore.save()
    const snapshot = services.zapret.snapshot()
    emit('zapret:state', snapshot)
    return snapshot
  })

  ipcMain.handle('zapret:setIpsetMode', (_event, mode: string) => {
    services.zapret.applyIpsetMode(mode)
    configStore.save()
    const snapshot = services.zapret.snapshot()
    emit('zapret:state', snapshot)
    return snapshot
  })

  ipcMain.handle('zapret:lists', () => services.zapret.listFiles())
  ipcMain.handle('zapret:readList', (_event, name: string) => services.zapret.readUserList(name))
  ipcMain.handle('zapret:writeList', (_event, name: string, text: string) => {
    services.zapret.writeUserList(name, text)
    return services.zapret.listFiles()
  })
  ipcMain.handle('zapret:commandLine', (_event, name?: string) => services.zapret.commandLineDisplay(name))
  ipcMain.handle('zapret:removeService', async () => {
    const removed = await services.zapret.removeService()
    return removed
      ? ok('служба удалена')
      : fail('не удалось удалить службу — возможно, она не установлена')
  })

  // ---------------------------------------------------------------- tgws
  ipcMain.handle('tgws:snapshot', () => services.tgws.snapshot())
  ipcMain.handle('tgws:saveSettings', (_event, patch: Record<string, unknown>) => {
    const target = configStore.get().tgws as unknown as Record<string, unknown>
    const key: Record<string, string> = {
      host: 'host', port: 'port', secret: 'secret', dcIp: 'dcIp', bufKb: 'bufKb',
      poolSize: 'poolSize', verbose: 'verbose', cfproxy: 'cfproxy', forceTestDc: 'forceTestDc',
      noSecure: 'noSecure', checkUpdates: 'checkUpdates', logMaxMb: 'logMaxMb'
    }
    for (const [name, value] of Object.entries(patch)) {
      const mapped = key[name]
      if (mapped) target[mapped] = value
    }
    configStore.save()
    const snapshot = services.tgws.snapshot()
    emit('tgws:state', snapshot)
    return snapshot
  })

  // ---------------------------------------------------------------- процессы
  const startOne = async (key: ComponentKey): Promise<{ ok: boolean; reason: string }> => {
    const component = componentOf(key)
    const result = await component.start()
    broadcastAll()
    if (!result.ok) {
      notice(
        'start',
        key === 'zapret' ? 'Не удалось включить zapret' : 'Не удалось включить TG WS Proxy',
        result.reason || 'причина не названа',
        key
      )
      return fail(result.reason)
    }
    return ok()
  }

  ipcMain.handle('process:start', (_event, key: ComponentKey) => startOne(key))
  ipcMain.handle('process:stop', async (_event, key: ComponentKey) => {
    const component = componentOf(key)
    const result = await component.stop()
    broadcastAll()
    return result.ok ? ok() : fail(result.reason)
  })

  ipcMain.handle('process:startAll', async () => {
    const z = await services.zapret.start()
    const t = await services.tgws.start()
    broadcastAll()
    if (!z.ok) notice('start', 'Не удалось включить zapret', z.reason || 'причина не названа', 'zapret')
    if (!t.ok) notice('start', 'Не удалось включить TG WS Proxy', t.reason || 'причина не названа', 'tgws')
    const reasons = [z.reason, t.reason].filter(Boolean)
    return z.ok || t.ok ? ok(reasons.join('; ')) : fail(reasons.join('; ') || 'ничего не запустилось')
  })

  ipcMain.handle('process:stopAll', async () => {
    await services.zapret.stop()
    await services.tgws.stop()
    broadcastAll()
    return ok()
  })

  // ---------------------------------------------------------------- диагностика
  ipcMain.handle('diagnostics:targets', () => {
    const configured = configStore.get().zapret.diagTargets
    return configured.length > 0 ? configured : DEFAULT_DIAG_TARGETS
  })

  ipcMain.handle('diagnostics:saveTargets', (_event, lines: string[]) => {
    const cleaned = lines.map((line) => line.trim()).filter((line) => line.length > 0).slice(0, 48)
    configStore.get().zapret.diagTargets = cleaned.length > 0 ? cleaned : [...DEFAULT_DIAG_TARGETS]
    configStore.save()
    return configStore.get().zapret.diagTargets
  })

  ipcMain.handle('diagnostics:checkOne', async (_event, line: string) => {
    const parsed = parseTarget(line)
    if (!parsed) {
      return { name: line, address: line, httpOk: false, httpStatus: 0, httpCode: 0, pingOk: false, pingMs: null, error: 'не удалось разобрать цель' }
    }
    return checkTargetSafe(parsed)
  })

  ipcMain.handle('diagnostics:checkAll', async () => {
    try {
      return await checkAll()
    } catch (error) {
      notice('check', 'Проверка сайтов не удалась', error instanceof Error ? error.message : String(error))
      throw error
    }
  })
  ipcMain.handle('diagnostics:probeAll', async () => {
    try {
      return await probeAll()
    } catch (error) {
      notice('check', 'Проверка сайтов не удалась', error instanceof Error ? error.message : String(error))
      throw error
    }
  })

  /**
   * Прогон стратегии.
   *
   * Стратегия проверяется на живой системе, поэтому всё последовательно и с
   * паузами: фильтр WinDivert освобождает ядро не мгновенно.
   */
  ipcMain.handle('diagnostics:testStrategy', async (_event, strategy: string) => {
    const previous = configStore.get().zapret.strategy
    const wasRunning = services.zapret.isRunning()

    if (wasRunning) await services.zapret.stop()
    configStore.get().zapret.strategy = strategy
    configStore.save()

    const started = await services.zapret.start()
    // Стратегия не поднялась — результат не выкидываем, а показываем причину
    // по каждой цели. Пустой список выглядел как «проверок не было» (0% из 0),
    // хотя проверять было что.
    const results = started.ok ? await checkAll() : failedTargets(started.reason)
    if (!started.ok) {
      // стратегия не поднялась — показываем это вместо пустого результата
      emit('strategy:progress', { strategy, results })
    } else {
      emit('strategy:progress', { strategy, results })
    }

    if (!started.ok) {
      notice(
        'check',
        `Стратегия не запустилась: ${strategy}`,
        started.reason || 'причина не названа'
      )
    }

    await services.zapret.stop()
    configStore.get().zapret.strategy = previous
    configStore.save()

    const finalResults = results
    emit('strategy:done', { strategy, results: finalResults })
    broadcastAll()
    return { strategy, status: 'done' as const, results: finalResults, startedAt: Date.now(), finishedAt: Date.now() }
  })

  /** Идёт ли прогон прямо сейчас: по этому ответу экран не запускает второй. */
  ipcMain.handle('diagnostics:status', () => ({
    busy: sweep.busy,
    strategy: sweep.strategy,
    done: sweep.done,
    total: sweep.total
  }))

  /** Остановить прогон: до конца текущей стратегии, потом всё вернётся как было. */
  ipcMain.handle('diagnostics:stop', () => {
    if (!sweep.busy) return { ok: false, reason: 'прогон не идёт' }
    sweep.stop = true
    sweep.cancel?.()
    return { ok: true, reason: '' }
  })

  /**
   * Прогон набора стратегий.
   *
   * Пустой набор — значит «все»: набор выбирают галочками, а галочки можно и
   * не трогать.
   */
  ipcMain.handle(
    'diagnostics:runQueue',
    async (_event, names: string[]) => {
      if (sweep.busy) {
        return { busy: true, winner: null, applied: false, results: {} }
      }
      const all = services.zapret.snapshot().strategies
      const queue = names.length > 0 ? names.filter((name) => all.includes(name)) : all
      if (queue.length === 0) {
        return { busy: false, winner: null, applied: false, results: {} }
      }

      sweep.busy = true
      sweep.stop = false
      sweep.done = 0
      sweep.total = queue.length
      const results: Record<string, DiagnosticsTargetResult[]> = {}

      try {
        for (const strategy of queue) {
          if (sweep.stop) break
          sweep.strategy = strategy
          sweepProgress()
          const run = await runStrategy(strategy)
          results[strategy] = run.results
          emit('strategy:progress', { strategy, results: run.results })
          emit('strategy:done', { strategy, results: run.results })
          sweep.done += 1
          sweepProgress()
        }

        const winner = pickWinner(results, queue)
        let applied = false
        if (winner) {
          configStore.get().zapret.strategy = winner
          configStore.save()
          applied = true
        }
        emit('diagnostics:done', { winner, applied, results })
        broadcastAll()
        return { busy: false, winner, applied, results }
      } finally {
        sweep.busy = false
        sweep.strategy = null
        sweep.stop = false
        sweep.done = 0
        sweep.total = 0
      }
    }
  )

  // ---------------------------------------------------------------- обновления

  /**
   * Проверка обновлений с рассылкой результата в интерфейс.
   *
   * Зовётся и при запуске программы, и по кнопке «Проверить»: если обновление
   * нашлось, интерфейс узнаёт о нём сам и может показать плашку — незачем
   * заставлять человека искать её в настройках.
   */
  ipcMain.handle('updates:announce', (_event, force: boolean) => announceUpdates(force))
  ipcMain.handle('sysdiag:run', async () => {
    try {
      return await runSystemChecks()
    } catch (error) {
      logger.write(`[ipc] диагностика системы не удалась: ${String(error)}`)
      return []
    }
  })

  ipcMain.handle('sysdiag:fix', async (_event, id: SysFix, option?: string) => {
    const fixes: Record<SysFix, (option?: string) => Promise<{ ok: boolean; message: string }>> = {
      windivert: fixWinDivert,
      conflicts: fixConflicts,
      'zapret-service': fixZapretService,
      timestamps: async () => {
        await enableTcpTimestamps()
        // перечитываем систему, а не верим вспомогательной функции: именно из-за
        // веры ей программа раньше рапортовала «починено» там, где ничего не вышло
        const on = timestampsOn(await tcpTimestampsOpt())
        return on
          ? { ok: true, message: 'TCP-метки времени включены' }
          : { ok: false, message: 'Включить метки времени не удалось' }
      },
      discord: fixDiscordCache,
      // Зашифрованный DNS в браузерах. option — id провайдера или 'off'.
      doh: async (option?: string) => {
        if (!option) return { ok: false, message: 'Провайдер не выбран' }
        const preset = DOH_PROVIDERS.find((item) => item.id === option)
        if (option !== 'off' && !preset) return { ok: false, message: 'Провайдер не выбран' }
        const provider = preset ? preset.url : null
        const applied = await applyBrowsersDoh(provider)
        const names = (ids: BrowserId[]) => ids.map((id) => BROWSER_NAMES[id]).join(', ')
        const parts: string[] = []
        if (applied.done.length > 0) {
          parts.push(provider ? `Включено: ${names(applied.done)}` : `Выключено: ${names(applied.done)}`)
        }
        if (applied.unconfirmed.length > 0) {
          // Яндекс Браузер сам подменяет DNS: настройку мы записали, а принял
          // он её или нет — из реестра не видно. Об этом и говорим.
          parts.push(
            `${names(applied.unconfirmed)}: настройка записана, но браузер ведёт DNS сам и мог её не принять — проверьте browser://policy`
          )
        }
        if (applied.busy.length > 0) {
          parts.push(`закройте и повторите: ${names(applied.busy)}`)
        }
        if (applied.failed.length > 0) {
          parts.push(`не вышло: ${names(applied.failed)}`)
        }
        return {
          ok: applied.failed.length === 0,
          message: parts.join('; ') || 'Браузеров с такой настройкой не найдено'
        }
      }
    }
    const fix = fixes[id]
    if (!fix) return { ok: false, message: `неизвестная починка: ${id}` }
    try {
      return await fix(option)
    } catch (error) {
      return { ok: false, message: String(error) }
    }
  })

  ipcMain.handle('updates:check', async (_event, force: boolean) => {
    try {
      const found = await checkComponents(services.zapret, services.tgws, force)
      for (const info of found) emit('update:available', info)
      broadcastAll()
      return { checked: found, versions: componentVersions(services.zapret, services.tgws) }
    } catch (error) {
      // Сеть может отвалиться в любую секунду, и это не сбой программы:
      // говорим словами, что не смогли связаться с GitHub.
      notice(
        'update',
        'Не удалось проверить обновления',
        error instanceof Error ? error.message : String(error),
        'github.com'
      )
      throw error
    }
  })

  ipcMain.handle('updates:apply', async (_event, key: ComponentKey) => {
    const result = await applyComponentUpdate(key, services.zapret, services.tgws)
    if (result.ok) {
      broadcastAll()
    } else {
      notice('update', `Не удалось обновить: ${key}`, result.message)
    }
    return result
  })

  ipcMain.handle('app-update:check', async (_event, force: boolean) => {
    const info = await checkApp(force)
    if (info) emit('app-update:available', info)
    return { available: info !== null, info }
  })

  ipcMain.handle('app-update:apply', async () => {
    // Установщик гасит программу и подменяет её файлы. Пока winws.exe работает,
    // файлы компонентов заняты, и обновление садится посреди установки —
    // поэтому гасим обходы сами, до запуска установщика (компоненты программы
    // гасят и при выходе, и здесь).
    await services?.zapret?.stop()
    await services?.tgws?.stop()
    const result = await applyAppUpdate()
    if (result.ok) broadcastAll()
    return result
  })

  // ---------------------------------------------------------------- прочее
  ipcMain.handle('shell:openPath', async (_event, target: 'components' | 'logs') => {
    const opened = await openInFileManager(target)
    if (!opened.ok) {
      notice(
        'folder',
        target === 'components' ? 'Не удалось открыть папку компонентов' : 'Не удалось открыть папку логов',
        opened.reason || 'проводник не ответил',
        opened.path
      )
    }
    return opened
  })

  ipcMain.handle('shell:openUrl', async (_event, url: string) => {
    // tg:// тоже пускаем: ссылка на прокси открывает сам Telegram, а не браузер
    if (!/^(https?:|tg:\/\/)/i.test(url)) return { ok: false }
    await shell.openExternal(url)
    return { ok: true }
  })

  ipcMain.handle('window:minimize', (event) => {
    BrowserWindow.fromWebContents(event.sender)?.minimize()
  })
  ipcMain.handle('window:close', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    if (!window) return
    // Крестик нарисован в интерфейсе, и это единственный случай, когда
    // закрытие идет от человека, а не от системы. Помечаем, чтобы обработчик
    // закрытия окна не спутал его с «Завершить задачу».
    markUiClose()
    window.close()
  })
  ipcMain.handle('window:isMaximized', (event) => {
    return BrowserWindow.fromWebContents(event.sender)?.isMaximized() ?? false
  })

  ipcMain.handle('window:toggleMaximize', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    if (!window) return
    if (window.isMaximized()) window.unmaximize()
    else window.maximize()
    emit('window:maximized', window.isMaximized())
  })

  // ---------------------------------------------------------------- программа
  ipcMain.handle('app:version', () => app.getVersion())

  /**
   * Перезапуск программы.
   *
   * Конфиг зовущая сторона сохраняет до вызова. Дальше app.relaunch() ставит
   * новый экземпляр в очередь, а app.exit() гасит текущий — именно exit, а не
   * quit: quit мог бы уйти в обработчик before-quit и повиснуть.
   *
   * Дозорные снимаем до перезапуска: перезапуск — это не выход, обходы должны
   * продолжать работать, пока новый экземпляр не подхватит их. Иначе дозорный
   * принял бы исчезновение программы за аварию и погасил обходы.
   */
  ipcMain.handle('app:restart', () => {
    logger.write('[hub] перезапуск по просьбе интерфейса')
    services?.zapret?.releaseGuardian()
    services?.tgws?.releaseGuardian()
    app.relaunch()
    app.exit(0)
  })

  /**
   * Удаление программы.
   *
   * Кнопка есть всегда, но работает только у копии, поставленной установщиком:
   * у запущенной из исходников деинсталлятора нет, и человеку об этом говорят
   * прямо, а не подсовывают кнопку, которая ничего не делает.
   */
  ipcMain.handle('app:uninstallInfo', () => {
    const target = uninstallerPath()
    return {
      path: target ?? '',
      reason: target ? '' : 'деинсталлятор не найден'
    }
  })

  ipcMain.handle('app:uninstall', async () => {
    const target = uninstallerPath()
    if (!target) return { ok: false, reason: 'деинсталлятор не найден' }
    logger.write('[hub] удаление программы: ' + target)
    try {
      // Отсоединённо: деинсталлятор живёт своей жизнью, программа уже уходит.
      spawn(target, [], { detached: true, stdio: 'ignore' }).unref()
    } catch (error) {
      return { ok: false, reason: String(error) }
    }
    // Закрываемся чуть погодя: иначе деинсталлятор первым делом спросит,
    // закрыть ли запущенную программу, и человек увидит лишний вопрос.
    setTimeout(() => {
      services?.zapret?.releaseGuardian()
      services?.tgws?.releaseGuardian()
      app.quit()
    }, 900)
    return { ok: true, reason: target }
  })

  logger.write('[hub] IPC зарегистрирован')
}

/** Результат «проверять нечего, стратегия не встала» — по каждой цели. */
function failedTargets(reason: string): DiagnosticsTargetResult[] {
  return targets().map((target) => ({
    name: target.name,
    address: target.address,
    httpOk: false,
    httpStatus: 0,
    httpCode: 0,
    pingOk: false,
    pingMs: null,
    error: `стратегия не запустилась: ${reason}`
  }))
}

/**
 * Прогон набора стратегий — в главном процессе.
 *
 * Раньше очередь перебирала интерфейс, и это ломалось двумя способами. Уходишь
 * с раздела диагностики — прогон обрывался на середине, и узнать, какая
 * стратегия лучше, было нельзя. Возвращаешься — прогона как будто и не было,
 * и человек нажимал «Прогнать» ещё раз, получая второй обход поверх первого.
 *
 * Теперь очередь живёт здесь: её не видно на экране, но её не видно и в
 * переходах между разделами. Ход дела приходит событиями, интерфейс только
 * показывает; остановить прогон можно кнопкой.
 */
const sweep = {
  busy: false,
  /** Какую стратегию проверяем прямо сейчас. */
  strategy: null as string | null,
  done: 0,
  total: 0,
  /** Попросили остановиться: до конца текущей стратегии и выходим. */
  stop: false,
  cancel: null as (() => void) | null
}

/**
 * Прогон одной стратегии: поднять winws, проверить сайты, погасить, вернуть
 * прежнюю стратегию на место.
 *
 * Возвращает результаты проверок и признак, удалось ли запуститься.
 */
async function runStrategy(strategy: string): Promise<{
  results: DiagnosticsTargetResult[]
  started: boolean
  reason: string
}> {
  const previous = configStore.get().zapret.strategy
  const wasRunning = services.zapret.isRunning()

  if (wasRunning) await services.zapret.stop()
  configStore.get().zapret.strategy = strategy
  configStore.save()

  const started = await services.zapret.start()
  // Стратегия не поднялась — результат не выкидываем, а показываем причину
  // по каждой цели. Пустой список выглядел как «проверок не было» (0% из 0),
  // хотя проверять было что.
  const results = started.ok ? await checkAll() : failedTargets(started.reason)

  await services.zapret.stop()
  configStore.get().zapret.strategy = previous
  configStore.save()

  if (!started.ok) {
    notice('check', `Стратегия не запустилась: ${strategy}`, started.reason || 'причина не названа')
  }

  return { results, started: started.ok, reason: started.reason }
}

/** Ход прогона: одна стратегия проверена, идёт следующая. */
function sweepProgress(): void {
  emit('diagnostics:progress', {
    strategy: sweep.strategy ?? '',
    done: sweep.done,
    total: sweep.total
  })
}

/** Проверка цели с защитой от необработанного отказа. */
async function checkTargetSafe(parsed: ReturnType<typeof parseTarget>): Promise<Awaited<ReturnType<typeof checkAll>>[number]> {
  if (!parsed) {
    return { name: '', address: '', httpOk: null, httpStatus: 0, httpCode: 0, pingOk: null, pingMs: null, error: 'пустая цель' }
  }
  try {
    return await checkTarget(parsed)
  } catch (error) {
    return {
      name: parsed.name,
      address: parsed.address,
      httpOk: false,
      httpStatus: 0,
      httpCode: 0,
      pingOk: false,
      pingMs: null,
      error: error instanceof Error ? error.message : String(error)
    }
  }
}

export { STATUS_STOPPED, parseTargets }
