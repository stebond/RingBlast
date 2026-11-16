"""Burden calculation methods.

Only methods whose formula is documented and unit-consistent are enabled.  The
legacy Excel macro contains 19 entries; the ones below are the subset that has
been re-derived and tested.  The others stay listed in LEGACY_NOT_PORTED with
the reason, so that the paper can state clearly what was dropped and why.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

from .models import DesignParams, Explosive, MissingInput, Rock

FT = 0.3048
IN_MM = 25.4


@dataclass
class BurdenInputs:
    rock: Rock
    expl: Explosive
    params: DesignParams
    mean_hole_length_m: float = 10.0   # average length of the ring holes (m)

    @property
    def d_mm(self) -> float:
        return self.params.hole_diameter_mm

    @property
    def d_m(self) -> float:
        return self.params.hole_diameter_mm / 1000.0

    @property
    def mc(self) -> float:
        """Charge per metre of hole (kg/m) = loading density * hole section."""
        return self.expl.density * math.pi * self.d_m ** 2 / 4.0 * 1000.0

    def need(self, value, what: str):
        if value is None:
            raise MissingInput(f"{what} is required for this method")
        return value


def langefors_kihlstrom(x: BurdenInputs, c_correction: str = "auto") -> float:
    """B = d/33 * sqrt(P s / (c_bar f S/B)); d (mm), P (kg/dm3), s (ANFO = 1).

    c_bar = c + 0.05 for B >= 1.4 m, c + 0.07/B for B < 1.4 m (c_correction="auto");
    c_correction="fixed" always uses c + 0.05 (legacy macro behaviour).
    """
    p = x.params
    c = p.c_langefors if p.c_langefors is not None else x.rock.c_langefors
    base = x.expl.density * x.expl.s_anfo / (p.fixation * p.sb_ratio)

    def b_of(c_bar: float) -> float:
        return x.d_mm / 33.0 * math.sqrt(base / c_bar)

    b = b_of(c + 0.05)
    if c_correction == "auto" and b < 1.4:
        for _ in range(50):                       # fixed-point iteration, B-dependent c_bar
            b_new = b_of(c + 0.07 / b)
            if abs(b_new - b) < 1e-9:
                break
            b = b_new
    return b


def hustrulid_powder_factor(x: BurdenInputs) -> float:
    """B*S = Mc * Lc / (H * K), S = (S/B) B  ->  B = sqrt(Mc * Lc/H / (K * S/B)).

    Lc/H is the charged fraction of the hole: 1 - stemming/H (H = mean hole length).
    """
    p = x.params
    h = x.mean_hole_length_m
    frac = max(0.05, 1.0 - p.stemming_m / h) if h > 0 else 1.0
    return math.sqrt(x.mc * frac / (p.powder_factor_target * p.sb_ratio))


def energy_method(x: BurdenInputs) -> float:
    """B = d_c sqrt(pi rho_e / (4 c)), c = s * eps_ss / (eps * eta)   (Berta 1985).

    s: new surface per m3 of rock (m2/m3), taken as 64/M with M the target maximum
    fragment size in metres (convention of the legacy macro, TO BE VERIFIED against
    the original source); eta = blasting efficiency: given, or impedance transmission
    coefficient times 0.15 (legacy macro).
    """
    p = x.params
    es = x.need(x.rock.frag_energy_kj_m2, "rock fragmentation energy") / 1000.0   # MJ/m2
    rho_r = x.need(x.rock.density, "rock density")
    vp = x.need(x.rock.vp_ms, "rock P-wave velocity")
    s_new = 64.0 / (p.max_fragment_cm / 100.0)
    if p.blasting_efficiency is not None:
        eta = p.blasting_efficiency
    else:
        zr, ze = rho_r * vp, x.expl.density * x.expl.vod_ms
        eta = (1.0 - ((ze - zr) / (ze + zr)) ** 2) * 0.15
    c = s_new * es / (x.expl.energy_mj_kg * eta)
    return x.d_m * math.sqrt(math.pi * x.expl.density * 1000.0 / (4.0 * c))


def konya_1972(x: BurdenInputs) -> float:
    rho_r = x.need(x.rock.density, "rock density")
    return 3.15 * (x.d_mm / IN_MM) * (x.expl.density / rho_r) ** (1 / 3) * FT


def konya_1983(x: BurdenInputs) -> float:
    rho_r = x.need(x.rock.density, "rock density")
    return (2 * x.expl.density / rho_r + 1.5) * (x.d_mm / IN_MM) * FT


def ash_1963(x: BurdenInputs) -> float:
    return x.params.ash_kb * (x.d_mm / IN_MM) / 12.0 * FT


def andersen_1952(x: BurdenInputs) -> float:
    d_ft, l_ft = x.d_m / FT, x.mean_hole_length_m / FT
    return x.params.andersen_k * math.sqrt(d_ft * l_ft) * FT


@dataclass(frozen=True)
class BurdenMethod:
    key: str
    label: str
    reference: str
    func: Callable[[BurdenInputs], float]
    requires: tuple[str, ...] = ()
    origin: str = "general"     # general | bench | ring
    note: str = ""


METHODS: dict[str, BurdenMethod] = {m.key: m for m in [
    BurdenMethod("langefors_kihlstrom", "Langefors-Kihlstrom", "Langefors & Kihlstrom, 1963",
                 langefors_kihlstrom, (), "bench", "most used; adapted to rings via S/B"),
    BurdenMethod("hustrulid_pf", "Powder factor (Hustrulid)", "Holmberg, Hustrulid & Cunningham, 2001",
                 hustrulid_powder_factor, (), "ring", "driven by target powder factor"),
    BurdenMethod("energy", "Energy / new surface", "Berta, 1985",
                 energy_method, ("rock.frag_energy_kj_m2", "rock.density", "rock.vp_ms"), "general",
                 "needs fragmentation energy and Vp"),
    BurdenMethod("konya_1972", "Konya", "Konya, 1972", konya_1972, ("rock.density",), "bench"),
    BurdenMethod("konya_1983", "Konya", "Konya, 1983", konya_1983, ("rock.density",), "bench"),
    BurdenMethod("ash_1963", "Ash", "Ash, 1963", ash_1963, (), "bench", "Kb = 30 default (macro: 25)"),
    BurdenMethod("andersen_1952", "Andersen", "Andersen, 1952", andersen_1952, (), "bench"),
]}

LEGACY_NOT_PORTED = {
    "Pearse 1955": "VBA operator-precedence bug ((PD/RT)^1/2) and mixed MPa / kg-cm2 units",
    "Hino 1959": "never implemented in the macro (needs cratering-test constant n)",
    "Allsman 1960": "unit mixing (PD in Pa, u set to VOD); needs review",
    "Hansen 1967": "bench-blasting formula, never implemented",
    "Ucar 1972": "bench-blasting formula",
    "Foldesi 1980": "gives ~71 m in the macro: powder factor hard-coded to 1, unit mismatch",
    "Praillet 1980": "bench-blasting formula, never implemented",
    "Jimeno 1980": "never implemented; valid for 165-250 mm only",
    "Bruce Carr 1985": "gives 0.0003 m in the macro: VOD hard-coded to 0.305",
    "Olofsson 1990": "burden never assigned in the macro (empty result)",
    "Rustan 1990": "computed but not reported by the macro",
}


def compute_burden(method: str, x: BurdenInputs) -> float:
    if method not in METHODS:
        raise KeyError(f"unknown burden method '{method}'. Available: {', '.join(METHODS)}")
    return METHODS[method].func(x)


def compare_methods(x: BurdenInputs) -> dict[str, Optional[float]]:
    """Burden from every available method (None where a needed property is missing)."""
    out: dict[str, Optional[float]] = {}
    for key, m in METHODS.items():
        try:
            out[key] = m.func(x)
        except MissingInput:
            out[key] = None
    return out
