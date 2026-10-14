"""Делает автономный HTML-превью README — для проверки в браузере.

    python tools/preview_readme.py

GitHub рисует Markdown сам, а картинки берёт из репозитория. В этой песочнице
превью работает без сети, поэтому скрипт вклеивает все скриншоты прямо в HTML
(base64) — файл открывается двойным щелчком и выглядит так же, как README
на GitHub.
"""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
OUT = ROOT / "docs" / "readme-preview.html"

CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 20px 80px;
  background: #0d1117; color: #e6edf3;
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans",
        Helvetica, Arial, sans-serif;
}
.page { max-width: 900px; margin: 0 auto; }
h1 { font-size: 40px; border-bottom: 1px solid #30363d; padding-bottom: 12px; margin: 32px 0 20px; }
h2 { font-size: 26px; border-bottom: 1px solid #30363d; padding-bottom: 10px; margin: 36px 0 16px; }
h3 { font-size: 19px; margin: 26px 0 12px; }
p, li { color: #c9d1d9; }
a { color: #58a6ff; text-decoration: none; }
a:hover { text-decoration: underline; }
code {
  background: #161b22; border: 1px solid #30363d; border-radius: 6px;
  padding: 2px 6px; font: 13px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
pre {
  background: #161b22; border: 1px solid #30363d; border-radius: 10px;
  padding: 16px; overflow: auto; font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
pre code { background: none; border: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; display: table; }
th, td { border: 1px solid #30363d; padding: 8px 12px; text-align: left; vertical-align: top; }
th { background: #161b22; font-weight: 600; }
tr:nth-child(even) td { background: #0f141b; }
img { max-width: 100%; border-radius: 8px; border: 1px solid #30363d; }
blockquote {
  margin: 0 0 16px; padding: 0 16px; color: #8b949e;
  border-left: 4px solid #30363d;
}
hr { border: none; border-top: 1px solid #30363d; margin: 32px 0; }
.center { text-align: center; }
.center img { border: none; }
.gallery td { border: none; padding: 6px; text-align: center; background: none !important; }
.gallery sub { color: #8b949e; font-size: 12px; }
details { border: 1px solid #30363d; border-radius: 8px; padding: 10px 14px; margin: 16px 0; }
summary { cursor: pointer; font-weight: 600; }
.note {
  border: 1px solid #30363d; border-left: 4px solid #d29922;
  border-radius: 8px; padding: 12px 16px; margin: 20px 0; background: #161b22;
}
.note b { color: #d29922; }
"""

#: мини-конвертер Markdown -> HTML (не полный, но для этого README хватит)
def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"(?<!\w)@(\w+)", r'<a href="https://github.com/\1">@\1</a>', text)
    return text


def to_html(md: str) -> str:
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    in_code = False
    code_buf: list[str] = []
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if not line.strip():
            i += 1
            continue

        if line.startswith("<"):
            # сырой HTML из README (<div align>, <table>, <td>, <img>, <details>):
            # теги оставляем как есть, только картинки вклеиваем base64
            out.append(embed_images(line))
            i += 1
            continue
        if line.startswith("<!--"):
            i += 1
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            cells = [r for r in cells if not all(set(c) <= set("-: ") and c for c in r)]
            is_gallery = any("<img" in c for r in cells for c in r)
            tag = ' class="gallery"' if is_gallery else ""
            out.append(f"<table{tag}>")
            for n, row in enumerate(cells):
                out.append("<tr>")
                for c in row:
                    cell = inline(c)
                    cell = re.sub(
                        r'&lt;img src="([^"]+)"([^&]*?)&gt;',
                        lambda m: img_tag(m.group(1), m.group(2)),
                        cell,
                    )
                    cell = re.sub(r"&lt;br&gt;", "<br>", cell)
                    cell = re.sub(r"&lt;sub&gt;", "<sub>", cell)
                    cell = re.sub(r"&lt;/sub&gt;", "</sub>", cell)
                    cell = re.sub(r"&lt;b&gt;", "<b>", cell)
                    cell = re.sub(r"&lt;/b&gt;", "</b>", cell)
                    cell = re.sub(r"&lt;code&gt;", "<code>", cell)
                    cell = re.sub(r"&lt;/code&gt;", "</code>", cell)
                    cell = re.sub(r'width="50%"', 'width="50%"', cell)
                    cell = cell.replace("</td >", "</td>")
                    cell = re.sub(r"&lt;(/?)(td|tr|table)([^&]*)&gt;", r"<\1\2\3>", cell)
                    out.append(f"<td>{cell}</td>" if n else f"<th>{cell}</th>")
                out.append("</tr>")
            out.append("</table>")
            continue

        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip("> ").rstrip())
                i += 1
            text_ = " ".join(buf)
            m = re.match(r"\[!(\w+)\]\s*(.*)", text_)
            if m:
                out.append(f'<div class="note"><b>{m.group(1)}</b> — {inline(m.group(2))}</div>')
            else:
                out.append(f"<blockquote>{inline(text_)}</blockquote>")
            continue

        if line.startswith("---"):
            out.append("<hr>")
            i += 1
            continue

        if line.startswith("* ") or re.match(r"^\d+\.\s", line):
            ordered = bool(re.match(r"^\d+\.\s", line))
            items = []
            while i < len(lines) and (
                lines[i].startswith("* ") or re.match(r"^\d+\.\s", lines[i])
                or (lines[i].startswith("  ") and lines[i].strip())
            ):
                item = re.sub(r"^(\*|\d+\.)\s+", "", lines[i]).strip()
                items.append(item)
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue

        out.append(f"<p>{inline(line)}</p>")
        i += 1
    return "\n".join(out)


IMG_RE = re.compile(r'<img\s+src="([^"]+)"([^>]*)>')


def embed_images(text: str) -> str:
    """Заменяет <img src="docs/..."> на data:URI — превью работает без сети."""
    def repl(m: re.Match) -> str:
        return img_tag(m.group(1), m.group(2))

    return IMG_RE.sub(repl, text)


def img_tag(src: str, attrs: str) -> str:
    path = ROOT / src
    if not path.exists():
        return f'<span style="color:#f85149">[нет {html.escape(src)}]</span>'
    data = base64.b64encode(path.read_bytes()).decode()
    width = re.search(r'width="(\d+)"', attrs or "")
    w = f' width="{width.group(1)}"' if width else ""
    alt = re.search(r'alt="([^"]*)"', attrs or "")
    a = alt.group(1) if alt else src
    return f'<img src="data:image/png;base64,{data}" alt="{html.escape(a)}"{w}>'


def main() -> int:
    md = README.read_text(encoding="utf-8")
    body = to_html(md)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "<!doctype html>\n<html lang=\"ru\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        "<title>Zapret Hub — README preview</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n<div class=\"page\">\n{body}\n</div>\n</body>\n</html>\n",
        encoding="utf-8",
    )
    print(f"готово: {OUT} ({OUT.stat().st_size // 1024} КБ)")
    print("откройте файл в браузере — это README такими, какими их увидит GitHub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
