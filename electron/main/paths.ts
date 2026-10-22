/**
 * Пути приложения Zapret Hub.
 *
 * Папка программы — только программа. Всё, что она скачивает и запоминает,
 * живёт отдельно.
 *
 *   C:/Users/<имя>/AppData/Roaming/ZapretHub/
 *       components/    zapret-discord-youtube и tg-ws-proxy
 *       data/          конфиг, манифест версий, логи, бэкапы
 *
 * Именно Roaming: app.getPath('appData') отдаёт %APPDATA%. Деинсталлятор
 * (build/installer.nsh) чистит эту же папку — проверка verify/uninstall-data-check.js
 * следит, чтобы они не разъехались.
 *
 *   C:/Program Files/Zapret Hub/
 *       ZapretHub.exe
 *       unins000.exe  деинсталлятор (если ставили через установщик)
 *
 * Зачем так. Раньше components/ и data/ лежали рядом с exe, и обновление —
 * которое заменяет файлы программы — заодно уносило их: человек ставит новую
 * версию, а у него пропадают и скачанный zapret со всеми его списками, и
 * настройки. Отдельная папка лечит это: обновление до неё не достаёт, а
 * удаление программы её убирает — деинсталлятор знает про неё и чистит.
 */
import { app, shell } from 'electron'
import path from 'node:path'
import fs from 'node:fs'

