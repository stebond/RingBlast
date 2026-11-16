"""Figures and numbers for the RingBlast paper  (python tools/make_paper_figures.py [outdir]).

Everything is computed with the RingBlast engine: no number in the paper is typed by hand.
Writes PNG figures (300 dpi) and results.json to <outdir> (default: paper/figures).
"""
from __future__ import annotations

import copy
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ringblast import db  # noqa: E402
from ringblast.burden import BurdenInputs, compare_methods, hustrulid_powder_factor, langefors_kihlstrom  # noqa: E402
from ringblast.design import run_design, sensitivity  # noqa: E402
from ringblast.export import _zone_arcs, stope_outline, stope_passing_curve  # noqa: E402
from ringblast.fragmentation import passing_curve  # noqa: E402
from ringblast.geometry import mean_hole_length  # noqa: E402
from ringblast.models import DesignParams, Explosive, Rock, StopeGeometry  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "paper" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.linewidth": 0.6, "axes.labelsize": 8,
                     "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7, "axes.titlesize": 8,
                     "savefig.dpi": 300, "figure.dpi": 150})
RED, GREY, BLUE, NAVY, GREEN = "#d62728", "#8c8c8c", "#1f77b4", "#16304f", "#2ca02c"
FILLS = ["#dbe9f6", "#fbe5cc", "#dff0d8", "#f3dcec"]
RESULTS: dict = {}

ROCKS, EXPL = db.load_rocks(), db.load_explosives()


def setup(cfg: dict):
    rock, ex = ROCKS[cfg["rock"]], EXPL[cfg["explosive"]]
    stope, p = StopeGeometry(**cfg["stope"]), DesignParams(**cfg.get("params", {}))
    return rock, ex, stope, p


def label(ax, text):
    ax.text(0.0, 1.0, text, transform=ax.transAxes, fontsize=9, fontweight="bold", va="bottom")


def draw_pattern(ax, result, stope, level=None, numbers=False, zones=False, names=True, fs=6.5):
    levels = result.levels if level is None else [result.levels[level - 1]]
    pts = stope_outline(stope)
    ax.plot(*zip(*(pts + [pts[0]])), color="k", lw=1.0)
    for lv in levels:
        for h in lv.ring.holes:
            if h.stemming_length > 1e-9:
                ax.plot(*zip(h.collar, h.charge_start), color=GREY, lw=0.5)
            ax.plot(*zip(h.charge_start, h.toe), color=RED, lw=0.8)
            if numbers:
                ax.annotate(str(h.index), h.toe, fontsize=fs, xytext=(2, 2), textcoords="offset points")
        if zones:
            for run in _zone_arcs(lv):
                ax.plot(*zip(*run), color=GREEN, lw=0.7, ls="--")
        x0, y0, x1, y1 = lv.spec.drift_rect
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=True, fc="white", ec=BLUE, lw=0.9, zorder=3))
        if names:
            left = lv.spec.side == "left"
            ax.annotate(lv.spec.name, (x0 if left else x1, y1), fontsize=fs, xytext=(-3 if left else 3, 3),
                        textcoords="offset points", color=BLUE, ha="right" if left else "left")
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")


def dim(ax, p0, p1, text, off=(0, 0), ha="center", va="center", rot=0, fs=7.5):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="<->", mutation_scale=7, lw=0.7, color=NAVY, shrinkA=0, shrinkB=0))
    ax.text((p0[0] + p1[0]) / 2 + off[0], (p0[1] + p1[1]) / 2 + off[1], text, ha=ha, va=va, rotation=rot,
            fontsize=fs, color=NAVY, bbox=dict(fc="white", ec="none", pad=0.6))


def axes_arrows(ax, x, y, ln, fs=8):
    for dx, dy, t in ((ln, 0, "x"), (0, ln, "y")):
        ax.add_patch(FancyArrowPatch((x, y), (x + dx, y + dy), arrowstyle="-|>", mutation_scale=8, lw=1.0, color="k"))
        ax.text(x + dx * 1.18 + (1.0 if dx else -0.8), y + dy * 1.1 + (-1.4 if dx else 0.6), t, fontsize=fs,
                style="italic", ha="center")


# ------------------------------------------------------------------ Case 1: program defaults
CASE1 = {"rock": "Limestone", "explosive": "anfo77",
         "stope": {"width": 25, "height": 80, "n_sublevels": 2, "drift_width": 5, "drift_height": 5,
                   "wall_angle_deg": 55},
         "params": {"hole_diameter_mm": 80, "burden_method": "langefors_kihlstrom", "sb_ratio": 1.25,
                    "fixation": 0.65, "c_langefors": 0.8, "rock_factor_A": 10, "zone_length_m": 5}}
