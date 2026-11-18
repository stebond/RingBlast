"""Ring (fan) geometry for every drift level of the stope.

Coordinates: x horizontal (0 = stope axis), y vertical up, y = H at the stope roof.
All holes of a ring radiate from the drift centre C = (cx, top - h/2), where the drift is
central (cx = 0) or at the side of the stope.  Toes lie on the boundary of the level's block:
  * sublevels: rectangle, two walls plus a flat line at the bottom (sublevel height minus the
    overlap B/2);
  * base drift: trapezoid, i.e. the hopper block between y = undercut height and the hopper
    floor, with sloping sides.

Toe placement (rules of the paper):
  (i)  the spacing at the toe never exceeds the nominal S = (S/B) * B and is reduced
       until the pattern closes *exactly* on the corner holes with equal spacing;
  (ii) the four corner holes are fixed.
Spacing is the perpendicular distance between adjacent holes measured at the toe
("2 s" in the legacy macro).  The legacy macro searched s by 0.1 % steps with a
0.1 m tolerance on the last toe; here the closure is solved exactly by bisection.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .models import Hole, LevelSpec, Ring, StopeGeometry, arch_points, arch_segment, arch_y

Point = tuple[float, float]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _march(c: Point, p0: Point, p1: Point, s: float, n: int) -> Optional[list[float]]:
    """Positions (distance from p0 along p0->p1) of n successive toes, or None if degenerate."""
    length = math.dist(p0, p1)
    d = ((p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length)
    toe = p0
    u = (p0[0] - c[0], p0[1] - c[1])
    nrm = math.hypot(*u)
    u = (u[0] / nrm, u[1] / nrm)
    out = []
    for _ in range(n):
        cr = _cross(u, d)
        if abs(cr) < 1e-9:
            return None
        t = s / abs(cr)                                  # point P1 at perpendicular distance s
        q = (toe[0] + t * d[0], toe[1] + t * d[1])
        rho2 = (q[0] - c[0]) ** 2 + (q[1] - c[1]) ** 2 - s * s
        if rho2 <= 0:
            return None
        delta = math.atan2(2 * s, math.sqrt(rho2))       # perpendicular offset 2s at foot of P1
        ang = math.atan2(u[1], u[0]) + (delta if cr > 0 else -delta)
        u = (math.cos(ang), math.sin(ang))
        # intersect new ray C + lam u with the line p0 + p d
        den = _cross(u, d)
        if abs(den) < 1e-12:
            return None
        w = (p0[0] - c[0], p0[1] - c[1])
        p = _cross(w, u) / den           # position along the line
        lam = _cross(w, d) / den         # distance along the ray
        if lam <= 0 or p <= (out[-1] if out else 0.0):
            return None
        out.append(p)
        toe = (p0[0] + p * d[0], p0[1] + p * d[1])
    return out


def solve_segment(c: Point, p0: Point, p1: Point, s_max_half: float,
                  n_max: int = 400) -> tuple[list[Point], float]:
    """Toe points strictly between p0 and p1 (+ p1 itself at the end) and the effective
    spacing 2s, using the smallest number of intervals with 2s <= 2*s_max_half."""
    length = math.dist(p0, p1)
    d = ((p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length)
    if abs(_cross((c[0] - p0[0], c[1] - p0[1]), d)) < 1e-9:
        # the drift axis lies on this edge (drift moved onto the wall of the stope): every ray to the
        # edge has the same direction, so the edge carries no toes of its own except the end corner p1
        return [p1], float("nan")

    def residual(s: float, n: int) -> float:
        pos = _march(c, p0, p1, s, n)
        return float("inf") if pos is None else pos[-1] - length

    for n in range(1, n_max + 1):
        if residual(s_max_half, n) < 0:
            continue                                     # even the largest s cannot reach p1
        lo, hi = 1e-6, s_max_half
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            (lo, hi) = (mid, hi) if residual(mid, n) < 0 else (lo, mid)
        s = 0.5 * (lo + hi)
        pos = _march(c, p0, p1, s, n)
        toes = [(p0[0] + q * d[0], p0[1] + q * d[1]) for q in pos[:-1]] + [p1]
        return toes, 2 * s
    raise RuntimeError("could not close the toe pattern; check geometry / spacing")


def _march_poly(c: Point, P: np.ndarray, L: np.ndarray, s: float, n: int) -> Optional[list[float]]:
    """Same marching as _march along a curved boundary given as a dense polyline P (m x 2) with
    cumulative arc length L.  Returns the arc-length positions of n successive toes, or None."""
    toe, idx, last = P[0], 0, 0.0
    u = (toe - c) / np.hypot(*(toe - c))
    cx, cy = c
    out = []
    for _ in range(n):
        sgn = 1.0 if (u[0] * (P[min(idx + 1, len(P) - 1)][1] - toe[1]) - u[1] * (P[min(idx + 1, len(P) - 1)][0] - toe[0])) > 0 else -1.0
        # point of the boundary at perpendicular distance s from the current ray
        f = sgn * (u[0] * (P[idx:, 1] - cy) - u[1] * (P[idx:, 0] - cx)) - s
        hit = np.nonzero(f >= 0)[0]
        if hit.size == 0:
            return None
        j = idx + int(hit[0])
        if j == idx:
            return None
        t = -f[j - 1 - idx] / (f[j - idx] - f[j - 1 - idx])
        q = P[j - 1] + t * (P[j] - P[j - 1])
        rho2 = (q[0] - cx) ** 2 + (q[1] - cy) ** 2 - s * s
        if rho2 <= 0:
            return None
        delta = math.atan2(2 * s, math.sqrt(rho2))
        ang = math.atan2(u[1], u[0]) + sgn * delta
        u = np.array([math.cos(ang), math.sin(ang)])
        # next toe: where the rotated ray meets the boundary
        h = sgn * (u[0] * (P[j - 1:, 1] - cy) - u[1] * (P[j - 1:, 0] - cx))
        hit = np.nonzero(h > 0)[0]
        if hit.size == 0:
            return None
        k = j - 1 + int(hit[0])
        if k == j - 1:
            return None
        t = -h[k - (j - 1) - 1] / (h[k - (j - 1)] - h[k - (j - 1) - 1])
        pt = P[k - 1] + t * (P[k] - P[k - 1])
        if (pt[0] - cx) * u[0] + (pt[1] - cy) * u[1] <= 0:
            return None
        pos = L[k - 1] + t * (L[k] - L[k - 1])
        if pos <= last:
            return None
        out.append(float(pos))
        toe, idx, last = pt, k - 1, float(pos)
    return out


def solve_curve(c: Point, curve: list[Point], s_max_half: float, n_max: int = 400) -> tuple[list[Point], float]:
    """Like solve_segment for a curved boundary (polyline `curve` from p0 to p1)."""
    P0 = np.asarray(curve, float)
    L0 = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P0, axis=0).T))])
    length = float(L0[-1])
    # straight extension beyond the end, so that an overshooting march gives a finite, positive residual
    tang = (P0[-1] - P0[-6]) / np.hypot(*(P0[-1] - P0[-6]))
    P = np.vstack([P0, P0[-1] + tang * length * 0.5])
    L = np.concatenate([L0, [length * 1.5]])
    c_ = np.asarray(c, float)

    def residual(s: float, n: int) -> float:
        pos = _march_poly(c_, P, L, s, n)
        return float("inf") if pos is None else pos[-1] - length

    def at(pos: float) -> Point:
        return (float(np.interp(pos, L, P[:, 0])), float(np.interp(pos, L, P[:, 1])))

    for n in range(1, n_max + 1):
        if residual(s_max_half, n) < 0:
            continue
        lo, hi = 1e-6, s_max_half
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            (lo, hi) = (mid, hi) if residual(mid, n) < 0 else (lo, mid)
        s = 0.5 * (lo + hi)
        pos = _march_poly(c_, P, L, s, n)
        return [at(q) for q in pos[:-1]] + [tuple(P0[-1])], 2 * s
    raise RuntimeError("could not close the toe pattern on the arched roof; check geometry / spacing")


def _exit_from_drift(c: Point, u: Point, half_w: float, half_h: float) -> Point:
    lam = min(half_w / abs(u[0]) if abs(u[0]) > 1e-12 else math.inf,
              half_h / abs(u[1]) if abs(u[1]) > 1e-12 else math.inf)
    return (c[0] + lam * u[0], c[1] + lam * u[1])


MIN_HOLE_LENGTH = 1.0     # m; shorter "holes" (toe on the drift boundary) are dropped


def level_specs(stope: StopeGeometry, burden: float) -> list[LevelSpec]:
    """Drift centre and blast block of every level, from the top sublevel to the base."""
    stope.validate()
    l2, big_h, h = stope.width / 2, stope.height, stope.drift_height
    hsub, u = stope.sublevel_height, stope.undercut_height
    specs: list[LevelSpec] = []
    count = 0
    for k in range(stope.n_sublevels):
        top = big_h - k * hsub
        vgap = stope.sublevel_gap_m if stope.sublevel_gap_m is not None else burden / 2
        y_bot = top - hsub + vgap                 # uncharged strip (vgap) between this block and the one below
        roof = stope.drift_roof_y(k)
        if roof - h < y_bot - 1e-9:
            raise ValueError(f"Sublevel {k + 1}: the drift reaches below the blast block (bottom of the block "
                             f"{top - y_bot:.1f} m under the top); raise the drift or lower the burden")
        rise = stope.roof_arch_rise_m if k == 0 else 0.0
        xs = stope.drift_xs(k)
        twin = len(xs) == 2
        for j, cx in enumerate(xs):
            hg = stope.twin_block_gap_m / 2           # uncharged strip along the centre line between the two blocks
            xl, xr = ((-l2, -hg) if j == 0 else (hg, l2)) if twin else (-l2, l2)
            yl, yr = (arch_y(l2, top, rise, xl), arch_y(l2, top, rise, xr)) if rise > 0 else (top, top)
            has_top = rise > 0 or (top - roof) >= MIN_HOLE_LENGTH
            side = ("left", "right")[j] if twin else ""
            count += 1
            specs.append(LevelSpec(
                count, f"Sublevel {k + 1}" + (f" {side}" if twin else ""), "sublevel",
                side or stope.position(k), (cx, roof - h / 2), roof,
                (xl, yl), (xl, y_bot), (xr, y_bot), (xr, yr), stope.drift_width, h,
                arch_rise=rise, top_toes=has_top, arch_half_width=l2 if rise > 0 else 0.0, arch_base_y=top,
                sublevel=k + 1, side=side))
    if stope.base_drift:
        # base drift: bottom centre of the stope (neck at the end of the hopper), fan upwards
        a, floor = stope.hopper_half_width, h
        specs.append(LevelSpec(count + 1, "Base", "base", "center",
                               (0.0, floor - h / 2), floor,
                               (-l2, u), (-a, floor), (a, floor), (l2, u),
                               stope.drift_width, h))
    return specs


def uncharged_regions(stope: StopeGeometry, burden: float) -> list[list[Point]]:
    """Rectangles of the stope that no block charges: the horizontal strips between consecutive sublevel
    blocks (and between the lowest sublevel and the base block) and, for two drifts per sublevel, the
    vertical strip between the left and the right block.  Used to draw them grey."""
    l2, big_h, hsub = stope.width / 2, stope.height, stope.sublevel_height
    vgap = stope.sublevel_gap_m if stope.sublevel_gap_m is not None else burden / 2
    hg = stope.twin_block_gap_m / 2
    out: list[list[Point]] = []
    for k in range(stope.n_sublevels):
        top = big_h - k * hsub
        y_bot = top - hsub + vgap
        if vgap > 1e-9:
            y_next = top - hsub
            out.append([(-l2, y_next), (l2, y_next), (l2, y_bot), (-l2, y_bot)])
        if stope.drifts_per_sublevel == 2 and hg > 1e-9:
            out.append([(-hg, y_bot), (hg, y_bot), (hg, top), (-hg, top)])
    return out


def gap_area_shares(stope: StopeGeometry, burden: float, specs: list[LevelSpec]) -> list[float]:
    """Plan area (m2) of the uncharged strips that belongs to each level, so that the volumes of the levels
    add up to the whole stope: every horizontal strip is shared equally by the block above and the block
    below it (a twin pair shares its half equally between left and right), the vertical strip between the
    left and right block is shared equally by the two."""
    l2, big_h, hsub = stope.width / 2, stope.height, stope.sublevel_height
    vgap = stope.sublevel_gap_m if stope.sublevel_gap_m is not None else burden / 2
    hg = stope.twin_block_gap_m
    share = [0.0] * len(specs)
    for k in range(stope.n_sublevels):
        top = big_h - k * hsub
        y_bot = top - hsub + vgap
        upper = [i for i, sp in enumerate(specs) if sp.kind == "sublevel" and sp.sublevel == k + 1]
        lower = [i for i, sp in enumerate(specs) if sp.kind == "sublevel" and sp.sublevel == k + 2] \
            or [i for i, sp in enumerate(specs) if sp.kind == "base"]
        strip = 2 * l2 * vgap
        for grp in (upper, lower):
            for i in grp:
                share[i] += strip / 2 / len(grp) if grp else 0.0
        if len(upper) == 2 and hg > 0:
            for i in upper:
                share[i] += hg * (top - y_bot) / 2
    return share


def _toe_hole_length(c: Point, toe: Point, hw: float, hh: float) -> float:
    v = (toe[0] - c[0], toe[1] - c[1])
    r = math.hypot(*v)
    if r == 0:
        return 0.0
    u = (v[0] / r, v[1] / r)
    return math.dist(_exit_from_drift(c, u, hw, hh), toe)


def build_ring(stope_or_spec, burden: float, spacing: float, stemming_m: float,
               level: int = 1) -> Ring:
    """Holes of one level, numbered from the upper-left corner anticlockwise along the toe
    contour (left edge down, bottom left->right, right edge up).

    Accepts a LevelSpec, or a StopeGeometry plus the 1-based `level` number.
    Each edge is marched from its lower end (rules i-ii, exact closure on the corners)."""
    spec = stope_or_spec if isinstance(stope_or_spec, LevelSpec) \
        else level_specs(stope_or_spec, burden)[level - 1]
    c, s_half = spec.centre, spacing / 2
    tl, bl, br, tr = spec.tl, spec.bl, spec.br, spec.tr

    seq: list[tuple[str, Point]]
    s_top, n_top = float("nan"), 0
    if spec.kind == "base":
        # base drift at the bottom centre: the fan covers the trapezoid between the two outer
        # rays, which run along the hopper walls to the upper corners tl and tr.  The toes are
        # on the top line only, closed exactly on tl and tr (the sloping sides are almost
        # radial from the drift, so they carry no toes of their own).
        top_toes, s_bot = solve_segment(c, tl, tr, s_half)       # top-left -> top-right
        seq = [("roof-corner", tl)] + [("top", p) for p in top_toes[:-1]] + [("roof-corner", tr)]
        s_left = s_right = float("nan")
        n_left = n_right = 0
        n_bot = len(top_toes)
    else:
        left_toes, s_left = solve_segment(c, bl, tl, s_half)     # lower end -> upper end
        right_toes, s_right = solve_segment(c, br, tr, s_half)
        bot_toes, s_bot = solve_segment(c, bl, br, s_half)       # bottom-left -> bottom-right
        seq = [("roof-corner", tl)] + [("wall", p) for p in left_toes[:-1][::-1]]
        seq += [("bottom-corner", bl)] + [("bottom", p) for p in bot_toes[:-1]]
        seq += [("bottom-corner", br)] + [("wall", p) for p in right_toes[:-1]]
        seq += [("roof-corner", tr)]
        n_left, n_right, n_bot = len(left_toes), len(right_toes), len(bot_toes)
        if spec.top_toes:                       # drift below the top of the block, or arched roof
            if spec.arch_rise > 0:
                top_toes, s_top = solve_curve(c, arch_segment(spec.arch_half_width, spec.arch_base_y, spec.arch_rise, tr[0], tl[0], 600), s_half)
            else:
                top_toes, s_top = solve_segment(c, tr, tl, s_half)   # top-right -> top-left
            seq += [("top", p) for p in top_toes[:-1]]
            n_top = len(top_toes)

    holes: list[Hole] = []
    x0, y0, x1, y1 = spec.drift_rect
    hw, hh = (x1 - x0) / 2, (y1 - y0) / 2
    # a toe that falls on the drift itself (e.g. a drift flush with the wall) gives no hole
    seq = [(k_, t_) for k_, t_ in seq if _toe_hole_length(c, t_, hw, hh) >= MIN_HOLE_LENGTH]
    for i, (kind, toe) in enumerate(seq, start=1):
        v = (toe[0] - c[0], toe[1] - c[1])
        r = math.hypot(*v)
        u = (v[0] / r, v[1] / r)
        collar = _exit_from_drift(c, u, hw, hh)
        stem = min(stemming_m, 0.95 * math.dist(collar, toe))
        cs = (collar[0] + stem * u[0], collar[1] + stem * u[1])
        holes.append(Hole(i, kind, collar, toe, cs, math.degrees(math.atan2(u[1], u[0])) % 360))
    return Ring(holes, c, bl[1], s_left, s_bot, n_left, n_bot, s_right, n_right, s_top, n_top)


def inside_region(spec: LevelSpec, x, y):
    """Boolean mask of points inside the (convex) block of a level; works on numpy arrays."""
    import numpy as np
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.ones(x.shape, bool)
    poly = spec.polygon
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        ok &= ((bx - ax) * (y - ay) - (by - ay) * (x - ax)) >= -1e-9  # anticlockwise polygon
    return ok


def mean_hole_length(stope: StopeGeometry, burden: float, n: int = 400) -> float:
    """Average distance from the drift centre to the toe contour of the reference (top)
    sublevel; used before the pattern exists by burden methods that depend on hole length."""
    spec = level_specs(stope, burden)[0]
    pts = []
    for k in range(n):
        t = k / (n - 1)
        edges = [(spec.bl, spec.tl), (spec.br, spec.tr), (spec.bl, spec.br)]
        if spec.top_toes and spec.arch_rise <= 0:
            edges.append((spec.tl, spec.tr))
        for p, q in edges:
            pts.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    if spec.top_toes and spec.arch_rise > 0:
        pts += arch_segment(spec.arch_half_width, spec.arch_base_y, spec.arch_rise, spec.tr[0], spec.tl[0], n)
    return sum(math.dist(spec.centre, p) for p in pts) / len(pts)