/** Корень программы: папка exe, если собрано; иначе корень проекта. */
export function baseDir(): string {
  if (app.isPackaged) return path.dirname(app.getPath('exe'))

  // Запуск из исходников: главный процесс лежит в out/main, а корень
  // проекта — там, где package.json. Ищем его вверх по дереву, а не считаем
  // шаги: иначе при любой смене раскладки сборки путь уезжает на уровень выше
  // проекта, и программа начинает писать data/ и components/ не туда.
  let dir = __dirname
  for (;;) {
    if (fs.existsSync(path.join(dir, 'package.json'))) return dir
    const parent = path.dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return process.cwd()
}

export const BASE_DIR = baseDir()

/**
 * Корень данных.
 *
 * В собранной программе — вне папки программы (см. шапку файла). Запуск из
 * исходников не трогаем: там и данные лежат в проекте, иначе проверки и
 * разработка разъехались бы с тем, что видит человек.
 */
export function dataRoot(): string {
  if (!app.isPackaged) return BASE_DIR
  try {
    return path.join(app.getPath('appData'), 'ZapretHub')
  } catch {
    // appData недоступен (крайний случай) — оставляем прежнее поведение.
    return BASE_DIR
  }
}

export const DATA_ROOT = dataRoot()
export const COMPONENTS_DIR = path.join(DATA_ROOT, 'components')
export const DATA_DIR = path.join(DATA_ROOT, 'data')
export const LOGS_DIR = path.join(DATA_DIR, 'logs')
export const BACKUPS_DIR = path.join(DATA_DIR, 'backups')
export const TEMP_DIR = path.join(DATA_DIR, 'tmp')

export const CONFIG_FILE = path.join(DATA_DIR, 'config.json')
export const MANIFEST_FILE = path.join(DATA_DIR, 'components.json')
export const HUB_LOG_FILE = path.join(LOGS_DIR, 'hub.log')

export const ZAPRET_DIR_NAME = 'zapret-discord-youtube'
export const TGWS_DIR_NAME = 'tg-ws-proxy'

export const ZAPRET_DIR = path.join(COMPONENTS_DIR, ZAPRET_DIR_NAME)
export const TGWS_DIR = path.join(COMPONENTS_DIR, TGWS_DIR_NAME)

/** Имя exe компонента tg-ws-proxy. */
export const EXE_NAME_TGWS = 'TgWsProxy_windows.exe'

/** Ищет файл по дереву, но не глубже depth уровней. */
export function findFileDeep(root: string, name: string, depth: number): string | null {
  if (depth < 0) return null
  let entries: fs.Dirent[]
  try {
    entries = fs.readdirSync(root, { withFileTypes: true })
  } catch {
    return null
  }
  for (const entry of entries) {
    if (entry.isFile() && entry.name.toLowerCase() === name.toLowerCase()) {
      return path.join(root, entry.name)
    }
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue
    if (['node_modules', '.git'].includes(entry.name)) continue
    const found = findFileDeep(path.join(root, entry.name), name, depth - 1)
    if (found) return found
  }
  return null
}

/** Примета пакета zapret: service.bat и рядом winws.exe (в bin или в корне). */
export function looksLikeZapret(dir: string): boolean {
  if (!fs.existsSync(path.join(dir, 'service.bat'))) return false
  return (
    fs.existsSync(path.join(dir, 'bin', 'winws.exe')) ||
    fs.existsSync(path.join(dir, 'winws.exe'))
  )
}

/** Примета пакета tg-ws-proxy: его exe, каким бы именем он ни лежал. */
export function looksLikeTgws(dir: string): boolean {
  if (fs.existsSync(path.join(dir, EXE_NAME_TGWS))) return true
  try {
    return fs.readdirSync(dir).some((name) => /^tg-?ws-?proxy.*\.exe$/i.test(name))
  } catch {
    return false
  }
}

/**
 * Ищет пакет компонента в папке components.
 *
 * Раньше путь был жёстко «components/zapret-discord-youtube», и если пакет
 * лежал под другим именем — скачан прежней версией программы, распакован
 * архивом с номером версии в имени папки или положен вручную, — программа
 * честно писала «Компоненты не установлены», хотя всё было на месте. Теперь
 * мы ищем пакет по приметам: у zapret это service.bat и winws.exe, у
 * tg-ws-proxy — его exe. Что нашли — тем и работаем.
 *
 * @param canonical папка по умолчанию
 * @param match проверка «это тот самый пакет» для папки-кандидата
 */
export function resolveComponentDir(canonical: string, match: (dir: string) => boolean): string {
  if (match(canonical)) return canonical

  // Папку компонентов кладут и руками, и прежние версии программы держали её
  // рядом с exe. Смотрим в обе: лучше работать с тем, что человек положил, чем
  // сказать «компоненты не установлены», хотя всё на месте.
  const roots = [COMPONENTS_DIR]
  const legacy = path.join(BASE_DIR, 'components')
  if (legacy !== COMPONENTS_DIR) roots.push(legacy)

  for (const root of roots) {
    if (match(root)) return root
    let entries: fs.Dirent[]
    try {
      entries = fs.readdirSync(root, { withFileTypes: true })
    } catch {
      continue
    }
    const folders = entries.filter((entry) => entry.isDirectory()).map((entry) => path.join(root, entry.name))
    for (const dir of folders) {
      if (match(dir)) return dir
    }
    // Пакет мог лежать не сразу в components, а во вложенной папке: так выходит,
    // когда архив распакован целиком. Смотрим на уровень глубже.
    for (const dir of folders) {
      let nested: fs.Dirent[]
      try {
        nested = fs.readdirSync(dir, { withFileTypes: true })
      } catch {
        continue
      }
      for (const entry of nested) {
        if (!entry.isDirectory()) continue
        const child = path.join(dir, entry.name)
        if (match(child)) return child
      }
    }
  }
  return canonical
}

/** Где лежит пакет zapret: по правилам или там, где его нашли. */
export function resolveZapretDir(): string {
  return resolveComponentDir(ZAPRET_DIR, looksLikeZapret)
}

/** Где лежит пакет tg-ws-proxy: по правилам или там, где его нашли. */
export function resolveTgwsDir(): string {
  return resolveComponentDir(TGWS_DIR, looksLikeTgws)
}

/**
 * Папка, в которой лежит winws.exe: у пакета zapret это bin, но пакет,
 * положенный вручную или распакованный иначе, держит exe в корне — тогда
 * bin создавать не надо, иначе программа снова скажет «не установлен».
 */
export function resolveZapretBinDir(): string {
  const dir = resolveZapretDir()
  if (fs.existsSync(path.join(dir, 'winws.exe'))) return dir
  return path.join(dir, 'bin')
}

/** Путь к winws.exe: сначала там, где пакет лежит по правилам, затем поиск. */
export function resolveWinws(): string | null {
  const dir = resolveZapretDir()
  const direct = [path.join(dir, 'bin', 'winws.exe'), path.join(dir, 'winws.exe')]
  const found = direct.find((candidate) => fs.existsSync(candidate))
  if (found) return found
  return findFileDeep(dir, 'winws.exe', 3)
}

/** Путь к exe tg-ws-proxy: ожидаемое имя, иначе любой подходящий в папке. */
export function resolveTgwsExe(): string | null {
  const dir = resolveTgwsDir()
  const direct = path.join(dir, EXE_NAME_TGWS)
  if (fs.existsSync(direct)) return direct
  try {
    const found = fs
      .readdirSync(dir)
      .filter((name) => /^tg-?ws-?proxy.*\.exe$/i.test(name))
      .sort()[0]
    if (found) return path.join(dir, found)
  } catch {
    /* папки нет — нечего искать */
  }
  return null
}

export const ZAPRET_LISTS_DIR = path.join(resolveZapretDir(), 'lists')
export const ZAPRET_BIN_DIR = resolveZapretBinDir()
export const ZAPRET_UTILS_DIR = path.join(resolveZapretDir(), 'utils')

export const APP_DIR_NAME = 'Zapret Hub'

/**
 * Переносит прежнюю раскладку в новое место.
 *
 * У человека, который ставил прежние версии, components/ и data/ лежат рядом с
 * exe. При первом запуске новой версии они переезжают в отдельную папку — иначе
 * обновление выглядело бы как потеря всего: ни обхода, ни настроек.
 */
function migrateOldLayout(): void {
  if (DATA_ROOT === BASE_DIR) return
  for (const name of ['components', 'data']) {
    const from = path.join(BASE_DIR, name)
    const to = path.join(DATA_ROOT, name)
    if (!fs.existsSync(from) || fs.existsSync(to)) continue
    try {
      fs.mkdirSync(DATA_ROOT, { recursive: true })
      fs.renameSync(from, to)
      loggerLess(`[paths] ${name} переехал(а) в ${to}`)
    } catch {
      // Не вышло переименовать (например, файлы заняты) — останется на месте,
      // а разрешение путей само найдёт пакет в старой папке.
    }
  }
}

/** Заметка в журнал, если он уже есть: сам logger берёт пути отсюда. */
function loggerLess(text: string): void {
  try {
    fs.appendFileSync(path.join(DATA_ROOT, 'data', 'logs', 'hub.log'), `${text}\n`)
  } catch {
    /* журнала ещё нет — не беда */
  }
}

export function ensureDirs(): void {
  migrateOldLayout()
  for (const dir of [
    COMPONENTS_DIR,
    DATA_DIR,
    LOGS_DIR,
    BACKUPS_DIR,
    TEMP_DIR,
    ZAPRET_DIR,
    ZAPRET_LISTS_DIR,
    ZAPRET_BIN_DIR,
    ZAPRET_UTILS_DIR,
    TGWS_DIR
  ]) {
    try {
      fs.mkdirSync(dir, { recursive: true })
    } catch {
      /* права выставит отдельный шаг, здесь просто не падаем */
    }
    grantUsersAccess(dir)
  }
}

/**
 * Выдаёт группе «Пользователи» полный доступ к папке.
 *
 * Программа работает с повышением прав (winws.exe требует WinDivert), а
 * проводник — всегда без него. Папки, созданные повышенным процессом,
 * наследуют права от родителя, и если владелец родителя — «Администраторы»
 * (так бывает при установке в Program Files), проводник не может открыть
 * такую папку. Право выдаём явно и с наследованием.
 *
 * Берём SID, а не имя: на локализованной Windows имя группы другое, а SID
 * всегда один. Ошибки молча игнорируются — если не вышло, открытие всё
 * равно пытаемся.
 */
function grantUsersAccess(dir: string): void {
  if (process.platform !== 'win32') return
  const { execFile } = require('node:child_process') as typeof import('node:child_process')
  try {
    execFile(
      'icacls',
      [dir, '/grant', '*S-1-5-32-545:(OI)(CI)F', '/C'],
      { windowsHide: true, timeout: 15000 },
      () => {}
    )
  } catch {
    /* права не критичны для открытия */
  }
}

export function uninstallerPath(): string | null {
  if (!app.isPackaged) return null
  const candidate = path.join(BASE_DIR, 'unins000.exe')
  return fs.existsSync(candidate) ? candidate : null
}

/**
 * Открывает папку в проводнике.
 *
 * Сначала пробуем штатный shell.openPath: он возвращает текст ошибки, если
 * проводник не открылся, и корректно работает из программы с повышенными
 * правами. Если и он не смог — вторым заходом зовём explorer.exe напрямую.
 *
 * Раньше функция отвечала просто «да/нет»: при отказе интерфейс молчал,
 * человек жал кнопку, ничего не происходило, и разбираться было негде.
 */
export async function openInFileManager(
  target: 'components' | 'logs'
): Promise<{ ok: boolean; path: string; reason: string }> {
  const dir = target === 'components' ? COMPONENTS_DIR : LOGS_DIR
  try {
    fs.mkdirSync(dir, { recursive: true })
  } catch (error) {
    return { ok: false, path: dir, reason: describe(error) }
  }
  grantUsersAccess(dir)

  const failure = await shell.openPath(dir)
  if (!failure) return { ok: true, path: dir, reason: '' }

  // Проводник отказал штатным путём — пробуем explorer.exe. Из процесса с
  // повышенными правами он иногда уводит окно за своё, зато открывает папку.
  try {
    const { execFile } = await import('node:child_process')
    await new Promise<void>((resolve) => {
      execFile('explorer', [dir], { windowsHide: true }, () => resolve())
    })
    return { ok: true, path: dir, reason: '' }
  } catch (error) {
    // Причину не пишем в журнал отсюда: журнал живёт в этой же программе и
    // берёт свой путь из этого файла — цикл импортов ронял бы запуск.
    // Причина уходит наружу, и её запишет тот, кто покажет ошибку человеку.
    return { ok: false, path: dir, reason: `${failure} ${describe(error)}`.trim() }
  }
}

/** Ошибка словами: у Error берём message, у остального — toString. */
export function describe(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
