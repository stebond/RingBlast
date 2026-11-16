"""Fragment size analysis of muck-pile photographs (2-D image analysis).

Method (the usual photo-analysis approach, cf. Split-Desktop / WipFrag):
  1. the photo is converted to grey scale, equalised and smoothed;
  2. fragment boundaries (shadows and dark gaps between blocks) are found with an adaptive
     threshold; the remaining bright areas are separated with a distance-transform watershed;
  3. each region gives an equivalent diameter  d = sqrt(4 A / pi)  using the image scale
     (pixels per cm, from a reference object of known length);
  4. the cumulative distribution is volume-weighted (V ~ d^3) and fitted with a Rosin-Rammler
     curve  P(x) = 1 - exp(-(x/xc)^n)  over the 10-90 % passing range.

Limitations (report them with the results): only the visible surface is measured, fragments
smaller than `min_size_cm` are not resolved (`unresolved_area_fraction`), overlapping blocks and
shadows bias the sizes, and the result must be checked against sieving or other photos
before it is used quantitatively.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

PERCENTILES = (10, 20, 50, 80, 90)


@dataclass
class FragmentResult:
    sizes_cm: np.ndarray                      # equivalent diameters of the detected fragments
    px_per_cm: float                          # scale used for the analysed (possibly resized) image
    image_area_cm2: float
    unresolved_area_fraction: float           # image area not covered by detected fragments
    percentiles_cm: dict = field(default_factory=dict)   # {10: D10, 50: D50, ...}
    dmax_cm: float = float("nan")
    rr_n: float = float("nan")                # Rosin-Rammler uniformity (fitted)
    rr_xc_cm: float = float("nan")            # Rosin-Rammler characteristic size (fitted)
    overlay: Optional[np.ndarray] = None      # BGR image with the detected fragments drawn

    @property
    def n_fragments(self) -> int:
        return int(len(self.sizes_cm))

    def summary(self) -> dict:
        d = {"n_fragments": self.n_fragments, "dmax_cm": self.dmax_cm, "rr_n": self.rr_n,
             "rr_xc_cm": self.rr_xc_cm, "unresolved_area_fraction": self.unresolved_area_fraction}
        d.update({f"d{p}_cm": self.percentiles_cm.get(p, float("nan")) for p in PERCENTILES})
        return d


def volume_weighted_curve(sizes_cm) -> tuple[np.ndarray, np.ndarray]:
    """Sorted sizes and cumulative passing fraction (volume ~ d^3)."""
    d = np.sort(np.asarray(sizes_cm, float))
    if d.size == 0:
        return d, d
    v = d ** 3
    return d, np.cumsum(v) / v.sum()


def percentile_size(sizes_cm, pct: float) -> float:
    d, p = volume_weighted_curve(sizes_cm)
    if d.size == 0:
        return float("nan")
    return float(np.interp(pct / 100.0, p, d))


def fit_rosin_rammler(sizes_cm, lo: float = 0.10, hi: float = 0.90) -> tuple[float, float]:
    """(n, xc) from a least-squares fit of ln(-ln(1-P)) = n ln x - n ln xc on lo<P<hi."""
    d, p = volume_weighted_curve(sizes_cm)
    ok = (p > lo) & (p < hi) & (d > 0)
    if ok.sum() < 3:
        return float("nan"), float("nan")
    xs, ys = np.log(d[ok]), np.log(-np.log(1.0 - p[ok]))
    n, b = np.polyfit(xs, ys, 1)
    return float(n), float(math.exp(-b / n))


def describe(sizes_cm) -> dict:
    sizes = np.asarray(sizes_cm, float)
    n, xc = fit_rosin_rammler(sizes)
    return {"percentiles_cm": {p: percentile_size(sizes, p) for p in PERCENTILES},
            "dmax_cm": float(sizes.max()) if sizes.size else float("nan"), "rr_n": n, "rr_xc_cm": xc}


def combine(results: list[FragmentResult]) -> dict:
    """Pooled distribution of several photos (every fragment counts with its volume)."""
    sizes = np.concatenate([r.sizes_cm for r in results]) if results else np.array([])
    out = describe(sizes)
    out["n_fragments"] = int(sizes.size)
    out["sizes_cm"] = sizes
    return out


SEG_DEFAULTS = {
    "contrast": 2.0,          # CLAHE clip limit (local contrast); 0 = off
    "gamma": 1.0,             # <1 brightens the shadows, >1 darkens the highlights
    "smoothing": 1.0,         # blur strength relative to the smallest fragment; 0 = off
    "threshold_mode": "adaptive",   # adaptive | otsu | fixed
    "threshold_shift": 0.0,   # adaptive: added to C (+ = fewer boundary pixels); otsu: added to the level
    "fixed_level": 110,       # grey level for threshold_mode "fixed" (0..255)
    "window": 3.0,            # adaptive window, in smallest-fragment diameters
    "invert": False,          # True if the fragments are DARKER than the gaps between them
    "erode_iter": 0,          # shrink the fragments: separates touching blocks
    "open_iter": 1,           # remove small bright specks
    "close_iter": 0,          # fill small dark holes inside fragments
    "max_fragment_fraction": 0.5,   # reject regions larger than this fraction of the image
}


def _prepare(img_bgr, px_per_cm, min_size_cm, sensitivity, max_dim, params):
    """Working-resolution image, pre-processed grey image and boundary-free foreground mask."""
    import cv2
    p = {**SEG_DEFAULTS, **(params or {})}
    if px_per_cm <= 0:
        raise ValueError("the image scale (pixels per cm) must be positive")
    h0, w0 = img_bgr.shape[:2]
    # work at a resolution where the smallest wanted fragment is ~10 px across (speed)
    k = min(1.0, max_dim / max(h0, w0), 10.0 / max(min_size_cm * px_per_cm, 1e-9))
    k = max(k, 0.1)
    img = cv2.resize(img_bgr, (round(w0 * k), round(h0 * k)), interpolation=cv2.INTER_AREA) if k < 1 else img_bgr.copy()
    scale = px_per_cm * k
    min_px = max(3.0, min_size_cm * scale)                    # smallest fragment diameter in pixels

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if abs(p["gamma"] - 1.0) > 1e-6:
        lut = (255.0 * (np.arange(256) / 255.0) ** p["gamma"]).clip(0, 255).astype(np.uint8)
        gray = cv2.LUT(gray, lut)
    if p["contrast"] > 0:
        gray = cv2.createCLAHE(clipLimit=float(p["contrast"]), tileGridSize=(8, 8)).apply(gray)
    if p["smoothing"] > 0:
        gray = cv2.GaussianBlur(gray, (0, 0), max(0.5, min_px / 12 * p["smoothing"]))

    ttype = cv2.THRESH_BINARY_INV if p["invert"] else cv2.THRESH_BINARY
    mode = p["threshold_mode"]
    if mode == "otsu":
        level, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        fg = cv2.threshold(gray, float(np.clip(level + p["threshold_shift"], 0, 255)), 255, ttype)[1]
    elif mode == "fixed":
        fg = cv2.threshold(gray, float(p["fixed_level"]), 255, ttype)[1]
    else:
        block = int(max(15, min_px * p["window"])) | 1        # local window ~ a few smallest fragments
        c = 2 + 10 * (1 - sensitivity) + p["threshold_shift"]  # lower C = more boundary pixels
        fg = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, ttype, block, c)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    if p["erode_iter"] > 0:
        fg = cv2.erode(fg, ker, iterations=int(p["erode_iter"]))
    if p["open_iter"] > 0:
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, ker, iterations=int(p["open_iter"]))
    if p["close_iter"] > 0:
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, ker, iterations=int(p["close_iter"]))
    return img, gray, fg, scale, k, min_px, p


def stage_image(img_bgr, px_per_cm, min_size_cm=3.0, sensitivity=0.5, params=None, stage="mask",
                max_dim: int = 1600) -> np.ndarray:
    """Intermediate result for tuning the parameters: stage 'pre' (grey image after gamma, contrast
    and smoothing) or 'mask' (photo with the rejected / boundary pixels painted red)."""
    import cv2
    img, gray, fg, scale, k, min_px, p = _prepare(img_bgr, px_per_cm, min_size_cm, sensitivity, max_dim, params)
    if stage == "pre":
        out = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    else:
        out = img.copy()
        red = np.zeros_like(out); red[:] = (0, 0, 255)
        sel = fg == 0
        out[sel] = (0.45 * out[sel] + 0.55 * red[sel]).astype(np.uint8)
    h0, w0 = img_bgr.shape[:2]
    ks = min(1.0, max_dim / max(h0, w0))
    return cv2.resize(out, (round(w0 * ks), round(h0 * ks)), interpolation=cv2.INTER_AREA) if ks != k else out


def analyse_image(img_bgr: np.ndarray, px_per_cm: float, min_size_cm: float = 3.0,
                  sensitivity: float = 0.5, max_dim: int = 1600, params: dict | None = None) -> FragmentResult:
    """Detect the fragments of a muck-pile photograph and measure them.

    px_per_cm   image scale (from a reference object); min_size_cm  smallest fragment kept;
    sensitivity 0..1, higher splits more (more, smaller fragments);
    params      pre-processing / threshold options, see SEG_DEFAULTS (missing keys use the defaults).
    """
    import cv2
    h0, w0 = img_bgr.shape[:2]
    img, gray, fg, scale, k, min_px, p = _prepare(img_bgr, px_per_cm, min_size_cm, sensitivity, max_dim, params)
    h, w = img.shape[:2]

    dist = cv2.distanceTransform(fg, cv2.DIST_L2, 5)
    r_min = max(1.5, min_px / 2 * (0.35 + 0.4 * (1 - sensitivity)))
    # scale-adaptive peak search: a peak must be the maximum of the distance map within a
    # radius proportional to its own value, so large blocks are not split into several peaks
    frac = 0.6 + 0.9 * (1 - sensitivity)
    peaks = np.zeros(dist.shape, bool)
    lo = r_min
    while lo < dist.max():
        hi = lo * 1.6
        rad = max(2, int(frac * hi))
        kern = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * rad + 1, 2 * rad + 1))
        peaks |= (dist >= lo) & (dist < hi) & (dist == cv2.dilate(dist, kern))
        lo = hi
    n_mark, markers = cv2.connectedComponents(peaks.astype(np.uint8))
    markers = cv2.watershed(img, markers.astype(np.int32))   # labels 1..n_mark-1; -1 = ridge lines

    sizes, keep = [], np.zeros((h, w), np.uint8)
    min_area = math.pi * (min_px / 2) ** 2
    covered = 0.0
    for lab in range(1, n_mark):
        mask = (markers == lab) & (fg > 0)
        area = int(mask.sum())
        if area < min_area or area > p["max_fragment_fraction"] * h * w:
            continue
        sizes.append(math.sqrt(4 * area / math.pi) / scale)
        covered += area
        keep[mask] = lab % 250 + 1
    # overlay at display resolution (up to max_dim), contours rescaled from the working resolution
    ks = min(1.0, max_dim / max(h0, w0))
    overlay = cv2.resize(img_bgr, (round(w0 * ks), round(h0 * ks)), interpolation=cv2.INTER_AREA) if ks < 1 else img_bgr.copy()
    f = ks / k
    for lab in np.unique(keep)[1:]:
        cnts, _ = cv2.findContours((keep == lab).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnts = [np.round(c * f).astype(np.int32) for c in cnts]
        cv2.drawContours(overlay, cnts, -1, (0, 255, 255), 1)
    sizes_arr = np.asarray(sizes, float)
    res = FragmentResult(sizes_arr, scale, h * w / scale ** 2, 1.0 - covered / (h * w), overlay=overlay)
    if sizes_arr.size:
        d = describe(sizes_arr)
        res.percentiles_cm, res.dmax_cm, res.rr_n, res.rr_xc_cm = (d["percentiles_cm"], d["dmax_cm"],
                                                                    d["rr_n"], d["rr_xc_cm"])
    return res


def from_sizes(sizes_cm, px_per_cm: float = 0.0, unresolved: float = float("nan")) -> FragmentResult:
    """Rebuild a result (without overlay) from stored fragment sizes, e.g. when a project is opened."""
    sizes = np.asarray(sizes_cm, float)
    res = FragmentResult(sizes, px_per_cm, 0.0, unresolved)
    if sizes.size:
        d = describe(sizes)
        res.percentiles_cm, res.dmax_cm, res.rr_n, res.rr_xc_cm = (d["percentiles_cm"], d["dmax_cm"],
                                                                    d["rr_n"], d["rr_xc_cm"])
    return res


def load_image(path):
    """Read an image file (any common format, with EXIF orientation applied) as a BGR array."""
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        return np.asarray(im)[:, :, ::-1].copy()


def exif_date(path) -> Optional[str]:
    """Shooting date (YYYY-MM-DD) from the EXIF data, if the photo has it."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = im.getexif()
            raw = ex.get_ifd(0x8769).get(0x9003) or ex.get(0x0132)    # DateTimeOriginal / DateTime
        if raw:
            return str(raw)[:10].replace(":", "-")
    except Exception:
        pass
    return None