rock, ex, stope, p = setup(CASE1)
res1 = run_design(rock, ex, stope, p)


def totals(res, stope):
    return {"burden_m": res.burden_m, "spacing_m": res.spacing_m, "n_holes": res.n_holes,
            "drilled_length_m": res.drilled_length_m, "charged_length_m": res.charged_length_m,
            "charge_kg": res.charge_kg, "volume_m3": res.volume_m3, "powder_factor": res.powder_factor,
            "mean_size_cm": res.weighted_mean_size_cm,
            "levels": [{"name": l.spec.name, "n_holes": l.n_holes, "drilled_m": l.drilled_length_m,
                        "charge_kg": l.charge_kg, "volume_m3": l.volume_m3, "pf": l.powder_factor,
                        "x50_cm": l.weighted_mean_size_cm, "spacing_eff": [l.ring.lateral_spacing_eff,
                        l.ring.bottom_spacing_eff, l.ring.right_spacing_eff]} for l in res.levels],
            "undercut_height_m": stope.undercut_height, "sublevel_height_m": stope.sublevel_height
            if hasattr(stope, "sublevel_height") else None}


RESULTS["case1"] = totals(res1, stope)
RESULTS["case1"]["zones"] = [[l.spec.name, [(z.index, z.r_in, z.r_out, z.powder_factor, z.mean_size_cm,
                                             z.uniformity_n) for z in l.zones]] for l in res1.levels]
RESULTS["case1"]["burden_all_methods"] = compare_methods(
    BurdenInputs(rock, ex, p, mean_hole_length(stope, res1.burden_m)))

# ================================================================== Fig. 1 geometry
fig, (a, b) = plt.subplots(1, 2, figsize=(7.2, 5.6), gridspec_kw={"width_ratios": [1.0, 1.25]})
pts = stope_outline(stope)
a.plot(*zip(*(pts + [pts[0]])), color="k", lw=1.2)
specs = [lv.spec for lv in res1.levels]
L, H, u = stope.width, stope.height, stope.undercut_height
for k, sp in enumerate(specs):
    a.add_patch(Polygon(sp.polygon, closed=True, fc=FILLS[k % 4], ec="none", alpha=0.9, zorder=0))
    x0, y0, x1, y1 = sp.drift_rect
    a.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc="white", ec=BLUE, lw=1.0, zorder=3))
    a.text(L / 4, (min(q[1] for q in sp.polygon) + max(q[1] for q in sp.polygon)) / 2 - 2, sp.name, ha="center", fontsize=7.5, color="#333", zorder=4)
a.plot(*zip(*(pts + [pts[0]])), color="k", lw=1.2, zorder=2)
dim(a, (-L / 2, -7), (L / 2, -7), "L", off=(0, -3))
dim(a, (L / 2 + 5, 0), (L / 2 + 5, H), "H", off=(3.2, 0), rot=90)
dim(a, (L / 2 + 1.3, 0), (L / 2 + 1.3, u), "u", off=(2.6, 0), rot=90, fs=7)
a.add_patch(Rectangle((-stope.hopper_half_width, 0), 2 * stope.hopper_half_width, stope.drift_height, fc="none", ec=BLUE, lw=0))
dim(a, (-stope.hopper_half_width, -2.2), (stope.hopper_half_width, -2.2), "l", off=(0, -2.6), fs=7)
sp0 = specs[0]
x0, y0, x1, y1 = sp0.drift_rect
dim(a, (x1 + 2.5, y0), (x1 + 2.5, y1), "h", off=(2.6, 0), rot=90, fs=7)
a.annotate("", xy=(-L / 2 + 6.5, u + 1.5), xytext=(-L / 2, u))
a.text(-L / 2 + 7.8, u - 3.5, r"$\alpha$", fontsize=9, color=NAVY)
a.plot([-L / 2, -L / 2 + 9], [u, u], color=NAVY, lw=0.5, ls=":")
a.text(L / 2 + 1, -7, "", fontsize=7)
axes_arrows(a, -L / 2 - 7.5, 3, 10)
a.plot(0, 0, "k+", ms=7, zorder=6)
a.text(1.0, -1.9, "O", fontsize=7, zorder=6)
a.plot([0, 0], [0, H], color="#999", lw=0.5, ls="-.", zorder=1)
a.set_xlim(-L / 2 - 11, L / 2 + 10)
a.set_ylim(-16, H + 5)
a.set_aspect("equal")
a.axis("off")
label(a, "(a)")

