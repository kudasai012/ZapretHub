/**
 * Переход с одной версии программы на другую.
 *
 * Пока установщик работает, старая программа уже закрыта — показывать
 * обновление некому. Поэтому переход видит та программа, которая поднялась
 * после обновления: она знает, с какой версии её обновляли (ключ
 * `--updated-from`) и показывает короткое окно «было → стало».
 *
 * Раньше вместо этого окна на экране висело командное окно сторожа: он
 * ждал конца установки и висел, даже когда установка давно кончилась.
 */

/** Ключ, с которым поднимается обновлённая программа. */
export const UPDATED_ARG = '--updated-from'

/**
 * Ключ переустановки: программа поставлена заново, версия та же.
 *
 * Без него окно перехода показало бы «1.0.8 → 1.0.8»: то же самое, что
 * написать «ничего не изменилось» большими буквами.
 */
export const REINSTALL_ARG = '--reinstall'

/** Так сторож поднимает программу после установки. */
export function relaunchArgs(fromVersion: string, reinstall: boolean): string[] {
  return reinstall ? [updatedArg(fromVersion), REINSTALL_ARG] : [updatedArg(fromVersion)]
}

/** Программу поставили заново, а не обновили. */
export function reinstalled(argv: string[] = process.argv): boolean {
  return argv.includes(REINSTALL_ARG)
}

/** Ключ вместе с версией: то, что сторож передаёт программе. */
export function updatedArg(fromVersion: string): string {
  return `${UPDATED_ARG}=${fromVersion}`
}

/**
 * Версия, с которой обновились.
 *
 * Пустая строка — значит, программу запустили обычно, и показывать переход
 * незачем. Ключ без версии тоже считаем за обычный запуск: сторож всегда
 * пишет его с версией.
 */
export function updatedFrom(argv: string[] = process.argv): string {
  const prefix = `${UPDATED_ARG}=`
  for (const arg of argv) {
    if (!arg.startsWith(prefix)) continue
    const version = arg.slice(prefix.length).trim()
    if (/^\d+\.\d+\.\d+/.test(version)) return version
  }
  return ''
}

/**
 * Окно перехода: что стоит сейчас и что было раньше.
 *
 * Страница собрана целиком из одного куска разметки: ни шрифтов, ни картинок
 * из интернета, ни отдельного файла на диске. Окно показывается на секунды
 * сразу после обновления, и ждать в этот момент загрузку чего бы то ни было
 * нельзя — человек должен увидеть ответ сразу.
 *
 * Цвета и шрифт — те же, что в самой программе: окно выглядит её частью, а не
 * чужой вставкой.
 */
export function updateSplashHtml(
  from: string,
  to: string,
  lang: 'ru' | 'en' = 'ru',
  reinstall = false
): string {
  const title =
    lang === 'en'
      ? reinstall
        ? 'Zapret Hub reinstalled'
        : 'Zapret Hub updated'
      : reinstall
        ? 'Zapret Hub переустановлен'
        : 'Zapret Hub обновлён'
  const ready = lang === 'en' ? 'Opening the window' : 'Открываю окно'
  const safe = (text: string): string =>
    text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  // Переустановка — это та же версия, поэтому стрелки «было → стало» здесь
  // нет: показываем версию один раз.
  const versions = reinstall
    ? `<b>${safe(to)}</b>`
    : `<b>${safe(from)}</b><span class="arrow">&#8594;</span><b>${safe(to)}</b>`
  return `<!doctype html>
<html lang="${lang}">
<head>
<meta charset="utf-8">
<title>Zapret Hub</title>
<style>
  :root { color-scheme: dark }
  * { box-sizing: border-box }
  html, body { height: 100%; margin: 0 }
  body {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 14px; background: #09090b; color: #fafafa; overflow: hidden;
    font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
    -webkit-font-smoothing: antialiased; user-select: none; cursor: default;
    animation: fade 260ms ease-out both;
  }
  .ring {
    width: 42px; height: 42px; border-radius: 50%;
    border: 3px solid rgba(250, 250, 250, 0.14);
    border-top-color: #fafafa;
    animation: spin 900ms linear infinite;
  }
  .title { font-size: 15px; font-weight: 600; letter-spacing: -0.01em }
  .versions { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #a1a1aa }
  .versions b { color: #fafafa; font-weight: 600; font-variant-numeric: tabular-nums }
  .arrow { animation: slide 1.5s ease-in-out infinite }
  .line { position: relative; width: 168px; height: 2px; border-radius: 2px; background: rgba(250,250,250,0.12); overflow: hidden }
  .line i { position: absolute; inset: 0; transform-origin: left; background: #fafafa; animation: fill 2600ms ease-out both }
  .hint { font-size: 11px; color: #71717a }
  @keyframes spin { to { transform: rotate(360deg) } }
  @keyframes fill { from { transform: scaleX(0) } to { transform: scaleX(1) } }
  @keyframes slide { 0%, 100% { opacity: .45; transform: translateX(-2px) } 50% { opacity: 1; transform: translateX(2px) } }
  @keyframes fade { from { opacity: 0; transform: scale(.97) } to { opacity: 1; transform: none } }
  @media (prefers-reduced-motion: reduce) {
    .ring, .arrow, .line i { animation-duration: 2600ms; animation-iteration-count: 1 }
  }
</style>
</head>
<body>
  <div class="ring"></div>
  <div class="title">${safe(title)}</div>
  <div class="versions">${versions}</div>
  <div class="line"><i></i></div>
  <div class="hint">${safe(ready)}</div>
</body>
</html>`
}
