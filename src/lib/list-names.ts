/**
 * Названия списков адресов.
 *
 * В пакете zapret списки называются служебными именами: list-general.txt,
 * list-general-user.txt, ipset-exclude-user.txt. Это не случайный мусор, а
 * общепринятые имена: любой, кто хоть раз правил zapret, узнаёт list-general
 * с первого взгляда, а выдуманные слова («Общий список», «Адреса: все») только
 * мешают — по ним невозможно найти нужный файл в папке пакета.
 *
 * Поэтому в интерфейсе показываем само имя списка, без расширения .txt:
 * «list-general», «list-general-user». Расширение не нужно: все списки — .txt.
 * А что список делает, объясняется подсказкой при наведении: она есть, но не
 * лезет в глаза.
 */

export type Lang = 'ru' | 'en'

/** Чем список отличается от остальных — для подсказки, не для подписи. */
const NOTES: Record<string, Record<Lang, string>> = {
  'list-general.txt': {
    ru: 'Общий список: сюда попадают заблокированные адреса из пакета zapret',
    en: 'The general list: blocked addresses that come with the zapret package'
  },
  'list-general-user.txt': {
    ru: 'Свои адреса к общему списку: сюда добавляет Zapret Hub и вы сами',
    en: 'Your own addresses for the general list: added by Zapret Hub and by you'
  },
  'list-exclude.txt': {
    ru: 'Исключения: эти адреса обход не трогает',
    en: 'Exclusions: addresses the bypass leaves alone'
  },
  'list-exclude-user.txt': {
    ru: 'Свои исключения: адреса, которые вы добавили в исключения',
    en: 'Your own exclusions: addresses you added to the exclusion list'
  },
  'list-google.txt': {
    ru: 'Список Google из пакета zapret',
    en: 'The Google list that comes with the zapret package'
  },
  'ipset-all.txt': {
    ru: 'Адреса, по которым zapret выбирает, что пропускать через себя',
    en: 'The addresses zapret uses to decide what to pass through itself'
  },
  'ipset-any.txt': {
    ru: 'Адреса без ограничений: через себя идёт всё',
    en: 'Addresses with no limit: everything goes through the bypass'
  },
  'ipset-exclude.txt': {
    ru: 'Адреса-исключения для ipset',
    en: 'Address exclusions for ipset'
  },
  'ipset-exclude-user.txt': {
    ru: 'Свои адреса-исключения для ipset',
    en: 'Your own address exclusions for ipset'
  }
}

/**
 * Название списка для интерфейса: служебное имя без расширения.
 *
 * Именно так список называют и в пакете zapret, и в его инструкциях, поэтому
 * «list-general» узнаётся сразу, а «Общий список» — нет.
 */
export function listTitle(name: string, _lang?: Lang): string {
  return name.replace(/\.txt$/i, '')
}

/** Чем этот список занят — для подсказки при наведении. */
export function listNote(name: string, lang: Lang): string {
  const known = NOTES[name.toLowerCase()]
  if (known) return known[lang]
  return lang === 'ru'
    ? `Список адресов ${listTitle(name)}`
    : `Address list ${listTitle(name)}`
}

/** Название и файл рядом: в подсказке к полю видно, какой файл правится. */
export function listLabel(name: string, _lang: Lang): string {
  return `${listTitle(name)} · ${name}`
}
