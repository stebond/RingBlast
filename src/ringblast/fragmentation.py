"""Kuz-Ram fragmentation (Kuznetsov mean size, Rosin-Rammler distribution, Cunningham
uniformity index) applied to radial fragmentation zones of a ring.

Equations (Cunningham 1983, 1987, 2005):
    X50 = A * K^-0.8 * Q^(1/6) * (115 / RWS)^(19/30)                [cm]
    n   = (2.2 - 14 B/D) * sqrt((1 + S/B)/2) * (1 - W/B)
          * (|BCL - CCL| / L + 0.1)^0.1 * (L / H)                   B (m), D (mm)
    R(x) = exp(-(x / Xc)^n),  Xc = X50 / (ln 2)^(1/n),  passing P = 1 - R
K powder factor (kg/m3), Q mass of explosive per hole (kg), RWS relative to ANFO = 100,
W standard deviation of drilling accuracy (m), BCL / CCL bottom / column charge length,
L charge length, H hole length (bench height in the original formulation).
Kuznetsov's size is treated as the median X50, as in Cunningham's formulation.

Booster (bottom charge): when `DesignParams.booster` is set, the last `booster_length_m` of
every charged hole (at the toe) holds the booster and the rest the column explosive.  BCL and
CCL are then the real lengths in the uniformity index, L = BCL + CCL is the charge length and
H the hole length; W = 0 is a sufficient assumption for ring blasting (set the deviation
parameters to 0).  The RWS used in Kuznetsov's equation is the weighted mean of booster and
column RWS over the length (space) each explosive occupies in the zone; the charge mass is
the sum of the two masses.  Without booster BCL = CCL is assumed (term 0.1^0.1).
"""
from __future__ import annotations

import math

import numpy as np

from .geometry import inside_region
from .models import DesignParams, Explosive, Hole, LevelSpec, Rock, ZoneResult


def kuznetsov_mean_size_cm(A: float, K: float, Q: float, rws: float) -> float:
    return A * K ** -0.8 * Q ** (1 / 6) * (115.0 / rws) ** (19 / 30)


def uniformity_index(B: float, S: float, d_mm: float, W: float, L_over_H: float = 1.0,
                     bcl_ccl_term: float = 0.1 ** 0.1) -> float:
    """Cunningham uniformity index.  `bcl_ccl_term` = (|BCL-CCL|/L + 0.1)^0.1; for a single
    explosive column (BCL = CCL) it equals 0.1^0.1 = 0.794."""
    n = (2.2 - 14.0 * B / d_mm) * math.sqrt((1.0 + S / B) / 2.0) * (1.0 - W / B)
    return n * bcl_ccl_term * L_over_H


def characteristic_size_cm(x50: float, n: float) -> float:
    return x50 / math.log(2.0) ** (1.0 / n)


def passing_curve(sizes_cm, xc: float, n: float):
    sizes = np.asarray(sizes_cm, dtype=float)
    return 1.0 - np.exp(-((sizes / xc) ** n))


# --------------------------------------------------------------------------- zoning
def _grid(spec: LevelSpec, h: float = 0.05):
    """Cell centres of the level's block (drift excluded) and the cell area."""
    poly = spec.polygon
    x0, x1 = min(p[0] for p in poly), max(p[0] for p in poly)
    y0, y1 = min(p[1] for p in poly), max(p[1] for p in poly)
    gx, gy = np.meshgrid(np.arange(x0 + h / 2, x1, h), np.arange(y0 + h / 2, y1, h))
    keep = inside_region(spec, gx, gy)
    dx0, dy0, dx1, dy1 = spec.drift_rect
    keep &= ~((gx >= dx0) & (gx <= dx1) & (gy >= dy0) & (gy <= dy1))
    return gx[keep], gy[keep], h * h


def section_kg_m(d_mm: float, expl: Explosive) -> float:
    """Charge per metre of hole (kg/m) = loading density x hole section."""
    return math.pi * (d_mm / 1000.0) ** 2 / 4.0 * expl.density * 1000.0


