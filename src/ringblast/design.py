"""Orchestrates a complete ring design: burden -> pattern -> charging -> zones -> totals."""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Iterable

from .burden import BurdenInputs, compute_burden
from .charging import decharge
from .fragmentation import analyse_zones, charge_mass_kg, weighted_mean_size
from .geometry import build_ring, level_specs, mean_hole_length
from .models import (DesignParams, DesignResult, Explosive, LevelResult, Rock, StopeGeometry)

DEFAULT_ROCK_FACTOR = 10.0


def resolve_burden(rock: Rock, expl: Explosive, stope: StopeGeometry, p: DesignParams) -> float:
    if p.burden_method == "manual":
        if not p.burden_manual_m or p.burden_manual_m <= 0:
            raise ValueError("manual burden requires burden_manual_m > 0")
        return p.burden_manual_m
    # hole length depends on B only weakly (through the overlap B/2): one pass is enough
    h = mean_hole_length(stope, 3.0)
    return compute_burden(p.burden_method, BurdenInputs(rock, expl, p, h))


def run_level(spec, burden: float, spacing: float, rock: Rock, expl: Explosive,
              p: DesignParams, a_factor: float, with_fragmentation: bool = True) -> LevelResult:
    """Pattern, charging, volume and fragmentation of one level."""
    from .fragmentation import _grid
    try:
        ring = build_ring(spec, burden, spacing, p.stemming_m)
    except RuntimeError as exc:
        raise RuntimeError(f"{spec.name}: {exc}") from exc
    decharge(ring.holes, spacing, p.decharge_levels, p.protect_corners,
             closed=bool(getattr(spec, "top_toes", False)) and getattr(spec, "kind", "") == "sublevel")
    drilled = sum(h.length for h in ring.holes)
    charged = sum(h.charged_length for h in ring.holes)
    mass = sum(charge_mass_kg(h, expl, p) for h in ring.holes)
    gx, _, cell = _grid(spec)
    volume = len(gx) * cell * burden
    zones = analyse_zones(ring.holes, spec, burden, spacing, rock, expl, p, a_factor) \
        if with_fragmentation else []
    return LevelResult(spec, ring, zones, len(ring.holes), drilled, charged, mass,
                       volume, mass / volume if volume else 0.0,
                       weighted_mean_size(zones) if zones else float("nan"))


def run_design(rock: Rock, expl: Explosive, stope: StopeGeometry, p: DesignParams,
               with_fragmentation: bool = True) -> DesignResult:
    """Design every drift level (n sublevels + base) with one burden and spacing."""
    warnings: list[str] = []
    burden = resolve_burden(rock, expl, stope, p)
    spacing = burden * p.sb_ratio
    if burden < 0.5 * p.hole_diameter_mm / 100 or burden > 60 * p.hole_diameter_mm / 1000:
        warnings.append(f"burden {burden:.2f} m is outside 15-60 hole diameters: check inputs")
    a = p.rock_factor_A or rock.rock_factor_A
    if a is None:
        a = DEFAULT_ROCK_FACTOR
        warnings.append(f"rock factor A not defined for '{rock.name}': default {a:g} used")
    levels = [run_level(spec, burden, spacing, rock, expl, p, a, with_fragmentation)
              for spec in level_specs(stope, burden)]
    return DesignResult(burden, spacing, levels, warnings)


def sensitivity(rock: Rock, expl: Explosive, stope: StopeGeometry, p: DesignParams,
                burdens: Iterable[float]) -> list[dict]:
    """Burden scan: number of holes, drilled length, charge and powder factor per ring."""
    rows = []
    for b in burdens:
        q = copy.copy(p)
        q.burden_method, q.burden_manual_m = "manual", float(b)
        try:
            r = run_design(rock, expl, stope, q, with_fragmentation=False)
        except (RuntimeError, ValueError) as exc:
            rows.append(dict(burden_m=b, error=str(exc)))
            continue
        rows.append(dict(burden_m=b, spacing_m=r.spacing_m, n_holes=r.n_holes,
                         drilled_length_m=r.drilled_length_m, charged_length_m=r.charged_length_m,
                         charge_kg=r.charge_kg, powder_factor=r.powder_factor))
    return rows