# ring detail
lv = res1.levels[0]
sp = lv.spec
poly = sp.polygon + [sp.polygon[0]]
b.plot(*zip(*poly), color="k", lw=1.2)
for h in lv.ring.holes:
    ax_stem = b.plot(*zip(h.collar, h.charge_start), color=GREY, lw=0.8)
    b.plot(*zip(h.charge_start, h.toe), color=RED, lw=1.2)
    ox = -9 if h.toe[0] < -1 else (3 if h.toe[0] > 1 else -2)
    oy = -8 if (h.kind in ("bottom", "bottom-corner")) else 2
    b.annotate(str(h.index), h.toe, fontsize=6, xytext=(ox, oy), textcoords="offset points")
x0, y0, x1, y1 = sp.drift_rect
b.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc="white", ec=BLUE, lw=1.1, zorder=3))
b.plot(*sp.centre, "o", color=NAVY, ms=3, zorder=4)
holes = lv.ring.holes
bot = [h for h in holes if h.kind in ("bottom", "bottom-corner") and h.toe[0] > 0]
if len(bot) >= 2:
    t1, t2 = sorted(bot, key=lambda h: h.toe[0])[:2]
    dim(b, (t1.toe[0], t1.toe[1] - 2.2), (t2.toe[0], t2.toe[1] - 2.2), "S", off=(0, -1.6), fs=7.5)
yb = sp.polygon[0][1] if False else min(q[1] for q in sp.polygon)
yt = max(q[1] for q in sp.polygon)
b.legend(handles=[plt.Line2D([], [], color=RED, lw=1.5, label="charged length"),
                  plt.Line2D([], [], color=GREY, lw=1.5, label="stemming / uncharged"),
                  plt.Line2D([], [], color=BLUE, lw=1.5, label="drift"),
                  plt.Line2D([], [], color="k", lw=1.5, label="block boundary"),
                  plt.Line2D([], [], color=NAVY, marker="o", lw=0, ms=3, label="fan centre")],
         loc="lower center", bbox_to_anchor=(0.5, -0.30), ncol=3, frameon=False)
b.set_xlim(-stope.width / 2 - 7, stope.width / 2 + 4.5)
b.set_ylim(yb - 6, yt + 3)
b.set_aspect("equal")
b.set_xlabel("x (m)")
b.set_ylabel("y (m)")
label(b, "(b)")
fig.tight_layout()
fig.savefig(OUT / "fig1_geometry.png", bbox_inches="tight")
plt.close(fig)

# ================================================================== Fig. 2 zones
fig, ax = plt.subplots(figsize=(3.5, 4.6))
draw_pattern(ax, res1, stope, level=1, numbers=False, zones=True, names=False)
lv = res1.levels[0]
cx, cy = lv.spec.centre
xb, yb_ = [q[0] for q in lv.spec.polygon], [q[1] for q in lv.spec.polygon]
for z in lv.zones:
    r = 0.5 * (z.r_in + z.r_out) if z.index > 1 else 0.5 * z.r_out
    ang = math.radians(-90 + (14 if z.index % 2 else -14))
    px, py = cx + r * math.cos(ang), cy + r * math.sin(ang)
    if min(xb) < px < max(xb) and min(yb_) < py < max(yb_):
        ax.text(px, py, str(z.index), fontsize=8, color=GREEN, fontweight="bold", ha="center", va="center",
                bbox=dict(fc="white", ec="none", pad=0.5, alpha=0.85), zorder=5)
ax.plot(cx, cy, "o", color=NAVY, ms=3, zorder=5)
ax.set_ylim(min(q[1] for q in lv.spec.polygon) - 4, max(q[1] for q in lv.spec.polygon) + 2)
fig.tight_layout()
fig.savefig(OUT / "fig2_zones.png", bbox_inches="tight")
plt.close(fig)
RESULTS["zones_n_level1"] = len(lv.zones)

# ================================================================== Fig. 3 workflow
fig, ax = plt.subplots(figsize=(7.2, 3.9))
ax.set_xlim(0, 100)
ax.set_ylim(0, 56)
ax.axis("off")


