/**
 * Единый контракт между главным процессом и интерфейсом.
 *
 * Методы сгруппированы по смыслу — window.hub.config.save(...), а не
 * window.hub['config:save'](...): так вызовы читаются как обычный код, и
 * главное, TypeScript проверяет их до сборки. Имена групп совпадают с именами
 * каналов IPC, но наружу торчит только эта форма.
 */

export type Lang = 'ru' | 'en'
export type ComponentKey = 'zapret' | 'tgws'
export type ProcessStatus = 'stopped' | 'starting' | 'running' | 'stopping' | 'crashed'

export interface GeneralSettings {
  language: Lang
  /**
   * Темы нет намеренно: окно одно и всегда тёмное.
   *
   * Светлый вариант был бы отдельной раскладкой — все поверхности, рамки и
   * подписи пришлось бы держать в двух видах, а выглядело бы хуже. Пока
   * переключателя нет, поэтому и поля в настройках нет.
   */
  minimizeToTray: boolean
  startMinimized: boolean
  sidebarCollapsed: boolean
  checkUpdatesOnStart: boolean
  stopComponentsOnQuit: boolean
}

export interface AutostartSettings {
  enabled: boolean
  startZapret: boolean
  startTgws: boolean
  delaySeconds: number
}

export interface UpdateSettings {
  autoCheck: boolean
  /** Когда последний раз спрашивали GitHub, в секундах. */
  lastCheck: number
}

export interface ZapretSettings {
  strategy: string
  gameMode: 'disabled' | 'tcp' | 'udp' | 'all'
  gameTcpRange: string
  gameUdpRange: string
  ipsetMode: 'loaded' | 'none' | 'any'
  diagTargets: string[]
  /**
   * Разрешить правку целей диагностики.
   *
   * Выключено по умолчанию: список проверяемых сайтов и так рабочий, а
   * ошибочная строка в нём выдаёт «стратегия не работает» там, где стратегия
   * ни при чём. Правку открываем только осознанно.
   */
  editTargets: boolean
}

export interface TgwsSettings {
  host: string
  port: number
  secret: string
  dcIp: string[]
  bufKb: number
  poolSize: number
  verbose: boolean
  cfproxy: boolean
  forceTestDc: boolean
  noSecure: boolean
  checkUpdates: boolean
  logMaxMb: number
}

export interface AppConfig {
  version: number
  general: GeneralSettings
  autostart: AutostartSettings
  updates: UpdateSettings
  zapret: ZapretSettings
  tgws: TgwsSettings
}

/** Снимок одного компонента — то, что рисует карточка на экране. */
export interface ComponentSnapshot {
  key: ComponentKey
  status: ProcessStatus
  installed: boolean
  version: string
  reason: string
}

export interface ZapretState {
  status: ProcessStatus
  installed: boolean
  version: string
  strategies: string[]
  strategy: string
  gameMode: ZapretSettings['gameMode']
  gameTcpRange: string
  gameUdpRange: string
  ipsetMode: ZapretSettings['ipsetMode']
  ipsetState: 'loaded' | 'none' | 'any'
  lists: string[]
  reason: string
  serviceState: string | null
  /** Где на диске лежит пакет: программа умеет находить его в другой папке. */
  dir: string
}

export interface TgwsState {
  status: ProcessStatus
  installed: boolean
  version: string
  settings: TgwsSettings
  reason: string
  /** Где на диске лежит пакет. */
  dir: string
}

export interface HomeState {
  zapret: ComponentSnapshot
  tgws: ComponentSnapshot
  zapretState: ZapretState
  tgwsState: TgwsState
  anyRunning: boolean
}

export interface DiagnosticsTargetResult {
  name: string
  address: string
  /** Ответил ли сайт по HTTP. Ноль — HTTP не проверяли (цель вида PING:). */
  httpOk: boolean | null
  /** Код ответа: 200, 403… Ноль — ответа не было. */
  httpStatus: number
  /** Код выхода curl: 28, 35… Ноль — запрос дошёл. */
  httpCode: number
  pingOk: boolean | null
  pingMs: number | null
  error: string
}

