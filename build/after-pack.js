/**
 * После упаковки: убираем из приложения то, что ему не нужно.
 *
 * Electron кладёт рядом с собой локали на пять десятков языков — около 40 МБ
 * мусора, из которого программе нужны два: русский и английский. Остальное
 * удаляем: приложение весит вдвое меньше, обновляется быстрее.
 *
 * Из asar тоже убираем node_modules: там только отладочный мусор для
 * разработчика, а не то, чем программа пользуется в работе.
 */
const fs = require('node:fs')
const path = require('node:path')

/** Сколько места заняли локали до уборки — для журнала. */
function dirSize(target) {
  let total = 0
  let entries = []
  try {
    entries = fs.readdirSync(target, { withFileTypes: true })
  } catch {
    return 0
  }
  for (const entry of entries) {
    const full = path.join(target, entry.name)
    if (entry.isDirectory()) total += dirSize(full)
    else {
      try {
        total += fs.statSync(full).size
      } catch {
        /* файл исчез между чтением и подсчётом — не наше дело */
      }
    }
  }
  return total
}

module.exports = async function afterPack(context) {
  const appOutDir = context.appOutDir
  const locales = path.join(appOutDir, 'locales')
  const keep = new Set(['en-US.pak', 'ru.pak'])

  let saved = 0
  try {
    for (const name of fs.readdirSync(locales)) {
      if (keep.has(name)) continue
      const full = path.join(locales, name)
      if (!fs.statSync(full).isFile()) continue
      saved += fs.statSync(full).size
      fs.unlinkSync(full)
    }
  } catch {
    /* папки локалей нет — значит, удалять нечего */
  }

  // node_modules внутри asar: программа работает из app.asar, а отладочные
  // зависимости ей не нужны. Удаляем через распаковку, чтобы asar остался
  // целым.
  const asar = path.join(appOutDir, 'resources', 'app.asar')
  try {
    if (fs.existsSync(asar)) {
      const before = dirSize(asar)
      const unpacked = path.join(appOutDir, 'resources', 'app.asar.unpacked', 'node_modules')
      if (fs.existsSync(unpacked)) {
        saved += dirSize(unpacked)
        fs.rmSync(unpacked, { recursive: true, force: true })
      }
      const after = dirSize(asar)
      saved += Math.max(0, before - after)
    }
  } catch {
    /* не смогли — не беда, приложение работает и без уборки */
  }

  console.log(`[afterPack] убрано лишнего: ${(saved / 1024 / 1024).toFixed(1)} МБ`)
}
