/**
 * Поиск деинсталлятора — чистые функции без обращения к системе.
 *
 * Вынесены отдельно, чтобы их можно было проверить на любом компьютере: вся
 * работа с реестром Windows сводится к «прочитать вывод и разобрать», а
 * разбор текста проверяется без Windows вообще.
 *
 * Почему одним именем файла не обойтись: имя деинсталлятора зависит от
 * настроек установщика и от того, куда и как ставили программу. NSIS называет
 * его `unins000.exe`, если имя удаления не задано, и «Uninstall Zapret
 * Hub.exe», если задано. Бывает и просто `Uninstall.exe`. Поэтому смотрим не
 * на одно имя, а на смысл: файл, которым удаляют программу.
 */

/** Имя программы, по которому ищем запись в реестре. */
import path from 'node:path'

export const APP_NAME = 'Zapret Hub'

/** Файл, похожий на деинсталлятор: uninstall*.exe или unins*.exe. */
export function isUninstallerName(name: string): boolean {
  const lower = name.toLowerCase().trim()
  if (!lower.endsWith('.exe')) return false
  const base = lower.slice(0, -4)
  return base.startsWith('uninstall') || /^unins\d*$/.test(base)
}

/**
 * Выбор деинсталлятора из списка имён файлов.
 *
 * Сначала точные имена — их знаем наверняка; потом любой подходящий. Точное
 * имя важно, когда в папке программы лежат и старый, и новый деинсталлятор:
 * запустить надо тот, который относится к этой установке.
 */
export function pickUninstallerName(names: string[], appName = APP_NAME): string | null {
  const wanted = [`Uninstall ${appName}.exe`, 'unins000.exe']
  for (const name of wanted) {
    const hit = names.find((item) => item.toLowerCase() === name.toLowerCase())
    if (hit) return hit
  }
  const found = names.filter(isUninstallerName).sort()
  return found.length > 0 ? found[0] : null
}

/**
 * Разбор вывода `reg query`.
 *
 * Вывод устроен так: строка без отступа — путь раздела, строки с отступом —
 * значение в формате «имя типа данные». Пустые строки разделяют разделы.
 */
export function parseRegOutput(output: string): { key: string; values: Record<string, string> }[] {
  const blocks: { key: string; values: Record<string, string> }[] = []
  let current: { key: string; values: Record<string, string> } | null = null

  for (const line of output.split(/\r?\n/)) {
    if (line.trim() === '') continue
    // Путь раздела начинается с начала строки, значения — с отступом
    if (/^\S/.test(line)) {
      if (current) blocks.push(current)
      current = { key: line.trim(), values: {} }
      continue
    }
    if (!current) continue
    const parts = line.trim().split(/\s+(REG_\w+)\s+/)
    if (parts.length >= 3) {
      current.values[parts[0].trim()] = parts.slice(2).join(' ').trim()
    }
  }
  if (current) blocks.push(current)
  return blocks
}

/**
 * Путь к exe из командной строки удаления.
 *
 * Путь бывает в кавычках, а бывает и без них — с пробелами в «Program Files».
 * Ключи после имени (например «/S») отбрасываем.
 */
export function exeFromCommandLine(text: string): string | null {
  if (!text) return null
  const quoted = text.match(/^"([^"]+\.exe)"/i)
  if (quoted) return quoted[1].trim()
  const plain = text.match(/^(.*?\.exe)/i)
  if (!plain) return null
  const candidate = plain[1].trim()
  // MsiExec без ключей не удаляет ничего: такой «деинсталлятор» не запустить
  return path.basename(candidate).toLowerCase() === 'msiexec.exe' ? null : candidate
}

/**
 * Строка удаления из разделов реестра.
 *
 * Записей с похожим именем может быть несколько (прежняя версия, установка на
 * другого пользователя), поэтому сначала ищем точное совпадение имени, а
 * потом — любое вхождение.
 */
export function pickUninstallString(
  blocks: { key: string; values: Record<string, string> }[],
  appName = APP_NAME
): string | null {
  const named = blocks.filter((block) => {
    const name = block.values.DisplayName ?? ''
    return name.trim().toLowerCase() === appName.toLowerCase()
  })
  const loose = blocks.filter((block) =>
    (block.values.DisplayName ?? '').toLowerCase().includes(appName.toLowerCase())
  )
  for (const list of [named, loose]) {
    for (const block of list) {
      const command = block.values.UninstallString || block.values.QuietUninstallString
      if (command) return command
    }
  }
  return null
}
