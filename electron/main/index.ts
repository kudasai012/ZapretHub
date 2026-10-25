/**
 * Главный процесс: окно, запуск, трей, жизненный цикл.
 *
 * Программа всегда работает с повышением прав — winws.exe требует WinDivert,
 * а без администратора он не стартует. Поэтому при запуске проверяем права и,
 * если их нет, просим пользователя подняться через UAC.
 */
import { app, BrowserWindow, Tray, Menu, nativeImage, shell, ipcMain } from 'electron'
import path from 'node:path'
import fs from 'node:fs'
import { isUiClose, resetUiClose } from './close-intent'
import { configStore, tmpDir } from './config'
import { ensureDirs, BASE_DIR, APP_DIR_NAME, DATA_ROOT } from './paths'
import { logger } from './logger'
import { ZapretComponent } from './zapret'
import { TgWsComponent } from './tgws'
import { announceUpdates, attachServices, broadcastAll, emit, registerIpc } from './ipc'
import {
  isAdmin,
  LOGIN_ARG,
  relaunchElevated,
  setAutostart,
  startedAtLogin,
  warmUpJobHelper
} from './win32'

// Один экземпляр на машину: две копии Hub дрались бы за один и тот же
// фильтр WinDivert, и вторая просто не запустилась бы.
if (!app.requestSingleInstanceLock()) {
  app.quit()
  process.exit(0)
}

let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null
let zapret: ZapretComponent
let tgws: TgWsComponent
let quitting = false

const devServerUrl = process.env.ELECTRON_RENDERER_URL

function createWindow(): void {
  const config = configStore.get()

  mainWindow = new BrowserWindow({
    width: 1240,
    height: 860,
    minWidth: 980,
    minHeight: 640,
    show: false,
    frame: false,
    backgroundColor: '#09090b',
    title: APP_DIR_NAME,
    icon: windowIconPath(),
    titleBarStyle: 'hidden',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
      // devtools полезны и в собранной программе: в них видно журнал и сеть
      devTools: true
    }
  })

  // Развёрнуто окно или нет — состояние нужно интерфейсу, чтобы кнопка в
  // верхней полосе показывала «развернуть» или «восстановить». Событие, а не
  // опрос: опрос ради одной иконки — лишняя работа.
  mainWindow.on('maximize', () => broadcastWindowState(mainWindow))
  mainWindow.on('unmaximize', () => broadcastWindowState(mainWindow))

  mainWindow.on('ready-to-show', () => {
    if (!mainWindow) return
    // «Запускать свёрнутым» — про окно, а не про способ запуска: человек
    // включил эту настройку и ждёт, что программа поднимется в трей и молча
    // начнёт работать. Раньше окно показывалось всегда, если программа
    // запущена руками, а не автозапуском Windows.
    //
    // Тот же смысл у ключа --tray: его пишет в реестр автозапуск (см.
    // setAutostart), и раньше программа его не замечала — при входе в Windows
    // окно открывалось само, хотя автозапуску велено подняться в трей.
    if (config.general.startMinimized) {
      logger.write('[hub] окно не показываем: включено «запускать свёрнутым»')
      return
    }
    if (startedAtLogin()) {
      // Сюда попадаем только при входе в Windows: автозапуск поднимает
      // программу в трей, и окно на экране появляться не должно.
      logger.write(`[hub] вход в Windows (${LOGIN_ARG}): окно не показываем`)
      return
    }
    mainWindow.show()
  })

  /**
   * Крестик и всё остальное.
   *
   * Крестик нарисован в интерфейсе, поэтому его видно: он приходит вызовом
   * оттуда. Если «свернуть в трей» включено — окно прячется, программа
   * остаётся работать; если выключено — крестик закрывает программу совсем
   * (раньше окно исчезало, а программа оставалась висеть в трее, и выбраться
   * оттуда можно было только через меню трея).
   *
   * Всё остальное — «Завершить задачу» в панели задач, «Закрыть все окна»,
   * выход из Windows — приходит как просьба закрыться от системы, мимо
   * интерфейса. Здесь прятаться в трей нельзя ни в коем случае: Windows
   * считает задачу исполненной, как только окна не стало, и принудительно
   * гасить нас не станет. Программа останется жить в трее, а вместе с ней и
   * компоненты — сколько их потом ни добивай. Поэтому на чужую просьбу
   * закрываемся по-настоящему.
   */
  mainWindow.on('close', (event) => {
    if (quitting) return
    const settings = configStore.get().general
    if (isUiClose() && settings.minimizeToTray) {
      resetUiClose()
      event.preventDefault()
      mainWindow?.hide()
      return
    }
    resetUiClose()
    event.preventDefault()
    quitting = true
    void (async () => {
      // Настройку «останавливать обходы при выходе» уважаем и здесь: кто
      // просил оставить обход работать без программы, тот его и получит.
      if (settings.stopComponentsOnQuit) await stopAllSafely()
      app.quit()
    })()
  })

  if (devServerUrl) {
    void mainWindow.loadURL(devServerUrl)
  } else {
    void mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'))
  }

  // внешние ссылки открываем в браузере по умолчанию, а не внутри окна
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })
}