/** Итог одной проверки системы. */
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

export interface UpdateInfo {
  key: ComponentKey
  current: string
  latest: string
  url: string
  notes: string
}

export interface AppUpdateInfo {
  current: string
  latest: string
  url: string
  notes: string
  publishedAt: string
}

export type UpdateTarget = 'zapret' | 'tgws' | 'app'

/** Где обновление и сколько сделано. */
export interface UpdateProgress {
  target: UpdateTarget
  /** Этап: скачивание, распаковка, готово или сбой. */
  stage: 'download' | 'unpack' | 'done' | 'error'
  percent: number
  message: string
}

/** Глубокий «частичный» патч: любая ветка настроек может быть неполной. */
export type ConfigPatch = {
  [K in keyof AppConfig]?: AppConfig[K] extends object ? Partial<AppConfig[K]> : AppConfig[K]
}

// --------------------------------------------------------------- события

export interface MainEvents {
  /** Сменился статус компонента. */
  'component:status': { key: ComponentKey; status: ProcessStatus; reason?: string }
  /** Новая строка из журнала компонента. */
  'component:log': { key: ComponentKey; line: string }
  /** Обновилось состояние zapret. */
  'zapret:state': ZapretState
  /** Обновилось состояние TG WS Proxy. */
  'tgws:state': TgwsState
  /** Обновилось состояние главного экрана. */
  'home:state': HomeState
  /** Стратегия ответила на проверки. */
  'strategy:progress': { strategy: string; results: DiagnosticsTargetResult[] }
  'strategy:done': { strategy: string; results: DiagnosticsTargetResult[] }
  /** Прогон набора: проверяется очередная стратегия. */
  'diagnostics:progress': { strategy: string; done: number; total: number }
  /** Прогон набора закончился: победитель выбран (или не выбран). */
  'diagnostics:done': {
    winner: string | null
    applied: boolean
    results: Record<string, DiagnosticsTargetResult[]>
  }
  /** Нашлось обновление компонента. */
  'update:available': UpdateInfo
  /** Нашлась новая версия программы. */
  'app-update:available': AppUpdateInfo
  /** Программа просит показать сообщение. */
  toast: { kind: 'success' | 'warning' | 'error' | 'info'; text: string }
  /** Окно развернули на весь экран или вернули к прежнему размеру. */
  'window:maximized': boolean
  /**
   * Настройки сохранились — где угодно, не обязательно этим окном.
   *
   * Без этого события интерфейс видел только свои собственные записи: тумблер
   * в настройках переключался, значение уходило в файл, а картинка оставалась
   * прежней — и казалось, что тумблер «не сработал».
   */
  'config:changed': AppConfig
  /** Шаг скачивания или распаковки обновления. */
  'update:progress': UpdateProgress
  /**
   * Случилась ошибка, которую человек должен увидеть, а не искать в журнале.
   *
   * Тост для этого не годится: он исчезает через несколько секунд и не вмещает
   * ни стек, ни путь к папке. Поэтому у ошибок отдельное окно — с текстом,
   * который можно прочитать и скопировать.
   */
  'error:notice': ErrorNotice
}

/** Ошибка, показанная в отдельном окне. */
export interface ErrorNotice {
  /** Чем вызвана: «запуск», «проверка», «обновление», «папка». */
  source: 'startup' | 'start' | 'check' | 'update' | 'folder' | 'unknown'
  /** Заголовок окна: коротко, что не получилось. */
  title: string
  /** Что именно говорит программа или система. */
  message: string
  /** Подробности, если есть: путь, аргументы, стек. */
  detail?: string
}

// --------------------------------------------------------------- методы

export interface HubApi {
  config: {
    get(): Promise<AppConfig>
    save(patch: ConfigPatch): Promise<AppConfig>
  }

  home: {
    snapshot(): Promise<HomeState>
  }

