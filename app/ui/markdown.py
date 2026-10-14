"""Простой рендер Markdown в HTML для описания релизов.

Нужен ровно тот набор, который встречается в телах релизов на GitHub:
заголовки, списки, жирный/курсив, код, ссылки, горизонтальные линии.
Полноценный парсер Markdown тут не нужен — и не хочется тащить
зависимость ради одного окна.
"""
from __future__ import annotations

import html
import re

__all__ = ["markdown_to_html"]

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_HR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_CODE_SPAN = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    """Разметка внутри строки: код, ссылки, жирный, курсив."""
    placeholders: list[str] = []

    def stash(rendered: str) -> str:
        placeholders.append(rendered)
        return f"\x00{len(placeholders) - 1}\x00"

    # код прячем первым делом: внутри него ничего не размечаем
    def code(match: re.Match) -> str:
        return stash(
            '<code style="background:rgba(255,255,255,0.08);'
            'border-radius:5px;padding:1px 5px;font-family:Consolas,monospace;'
            'font-size:9pt;color:#cfe0ff;">'
            + html.escape(match.group(1))
            + "</code>"
        )

    text = _CODE_SPAN.sub(code, text)

    def link(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        return stash(
            f'<a href="{html.escape(url, quote=True)}" '
            f'style="color:#82a8ff;text-decoration:none;">'
            f"{html.escape(label)}</a>"
        )

    text = _LINK.sub(link, text)
    text = html.escape(text)

    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<i>\1</i>", text)

    # возвращаем спрятанное
    def restore(match: re.Match) -> str:
        return placeholders[int(match.group(1))]

    return re.sub(r"\x00(\d+)\x00", restore, text)


def markdown_to_html(markdown: str) -> str:
    """Превращает текст релиза в HTML для QTextBrowser."""
    lines = (markdown or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    list_stack: list[str] = []
    paragraph: list[str] = []

    def close_list() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    def start_paragraph() -> None:
        """Начало абзаца всегда закрывает список: текст идёт после него."""
        close_list()

    def flush_paragraph() -> None:
        if paragraph:
            text = " ".join(part for part in paragraph if part)
            out.append(
                '<p style="margin:0 0 8px 0;line-height:150%;">'
                + _inline(text)
                + "</p>"
            )
            paragraph.clear()

    def open_list(tag: str, style: str) -> None:
        if not list_stack or list_stack[-1] != tag:
            close_list()
            list_stack.append(tag)
            out.append(style)

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            # пустая строка сама по себе список не закрывает: в Markdown
            # между пунктами может быть отбивка, и это всё ещё один список
            flush_paragraph()
            continue
        if _HR.match(line):
            flush_paragraph()
            close_list()
            out.append('<hr style="border:none;border-top:1px solid #2a3448;">')
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            size = {1: "14pt", 2: "12pt", 3: "10.5pt"}.get(level, "10pt")
            out.append(
                f'<p style="margin:12px 0 6px 0;font-size:{size};'
                f'font-weight:700;color:#eaeef7;">'
                + _inline(heading.group(2))
                + "</p>"
            )
            continue

        bullet = _BULLET.match(line)
        if bullet:
            flush_paragraph()
            open_list("ul", '<ul style="margin:0 0 8px 0;padding-left:20px;">')
            out.append(
                '<li style="margin:0 0 4px 0;line-height:145%;">'
                + _inline(bullet.group(1))
                + "</li>"
            )
            continue

        numbered = _NUMBERED.match(line)
        if numbered:
            flush_paragraph()
            open_list("ol", '<ol style="margin:0 0 8px 0;padding-left:22px;">')
            out.append(
                '<li style="margin:0 0 4px 0;line-height:145%;">'
                + _inline(numbered.group(1))
                + "</li>"
            )
            continue

        start_paragraph()
        paragraph.append(line.strip())

    flush_paragraph()
    close_list()
    body = "".join(out)
    return (
        '<div style="color:#c9d2e4;font-size:10pt;font-family:'
        "'Segoe UI',sans-serif;\">" + body + "</div>"
    )
