"""Charging scheme: stemming + recursive decharging (rule III).

After the collar stemming, holes are thinned in passes.  In pass j (j = 1, 2, ...) every
(2j)-th hole starting from hole j+1 (1-based) is decharged from the collar until its distance
to the charged parts of its neighbours at +-j is at least S/2.  The four corner holes keep
their full charge when `protect_corners` is set (rule II of the paper).

The legacy macro considered, for even numbers of holes, only the previous neighbour and did
not exclude the two bottom corner holes from decharging; both are corrected here.
"""
from __future__ import annotations

import math

from .models import Hole


def point_segment_distance(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    if den == 0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / den))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _thin(holes: list[Hole], i: int, neigh: list[int], half: float, step: float) -> None:
    """Decharge hole i from the collar until its charge is at least `half` from the charged parts of `neigh`."""
    h = holes[i]
    ax, ay = h.charge_start
    tx, ty = h.toe
    length = math.hypot(tx - ax, ty - ay)
    if length == 0:
        return
    ux, uy = (tx - ax) / length, (ty - ay) / length
    nb = [holes[k] for k in neigh]
    moved = 0.0
    while moved < length:
        p = (ax + moved * ux, ay + moved * uy)
        if min(point_segment_distance(p, k.charge_start, k.toe) for k in nb) >= half:
            break
        moved += step
    moved = min(moved, length)
    h.charge_start = (ax + moved * ux, ay + moved * uy)


def decharge(holes: list[Hole], spacing: float, levels: int = 2,
             protect_corners: bool = True, step: float = 0.02, closed: bool = False) -> None:
    """Move `charge_start` of selected holes towards the toe (in place).

    `closed`: the holes form a closed contour (drift below the top of its block: the last hole is
    the neighbour of the first), so neighbours wrap around and the last hole can be thinned too.

    A final check handles what the alternating passes cannot: two neighbouring holes whose charged
    parts are closer than S/2 (typically next to a protected corner hole, or the last and the first
    hole of the sequence, or a hole thinned only with respect to its +-2 neighbours).  The fuller
    hole of the pair that is not a protected corner is decharged until it is at least S/2 from the
    charged parts of its two neighbours; this is repeated until no pair is too close."""
    n = len(holes)
    half = spacing / 2.0
    protected = lambda i: protect_corners and holes[i].kind in ("roof-corner", "bottom-corner")
    for j in range(1, levels + 1):
        for i in range(j, n if closed else n - 1, 2 * j):    # 0-based index of the hole to thin
            if protected(i):
                continue
            idx = [(i - j) % n, (i + j) % n] if closed else [k for k in (i - j, i + j) if 0 <= k < n]
            _thin(holes, i, idx, half, step)
    # final check of every pair of neighbouring holes (see the docstring)
    pairs = [(i, (i + 1) % n) for i in range(n if closed else n - 1)]
    for _ in range(3 * n):
        worst = None
        for i, k in pairs:
            a, b = holes[i], holes[k]
            if a.charged_length < 1e-9 or b.charged_length < 1e-9:
                continue
            gap = min(point_segment_distance(a.charge_start, b.charge_start, b.toe),
                      point_segment_distance(b.charge_start, a.charge_start, a.toe))
            free = [x for x in (i, k) if not protected(x)]
            if gap < half - 1e-6 and free and (worst is None or gap < worst[0]):
                worst = (gap, max(free, key=lambda x: holes[x].charged_length))   # decharge the fuller hole
        if worst is None:
            break
        t = worst[1]
        idx = [(t - 1) % n, (t + 1) % n] if closed else [x for x in (t - 1, t + 1) if 0 <= x < n]
        before = holes[t].charge_start
        _thin(holes, t, idx, half, step)
        if holes[t].charge_start == before:
            break