def box(x, y, w, h, text, fc="#eaf1f8", ec=NAVY, fs=7.2, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=1.2", fc=fc, ec=ec, lw=0.9))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else None,
            linespacing=1.25)


def arrow(p0, p1):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=8, lw=0.9, color=NAVY))


box(1, 40, 22, 13, "INPUTS\nstope geometry\nrock and explosive DB\ndesign parameters", fc="#fff3d6", fs=6.6)
box(28, 40, 20, 13, "BURDEN\n7 empirical methods\nor manual value", fs=6.6)
box(53, 40, 22, 13, "RING GEOMETRY\nblocks, fans, toes,\nexact closure", fs=6.6)
box(80, 40, 19, 13, "CHARGING\nstemming, rules\n(i)-(iii), decharging", fs=6.6)
box(80, 20, 19, 13, "FRAGMENTATION\nannular zones,\nKuz-Ram + R-R", fs=6.6)
box(53, 20, 22, 13, "OUTPUTS\nDXF, CSV, JSON, HTML,\nplots and statistics", fc="#dff0d8", fs=6.6)
box(28, 20, 20, 13, "COMPARISON\npredicted vs measured\nfragmentation", fc="#fbe5cc", fs=6.6)
box(1, 20, 22, 13, "MUCK-PILE PHOTOS\nscale, segmentation,\nmeasured size curve", fc="#fbe5cc", fs=6.6)
arrow((23, 46.5), (28, 46.5))
arrow((48, 46.5), (53, 46.5))
arrow((75, 46.5), (80, 46.5))
arrow((89.5, 40), (89.5, 33))
arrow((80, 26.5), (75, 26.5))
arrow((53, 26.5), (48, 26.5))
arrow((23, 26.5), (28, 26.5))
box(1, 3, 98, 11, "Interfaces:  graphical user interface (PySide6)   |   command line (ringblast run / compare / sensitivity)   |   Python API\n"
    "Open-source stack:  numpy, matplotlib, ezdxf, OpenCV, Pillow", fc="#f3f3f3", ec="#888", fs=7.2)
ax.text(50, 56.2, "RingBlast processing chain", ha="center", fontsize=8.5, fontweight="bold", color=NAVY)
fig.savefig(OUT / "fig3_workflow.png", bbox_inches="tight")
plt.close(fig)

# ================================================================== Fig. 4 GUI screenshots
from PIL import Image  # noqa: E402

shots = [ROOT / "figures/screenshots/01_stope_layout.png", ROOT / "figures/screenshots/02_blast_design_pattern.png"]
if shots[1].exists():
    fig, a_ = plt.subplots(figsize=(7.2, 4.6))
    a_.imshow(Image.open(shots[1]).convert("RGB"))
    a_.axis("off")
    fig.tight_layout(pad=0.2)
    fig.savefig(OUT / "fig4_gui.png", bbox_inches="tight", dpi=220)
    plt.close(fig)

# ================================================================== Fig. 5 case 1 results
fig, (a, b) = plt.subplots(1, 2, figsize=(7.2, 4.8), gridspec_kw={"width_ratios": [1, 1.1]})
draw_pattern(a, res1, stope, numbers=False, zones=False, names=True)
label(a, "(a)")
xs = np.geomspace(0.5, 150, 500)


def logsize(ax):
    """Logarithmic size axis with plain-number ticks (as in the program)."""
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter
    ax.set_xscale("log")
    ax.set_xlim(0.5, 150)
    ax.xaxis.set_major_locator(FixedLocator([0.5, 1, 2, 5, 10, 20, 50, 100]))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.grid(True, which="both", alpha=0.25, lw=0.4)



def mix(zones):
    zs = [z for z in zones if not math.isnan(z.mean_size_cm)]
    tot = sum(z.area_m2 for z in zs)
    return sum(z.area_m2 * passing_curve(xs, z.characteristic_size_cm, z.uniformity_n) for z in zs) / tot


cols = ["#1f77b4", "#ff7f0e", "#2ca02c"]
for k, lv in enumerate(res1.levels):
    b.plot(xs, 100 * mix(lv.zones), color=cols[k % 3], lw=1.2, label=lv.spec.name)
b.plot(xs, 100 * mix(res1.zones), "k--", lw=1.6, label="whole stope")
b.set_xlabel("size (cm)")
b.set_ylabel("passing (%)")
b.set_ylim(0, 100)
logsize(b)
b.legend(loc="lower right", frameon=False)
label(b, "(b)")
fig.tight_layout()
fig.savefig(OUT / "fig5_case1.png", bbox_inches="tight")
plt.close(fig)