/**
 * Иконка приложения: рядом с exe, рядом с dev-сборкой, затем внутри asar.
 * Внутренний кандидат идёт до BASE_DIR, потому что рядом с exe в собранном
 * приложении icon.ico нет (electron-builder вживляет её в сам exe), а в asar
 * build/icon.png лежит всегда — она же гарантия непустой иконки в трее.
 */
function appIconPath(): string | undefined {
  const candidates = [
    path.join(__dirname, '../../build/icon.png'),
    path.join(__dirname, '../../build/icon.ico'),
    path.join(BASE_DIR, 'assets', 'icon.ico'),
    path.join(BASE_DIR, 'build', 'icon.ico')
  ]
  return candidates.find((candidate) => fs.existsSync(candidate))
}

/**
 * Иконка окна: Windows понимает и PNG, но .ico несёт сразу все размеры —
 * поэтому для окна предпочитаем его, а PNG остаётся запасным вариантом.
 */
function windowIconPath(): string | undefined {
  const candidates = [
    path.join(__dirname, '../../build/icon.ico'),
    path.join(BASE_DIR, 'assets', 'icon.ico'),
    path.join(BASE_DIR, 'build', 'icon.ico'),
    path.join(__dirname, '../../build/icon.png')
  ]
  return candidates.find((candidate) => fs.existsSync(candidate)) ?? appIconPath()
}

/**
 * Запасная иконка: пустой nativeImage даёт в трее пустое место,
 * поэтому встроен маленький PNG (32×32, тёмный круг с молнией) — тот же знак,
 * что в окне. Два представления (1x и 2x), чтобы иконка была резкой на любом DPI.
 */
const FALLBACK_ICON_DATA_URL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAABH0lEQVR4nM2X3QrDIAyFVXYpFAp7/wccFATvu4uRksZozU+3nUvrej5PQlZjECrnZR89r7VEyfumNmPTbXsN967rUwRzuQHMwRgbcKL7riC6D6XGWhB2EZtLjTmQEUS60zyETwKQBtfAJwAPc65JRxBNAt7mHAQLkPOye8Q++j1A4BQSmJtcw/V8oALPI4G7oqeipWh64NuK1trj00jeAZ6mBKR15/TwNKdrM4nc1gOz5VABeEQPUpWAnk4TPchcAou5C4BVqdYSe38UUs2eHmZArSW6JaAdZAeAJgVNanTqphDkn9JUmtODZ8ILmhQ08x8fuOmBWQhNuTjYEwCQzUJIux57gH7+Wf6fFxMLiNvVjIPABj25X05HMJykM+UN5BHcJ7eBzX8AAAAASUVORK5CYII='

