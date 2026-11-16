"""Synthetic muck-pile photo with known fragment sizes (guillotine-cut rectangles)."""
import numpy as np

SCALE = 6.0   # pixels per cm


def make_photo(seed=3, h=900, w=1200):
    import cv2
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 25, np.uint8)
    cells = []

    def split(x0, y0, x1, y1, depth=0):
        cw, ch = x1 - x0, y1 - y0
        if cw < 70 or ch < 70 or (depth > 1 and rng.random() < 0.25):
            cells.append((x0, y0, x1, y1))
            return
        if cw > ch:
            c = int(x0 + cw * rng.uniform(0.35, 0.65)); split(x0, y0, c, y1, depth + 1); split(c, y0, x1, y1, depth + 1)
        else:
            c = int(y0 + ch * rng.uniform(0.35, 0.65)); split(x0, y0, x1, c, depth + 1); split(x0, c, x1, y1, depth + 1)

    split(0, 0, w, h)
    sizes = []
    for x0, y0, x1, y1 in cells:
        g, gap = int(rng.uniform(100, 210)), 3
        j = lambda: int(rng.integers(0, 6))
        pts = np.array([[x0 + gap + j(), y0 + gap + j()], [x1 - gap - j(), y0 + gap + j()],
                        [x1 - gap - j(), y1 - gap - j()], [x0 + gap + j(), y1 - gap - j()]], np.int32)
        cv2.fillPoly(img, [pts], (g, int(g * .95), int(g * .9)))
        sizes.append(np.sqrt(4 * cv2.contourArea(pts) / np.pi) / SCALE)
    img = np.clip(img.astype(np.int16) + rng.normal(0, 5, img.shape), 0, 255).astype(np.uint8)
    return img, np.array(sizes)
