"""Сборка иконки приложения: assets/icon_candidate.png → icon.png + icon.ico.

    python tools/make_icon.py [источник.png]

Источник — квадратная картинка иконки. На выходе:
  assets/icon.png   1024×1024 (для предпросмотра и сборки PyInstaller)
  assets/icon.ico   многоразмерный (16…256) — для окна, панели задач и трея
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else ASSETS / "icon_candidate.png"

# размеры, которые Windows запрашивает у .ico
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
MASTER_SIZE = 1024


def prepare(source: Path) -> Image.Image:
    """Приводит источник к квадрату 1024×1024 и слегка поднимает резкость."""
    image = Image.open(source).convert("RGB")
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side))

    # суперсэмплинг: уменьшаем с фильтром высокого качества
    image = image.resize((MASTER_SIZE, MASTER_SIZE), Image.LANCZOS)

    # лёгкая коррекция: контраст и резкость, чтобы мелкие размеры не «мылились»
    image = ImageEnhance.Contrast(image).enhance(1.04)
    image = ImageEnhance.Color(image).enhance(1.05)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.6, percent=65, threshold=3))
    return image


def sharpen_small(image: Image.Image) -> Image.Image:
    """Для мелких размеров: гасим свечение и поднимаем контраст, чтобы не мылилось."""
    lut = [min(255, int((v / 255.0) ** 1.18 * 255)) for v in range(256)]
    image = image.point(lut * 3)
    return ImageEnhance.Contrast(image).enhance(1.16)


def build_ico(master: Image.Image) -> None:
    frames = []
    for size in ICO_SIZES:
        source = sharpen_small(master) if size <= 32 else master
        frames.append(source.resize((size, size), Image.LANCZOS))
    master.save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=[(size, size) for size in ICO_SIZES],
        append_images=frames[1:],
    )


def main() -> int:
    if not SOURCE.exists():
        print(f"источник не найден: {SOURCE}")
        return 1
    ASSETS.mkdir(parents=True, exist_ok=True)

    master = prepare(SOURCE)
    master.save(ASSETS / "icon.png", format="PNG", optimize=True)
    print(f"сохранён {ASSETS / 'icon.png'} ({master.size[0]}×{master.size[1]})")

    build_ico(master)
    print(f"сохранён {ASSETS / 'icon.ico'} ({', '.join(str(s) for s in ICO_SIZES)})")

    # превью: как иконка выглядит в мелких размерах
    columns = [256, 64, 48, 32, 24, 16]
    preview = Image.new("RGB", (len(columns) * 70 + 20, 300), (8, 10, 15))
    x = 10
    for size in columns:
        icon = master.resize((size, size), Image.LANCZOS)
        preview.paste(icon, (x, 20))
        x += 70
    preview.save(ROOT.parent / "icon_preview.png")
    print(f"превью: {ROOT.parent / 'icon_preview.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