function trayIcon(): Electron.NativeImage {
  const found = appIconPath()
  const fromFile = found ? nativeImage.createFromPath(found) : null
  if (fromFile && !fromFile.isEmpty()) return fromFile
  return nativeImage.createFromDataURL(FALLBACK_ICON_DATA_URL)
}

function createTray(): void {
  if (tray) return
  const image = trayIcon()
  tray = new Tray(image.resize({ width: 16, height: 16 }))
  tray.setToolTip(APP_DIR_NAME)
  updateTrayMenu()
  tray.on('double-click', () => {
    if (!mainWindow) return
    mainWindow.show()
    mainWindow.focus()
  })
}

/**
 * Меню трея.
 *
 * Обходы переключаются по одному: zapret и TG WS Proxy — разные вещи, и
 * включать их вместе чаще всего не нужно (Telegram через прокси — отдельно от
 * Discord и YouTube). Раньше в меню была одна кнопка на всё, и «выключить
 * телеграм, оставив запрет» из трея было невозможно.
 *
 * Подпись каждой строки говорит и что это за компонент, и что сейчас с ним:
 * «Zapret — остановлен» / «TG WS Proxy — работает».
 */
function updateTrayMenu(): void {
  if (!tray) return

  const items: Electron.MenuItemConstructorOptions[] = [
    { label: 'Показать окно', click: () => { mainWindow?.show(); mainWindow?.focus() } },
    { type: 'separator' }
  ]

  for (const component of [zapret, tgws]) {
    if (!component) continue
    const running = component.isRunning()
    items.push({
      label: `${component.title} — ${running ? 'работает' : 'остановлен'}`,
      click: () => {
        void (running ? component.stop() : component.start()).then(() => updateTrayMenu())
      }
    })
  }

  const anyRunning = zapret?.isRunning() || tgws?.isRunning()
  items.push(
    { type: 'separator' },
    {
      label: anyRunning ? 'Остановить всё' : 'Запустить всё',
      click: () => {
        void (anyRunning ? stopAll() : startAll())
      }
    },
    { type: 'separator' },
    {
      label: 'Выход',
      click: () => {
        quitting = true
        void (async () => {
          await stopAllSafely()
          app.quit()
        })()
      }
    }
  )

  tray.setContextMenu(Menu.buildFromTemplate(items))
}

/** Сообщает интерфейсу, развёрнуто ли окно. */
function broadcastWindowState(window: BrowserWindow | null): void {
  if (!window) return
  emit('window:maximized', window.isMaximized())
}

/**
 * «Запустить всё» из трея.
 *
 * Тумблеры автозапуска решают, что поднимать при запуске программы, — но не
 * это. Человек нажал «Запустить всё» своими руками, и раньше программа
 * спрашивала у настроек разрешение: если тумблер автозапуска Zapret был
 * выключен, кнопка молча ничего не делала с Zapret. Теперь запускается всё,
 * что установлено.
 */
async function startAll(): Promise<void> {
  for (const component of [zapret, tgws]) {
    if (!component) continue
    if (!component.installed()) continue
    await component.start()
  }
  broadcastAll()
  updateTrayMenu()
}

/** Переключение одного компонента: меню трея пересобирается само. */
async function toggleOne(key: 'zapret' | 'tgws'): Promise<void> {
  const component = key === 'zapret' ? zapret : tgws
  if (!component) return
  if (component.isRunning()) await component.stop()
  else await component.start()
  broadcastAll()
  updateTrayMenu()
}

/**
 * Гасит обходы, не позволяя выходу зависнуть.
 *
 * Остановка — это обращения к системе (taskkill, PowerShell), а они иногда
 * подвисают. Виснущий выход — хуже неостановленного обхода: человек закроет
 * программу через диспетчер задач, и дозорный всё равно погасит компоненты.
 */