  zapret: {
    snapshot(): Promise<ZapretState>
    setStrategy(name: string): Promise<ZapretState>
    setGameFilter(patch: { mode?: string; tcp?: string; udp?: string }): Promise<ZapretState>
    setIpsetMode(mode: string): Promise<ZapretState>
    lists(): Promise<string[]>
    readList(name: string): Promise<string>
    writeList(name: string, text: string): Promise<string[]>
    commandLine(name?: string): Promise<string>
    removeService(): Promise<{ ok: boolean; message: string }>
  }

  tgws: {
    snapshot(): Promise<TgwsState>
    saveSettings(patch: Partial<TgwsSettings>): Promise<TgwsState>
  }

  process: {
    start(key: ComponentKey): Promise<{ ok: boolean; reason: string }>
    stop(key: ComponentKey): Promise<{ ok: boolean; reason: string }>
    startAll(): Promise<{ ok: boolean; reason: string }>
    stopAll(): Promise<{ ok: boolean; reason: string }>
  }

  diagnostics: {
    targets(): Promise<string[]>
    saveTargets(lines: string[]): Promise<string[]>
    checkOne(target: string): Promise<DiagnosticsTargetResult>
    testStrategy(strategy: string): Promise<{ strategy: string; results: DiagnosticsTargetResult[] }>
    checkAll(): Promise<DiagnosticsTargetResult[]>
    probeAll(): Promise<{ anyOk: boolean; results: DiagnosticsTargetResult[] }>
    /** Идёт ли прогон прямо сейчас, и какую стратегию он проверяет. */
    status(): Promise<{ busy: boolean; strategy: string | null; done: number; total: number }>
    /**
     * Прогон набора стратегий.
     *
     * Идёт в главном процессе, а не в интерфейсе: уходишь с раздела
     * диагностики — прогон не должен рваться, и вернувшись, человек видит его
     * живым, а не дважды нажимает «Прогнать» на уже идущий прогон.
     */
    runQueue(strategies: string[]): Promise<{
      busy: boolean
      winner: string | null
      applied: boolean
      results: Record<string, DiagnosticsTargetResult[]>
    }>
    /** Остановить идущий прогон: обходы гасятся, прежняя стратегия вернётся. */
    stop(): Promise<{ ok: boolean; reason: string }>
  }

  sysdiag: {
    /** Проверки системы: то же, что делает service.bat пакета zapret. */
    run(): Promise<SysCheck[]>
    /** Починить то, что можно: служба WinDivert, чужие обходы, кэш Discord. */
    fix(id: SysFix): Promise<{ ok: boolean; message: string }>
  }

  updates: {
    check(force: boolean): Promise<{ checked: UpdateInfo[] }>
    apply(key: ComponentKey): Promise<{ ok: boolean; message: string }>
  }

  appUpdate: {
    check(force: boolean): Promise<{ available: boolean; info: AppUpdateInfo | null }>
    /** Скачивает установщик и запускает его. */
    apply(): Promise<{ ok: boolean; message: string }>
  }

  shell: {
    /**
     * Открыть папку в проводнике.
     *
     * Вместе с ответом уходит путь: если проводник не открылся, окно ошибки
     * покажет и причину, и ту самую папку, которую искали.
     */
    openPath(target: 'components' | 'logs'): Promise<{ ok: boolean; path: string; reason: string }>
    openUrl(url: string): Promise<{ ok: boolean }>
  }

  app: {
    /** Версия программы. */
    version(): Promise<string>
    /**
     * Перезапускает программу.
     *
     * Нужен там, где настройка меняет поведение самой программы, а не только
     * картинку: язык интерфейса — как раз такой случай. Конфиг при этом уже
     * сохранён зовущей стороной, перезапуск только применяет его.
     */
    restart(): Promise<void>
  }

  window: {
    minimize(): Promise<void>
    close(): Promise<void>
    isMaximized(): Promise<boolean>
    /** Развернуть на весь экран или вернуть прежний размер. */
    toggleMaximize(): Promise<void>
  }

  /** Подписка на событие из главного процесса. Возвращает функцию отписки. */
  on<K extends keyof MainEvents>(channel: K, listener: (payload: MainEvents[K]) => void): () => void
}
