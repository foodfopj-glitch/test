# -*- coding: utf-8 -*-
"""
Рисует иконку программы (data/icon.png и data/icon.ico).

Запуск:  python tools/make_icon.py
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def draw_icon(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size

    # фоновая «таблетка» со скруглением
    pad = int(s * 0.06)
    draw.rounded_rectangle([pad, pad, s - pad, s - pad], radius=int(s * 0.26),
                           fill=(28, 39, 51, 255))
    draw.rounded_rectangle([pad, pad, s - pad, s - pad], radius=int(s * 0.26),
                           outline=(46, 204, 113, 255), width=max(2, int(s * 0.03)))

    # микрофон
    cx = s // 2
    cap_w, cap_h = int(s * 0.22), int(s * 0.34)
    top = int(s * 0.20)
    draw.rounded_rectangle([cx - cap_w // 2, top, cx + cap_w // 2, top + cap_h],
                           radius=cap_w // 2, fill=(232, 238, 246, 255))
    # дуга-подставка
    arc_box = [cx - int(s * 0.19), top + int(s * 0.14), cx + int(s * 0.19), top + int(s * 0.52)]
    draw.arc(arc_box, start=0, end=180, fill=(232, 238, 246, 255),
             width=max(3, int(s * 0.035)))
    # ножка
    draw.line([cx, top + int(s * 0.50), cx, top + int(s * 0.62)],
              fill=(232, 238, 246, 255), width=max(3, int(s * 0.032)))
    draw.line([cx - int(s * 0.09), top + int(s * 0.62), cx + int(s * 0.09), top + int(s * 0.62)],
              fill=(232, 238, 246, 255), width=max(3, int(s * 0.032)))

    # медицинский крест
    cross = int(s * 0.15)
    cxx, cyy = int(s * 0.76), int(s * 0.24)
    t = max(3, int(s * 0.035))
    draw.rectangle([cxx - t // 2, cyy - cross // 2, cxx + t // 2, cyy + cross // 2],
                   fill=(46, 204, 113, 255))
    draw.rectangle([cxx - cross // 2, cyy - t // 2, cxx + cross // 2, cyy + t // 2],
                   fill=(46, 204, 113, 255))
    return img


def main() -> int:
    os.makedirs(DATA, exist_ok=True)
    icon = draw_icon(256)
    png = os.path.join(DATA, "icon.png")
    icon.save(png)
    ico = os.path.join(DATA, "icon.ico")
    icon.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Готово:", png)
    print("Готово:", ico)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