def split_charge(hole: Hole, p: DesignParams) -> tuple[float, float]:
    """(BCL, CCL): booster length at the toe and column length of one charged hole (m)."""
    total = hole.charged_length
    if p.booster is None or p.booster_length_m <= 0 or total <= 0:
        return 0.0, total
    bcl = min(p.booster_length_m, total)
    return bcl, total - bcl


def charge_mass_kg(hole: Hole, expl: Explosive, p: DesignParams) -> float:
    """Mass of explosive in one hole (kg), booster and column."""
    bcl, ccl = split_charge(hole, p)
    mass = ccl * section_kg_m(p.hole_diameter_mm, expl)
    if bcl:
        mass += bcl * section_kg_m(p.hole_diameter_mm, p.booster)
    return mass


def _booster_start(hole: Hole, bcl: float):
    """Point where the booster begins (towards the toe)."""
    ax, ay = hole.charge_start
    tx, ty = hole.toe
    length = math.hypot(tx - ax, ty - ay)
    if length == 0:
        return hole.toe
    t = (length - bcl) / length
    return ax + t * (tx - ax), ay + t * (ty - ay)


def _charged_length_in_zone(hole: Hole, centre, r_in: float, r_out: float,
                            step: float = 0.01, a=None, b=None) -> float:
    """Length of the segment a->b (default: the charged part of the hole) inside the zone."""
    ax, ay = a if a is not None else hole.charge_start
    tx, ty = b if b is not None else hole.toe
    length = math.hypot(tx - ax, ty - ay)
    if length == 0:
        return 0.0
    k = max(2, int(length / step))
    t = (np.arange(k) + 0.5) / k
    px, py = ax + t * (tx - ax), ay + t * (ty - ay)
    r = np.hypot(px - centre[0], py - centre[1])
    return float(np.count_nonzero((r >= r_in) & (r < r_out)) * length / k)


