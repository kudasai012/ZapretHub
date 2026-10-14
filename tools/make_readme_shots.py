"""Пересобирает единственный скриншот для README — docs/f_home.png.

    python tools/make_readme_shots.py

Что делает:
  1) гоняет tools/screenshots.py во временную папку (offscreen Qt);
  2) берёт кадр «Главная — всё работает» и кладёт его в docs/f_home.png;
  3) оптимизирует PNG (256 цветов + optimize).

Больше никаких картинок в README нет — одна на весь репозиторий.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "f_home.png"

#: какой кадр tools/screenshots.py берём на роль героя README
SOURCE = "dashboard_running.png"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="zhub-shots-") as tmp:
        raw = Path(tmp)
        print("[1/2] снимаю интерфейс...")
        env = dict(**os.environ, QT_QPA_PLATFORM="offscreen")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "screenshots.py"), str(raw)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(proc.stdout[-2000:])
            print(proc.stderr[-2000:], file=sys.stderr)
            print("не удалось снять скриншот")
            return 1
        src = raw / SOURCE
        if not src.exists():
            print(f"screenshots.py не сохранил {SOURCE}")
            return 1

        print("[2/2] оптимизирую...")
        from PIL import Image

        before = src.stat().st_size
        im = Image.open(src).convert("RGB")
        # тёмный интерфейс с плоскими заливками отлично сжимается палитрой
        im.quantize(colors=256, method=Image.MEDIANCUT,
                    dither=Image.FLOYDSTEINBERG).save(OUT, optimize=True)
        after = OUT.stat().st_size

    print(f"готово: {OUT}  {im.size[0]}x{im.size[1]}")
    print(f"       {before // 1024} КБ -> {after // 1024} КБ "
          f"(-{100 - after * 100 // max(before, 1)}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
