# Gera o icone do app (1024x1024 PNG) para o TikTok Developer Portal.
# Uso: python tools/gerar_icone_tiktok.py
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

SIZE = 1024
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "atlas_icon_1024.png")


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def main() -> None:
    top = (14, 21, 42)      # azul bem escuro
    bottom = (37, 99, 235)  # azul vibrante

    img = Image.new("RGB", (SIZE, SIZE), top)
    draw = ImageDraw.Draw(img)

    # Fundo em degrade (de cima escuro para baixo azul).
    for y in range(SIZE):
        t = y / (SIZE - 1)
        draw.line([(0, y), (SIZE, y)], fill=_lerp(top, bottom, t))

    # Anel (estilo "planeta / atlas").
    cx = cy = SIZE // 2
    r_out = int(SIZE * 0.34)
    ring_w = int(SIZE * 0.045)
    draw.ellipse(
        [cx - r_out, cy - r_out, cx + r_out, cy + r_out],
        outline=(148, 197, 255),
        width=ring_w,
    )

    # Orbita inclinada (elipse fina atravessando).
    r_orbit = int(SIZE * 0.30)
    orbit = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    od = ImageDraw.Draw(orbit)
    od.ellipse(
        [cx - r_orbit, cy - int(r_orbit * 0.42), cx + r_orbit, cy + int(r_orbit * 0.42)],
        outline=(96, 165, 250, 230),
        width=int(SIZE * 0.02),
    )
    orbit = orbit.rotate(28, center=(cx, cy), resample=Image.BICUBIC)
    img.paste(orbit, (0, 0), orbit)

    # Letra "A" central.
    letter = "A"
    font = None
    for name in ("segoeuib.ttf", "arialbd.ttf", "Arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, int(SIZE * 0.44))
            break
        except Exception:  # noqa: BLE001
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), letter, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = cx - tw / 2 - bbox[0]
    ty = cy - th / 2 - bbox[1]
    draw.text((tx, ty), letter, font=font, fill=(255, 255, 255))

    img.save(OUT, "PNG")
    print(f"OK -> {OUT}  ({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
