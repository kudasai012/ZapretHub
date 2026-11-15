/**
 * Простая разметка заметок о выпуске.
 *
 * Заметки к релизу пишут на GitHub разметкой: заголовки решёткой, списки
 * дефисами, жирный звёздочками. В окне обновления это показывалось как есть,
 * и человек видел «* » и «### » вместо текста.
 *
 * Своя разборка, а не готовая библиотека: из всей разметки нужны пять случаев,
 * а тянуть ради них пол-мегабайта кода в окно, которое показывается раз в
 * месяц, незачем. Разбор отдаёт токены, а не готовую строку HTML: вставлять
 * чужой HTML в окно программы нельзя — это сразу дыра.
 */

/** Кусок строки внутри абзаца или заголовка. */
export type Inline =
  | { kind: 'text'; text: string }
  | { kind: 'bold'; text: string }
  | { kind: 'italic'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'link'; text: string; href: string }

/** Кусок текста заметки: заголовок, абзац, список, код, цитата или черта. */
export type Block =
  | { kind: 'heading'; level: number; content: Inline[] }
  | { kind: 'paragraph'; content: Inline[] }
  | { kind: 'list'; ordered: boolean; items: Inline[][] }
  | { kind: 'code'; text: string }
  | { kind: 'quote'; content: Inline[] }
  | { kind: 'rule' }

/**
 * Ссылки наружу: только http и https.
 *
 * javascript: и file: не пропускаем: заметка приходит с GitHub, и щелчок по
 * такой ссылке выполнял бы что угодно уже внутри программы.
 */
export function safeHref(href?: string): string {
  const url = (href ?? '').trim()
  return /^https?:\/\//i.test(url) ? url : ''
}

/**
 * Разборка строки внутри абзаца.
 *
 * Порядок важен: сначала ссылки и код, иначе звёздочки из адреса или из
 * текста в обратных кавычках превратятся в жирный шрифт.
 */
export function parseInline(text?: string): Inline[] {
  const out: Inline[] = []
  let rest: string = text ?? ''
  // Набор один на весь проход: так разметка не перескакивает через куски,
  // которые уже разобраны.
  const pattern = /\[([^\]]*)\]\(([^)\s]+)\)|`([^`]+)`|\*\*([^*]+)\*\*|\*([^*]+)\*|_([^_]+)_/
  const push = (text_: string): void => {
    if (text_ === '') return
    const last = out[out.length - 1]
    if (last?.kind === 'text') last.text += text_
    else out.push({ kind: 'text', text: text_ })
  }
  while (rest !== '') {
    const found = pattern.exec(rest)
    if (!found || found.index === undefined) break
    push(rest.slice(0, found.index))
    if (found[1] !== undefined) {
      const href = safeHref(found[2] ?? '')
      // Адрес не наружу — оставляем как простой текст, а не как ссылку.
      if (href) out.push({ kind: 'link', text: found[1] || href, href })
      else push(found[0])
    } else if (found[3] !== undefined) {
      out.push({ kind: 'code', text: found[3] })
    } else if (found[4] !== undefined) {
      out.push({ kind: 'bold', text: found[4] })
    } else if (found[5] !== undefined) {
      out.push({ kind: 'italic', text: found[5] })
    } else if (found[6] !== undefined) {
      out.push({ kind: 'italic', text: found[6] })
    }
    rest = rest.slice(found.index + found[0].length)
  }
  push(rest)
  return out
}

/** Заголовок ли это и какого уровня. */
function headingLevel(line: string): number {
  const found = /^(#{1,6})\s+/.exec(line)
  return found ? found[1].length : 0
}

/**
 * Разборка заметки целиком.
 *
 * Разметка на GitHub прощает многое, поэтому неизвестное не выбрасывается, а
 * остаётся текстом: лучше показать лишнюю строку, чем потерять половину
 * заметки о выпуске.
 */
export function parseMarkdown(text?: string): Block[] {
  // Заметка может не прийти вовсе: GitHub разрешает выпуск без описания, а ответ
  // мог оборваться на середине.
  const lines = (text ?? '').replace(/\r\n?/g, '\n').split('\n')
  const blocks: Block[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    const trimmed = line.trim()

    if (trimmed === '') {
      index += 1
      continue
    }

    // Код тройными кавычками: внутри него разметки нет.
    if (/^```/.test(trimmed)) {
      const body: string[] = []
      index += 1
      while (index < lines.length && !/^```/.test(lines[index].trim())) {
        body.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push({ kind: 'code', text: body.join('\n') })
      continue
    }

    if (/^(---|\*\*\*|___)\s*$/.test(trimmed)) {
      blocks.push({ kind: 'rule' })
      index += 1
      continue
    }

    const level = headingLevel(trimmed)
    if (level > 0) {
      blocks.push({
        kind: 'heading',
        level,
        // Решётки на конце («## Заголовок ##») — тоже разметка GitHub.
        content: parseInline(trimmed.replace(/^#{1,6}\s+/, '').replace(/\s+#+\s*$/, ''))
      })
      index += 1
      continue
    }

    if (/^>\s?/.test(trimmed)) {
      const body: string[] = []
      while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
        body.push(lines[index].trim().replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push({ kind: 'quote', content: parseInline(body.join(' ')) })
      continue
    }

    // Список: подряд идущие строки с дефисом, звёздочкой или номером.
    const bullet = /^[-*+]\s+/.exec(trimmed)
    const numbered = /^\d+[.)]\s+/.exec(trimmed)
    if (bullet || numbered) {
      const ordered = numbered !== null
      const marker = ordered ? numbered : bullet
      const items: Inline[][] = []
      while (index < lines.length) {
        const current = lines[index].trim()
        const same = ordered ? /^\d+[.)]\s+/.exec(current) : /^[-*+]\s+/.exec(current)
        if (!same) break
        items.push(parseInline(current.slice(same[0].length)))
        index += 1
      }
      if (items.length > 0) {
        blocks.push({ kind: 'list', ordered, items })
        continue
      }
      void marker
    }

    // Абзац: до пустой строки или до начала следующего блока.
    const body: string[] = []
    while (index < lines.length) {
      const current = lines[index].trim()
      if (
        current === '' ||
        /^```/.test(current) ||
        headingLevel(current) > 0 ||
        /^>\s?/.test(current) ||
        /^[-*+]\s+/.test(current) ||
        /^\d+[.)]\s+/.test(current) ||
        /^(---|\*\*\*|___)\s*$/.test(current)
      ) {
        break
      }
      body.push(current)
      index += 1
    }
    if (body.length > 0) blocks.push({ kind: 'paragraph', content: parseInline(body.join(' ')) })
    else index += 1
  }

  return blocks
}
