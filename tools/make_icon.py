"""Draws the RingBlast icon: launcher/ringblast.ico (multi-size) and launcher/ringblast.png.
Run:  python tools/make_icon.py      (needs Pillow)

Motif: a stope cross-section (rock face) with the fan of drill holes of a ring blast radiating
from the drift, the toes of the holes marked by amber charges.
"""
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
N = 1024                                  # master size; drawn once, downscaled for every icon size
S = 4                                     # supersampling inside the master (anti-aliasing)


def vertical_gradient(size, top, bottom):
    g = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        g.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return g.resize((size, size))


def master(simple: bool = False) -> Image.Image:
    W = N * S
    k = W / 1024                           # design coordinates are given on a 1024 grid
    pt = lambda x, y: (x * k, y * k)

    # ---- background: rounded square, deep blue gradient
    bg = vertical_gradient(W, (40, 62, 92), (16, 26, 44))
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], radius=int(210 * k), fill=255)
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    img.paste(bg, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # ---- stope: tall rectangle (rock face), slightly lighter than the background
    x0, x1, y0, y1 = 232, 792, 118, 880
    d.rounded_rectangle([x0 * k, y0 * k, x1 * k, y1 * k], radius=int(26 * k), fill=(58, 84, 120, 255),
                        outline=(168, 190, 220, 255), width=int(16 * k))

    # ---- drift at the bottom centre
    dx, dy = 512, 842                      # fan centre
    d.rounded_rectangle([(dx - 78) * k, (dy - 34) * k, (dx + 78) * k, y1 * k + 8 * k], radius=int(14 * k),
                        fill=(16, 26, 44, 255), outline=(255, 176, 32, 255), width=int(12 * k))

    # ---- fan of holes: from the drift to toes spread along the top and the two walls
    toes = []
    n_top = 5 if simple else 7             # small sizes: fewer, bolder holes
    for i in range(n_top):                 # top edge
        toes.append((x0 + 58 + i * (x1 - x0 - 116) / (n_top - 1), y0 + 58))
    toes += [(x0 + 58, 420), (x1 - 58, 420)] if simple else [(x0 + 58, 330), (x1 - 58, 330), (x0 + 58, 560), (x1 - 58, 560)]
    for tx, ty in toes:
        d.line([pt(dx, dy), pt(tx, ty)], fill=(235, 242, 252, 255), width=int((26 if simple else 14) * k))
    for tx, ty in toes:                    # charges at the toes
        r = 44 if simple else 30
        d.ellipse([(tx - r) * k, (ty - r) * k, (tx + r) * k, (ty + r) * k], fill=(255, 176, 32, 255),
                  outline=(255, 226, 150, 255), width=int(7 * k))
    r = 26                                 # collar point
    d.ellipse([(dx - r) * k, (dy - r) * k, (dx + r) * k, (dy + r) * k], fill=(255, 176, 32, 255))

    # ---- soft glossy highlight on the upper half of the tile
    hl = Image.new("L", (W, W), 0)
    ImageDraw.Draw(hl).ellipse([-0.3 * W, -0.85 * W, 1.3 * W, 0.42 * W], fill=38)
    hl = ImageChops.multiply(hl, mask)
    img.paste((255, 255, 255, 255), (0, 0), hl)
    return img.resize((N, N), Image.LANCZOS)


def main():
    out = ROOT / "launcher"
    out.mkdir(exist_ok=True)
    img = master()
    img.save(out / "ringblast.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    small = master(simple=True)
    frames = [(small if s <= 48 else img).resize((s, s), Image.LANCZOS) for s in sizes]
    img.save(out / "ringblast.ico", format="ICO", sizes=[(s, s) for s in sizes], append_images=frames)
    print("written", out / "ringblast.ico", "and", out / "ringblast.png")


if __name__ == "__main__":
    main()