async function stopAllSafely(): Promise<void> {
  const STOP_TIMEOUT_MS = 20000
  await Promise.race([
    stopAll(),
    new Promise<void>((resolve) => setTimeout(resolve, STOP_TIMEOUT_MS))
  ])
}

async function stopAll(): Promise<void> {
  await zapret?.stop()
  await tgws?.stop()
  broadcastAll()
  updateTrayMenu()
}

/** Подписывает компоненты на свои события, чтобы интерфейс узнавал о смене статуса. */
function watchComponents(): void {
  // статус меняется внутри ManagedProcess; опрашиваем его регулярно и
  // рассылаем всем, кто слушает. Дёшево: раз в 700 мс, только при изменении.
  let last = ''
  const tick = (): void => {
    const signature = `${zapret.status}|${zapret.statusReason}|${tgws.status}|${tgws.statusReason}`
    if (signature !== last) {
      last = signature
      broadcastAll()
      updateTrayMenu()
    }
  }
  tick()
  setInterval(tick, 700).unref()
}

async function bootstrap(): Promise<void> {
  ensureDirs()
  configStore.load()

  // Сборку для заданий Windows компилируем сразу: она нужна дозорному в первые
  // же секунды после запуска компонента, а компиляция занимает секунду-две.
  // За это время распакованная копия TgWsProxy успела бы пожить без задания.
  warmUpJobHelper()

  zapret = new ZapretComponent()
  tgws = new TgWsComponent()
  attachServices({ zapret, tgws })
  registerIpc()

  logger.write(`[hub] запуск, версия ${app.getVersion()}, каталог ${BASE_DIR}`)
  // Где мы ищем компоненты и что нашли. Строка нужна для одного вопроса:
  // «программа пишет „компонент не установлен“, а он установлен». По этой
  // строке в журнале видно, в какой папке мы искали и какой из файлов не
  // нашли — раньше оставалось только гадать.
  // Это строка-помощь, а не часть работы программы: сбоем в ней запуск
  // останавливать нельзя ни в коем случае.
  try {
    const zapretFacts = zapret.installFacts()
    const tgwsFacts = tgws.installFacts()
    logger.write(
      `[hub] zapret: папка ${zapretFacts.dir}, service.bat ${zapretFacts.service ? 'есть' : 'нет'}, ` +
        `winws.exe ${zapretFacts.winws ?? 'нет'}, данных: ${DATA_ROOT}`
    )
    logger.write(`[hub] tg-ws-proxy: папка ${tgwsFacts.dir}, exe ${tgwsFacts.exe ?? 'нет'}`)
  } catch (error) {
    logger.write(`[hub] не удалось описать компоненты для журнала: ${String(error)}`)
  }
  if (process.platform === 'win32' && !isAdmin()) {
    logger.write('[hub] нет прав администратора — перезапуск с повышением')
    relaunchElevated(process.execPath, process.argv.slice(1))
    app.quit()
    return
  }

  // автозапуск: восстанавливаем запись в реестре, если настройка включена
  const autostart = configStore.get().autostart
  if (autostart.enabled) await setAutostart(true, process.execPath)

  createWindow()
  createTray()
  watchComponents()

  // Обходы поднимаются сами, если включён их автозапуск, — независимо от того,
  // запущена программа вместе с Windows или руками. Раньше эта задержка
  // работала только внутри автозапуска Windows, и человек, включавший
  // «запускать Zapret при старте», не получал ничего: программа молча
  // останавливалась с остановленными обходами.
  const wanted: Array<[string, boolean]> = [
    ['zapret', autostart.startZapret],
    ['tgws', autostart.startTgws]
  ]
  const toStart = wanted.filter(([, on]) => on).map(([key]) => key as 'zapret' | 'tgws')
  if (toStart.length > 0) {
    const delay = autostart.delaySeconds
    const start = (): void => {
      void (async () => {
        for (const key of toStart) await toggleOne(key)
      })()
    }
    if (delay > 0) setTimeout(start, delay * 1000).unref()
    else start()
  }

  // Проверка обновлений при запуске: обе настройки про одно и то же, поэтому
  // спрашиваем и ту, что в общих настройках, и ту, что в разделе обновлений.
  if (configStore.get().general.checkUpdatesOnStart && configStore.get().updates.autoCheck) {
    // Через IPC, а не напрямую: проверка рассылает результат в интерфейс,
    // и плашка обновления появляется сама, без участия человека.
    setTimeout(() => {
      void announceUpdates(false).then((result) => {
        if (result.checked.length > 0 || result.app) {
          logger.write(`[hub] найдены обновления: ${result.checked.map((f) => f.key).join(', ') || 'программа'}`)
        }
      })
    }, 4000).unref()
  }
}

