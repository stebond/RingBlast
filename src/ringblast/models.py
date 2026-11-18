"""Data models for RingBlast. SI units unless stated (m, kg, t/m3, mm for hole diameter)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


class MissingInput(ValueError):
    """A calculation method needs a rock/explosive property that is not available."""


@dataclass(frozen=True)
class Rock:
    name: str
    density: Optional[float] = None            # t/m3
    ucs_mpa: Optional[float] = None
    shear_mpa: Optional[float] = None
    tensile_mpa: Optional[float] = None
    vp_ms: Optional[float] = None              # P-wave (sonic) velocity
    frag_energy_kj_m2: Optional[float] = None  # specific surface energy for fragmentation
    c_langefors: float = 0.4                   # rock constant c (kg/m3)
    rock_factor_A: Optional[float] = None      # Kuz-Ram rock factor
    youngs_gpa: Optional[float] = None
    name_it: str = ""
    source: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Explosive:
    name: str
    density: float                 # kg/dm3, loading density
    energy_mj_kg: float
    vod_ms: float
    rws_anfo: float                # relative weight strength, ANFO = 100
    det_pressure_gpa: Optional[float] = None
    source: str = ""
    notes: str = ""

    @property
    def s_anfo(self) -> float:
        """Relative weight strength with ANFO = 1 (used by Langefors-Kihlstrom)."""
        return self.rws_anfo / 100.0


def arch_segment(half_width: float, y: float, rise: float, x_from: float, x_to: float,
                 n: int = 90) -> list[tuple[float, float]]:
    """Points of the circular roof arc between two abscissas, ends included, evenly spaced in angle.

    The arc is the circle through the two top corners (+-half_width, y) of the roof rectangle with
    its crown `rise` above that edge (rise = 0: the straight edge)."""
    if rise <= 0:
        return [(x_from, y), (x_to, y)]
    radius = (half_width ** 2 + rise ** 2) / (2 * rise)
    cy = y + rise - radius
    t0, t1 = math.asin(max(-1.0, min(1.0, x_from / radius))), math.asin(max(-1.0, min(1.0, x_to / radius)))
    return [(radius * math.sin(t0 + (t1 - t0) * k / n), cy + radius * math.cos(t0 + (t1 - t0) * k / n))
            for k in range(n + 1)]


def arch_points(half_width: float, y: float, rise: float, n: int = 90) -> list[tuple[float, float]]:
    """Whole roof arc from the right wall to the left wall, endpoints included."""
    return arch_segment(half_width, y, rise, half_width, -half_width, n)


def arch_y(half_width: float, y: float, rise: float, x: float) -> float:
    """Height of the roof at abscissa x (the flat edge y if rise = 0)."""
    if rise <= 0:
        return y
    radius = (half_width ** 2 + rise ** 2) / (2 * rise)
    return y + rise - radius + math.sqrt(radius ** 2 - x ** 2)


@dataclass
class StopeGeometry:
    """Cross-section of a stope (plane of the ring), x horizontal, y vertical (up).

    The stope has `n_sublevels` rectangular sublevels (drift at the top of each block) and,
    if `base_drift`, a base drift at the top of the hopper block, whose ring covers the
    trapezoid between y = undercut_height and the hopper floor (see geometry.level_specs).
    Sublevel drifts can be central or flush with the left/right wall (`drift_position`, or
    one entry per sublevel in `drift_positions`, top to bottom).  The base drift is always at
    the bottom centre of the stope, in the neck at the end of the hopper, and fans upwards.
    """
    width: float                  # L: stope width between walls (m)
    height: float                 # H: stope height (m)
    n_sublevels: int = 2
    drift_width: float = 5.0      # l (m)
    drift_height: float = 5.0     # h (m)
    wall_angle_deg: float = 55.0  # hopper wall angle of the undercut
    drift_position: str = "center"             # center | left | right
    drift_wall_distance_m: float = 0.0         # wall-to-drift distance for side drifts (0 = flush with the wall);
                                               # two drifts at the sides: may be negative, down to -drift_width/2
                                               # (drift axis on the wall of the stope)
    drift_positions: Optional[list] = None     # per-sublevel override (n_sublevels entries, top to bottom)
    base_drift: bool = True
    undercut_height_m: Optional[float] = None  # None -> ceil(L/2 tan(angle) + h/2) (legacy macro)
    hopper_bottom_width_m: Optional[float] = None  # None -> drift_width
    sublevel_gap_m: Optional[float] = None     # vertical clear distance between the charged blocks of consecutive
                                               # sublevels (uncharged, drawn grey); None -> half the burden (legacy)
    twin_block_gap_m: float = 0.0              # two drifts per sublevel: clear distance between the left and the right
                                               # block (uncharged strip along the centre line, drawn grey)
    drifts_per_sublevel: int = 1               # 1, or 2 symmetric drifts (each fires one half of the block)
    twin_position: str = "sides"               # two drifts: "sides" (at the walls), "halves" (centre of each half)
                                               # or "gap" (symmetric, with `twin_gap_m` between the two drifts)
    twin_gap_m: float = 5.0                    # "gap": clear distance between the two drift rectangles
    drift_vertical: str = "top"                # sublevel drifts: "top" (roof at the top of the block, minus
                                               # drift_top_distance_m) or "center" (centred in the sublevel)
    drift_top_distance_m: float = 0.0          # "top": distance between the top of the block and the drift roof
    roof_arch_rise_m: float = 0.0              # 0 = flat roof; else the arc rises this far above the top edge

    @property
    def undercut_height(self) -> float:
        if self.undercut_height_m is not None:
            return float(self.undercut_height_m)
        return float(math.ceil(self.width / 2 * math.tan(math.radians(self.wall_angle_deg))
                               + self.drift_height / 2))

    @property
    def sublevel_height(self) -> float:
        return (self.height - self.undercut_height) / self.n_sublevels

    @property
    def n_levels(self) -> int:
        return self.n_sublevels * self.drifts_per_sublevel + (1 if self.base_drift else 0)

    @property
    def min_wall_distance(self) -> float:
        """Smallest allowed wall distance: 0, or -drift_width/2 for two drifts at the sides (the drift
        axis can be moved onto the wall of the stope)."""
        return -self.drift_width / 2 if (self.drifts_per_sublevel == 2 and self.twin_position == "sides") else 0.0

    def drift_xs(self, level: int) -> list[float]:
        """Abscissas of the drift centres of sublevel `level` (0-based), left to right."""
        if self.drifts_per_sublevel == 2:
            if self.twin_position == "gap":
                x = self.twin_gap_m / 2 + self.drift_width / 2
            elif self.twin_position == "halves":
                x = self.width / 4
            else:
                x = self.width / 2 - self.drift_wall_distance_m - self.drift_width / 2
            return [-x, x]
        return [self.drift_x(level)]

    @property
    def hopper_half_width(self) -> float:
        w = self.hopper_bottom_width_m if self.hopper_bottom_width_m is not None else self.drift_width
        return w / 2.0

    def position(self, level: int) -> str:
        """Drift position of level `level` (0-based; the base drift is always central)."""
        if level >= self.n_sublevels:
            return "center"
        if self.drift_positions:
            return self.drift_positions[level]
        return self.drift_position

    def drift_x(self, level: int) -> float:
        pos = self.position(level)
        edge = self.width / 2 - self.drift_wall_distance_m - self.drift_width / 2
        return {"center": 0.0, "left": -edge, "right": edge}[pos]

    def drift_roof_y(self, level: int) -> float:
        """Elevation of the roof of sublevel drift `level` (0-based)."""
        top = self.height - level * self.sublevel_height
        if self.drift_vertical == "center":
            return top - self.sublevel_height / 2 + self.drift_height / 2
        return top - self.drift_top_distance_m

    def validate(self) -> None:
        if min(self.width, self.height, self.drift_width, self.drift_height) <= 0:
            raise ValueError("all geometry dimensions must be positive")
        if self.n_sublevels < 1:
            raise ValueError("at least one sublevel is required")
        if self.drift_width >= self.width:
            raise ValueError("drift wider than the stope")
        if self.sublevel_height <= self.drift_height:
            raise ValueError("sublevel height must exceed drift height")
        if self.sublevel_gap_m is not None and self.sublevel_gap_m < 0:
            raise ValueError("the vertical gap between the sublevel blocks cannot be negative")
        if self.twin_block_gap_m < 0 or (self.drifts_per_sublevel == 2 and self.twin_block_gap_m >= self.width):
            raise ValueError("the gap between the left and right blocks must be between 0 and the stope width")
        if self.drift_positions and len(self.drift_positions) != self.n_sublevels:
            raise ValueError(f"drift_positions needs {self.n_sublevels} entries (one per sublevel)")
        for k in range(self.n_sublevels):
            if self.position(k) not in ("center", "left", "right"):
                raise ValueError("drift position must be center, left or right")
        if self.drifts_per_sublevel not in (1, 2):
            raise ValueError("drifts per sublevel must be 1 or 2")
        if self.twin_position not in ("sides", "halves", "gap"):
            raise ValueError("position of two drifts must be sides, halves or gap")
        if self.drifts_per_sublevel == 2 and self.twin_position == "gap":
            if self.twin_gap_m < 0:
                raise ValueError("the gap between the two drifts cannot be negative")
            if self.twin_gap_m / 2 + self.drift_width / 2 > self.width / 2 + 1e-9:
                raise ValueError(f"the gap is too large: the drift axes would be beyond the walls "
                                 f"(maximum gap {self.width - self.drift_width:g} m)")
        if self.drifts_per_sublevel == 2:
            xs = self.drift_xs(0)
            if (self.twin_position != "gap" and xs[1] - self.drift_width / 2 < -1e-9) or (self.twin_position == "halves"
                                                         and self.drift_width > self.width / 2 - 1e-9):
                raise ValueError("the two drifts do not fit side by side in the stope width")
        if self.drift_vertical not in ("top", "center"):
            raise ValueError("vertical drift position must be top or center")
        if self.drift_top_distance_m < 0 or self.roof_arch_rise_m < 0:
            raise ValueError("drift distance from the top and roof arch rise cannot be negative")
        if self.drift_vertical == "top" and self.drift_top_distance_m + self.drift_height > self.sublevel_height:
            raise ValueError("drift does not fit in the sublevel: reduce its distance from the top")
        if self.roof_arch_rise_m > self.width / 2:
            raise ValueError("roof arch rise cannot exceed half the stope width (a semicircle)")
        if self.min_wall_distance < 0 and self.drift_wall_distance_m < self.min_wall_distance - 1e-9:
            raise ValueError(f"wall distance cannot be below {self.min_wall_distance:g} m: "
                             "the drift axis cannot go beyond the wall of the stope")
        if self.min_wall_distance == 0 and self.drift_wall_distance_m < 0:
            raise ValueError("wall distance cannot be negative")
        if any(self.position(k) != "center" for k in range(self.n_sublevels)) and \
                self.drift_width + 2 * self.drift_wall_distance_m > self.width:
            raise ValueError("side drift does not fit in the stope width")
        if self.base_drift and (self.hopper_half_width >= self.width / 2
                                or self.undercut_height <= self.drift_height):
            raise ValueError("inconsistent hopper geometry")


@dataclass
class DesignParams:
    hole_diameter_mm: float = 80.0
    burden_method: str = "langefors_kihlstrom"
    burden_manual_m: Optional[float] = None
    sb_ratio: float = 1.25                 # spacing / burden
    fixation: float = 0.65                 # Langefors fixation factor f
    c_langefors: Optional[float] = None    # None -> rock.c_langefors
    powder_factor_target: float = 0.8      # kg/m3 (Hustrulid / powder-factor method)
    stemming_diameters: float = 20.0       # uncharged collar length, in hole diameters
    zone_length_m: float = 5.0             # radial thickness of a fragmentation zone
    zone_centre: str = "fan"               # "fan" (drift centre) or "roof" (legacy macro)
    rock_factor_A: Optional[float] = None  # None -> rock.rock_factor_A, else 10
    blasting_efficiency: Optional[float] = None  # eta of the energy method; None -> impedance-based
    max_fragment_cm: float = 100.0         # energy method: size used to get new surface
    deviation_base_m: float = 0.10         # drilling deviation W = base + per_m * radial distance
    deviation_per_m: float = 0.001
    protect_corners: bool = True           # rule II: corner holes keep full charge
    decharge_levels: int = 2               # recursive decharging passes (1..3)
    ash_kb: float = 30.0
    andersen_k: float = 1.0
    booster: Optional[Explosive] = None    # bottom charge (booster) explosive; None = single explosive
    booster_length_m: float = 0.5          # booster length BCL at the toe of every charged hole

    @property
    def stemming_m(self) -> float:
        return self.stemming_diameters * self.hole_diameter_mm / 1000.0


@dataclass
class Hole:
    index: int
    kind: str                       # roof-corner | wall | bottom-corner | bottom | top
    collar: tuple[float, float]
    toe: tuple[float, float]
    charge_start: tuple[float, float]
    angle_deg: float = 0.0

    @staticmethod
    def _len(a, b) -> float:
        return math.hypot(b[0] - a[0], b[1] - a[1])

    @property
    def length(self) -> float:
        return self._len(self.collar, self.toe)

    @property
    def charged_length(self) -> float:
        return self._len(self.charge_start, self.toe)

    @property
    def stemming_length(self) -> float:
        return self._len(self.collar, self.charge_start)


@dataclass
class LevelSpec:
    """One ring level: drift position and the trapezoid (rectangle for sublevels) to blast.
    Vertices: tl, bl, br, tr = top-left, bottom-left, bottom-right, top-right toe corners."""
    index: int                      # 1-based, top to bottom
    name: str                       # "Sublevel 1", ..., "Base"
    kind: str                       # sublevel | base
    position: str                   # center | left | right
    centre: tuple[float, float]     # drift centre = fan centre
    top_y: float                    # roof of the drift / top of the block
    tl: tuple[float, float]
    bl: tuple[float, float]
    br: tuple[float, float]
    tr: tuple[float, float]
    drift_width: float
    drift_height: float
    arch_rise: float = 0.0          # >0: the top boundary (tl-tr) is an arc rising this far above the flat roof edge
    arch_half_width: float = 0.0    # half width of the whole stope roof (the arc spans -half_width..+half_width)
    arch_base_y: float = 0.0        # height of the flat roof edge the arc rises from (top of the roof rectangle)
    sublevel: int = 0               # 1-based sublevel number (0 = base)
    side: str = ""                  # "left" / "right" for the drifts of a two-drift sublevel
    top_toes: bool = False          # toes also on the top boundary (drift below the top of the block / arched roof)

    @property
    def drift_rect(self) -> tuple[float, float, float, float]:
        cx = self.centre[0]
        return (cx - self.drift_width / 2, self.top_y - self.drift_height,
                cx + self.drift_width / 2, self.top_y)

    @property
    def polygon(self) -> list[tuple[float, float]]:
        arc = (arch_segment(self.arch_half_width, self.arch_base_y, self.arch_rise, self.tr[0], self.tl[0])[1:-1]
               if self.arch_rise > 0 else [])
        return [self.tl, self.bl, self.br, self.tr] + arc


@dataclass
class Ring:
    holes: list[Hole]
    centre: tuple[float, float]
    y_bottom: float
    lateral_spacing_eff: float          # left edge
    bottom_spacing_eff: float
    n_lateral_intervals: int            # left edge
    n_bottom_intervals: int
    right_spacing_eff: float = float("nan")
    n_right_intervals: int = 0
    top_spacing_eff: float = float("nan")      # top boundary (only when the drift is below the top or the roof is arched)
    n_top_intervals: int = 0


@dataclass
class ZoneResult:
    index: int
    r_in: float
    r_out: float
    area_m2: float
    volume_m3: float
    charged_length_m: float
    charge_kg: float
    powder_factor: float
    n_holes_active: int
    charge_per_hole_kg: float
    local_spacing_m: float
    mean_size_cm: float
    uniformity_n: float
    characteristic_size_cm: float
    rws_eff: float = float("nan")   # length-weighted relative weight strength of booster + column


@dataclass
class LevelResult:
    spec: LevelSpec
    ring: Ring
    zones: list[ZoneResult]
    n_holes: int
    drilled_length_m: float
    charged_length_m: float
    charge_kg: float
    volume_m3: float
    powder_factor: float
    weighted_mean_size_cm: float


@dataclass
class DesignResult:
    burden_m: float
    spacing_m: float
    levels: list[LevelResult]
    warnings: list[str] = field(default_factory=list)

    # ---- totals for the whole stope (all levels)
    @property
    def n_holes(self) -> int:
        return sum(l.n_holes for l in self.levels)

    @property
    def drilled_length_m(self) -> float:
        return sum(l.drilled_length_m for l in self.levels)

    @property
    def charged_length_m(self) -> float:
        return sum(l.charged_length_m for l in self.levels)

    @property
    def charge_kg(self) -> float:
        return sum(l.charge_kg for l in self.levels)

    @property
    def volume_m3(self) -> float:
        return sum(l.volume_m3 for l in self.levels)

    @property
    def powder_factor(self) -> float:
        return self.charge_kg / self.volume_m3 if self.volume_m3 > 0 else 0.0

    @property
    def zones(self) -> list[ZoneResult]:
        return [z for l in self.levels for z in l.zones]

    @property
    def weighted_mean_size_cm(self) -> float:
        zs = [z for z in self.zones if not math.isnan(z.mean_size_cm)]
        den = sum(z.area_m2 for z in zs)
        return sum(z.mean_size_cm * z.area_m2 for z in zs) / den if den else float("nan")

    @property
    def ring(self) -> Ring:
        """Ring of the top sublevel (reference level)."""
        return self.levels[0].ring
