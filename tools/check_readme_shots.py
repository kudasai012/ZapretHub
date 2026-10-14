"""Проверяет, что docs/f_home.png на месте и README на него ссылается.

    python tools/check_readme_shots.py

Ловит типичную беду: картинку переименовали или удалили, а README о ней
не знает — на GitHub вместо скриншота показывается значок «битая картинка».
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
IMG = ROOT / "docs" / "f_home.png"
REF = "docs/f_home.png"

errors: list[str] = []
warnings: list[str] = []


def main() -> int:
    if not README.exists():
        print("нет README.md")
        return 1

    text = README.read_text(encoding="utf-8")
    refs = sorted(set(re.findall(r'(?:src="|!\[[^\]]*\]\()([^")]+\.png)', text)))

    for ref in refs:
        if ref.startswith(("/", "http://", "https://")):
            errors.append(f"{ref}: путь должен быть относительным, иначе GitHub не покажет")
        elif not (ROOT / ref).exists():
            errors.append(f"README ссылается на {ref}, а файла нет")

    if not IMG.exists():
        errors.append(f"нет {REF} — это единственная картинка README")
    else:
        size = IMG.stat().st_size
        if size > 512 * 1024:
            warnings.append(f"{REF} весит {size // 1024} КБ — стоит оптимизировать")
        from PIL import Image

        with Image.open(IMG) as im:
            if im.size[0] < 900:
                warnings.append(f"{REF} всего {im.size[0]}x{im.size[1]} — на GitHub будет мыльно")

    if len(refs) > 1:
        warnings.append(f"в README {len(refs)} картинок, а задумана одна: {', '.join(refs)}")

    print("проверяю README.md и docs/f_home.png")
    print(f"  ссылок на .png в README : {len(refs)}")
    print(f"  docs/f_home.png         : "
          f"{'есть, ' + str(IMG.stat().st_size // 1024) + ' КБ' if IMG.exists() else 'НЕТ'}")
    for w in warnings:
        print(f"  ?  {w}")
    for e in errors:
        print(f"  X  {e}")
    if errors:
        print(f"\nОШИБОК: {len(errors)}")
        return 1
    print("\nвсё чисто")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