# zones of one level (fig. 2 companion)
fig, ax = plt.subplots(figsize=(3.6, 2.8))
lv = res1.levels[0]
for z, c in zip(lv.zones, plt.cm.viridis(np.linspace(0.1, 0.9, len(lv.zones)))):
    ax.plot(xs, 100 * passing_curve(xs, z.characteristic_size_cm, z.uniformity_n), color=c, lw=1.2, label=f"zone {z.index}")
ax.set_xlabel("size (cm)")
ax.set_ylabel("passing (%)")
ax.set_ylim(0, 100)
logsize(ax)
ax.legend(frameon=False, ncol=2)
fig.tight_layout()
fig.savefig(OUT / "fig2b_zone_curves.png", bbox_inches="tight")
plt.close(fig)

# fig. 2 combined: zone map (a) + zone curves on a logarithmic axis (b)
img = plt.imread(OUT / "fig2_zones.png")
fig = plt.figure(figsize=(7.2, 3.6))
a = fig.add_axes([0.0, 0.0, 0.48, 1.0]); a.imshow(img); a.axis("off"); a.text(0.0, 1.0, "(a)", transform=a.transAxes, fontweight="bold", va="top")
b = fig.add_axes([0.58, 0.16, 0.40, 0.76])
for z, c in zip(lv.zones, plt.cm.viridis(np.linspace(0.1, 0.9, len(lv.zones)))):
    b.plot(xs, 100 * passing_curve(xs, z.characteristic_size_cm, z.uniformity_n), color=c, lw=1.2, label=f"zone {z.index}")
b.set_xlabel("size (cm)"); b.set_ylabel("passing (%)"); b.set_ylim(0, 100); logsize(b)
b.legend(frameon=False, ncol=2, loc="lower right", fontsize=7)
fig.text(0.53, 0.97, "(b)", fontweight="bold", va="top")
fig.savefig(OUT / "fig2_combined.png", bbox_inches="tight")
plt.close(fig)

# ================================================================== Fig. 6 sensitivity
bs = [round(2.0 + 0.1 * i, 2) for i in range(0, 26)]
rows = [r for r in sensitivity(rock, ex, stope, p, bs) if "error" not in r]
RESULTS["sensitivity"] = rows
fig, a = plt.subplots(figsize=(3.6, 2.9))
a.plot([r["burden_m"] for r in rows], [r["powder_factor"] for r in rows], "o-", color=RED, ms=3, lw=1.0)
a.set_xlabel("burden B (m)")
a.set_ylabel("powder factor (kg/m³)", color=RED)
a.axhline(0.8, color="k", lw=0.6, ls=":")
a.axvline(res1.burden_m, color=GREY, lw=0.8, ls="--")
a.text(res1.burden_m + 0.05, a.get_ylim()[1] * 0.97, "Langefors–Kihlström", rotation=90, fontsize=6.5, va="top")
a2 = a.twinx()
a2.plot([r["burden_m"] for r in rows], [r["n_holes"] for r in rows], "s-", color=BLUE, ms=3, lw=1.0)
a2.set_ylabel("number of holes", color=BLUE)
a.grid(alpha=0.3, lw=0.4)
fig.tight_layout()
fig.savefig(OUT / "fig6_sensitivity.png", bbox_inches="tight")
plt.close(fig)
# burden for PF = 0.8 by linear interpolation
pf = np.array([r["powder_factor"] for r in rows])
bb = np.array([r["burden_m"] for r in rows])
RESULTS["burden_at_pf_0.8"] = float(np.interp(0.8, pf[::-1], bb[::-1])) if pf.min() < 0.8 < pf.max() else None

# ================================================================== Fig. 7 layout options
LAYOUT_CASES = [
    ("(a) side drifts", "case_side_drift"),
    ("(b) arched roof,\ncentred drifts", "case_arched_roof_centered_drifts"),
    ("(c) two drifts per\nsublevel", "case_two_drifts_per_sublevel"),
]
fig, axs = plt.subplots(1, 3, figsize=(7.2, 4.4))
for ax_, (title, name) in zip(axs, LAYOUT_CASES):
    cfg = json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8"))
    r_, e_, s_, p_ = setup(cfg)
    rr = run_design(r_, e_, s_, p_)
    draw_pattern(ax_, rr, s_, names=False)
    ax_.set_title(title, fontsize=8)
    RESULTS[name] = totals(rr, s_)
