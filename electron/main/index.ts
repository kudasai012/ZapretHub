/**
 * Главный процесс: окно, запуск, трей, жизненный цикл.
 *
 * Программа всегда работает с повышением прав — winws.exe требует WinDivert,
 * а без администратора он не стартует. Поэтому при запуске проверяем права и,
 * если их нет, просим пользователя подняться через UAC.
 */
import { app, BrowserWindow, Menu, Tray, nativeImage, screen, shell, ipcMain } from 'electron'
import path from 'node:path'
import fs from 'node:fs'
import { configStore, tmpDir } from './config'
import { ensureDirs, BASE_DIR, APP_DIR_NAME, DATA_ROOT } from './paths'
import { logger } from './logger'
import { pollPeriodMs } from './performance'
import { reinstalled, updatedFrom, updateSplashHtml } from './updated'
import { ZapretComponent } from './zapret'
import { TgWsComponent } from './tgws'
import { announceUpdates, attachServices, broadcastAll, emit, registerIpc } from './ipc'
import {
  isAdmin,
  LOGIN_ARG,
  openWindowToShell,
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
/** Программа выходит по-настоящему: свои обходы она уже погасила. */
let quitting = false
/** Система завершает работу или пользователь выходит из Windows. */
let sessionEnding = false

const devServerUrl = process.env.ELECTRON_RENDERER_URL

/**
 * Создаём окно.
 *
 * `showNow` — окно просят показать сразу: так бывает, когда человек щёлкает по
 * иконке в трее, а окна нет (см. showWindow). Обычный запуск решает сам: при
 * «запускать свёрнутым» и при входе в Windows окно не показывается.
 */
function createWindow(showNow = false): void {
  const config = configStore.get()

  /**
   * Размер окна по умолчанию: главная должна помещаться целиком.
   *
   * С результатами проверки стратегии страница выходит на ~880 px, и при
   * прежних 860 px человек получал полосу прокрутки сразу после открытия —
   * хотя кнопок на экране прибавилось всего одна. Расти выше экрана нельзя:
   * на ноутбуке с 768 px по вертикали окно уехало бы за край, поэтому
   *поэтому опираемся на рабочую область экрана.
   */
  const area = screen.getPrimaryDisplay().workAreaSize
  const startWidth = Math.min(1240, Math.max(980, area.width - 40))
  const startHeight = Math.min(980, Math.max(700, area.height - 40))

  mainWindow = new BrowserWindow({
    width: startWidth,
    height: startHeight,
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
  // Окно больше не живёт от запуска до выхода: уходя в трей, оно
  // уничтожается по-настоящему (см. обработчик закрытия), и программа
  // продолжает работать без единого окна — только с иконкой в трее.
  mainWindow.on('closed', () => {
    mainWindow = null
    logger.write('[hub] окно закрыто, программа осталась в трее')
  })

  mainWindow.on('maximize', () => broadcastWindowState(mainWindow))
  mainWindow.on('unmaximize', () => broadcastWindowState(mainWindow))
  refreshOnShow(mainWindow)

  mainWindow.on('ready-to-show', () => {
    if (!mainWindow) return
    if (showNow) {
      mainWindow.show()
      mainWindow.focus()
      return
    }
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
   * Закрытие окна — крестиком, из списка окон по Alt+Tab, с панели задач.
   *
   * Пока окно прятали (preventDefault + hide), программа гибла: окно оставалось
   * живым, только невидимым, и Windows считала, что её просьбу закрыть
   * проигнорировали. Список окон, панель задач и «Просмотр задач» закрывают
   * окна через EndTask — он сначала просит вежливо (WM_CLOSE), а если окно на
   * месте, снимает задачу: процесс убивают без всякого выхода, обходы остаются
   * работать, а при следующем запуске обход не включается — фильтр WinDivert
   * занят прежней копией winws. Прятать окно значило подставляться под эту
   * расправу.
   *
   * Поэтому в трей окно уходит по-настоящему: закрытие не перехватываем, окно
   * уничтожается, и просьба Windows оказывается исполненной — снимать задачу
   * не за что. Программа при этом не выходит: Electron не закрывается сам по
   * гибели окна, а `app.quit()` здесь не вызывается. Остаётся иконка в трее,
   * обходы продолжают работать, а окно создаётся заново, когда человек его
   * попросит (showWindow).
   *
   * Исключение одно — завершение работы Windows или выход пользователя: тут
   * система ждёт настоящего выхода, и программа закрывается полностью.
   */
  mainWindow.on('close', (event) => {
    if (quitting) return
    const settings = configStore.get().general
    if (!sessionEnding && settings.minimizeToTray) {
      // Ничего не перехватываем: окно должно исчезнуть с экрана по-настоящему,
      // а программа — остаться работать в трее.
      logger.write('[hub] закрытие окна: уходим в трей')
      return
    }
    event.preventDefault()
    quitting = true
    // Окно убираем с экрана сразу, до остановки компонентов.
    //
    // Остановка — не миг: пока гасится winws.exe со всем деревом, проходят
    // секунды. Раньше окно всё это время оставалось на экране, и Windows
    // видела живое окно, которое не закрывается: программа объявлялась
    // «не отвечающей», а следующим шагом ей снимали задачу. Снятая задача —
    // это гибель программы без всякого выхода: компоненты остаются работать, а
    // при следующем запуске обход не включается, потому что фильтр WinDivert
    // занят прежней копией winws. Спрятанное окно такой подсказки не вызывает,
    // а выход при этом остаётся настоящим: программа закрывается, а не
    // прячется в трей.
    mainWindow?.hide()
    void (async () => {
      try {
        // Настройку «останавливать обходы при выходе» уважаем и здесь: кто
        // просил оставить обход работать без программы, тот его и получит.
        if (settings.stopComponentsOnQuit) await stopAllSafely()
      } catch (error) {
        logger.write(`[hub] выход: остановка не удалась — ${String(error)}`)
      } finally {
        // Выход — в finally: окно уже спрятано, и если остановка сорвётся,
        // программа не останется невидимым процессом без всякого выхода.
        app.quit()
      }
    })()
  })

  /**
   * Завершение работы Windows или выход пользователя.
   *
   * В этот момент сворачиваться в трей нельзя: система ждёт, что программа
   * выйдет, и убьёт её сама, не дождавшись. Выходим сами — так обходы погаснут
   * по правилам, а не вместе с процессом.
   */
  mainWindow.on('session-end', () => {
    sessionEnding = true
    if (quitting) return
    quitting = true
    void (async () => {
      try {
        if (configStore.get().general.stopComponentsOnQuit) await stopAllSafely()
      } catch (error) {
        logger.write(`[hub] выход при завершении работы Windows: ${String(error)}`)
      } finally {
        app.quit()
      }
    })()
  })

  /**
   * Открываем окно для закрытия от оболочки Windows.
   *
   * Программа работает с правами администратора, а оболочка Windows — список
   * окон по Alt+Tab, панель задач — обычными. UIPI не пропускает WM_CLOSE от
   * программы с меньшими правами к окну с большими, поэтому закрыть окно из
   * списка окон было нельзя: Windows видела живое окно, объявляла программу
   * «не отвечающей» и снимала задачу. Снятая задача убивает программу сразу,
   * мимо всякого выхода: компоненты остаются работать, а при следующем запуске
   * обход не включается — фильтр WinDivert занят прежней копией winws.
   *
   * Делаем это один раз, при создании окна, и в фоне: сборка компилируется
   * секунду-две, а окно должно появиться сразу.
   */
  openWindowToShell(mainWindow.getNativeWindowHandle(), (answer) => {
    // 3 — пропущены и WM_CLOSE, и WM_SYSCOMMAND; всё, что меньше, — в журнал:
    // по нему видно, дошло ли дело до Windows на этой машине.
    logger.write(`[hub] окно открыто для оболочки: ${answer || 'ответа нет'}`)
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
 * Показываем окно — создаём заново, если его нет.
 *
 * Окно больше не живёт всё время работы программы: уходя в трей, оно
 * уничтожается, поэтому «показать окно» обычно значит «создать окно снова».
 * Создание занимает доли секунды — это плата за то, что закрытие окна из
 * списка окон больше не убивает программу.
 */
/** Сколько держим окно перехода: успевает прочитать, но не надоедает. */
const SPLASH_MS = 2600

/**
 * Окно перехода: «было 1.0.6 — стало 1.0.7».
 *
 * Программа поднимается уже обновлённой, поэтому увидеть этот переход может
 * только она сама: старая к этому моменту закрыта, установщик работает тихо.
 * Раньше вместо окна на экране висело командное окно сторожа — оно и смотрелось
 * чужим, и закрывалось не всегда.
 *
 * Окно не зависит от основного: у него нет своей предзагрузки и нет Node,
 * разметка полностью своя (см. updateSplashHtml). Оно живёт несколько секунд,
 * закрывается само и отдаёт экран настоящему окну.
 */
function showUpdateSplash(from: string, to: string, openMain: boolean, again = false): void {
  const lang = configStore.get().general.language
  const splash = new BrowserWindow({
    width: 420,
    height: 260,
    frame: false,
    resizable: false,
    movable: true,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    // Окно не должно отсчитываться как второе окно программы: в панели задач
    // и в Alt+Tab ему делать нечего, оно на несколько секунд.
    skipTaskbar: true,
    alwaysOnTop: true,
    center: true,
    show: false,
    backgroundColor: '#09090b',
    title: APP_DIR_NAME,
    icon: windowIconPath(),
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      // Своей разметке ничего внешнего не нужно: ни сеть, ни отдельные окна.
      offscreen: false
    }
  })
  splash.once('ready-to-show', () => splash.show())
  // Закрыть по щелчку: человеку не обязательно ждать, если он уже прочитал.
  const close = (): void => {
    if (!splash.isDestroyed()) splash.close()
  }
  splash.loadURL(
    `data:text/html;charset=utf-8,${encodeURIComponent(updateSplashHtml(from, to, lang, again))}`
  )
  setTimeout(() => {
    close()
    // Настоящее окно открываем сразу за переходом: пустая пауза между ними
    // читается как «программа задумалась».
    if (openMain) createWindow(true)
  }, SPLASH_MS)
}

function showWindow(): void {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.show()
    mainWindow.focus()
    return
  }
  createWindow(true)
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
  tray.on('double-click', () => showWindow())
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
    { label: 'Показать окно', click: () => showWindow() },
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
/**
 * Поднимает оба компонента.
 *
 * Вместе, а не по очереди: раньше программа ждала, пока поднимется zapret, и
 * только потом принималась за TG WS Proxy — человек нажимал «Запустить всё» и
 * считал секунды, хотя друг другу компоненты не мешают.
 */
async function startAll(): Promise<void> {
  const startedAt = Date.now()
  await Promise.all(
    [zapret, tgws].map((component) => {
      if (!component) return Promise.resolve()
      if (!component.installed()) return Promise.resolve()
      return component.start()
    })
  )
  logger.write(`[hub] компоненты подняты за ${Date.now() - startedAt} мс`)
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
  // Предел есть и у выхода: если компонент не отдаётся, ждём его не бесконечно,
  // иначе программа висит невидимым процессом и не закрывается вовсе.
  const STOP_TIMEOUT_MS = 12000
  await Promise.race([
    stopAll(),
    new Promise<void>((resolve) => setTimeout(resolve, STOP_TIMEOUT_MS))
  ])
}

async function stopAll(): Promise<void> {
  // Гасим оба компонента вместе, а не по очереди: выход не должен дожидаться,
  // пока догорит первый, чтобы приняться за второй.
  await Promise.all([zapret?.stop(), tgws?.stop()])
  broadcastAll()
  updateTrayMenu()
}

/** Видно ли окно: свёрнутое в трей окно перерисовывать незачем. */
function windowOnScreen(): boolean {
  return !!mainWindow && !mainWindow.isDestroyed() && mainWindow.isVisible() && !mainWindow.isMinimized()
}

/**
 * Подписывает компоненты на свои события, чтобы интерфейс узнавал о смене
 * статуса.
 *
 * Интервал не постоянный: когда программы не видно, состояние нужно только
 * значку в трее, а будить им интерфейс незачем — опрашиваем втрое реже. Как
 * только окно вернулось на экран, опрос снова частый, а свежее состояние
 * приходит сразу, не дожидаясь очередного прохода.
 */
function watchComponents(): void {
  let last = ''
  let timer: NodeJS.Timeout | null = null

  const tick = (): void => {
    const signature = `${zapret.status}|${zapret.statusReason}|${tgws.status}|${tgws.statusReason}`
    if (signature !== last) {
      last = signature
      // Пока окна нет, рассылать состояние некому: интерфейс всё равно
      // обновится, едва окно вернётся (см. refreshOnShow). Значок в трее
      // от этого не зависит — он строится здесь же.
      if (windowOnScreen()) broadcastAll()
      updateTrayMenu()
    }
  }

  const schedule = (): void => {
    const period = pollPeriodMs(windowOnScreen())
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      tick()
      schedule()
    }, period)
    timer.unref()
  }

  tick()
  schedule()
}

/**
 * Обновляет интерфейс, едва окно вернулось на экран.
 *
 * Пока программы не было видно, состояние ей не рассылалось — иначе каждое
 * обновление будило бы спящий интерфейс. Здесь она получает его целиком,
 * поэтому на экране всегда свежие цифры, а не те, что были до свёртывания.
 */
function refreshOnShow(window: BrowserWindow): void {
  window.on('show', () => {
    broadcastAll()
    broadcastWindowState(window)
  })
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

  const autostart = configStore.get().autostart

  // Окно создаём, только если его должны увидеть: запускаясь в трей, программа
  // не держит в памяти лишний интерфейс — а он появляется по первому щелчку по
  // иконке в трее (showWindow).
  // Обычно окно создаём, если его должны увидеть: запускаясь в трей, программа
  // не держит в памяти лишний интерфейс — а он появляется по первому щелчку по
  // иконке в трее (showWindow).
  const shouldShow = !configStore.get().general.startMinimized && !startedAtLogin()
  const previous = updatedFrom()
  const again = reinstalled()
  // Переустановку показываем и тогда, когда версия не изменилась: программу
  // поставили заново, и человек должен это увидеть.
  if (previous && (again || previous !== app.getVersion())) {
    // Программу подняли после обновления или переустановки: показываем,
    // с какой версии пришли. Ключи передаёт сторож (см. spawnRelaunchGuard).
    logger.write(
      `[hub] запуск после ${again ? 'переустановки' : 'обновления'}: ${previous} → ${app.getVersion()}`
    )
    showUpdateSplash(previous, app.getVersion(), shouldShow, again)
  } else if (shouldShow) {
    createWindow()
  }
  createTray()
  watchComponents()

  // Запись автозапуска — не повод задерживать окно. Раньше мы ждали reg.exe
  // до создания окна, и программа думала лишние доли секунды на ровном месте:
  // запись в реестр ничему не мешает, а человеку важно увидеть окно.
  if (autostart.enabled) void setAutostart(true, process.execPath)

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
      const startedAt = Date.now()
      void (async () => {
        await Promise.all(toStart.map((key) => toggleOne(key)))
        logger.write(`[hub] автозапуск обходов занял ${Date.now() - startedAt} мс`)
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

app.on('second-instance', () => showWindow())

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
  // Тот же порядок, что и при закрытии окна: сначала убираем окно, потом
  // гасим компоненты — иначе Windows успевает объявить программу зависшей.
  mainWindow?.hide()
  try {
    await stopAllSafely()
  } catch (error) {
    logger.write(`[hub] выход: остановка не удалась — ${String(error)}`)
  } finally {
    app.quit()
  }
})

app.on('will-quit', () => {
  zapret?.dispose?.()
  tgws?.dispose?.()
  logger.write('[hub] выход')
})

export { tmpDir }
export { ipcMain }
