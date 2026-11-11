/**
 * Разбор ссылок, которые человек вставляет в строку на Главной.
 *
 * Вставляют по-разному: одну ссылку, несколько в ряд через пробел, столбиком
 * из блокнота, списком через запятую — иногда с «https://», путём и «?utm».
 * Спискам zapret нужно только имя: `discord.com`, без схемы и без пути.
 * Поэтому здесь ссылки приводятся к именам, а всё, что именем не стало,
 * отбрасывается — молча дописывать в список мусор нельзя.
 */

/** На что похоже имя сайта: латиница, цифры, точки и дефисы. */
const HOST = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/

/** Разделители: пробелы, запятые, точки с запятой, табуляция, перевод строки. */
const SPLIT = /[\s,;]+/

/**
 * Имя сайта из того, что вставил человек.
 *
 * Пустая строка — значит, это не сайт: пусть лучше пропадёт, чем попадёт в
 * список адресов и сломает обход.
 */
export function hostOf(raw: string): string {
  let text = raw.trim().toLowerCase()
  if (text === '') return ''
  // Схему и путь отбрасываем: в списках zapret только имена.
  const withoutScheme = text.replace(/^[a-z][a-z0-9+.-]*:\/\//, '')
  text = withoutScheme.split(/[/?#]/)[0]
  // Порт и имя пользователя в списке не нужны.
  text = text.split('@').pop() ?? ''
  text = text.split(':')[0]
  // «www.» в списке zapret не пишут: обход всё равно смотрит на домен целиком,
  // и два варианта одного сайта в списке — это две строки вместо одной.
  if (text.startsWith('www.')) text = text.slice(4)
  text = text.replace(/\.+$/, '')
  if (!HOST.test(text)) return ''
  return text
}

/**
 * Имена сайтов из строки ввода.
 *
 * Повторы внутри одной вставки убираются: вставили один и тот же адрес дважды —
 * в список он попадёт один раз.
 */
export function parseAddresses(input: string): string[] {
  const found: string[] = []
  const seen = new Set<string>()
  for (const piece of input.split(SPLIT)) {
    const host = hostOf(piece)
    if (!host || seen.has(host)) continue
    seen.add(host)
    found.push(host)
  }
  return found
}

/**
 * Дописывает адреса к тексту списка.
 *
 * Что уже есть в списке, не повторяется: сравнение без учёта регистра, потому
 * что для обхода `Example.com` и `example.com` — один и тот же адрес.
 * Комментарии и пустые строки остаются на месте — человек мог писать туда
 * пояснения, и стирать их незачем.
 */
export function mergeListText(
  text: string,
  hosts: string[]
): { text: string; added: string[] } {
  const lines = text.split('\n')
  const known = new Set(
    lines
      .map((line) => line.trim().toLowerCase())
      .filter((line) => line !== '' && !line.startsWith('#'))
  )
  const added: string[] = []
  for (const host of hosts) {
    if (known.has(host.toLowerCase())) continue
    known.add(host.toLowerCase())
    added.push(host)
  }
  if (added.length === 0) return { text, added }

  // Перевод строки в конце мог отсутствовать — дописываем, чтобы первый же
  // новый адрес не приклеился к последней строке.
  const base = text === '' || text.endsWith('\n') ? text : `${text}\n`
  return { text: `${base}${added.join('\n')}\n`, added }
}