fig.tight_layout()
fig.savefig(OUT / "fig7_layout_options.png", bbox_inches="tight")
plt.close(fig)

# ================================================================== Case study 2: two Italian quarries
CF = {"rock": "Limestone", "explosive": "anfo77",
      "params": {"hole_diameter_mm": 100, "burden_method": "langefors_kihlstrom", "sb_ratio": 1.3,
                 "fixation": 0.65, "c_langefors": 0.8, "rock_factor_A": 10, "zone_length_m": 5}}
variants = [
    ("(a) 3+1,\ncentral", dict(width=30, height=116, n_sublevels=3, drift_position="center")),
    ("(b) 2+1,\ncentral", dict(width=30, height=116, n_sublevels=2, drift_position="center")),
    ("(c) 3+1,\nat the walls", dict(width=30, height=116, n_sublevels=3, drift_position="left")),
    ("(d) 2+1,\nat the walls", dict(width=30, height=116, n_sublevels=2, drift_position="left")),
]
GR = ("(e) Gola della Rossa\n2+1, at the walls", dict(width=30, height=104, n_sublevels=2, drift_position="left"))
fig, axs = plt.subplots(1, 5, figsize=(7.2, 6.4), gridspec_kw={"width_ratios": [1, 1, 1, 1, 1]}, sharey=False)
RESULTS["case2"] = {}
for ax_, (title, kw) in zip(axs, variants + [GR]):
    st = StopeGeometry(drift_width=5, drift_height=5, wall_angle_deg=55, **kw)
    r_, e_ = ROCKS[CF["rock"]], EXPL[CF["explosive"]]
    pp = DesignParams(**CF["params"])
    rr = run_design(r_, e_, st, pp)
    draw_pattern(ax_, rr, st, names=False, fs=5.5)
    ax_.set_title(title, fontsize=6.5)
    ax_.set_xlabel("x (m)", fontsize=6.5)
    ax_.set_ylabel("y (m)" if ax_ is axs[0] else "", fontsize=6.5)
    ax_.set_xlim(-st.width / 2 - 2, st.width / 2 + 2)
    ax_.tick_params(labelsize=6)
    RESULTS["case2"][title] = totals(rr, st)
fig.tight_layout()
fig.savefig(OUT / "fig8_case2.png", bbox_inches="tight")
plt.close(fig)

# ================================================================== validation against hand calculations
val = {}
# (1) powder-factor method, worked example of the lecture notes: Mc = 9.64 kg/m, K = 0.8 kg/m3, D = 0.1 m,
#     H = 10 m, stemming = 20 D, S/B = 1.3  -> B = 2.72 m, S = 3.54 m
d100 = 100.0
rho_for_mc = 9.64 / (math.pi * (d100 / 1000) ** 2 / 4 * 1000)
e1 = Explosive(name="example", density=rho_for_mc, energy_mj_kg=3.0, vod_ms=4000.0, rws_anfo=100.0)
p1 = DesignParams(hole_diameter_mm=d100, sb_ratio=1.3, powder_factor_target=0.8, stemming_diameters=20.0)
x1 = BurdenInputs(ROCKS["Limestone"], e1, p1, 10.0)
b1 = hustrulid_powder_factor(x1)
val["pf_method"] = {"B": b1, "S": 1.3 * b1, "reference_B": 2.72, "reference_S": 3.54}
# (2) Langefors-Kihlstrom: P = 0.75 kg/dm3, RWS = 0.973, d = 100 mm, c_bar = 0.85, f = 0.65, S/B = 1.3 -> 3.05 m
e2 = Explosive(name="example2", density=0.75, energy_mj_kg=3.0, vod_ms=4000.0, rws_anfo=97.3)
p2 = DesignParams(hole_diameter_mm=100.0, sb_ratio=1.3, fixation=0.65, c_langefors=0.80)
x2 = BurdenInputs(ROCKS["Limestone"], e2, p2, 10.0)
b2 = langefors_kihlstrom(x2, c_correction="fixed")
val["langefors"] = {"B": b2, "S": 1.3 * b2, "reference_B": 3.05, "reference_S": 3.97}
RESULTS["validation"] = val

(OUT / "results.json").write_text(json.dumps(RESULTS, indent=1, default=lambda o: None), encoding="utf-8")
print("done ->", OUT)
print(json.dumps(RESULTS["case1"], indent=1, default=str)[:1800])
print(val)