app.whenReady().then(bootstrap).catch((error) => {
  const message = error instanceof Error ? `${error.message}\n${error.stack ?? ''}` : String(error)
  logger.write(`[hub] сбой запуска: ${message}`)
  // Окно может быть ещё не создано, поэтому сначала показываем системное
  // окно с текстом ошибки: раньше программа просто молчала в трее, и
  // разбираться приходилось по журналу.
  dialogError('Zapret Hub не запустился', message)
})

/**
 * Ошибка в системном окне — на случай, когда своего окна ещё нет.
 *
 * Пока программа не создала BrowserWindow, показать ошибку внутри интерфейса
 * негде, а упасть в журнал — значит оставить человека без ответа.
 */
function dialogError(title: string, message: string): void {
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { dialog } = require('electron') as typeof import('electron')
    void dialog.showMessageBox({
      type: 'error',
      title: 'Zapret Hub',
      message: title,
      detail: message,
      buttons: ['Закрыть']
    })
  } catch {
    /* диалог не показался — в журнале уже есть запись */
  }
}

// Всё, что упало мимо обработчиков: показываем окном, а не только журналом.
// Ошибка вида «Cannot find module» раньше выглядела как «программа ничего не
// делает», потому что в интерфейс не попадала никак.
process.on('uncaughtException', (error) => {
  logger.write(`[hub] необработанная ошибка: ${error?.stack ?? String(error)}`)
  emit('error:notice', {
    source: 'unknown',
    title: 'В программе случилась ошибка',
    message: error instanceof Error ? error.message : String(error),
    detail: error instanceof Error ? error.stack ?? '' : ''
  })
})

process.on('unhandledRejection', (reason) => {
  const text = reason instanceof Error ? `${reason.message}\n${reason.stack ?? ''}` : String(reason)
  logger.write(`[hub] не дождались ответа: ${text}`)
  emit('error:notice', {
    source: 'unknown',
    title: 'Действие не доведено до конца',
    message: reason instanceof Error ? reason.message : String(reason),
    detail: text
  })
})

app.on('second-instance', () => {
  if (!mainWindow) return
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
})

app.on('window-all-closed', () => {
  // Трей остаётся живым: закрытое окно не значит, что пора выходить.
})

/**
 * Выход.
 *
 * По умолчанию обходы гаснут вместе с программой: человек закрыл Zapret Hub —
 * значит, обход ему больше не нужен, а висящий winws.exe только мешает
 * (занятые файлы компонентов, обход без всякого управления). Кто хочет, чтобы
 * обход работал без программы, выключает это в настройках.
 *
 * Дозорный страхует и те случаи, когда до этого кода дело не доходит: снятая
 * задача в диспетчере, падение, обрыв питания.
 */
app.on('before-quit', async (event) => {
  if (quitting) return
  const config = configStore.get()
  if (!config.general.stopComponentsOnQuit) return
  event.preventDefault()
  quitting = true
  await stopAllSafely()
  app.quit()
})

app.on('will-quit', () => {
  zapret?.dispose?.()
  tgws?.dispose?.()
  logger.write('[hub] выход')
})

export { tmpDir }
export { ipcMain }