def analyse_zones(holes: list[Hole], spec: LevelSpec, burden: float,
                  spacing: float, rock: Rock, expl: Explosive, p: DesignParams,
                  rock_factor: float) -> list[ZoneResult]:
    centre = spec.centre if p.zone_centre == "fan" else (spec.centre[0], spec.top_y)
    gx, gy, cell = _grid(spec)
    gr = np.hypot(gx - centre[0], gy - centre[1])
    r_max = float(gr.max())
    # equal zones of thickness R; a last zone thinner than R/2 is merged into the previous one
    n_zones = max(1, round(r_max / p.zone_length_m))
    edges = [i * p.zone_length_m for i in range(n_zones)] + [max(r_max, n_zones * p.zone_length_m) + 1e-6]
    sec_c = section_kg_m(p.hole_diameter_mm, expl)
    sec_b = section_kg_m(p.hole_diameter_mm, p.booster) if p.booster is not None else sec_c
    rws_b = p.booster.rws_anfo if p.booster is not None else expl.rws_anfo
    split = [split_charge(h, p) for h in holes]
    zones: list[ZoneResult] = []
    for i in range(1, n_zones + 1):
        r_in, r_out = edges[i - 1], edges[i]
        area = float(np.count_nonzero((gr >= r_in) & (gr < r_out)) * cell)
        if area <= 0:
            continue
        len_b, len_c = [], []
        for h, (bcl, _ccl) in zip(holes, split):
            if bcl > 0:
                bs = _booster_start(h, bcl)
                len_b.append(_charged_length_in_zone(h, centre, r_in, r_out, a=bs, b=h.toe))
                len_c.append(_charged_length_in_zone(h, centre, r_in, r_out, a=h.charge_start, b=bs))
            else:
                len_b.append(0.0)
                len_c.append(_charged_length_in_zone(h, centre, r_in, r_out))
        lens = [b + c for b, c in zip(len_b, len_c)]
        charged = sum(lens)
        active = sum(1 for v in lens if v > 0.05)
        charge = sum(len_c) * sec_c + sum(len_b) * sec_b
        # RWS of the mixture: mean weighted on the length (space) occupied by each explosive
        rws_eff = (sum(len_c) * expl.rws_anfo + sum(len_b) * rws_b) / charged if charged > 0 else expl.rws_anfo
        volume = area * burden
        pf = charge / volume if volume > 0 else 0.0
        q_hole = charge / active if active else 0.0
        # local spacing from the geometry: arc length of the mid circle inside the region
        r_mid = 0.5 * (r_in + min(r_out, r_max))
        th = np.linspace(0.0, 2 * math.pi, 3601, endpoint=False)
        ax_, ay_ = centre[0] + r_mid * np.cos(th), centre[1] + r_mid * np.sin(th)
        inside = inside_region(spec, ax_, ay_)
        arc = float(np.count_nonzero(inside) * r_mid * (2 * math.pi / 3600))
        s_loc = arc / active if active else spacing
        s_loc = max(0.2 * spacing, min(s_loc, spacing))
        w = p.deviation_base_m + p.deviation_per_m * r_out
        # Cunningham's L/H, per hole (charged length / hole length), averaged over active holes
        ratios = [h.charged_length / h.length for h, v in zip(holes, lens) if v > 0.05]
        l_over_h = sum(ratios) / len(ratios) if ratios else 1.0
        if p.booster is not None and p.booster_length_m > 0:
            # Cunningham: (|BCL - CCL| / L + 0.1)^0.1 per hole (L = BCL + CCL), mean of active holes
            terms = [(abs(b - c) / (b + c) + 0.1) ** 0.1 for (b, c), v in zip(split, lens) if v > 0.05 and b + c > 0]
            bc_term = sum(terms) / len(terms) if terms else 0.1 ** 0.1
        else:
            bc_term = 0.1 ** 0.1
        if pf > 0 and q_hole > 0:
            x50 = kuznetsov_mean_size_cm(rock_factor, pf, q_hole, rws_eff)
            n = uniformity_index(burden, s_loc, p.hole_diameter_mm, w, l_over_h, bc_term)
            n = max(n, 0.3)
            xc = characteristic_size_cm(x50, n)
        else:
            x50 = n = xc = float("nan")
        zones.append(ZoneResult(i, r_in, r_out, area, volume, charged, charge, pf, active,
                                q_hole, s_loc, x50, n, xc, rws_eff))
    return zones


def weighted_mean_size(zones: list[ZoneResult]) -> float:
    num = sum(z.mean_size_cm * z.area_m2 for z in zones if not math.isnan(z.mean_size_cm))
    den = sum(z.area_m2 for z in zones if not math.isnan(z.mean_size_cm))
    return num / den if den else float("nan")


def cunningham_rock_factor(density_t_m3: float, ucs_mpa: float, youngs_gpa: float,
                           mass: str = "massive", joint_spacing: str = "", joint_angle: str = "") -> float:
    """A = 0.06 (RMD + RDI + HF)  (Cunningham 1987 / Lilly 1986).

    RDI = 25 rho - 50;  HF = E/3 (E < 50 GPa) or UCS/5 (E >= 50 GPa).
    RMD: 10 powdery/friable, 50 massive, or JF = JPS + JPA for jointed rock with
    JPS in {"close": 10, "intermediate": 20, "wide": 50} and
    JPA in {"out of face": 20, "strike normal": 30, "into face": 40}.
    """
    rdi = 25.0 * density_t_m3 - 50.0
    hf = youngs_gpa / 3.0 if youngs_gpa < 50.0 else ucs_mpa / 5.0
    if mass == "powdery":
        rmd = 10.0
    elif mass == "massive":
        rmd = 50.0
    elif mass == "jointed":
        jps = {"close": 10.0, "intermediate": 20.0, "wide": 50.0}[joint_spacing]
        jpa = {"out of face": 20.0, "strike normal": 30.0, "into face": 40.0}[joint_angle]
        rmd = jps + jpa
    else:
        raise ValueError("mass must be powdery, massive or jointed")
    return 0.06 * (rmd + rdi + hf)
