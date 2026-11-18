"""Exports: DXF (ezdxf), hole table CSV, JSON summary, HTML report."""
from __future__ import annotations

import html as _html

import base64
import csv
import io
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np

from . import plotstyle
from .fragmentation import _booster_start, passing_curve, split_charge
from .geometry import inside_region
from .models import (DesignParams, DesignResult, Explosive, LevelResult, Rock, StopeGeometry,
                     arch_points)

LAYERS = {  # name: (AutoCAD colour index, linetype)
    "STOPE": (7, "Continuous"), "DRIFTS": (4, "Continuous"),
    "HOLES_CHARGED": (1, "Continuous"), "HOLES_BOOSTER": (5, "Continuous"), "HOLES_STEMMING": (8, "Continuous"),
    "ZONES": (3, "Continuous"), "LABELS": (2, "Continuous"),
}


def stope_outline(stope: StopeGeometry) -> list[tuple[float, float]]:
    l2, h, u = stope.width / 2, stope.height, stope.undercut_height
    roof = [(-l2, h)] + arch_points(l2, h, stope.roof_arch_rise_m)[::-1][1:-1] + [(l2, h)]   # left -> right
    if not stope.base_drift:
        return [(-l2, 0)] + roof + [(l2, 0)]
    a, t = stope.hopper_half_width, stope.drift_height
    return [(-a, 0), (-a, t), (-l2, u)] + roof + [(l2, u), (a, t), (a, 0)]


def _zone_arcs(level: LevelResult):
    """Polylines of the zone boundaries (circles about the fan centre) inside the block."""
    spec = level.spec
    th = np.linspace(0.0, 2 * math.pi, 1441)
    for z in level.zones[:-1]:
        x, y = spec.centre[0] + z.r_out * np.cos(th), spec.centre[1] + z.r_out * np.sin(th)
        ok = inside_region(spec, x, y)
        run: list[tuple[float, float]] = []
        for xi, yi, oi in zip(x, y, ok):
            if oi:
                run.append((float(xi), float(yi)))
            elif run:
                yield run
                run = []
        if run:
            yield run


def export_dxf(path, result: DesignResult, stope: StopeGeometry, labels: bool = True,
               params: DesignParams | None = None) -> Path:
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.M
    for name, (color, lt) in LAYERS.items():
        doc.layers.add(name, color=color, linetype=lt)
    msp = doc.modelspace()
    msp.add_lwpolyline(stope_outline(stope), close=True, dxfattribs={"layer": "STOPE"})
    for lv in result.levels:
        spec = lv.spec
        x0, y0, x1, y1 = spec.drift_rect
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                           dxfattribs={"layer": "DRIFTS"})
        if labels:
            t = msp.add_text(spec.name, height=1.0, dxfattribs={"layer": "LABELS"})
            t.set_placement((x1 + 0.5, y0 + 0.5))
        for h in lv.ring.holes:
            if h.stemming_length > 1e-9:
                msp.add_line(h.collar, h.charge_start, dxfattribs={"layer": "HOLES_STEMMING"})
            bcl = split_charge(h, params)[0] if params is not None else 0.0
            if bcl > 0:
                bs = _booster_start(h, bcl)
                msp.add_line(h.charge_start, bs, dxfattribs={"layer": "HOLES_CHARGED"})
                msp.add_line(bs, h.toe, dxfattribs={"layer": "HOLES_BOOSTER", "lineweight": 50})
            else:
                msp.add_line(h.charge_start, h.toe, dxfattribs={"layer": "HOLES_CHARGED"})
            if labels:
                t = msp.add_text(str(h.index), height=0.7, dxfattribs={"layer": "LABELS"})
                t.set_placement((h.toe[0] + (0.3 if h.toe[0] >= spec.centre[0] else -1.2), h.toe[1]))
        for run in _zone_arcs(lv):
            if len(run) > 1:
                msp.add_lwpolyline(run, dxfattribs={"layer": "ZONES"})
    path = Path(path)
    doc.saveas(path)
    return path


def export_hole_csv(path, result: DesignResult, stope: StopeGeometry,
                    params: DesignParams | None = None) -> Path:
    path = Path(path)
    params = params or DesignParams()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["level", "hole", "kind", "collar_x", "collar_y", "toe_x", "toe_y", "length_m",
                    "stemming_m", "charged_m", "booster_m", "column_m", "angle_deg_from_x_axis"])
        for lv in result.levels:
            for h in lv.ring.holes:
                w.writerow([lv.spec.name, h.index, h.kind, *(round(v, 3) for v in (*h.collar, *h.toe)),
                            round(h.length, 3), round(h.stemming_length, 3),
                            round(h.charged_length, 3), *(round(v, 3) for v in split_charge(h, params)),
                            round(h.angle_deg, 2)])
    return path


def _level_dict(lv: LevelResult) -> dict:
    r = lv.ring
    return {"name": lv.spec.name, "kind": lv.spec.kind, "drift_position": lv.spec.position,
            "drift_centre": list(lv.spec.centre), "n_holes": lv.n_holes,
            "effective_spacing_left_m": r.lateral_spacing_eff, "effective_spacing_bottom_m": r.bottom_spacing_eff,
            "effective_spacing_right_m": r.right_spacing_eff, "effective_spacing_top_m": r.top_spacing_eff,
            "drilled_length_m": lv.drilled_length_m, "charged_length_m": lv.charged_length_m,
            "charge_kg": lv.charge_kg, "volume_m3": lv.volume_m3, "powder_factor_kg_m3": lv.powder_factor,
            "weighted_mean_size_cm": lv.weighted_mean_size_cm, "zones": [asdict(z) for z in lv.zones]}


def summary_dict(result: DesignResult, stope: StopeGeometry, rock: Rock, expl: Explosive,
                 p: DesignParams) -> dict:
    return {
        "inputs": {"rock": asdict(rock), "explosive": asdict(expl), "stope": asdict(stope),
                   "params": asdict(p)},
        "design": {"burden_m": result.burden_m, "spacing_m": result.spacing_m},
        "levels": [_level_dict(lv) for lv in result.levels],
        "stope_totals": {"n_levels": len(result.levels), "n_holes": result.n_holes,
                         "drilled_length_m": result.drilled_length_m,
                         "charged_length_m": result.charged_length_m, "charge_kg": result.charge_kg,
                         "volume_m3": result.volume_m3, "powder_factor_kg_m3": result.powder_factor,
                         "weighted_mean_size_cm": result.weighted_mean_size_cm},
        "warnings": result.warnings,
    }


def export_json(path, result, stope, rock, expl, p) -> Path:
    path = Path(path)
    path.write_text(json.dumps(summary_dict(result, stope, rock, expl, p), indent=2,
                               default=lambda o: None), encoding="utf-8")
    return path


# ------------------------------------------------------------------ plots / report
def _finish(fig):
    fig.set_facecolor(plotstyle.get().figure_bg)
    return fig


def _label_level(ax, stope: StopeGeometry, sp, fontsize: float, color: str | None = None) -> None:
    """Name of a level, centred vertically on its drift and placed just outside the stope (left drifts on the
    left, all the others on the right), on two lines so that it stays inside the wider plot range."""
    x0, y0, x1, y1 = sp.drift_rect
    left = sp.side == "left"
    text = sp.name.replace(" left", "\nleft").replace(" right", "\nright")
    if not sp.side:
        text = f"{sp.name}\n({sp.position})"
    x = min(-stope.width / 2, x0) - 0.8 if left else max(stope.width / 2, x1) + 0.8
    kw = {"color": color} if color else {}
    ax.text(x, (y0 + y1) / 2, text, fontsize=fontsize, ha="right" if left else "left", va="center",
            clip_on=False, **kw)


def _x_range(stope: StopeGeometry, specs=None) -> tuple[float, float]:
    """Horizontal plot range: the stope plus every drift (a drift may stick out of the stope outline) and a
    margin wide enough for the level labels."""
    from .geometry import level_specs
    specs = specs if specs is not None else level_specs(stope, 0.0)
    lo = min([-stope.width / 2] + [sp.drift_rect[0] for sp in specs])
    hi = max([stope.width / 2] + [sp.drift_rect[2] for sp in specs])
    m = max(12.0, 0.5 * (hi - lo))
    return lo - m, hi + m


def _level_list(result: DesignResult, level):
    """`level`: None (all), one 1-based level number, or several numbers (e.g. the left and right drift of a sublevel)."""
    if level is None:
        return list(result.levels)
    idx = [level] if isinstance(level, int) else list(level)
    return [result.levels[i - 1] for i in idx]


def _draw_layout(ax, stope: StopeGeometry, burden: float, st, alpha: float = 0.85, labels: bool = True) -> None:
    """Stope outline, blocks of every level, grey uncharged gaps and drift rectangles (shared by the layout
    drawing and the ring pattern, so that the charges are drawn over the same geometry)."""
    from matplotlib.patches import Polygon, Rectangle
    from .geometry import level_specs, uncharged_regions
    out = stope_outline(stope)
    ax.fill(*zip(*out), color=st.stope_fill, zorder=0)
    ax.plot(*zip(*(out + [out[0]])), color=st.stope_outline, lw=1.2 * st.line_width)
    specs = level_specs(stope, burden)
    for lv in specs:
        color = st.block_base if lv.kind == "base" else (st.block_sublevel_1 if lv.sublevel % 2 else st.block_sublevel_2)
        ax.fill(*zip(*lv.polygon), color=color, alpha=alpha, zorder=1)
    for poly in uncharged_regions(stope, burden):
        ax.add_patch(Polygon(poly, closed=True, fc=st.gap_color, ec="none", zorder=1.5))
    for lv in specs:
        x0, y0, x1, y1 = lv.drift_rect
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc=st.drift_fill, ec=st.drift_color,
                               lw=1.4 * st.line_width, zorder=3))
        if labels:
            ax.plot(*lv.centre, "+", color=st.drift_color, zorder=4)
            _label_level(ax, stope, lv, st.legend_size + 1)


def plot_stope_layout(stope: StopeGeometry, fig=None, burden: float = 0.0):
    """Drawing of the stope before any blast calculation: outline, hopper (trapezoidal base),
    sublevel blocks, drift positions and the uncharged gaps (grey)."""
    from matplotlib.figure import Figure
    st = plotstyle.get()
    with plotstyle.context():
        if fig is None:
            fig = Figure(figsize=(3.6, 5.0))
        fig.clear()
        ax = fig.add_subplot(111)
        _draw_layout(ax, stope, burden, st)
        ax.set_xlim(*_x_range(stope))
        ax.set_ylim(-2, stope.height + stope.roof_arch_rise_m + 3)
        ax.set_aspect("equal")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        ax.set_title(f"Stope layout: {stope.width:g} x {stope.height:g} m\n{stope.n_sublevels} sublevels"
                     + (" x 2 drifts" if stope.drifts_per_sublevel == 2 else "")
                     + (" + base" if stope.base_drift else ""))
    return _finish(fig)


def plot_pattern(result: DesignResult, stope: StopeGeometry, level=None, show_zones: bool = True,
                 params: DesignParams | None = None):
    """All levels (level=None) or one level (1-based, hole numbers shown).  show_zones=False omits the
    circles that bound the fragmentation zones.  With `params.booster` set, the booster at the toe of each
    hole is drawn in its own colour and thicker."""
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    st = plotstyle.get()
    levels = _level_list(result, level)
    with plotstyle.context():
        fig = Figure(figsize=(4.6, 6.4 if level is None else 5.2)); ax = fig.subplots()
        _draw_layout(ax, stope, result.burden_m, st, alpha=0.35, labels=False)      # the geometry, charges on top
        for lv in levels:
            for h in lv.ring.holes:
                if h.stemming_length > 1e-9:
                    ax.plot(*zip(h.collar, h.charge_start), color=st.stemming_color, lw=0.7 * st.line_width)
                bcl, _ccl = split_charge(h, params) if params is not None else (0.0, 0.0)
                col_end = _booster_start(h, bcl) if bcl > 0 else h.toe
                ax.plot(*zip(h.charge_start, col_end), color=st.charged_color, lw=0.9 * st.line_width)
                if bcl > 0:
                    ax.plot(*zip(col_end, h.toe), color=st.booster_color, lw=2.0 * st.line_width,
                            solid_capstyle="butt")
                if level is not None:
                    ax.annotate(str(h.index), h.toe, fontsize=st.tick_size - 2, xytext=(2, 2),
                                textcoords="offset points")
            for run in (_zone_arcs(lv) if show_zones else []):
                ax.plot(*zip(*run), color=st.zone_color, lw=0.6 * st.line_width)
            _label_level(ax, stope, lv.spec, st.legend_size, st.drift_color)
        ys = [p[1] for lv in levels for p in lv.spec.polygon] + [lv.spec.drift_rect[1] for lv in levels]
        ax.set_xlim(*_x_range(stope, [lv.spec for lv in result.levels]))
        ax.set_ylim(min(ys) - 2, max(ys) + 3)
        ax.set_aspect("equal")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        has_b = params is not None and params.booster is not None and params.booster_length_m > 0
        ax.set_title("Ring pattern (booster / charged / stemming-uncharged)" if has_b
                     else "Ring pattern (charged / stemming-uncharged)")
    return _finish(fig)


def stope_passing_curve(result: DesignResult, x):
    """Area-weighted Kuz-Ram passing curve (0-1) of the whole stope (or None if undefined)."""
    zs = [z for z in result.zones if not math.isnan(z.mean_size_cm)]
    tot = sum(z.area_m2 for z in zs)
    if not tot:
        return None
    return sum(z.area_m2 * passing_curve(x, z.characteristic_size_cm, z.uniformity_n) for z in zs) / tot


def _size_axis(ax, log_x: bool) -> None:
    """Size axis in cm: logarithmic with plain-number ticks (1, 2, 5, 10, ...) or linear."""
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter
    if log_x:
        ax.set_xscale("log")
        ax.set_xlim(0.5, 150)
        ticks = [0.5, 1, 2, 5, 10, 20, 50, 100]
        ax.xaxis.set_major_locator(FixedLocator(ticks))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.grid(True, which="both", alpha=0.25, lw=0.4)
    else:
        ax.set_xscale("linear")
        ax.set_xlim(0, 150)


def plot_fragmentation(result: DesignResult, level=None, log_x: bool = True):
    """One level: curve of each radial zone.  All levels: area-weighted curve of every level
    plus the whole-stope curve."""
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    st = plotstyle.get()
    x = np.geomspace(0.5, 150, 400) if log_x else np.linspace(0.5, 150, 400)

    def mix(zones):
        zs = [z for z in zones if not math.isnan(z.mean_size_cm)]
        tot = sum(z.area_m2 for z in zs)
        return sum(z.area_m2 * passing_curve(x, z.characteristic_size_cm, z.uniformity_n) for z in zs) / tot

    with plotstyle.context():
        fig = Figure(figsize=(5.2, 3.6)); ax = fig.subplots()
        group = _level_list(result, level) if level is not None and not isinstance(level, int) else None
        if group is not None:                                   # several levels (e.g. left + right drift of a sublevel)
            for lv, c in zip(group, plotstyle.palette_colors(len(group))):
                ax.plot(x, 100 * mix(lv.zones), color=c, label=lv.spec.name)
            ax.plot(x, 100 * mix([z for lv in group for z in lv.zones]), "--", lw=1.6 * st.line_width,
                    color=st.predicted_color, label="together")
        elif level is not None:
            zones = [z for z in result.levels[level - 1].zones if not math.isnan(z.mean_size_cm)]
            for z, c in zip(zones, plotstyle.palette_colors(len(zones))):
                ax.plot(x, 100 * passing_curve(x, z.characteristic_size_cm, z.uniformity_n), color=c,
                        label=f"zone {z.index}")
        else:
            for lv, c in zip(result.levels, plotstyle.palette_colors(len(result.levels))):
                ax.plot(x, 100 * mix(lv.zones), color=c, label=lv.spec.name)
            ax.plot(x, 100 * mix(result.zones), "--", lw=1.6 * st.line_width, color=st.predicted_color,
                    label="whole stope")
        ax.set_xlabel("size (cm)")
        ax.set_ylabel("passing (%)")
        ax.set_ylim(0, 100)
        _size_axis(ax, log_x)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(ncol=2)
        ax.set_title("Kuz-Ram fragmentation")
    return _finish(fig)


def plot_image_distributions(entries: list[dict], pooled_sizes=None, predicted=None, log_x: bool = True):
    """Measured size distributions of the muck-pile photos.

    entries: [{"name": str, "sizes_cm": array}], pooled_sizes: all fragments together,
    predicted: (x_cm, passing 0-1) of the Kuz-Ram design (optional)."""
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    from .imageanalysis import volume_weighted_curve
    st = plotstyle.get()
    with plotstyle.context():
        fig = Figure(figsize=(5.2, 3.8)); ax = fig.subplots()
        for e, c in zip(entries, plotstyle.palette_colors(len(entries))):
            d, p = volume_weighted_curve(e["sizes_cm"])
            if d.size:
                ax.plot(d, 100 * p, color=c, lw=0.9 * st.line_width, label=e["name"])
        if pooled_sizes is not None and len(pooled_sizes):
            d, p = volume_weighted_curve(pooled_sizes)
            ax.plot(d, 100 * p, color=st.measured_color, lw=2 * st.line_width, label="all photos")
        if predicted is not None:
            ax.plot(predicted[0], 100 * np.asarray(predicted[1]), "--", color=st.predicted_color,
                    lw=1.6 * st.line_width, label="Kuz-Ram (design)")
        ax.set_xlabel("size (cm)")
        ax.set_ylabel("passing, volume-weighted (%)")
        ax.set_ylim(0, 100)
        if log_x:
            _size_axis(ax, True)
            ax.set_xlim(0.5, 300)
        else:
            _size_axis(ax, False)
            ax.set_xlim(0, 150)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(ncol=2)
        ax.set_title("Measured fragmentation (photo analysis)")
    return _finish(fig)


def _png_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    return base64.b64encode(buf.getvalue()).decode()


def report_meta(project: str = "") -> str:
    """Line printed under the title of every report: project, program version, date and time."""
    from datetime import datetime
    from .about import NAME, VERSION
    parts = ([f"Project: {project}"] if project else []) + [f"{NAME} {VERSION}", f"{datetime.now():%Y-%m-%d %H:%M}"]
    return "  |  ".join(parts)


def export_report_html(path, result, stope, rock, expl, p, title="Blast design report", project: str = "") -> Path:
    s = summary_dict(result, stope, rock, expl, p)
    tot = s["stope_totals"]
    lrows = "".join(
        f"<tr><td style='text-align:left'>{l['name']}</td><td>{l['drift_position']}</td><td>{l['n_holes']}</td>"
        f"<td>{l['drilled_length_m']:.1f}</td><td>{l['charge_kg']:.0f}</td><td>{l['volume_m3']:.0f}</td>"
        f"<td>{l['powder_factor_kg_m3']:.2f}</td><td>{l['weighted_mean_size_cm']:.1f}</td></tr>"
        for l in s["levels"])
    details = ""
    for lv in result.levels:
        zrows = "".join(
            f"<tr><td>{z.index}</td><td>{z.r_in:.1f}-{z.r_out:.1f}</td><td>{z.area_m2:.1f}</td>"
            f"<td>{z.charged_length_m:.1f}</td><td>{z.charge_kg:.0f}</td><td>{z.powder_factor:.2f}</td>"
            f"<td>{z.mean_size_cm:.1f}</td><td>{z.uniformity_n:.2f}</td></tr>" for z in lv.zones)
        hrows = "".join(
            f"<tr><td>{h.index}</td><td>{h.kind}</td><td>{h.length:.2f}</td><td>{h.stemming_length:.2f}</td>"
            f"<td>{h.charged_length:.2f}</td></tr>" for h in lv.ring.holes)
        details += (f"<h2>{lv.spec.name}</h2><div class='f'><img src='data:image/png;base64,"
                    f"{_png_b64(plot_pattern(result, stope, lv.spec.index, params=p))}' height='360'>"
                    f"<img src='data:image/png;base64,{_png_b64(plot_fragmentation(result, lv.spec.index))}' height='260'></div>"
                    "<h3>Fragmentation zones</h3><table><tr><th>Zone</th><th>r (m)</th><th>Area (m2)</th>"
                    "<th>Charged (m)</th><th>Charge (kg)</th><th>PF (kg/m3)</th><th>X50 (cm)</th><th>n</th></tr>"
                    f"{zrows}</table><h3>Holes</h3><table><tr><th>#</th><th>Kind</th><th>Length (m)</th>"
                    f"<th>Stemming (m)</th><th>Charged (m)</th></tr>{hrows}</table>")
    warn = "".join(f"<li>{w}</li>" for w in result.warnings) or "<li>none</li>"
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{_html.escape(title)}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;max-width:900px;margin:2em auto;color:#222}}
table{{border-collapse:collapse;margin:1em 0}}td,th{{border:1px solid #bbb;padding:3px 9px;text-align:right}}
th{{background:#eee}}h2{{border-bottom:2px solid #2a6;padding-bottom:3px;page-break-before:always}}
.f{{display:flex;gap:1em}}.meta{{color:#555;margin-top:-0.6em}}</style></head><body><h1>{title}</h1>
<p class="meta">{_html.escape(report_meta(project))}</p>
<h2 style="page-break-before:avoid">Inputs</h2><p>Rock: <b>{rock.name}</b> &middot; Explosive: <b>{expl.name}</b> &middot;
hole diameter {p.hole_diameter_mm:g} mm &middot; stope {stope.width:g} x {stope.height:g} m,
{stope.n_sublevels} sublevels{' + base drift' if stope.base_drift else ''}, drift {stope.drift_width:g} x {stope.drift_height:g} m &middot;
burden method <b>{p.burden_method}</b>, S/B = {p.sb_ratio:g}</p>
<table><tr><th>Burden (m)</th><td>{s['design']['burden_m']:.2f}</td><th>Nominal spacing (m)</th><td>{s['design']['spacing_m']:.2f}</td></tr></table>
<h2 style="page-break-before:avoid">Results by level</h2><table><tr><th>Level</th><th>Drift</th><th>Holes</th><th>Drilled (m)</th>
<th>Explosive (kg)</th><th>Volume (m3)</th><th>PF (kg/m3)</th><th>Mean size (cm)</th></tr>{lrows}
<tr><th style='text-align:left'>Total</th><td></td><th>{tot['n_holes']}</th><th>{tot['drilled_length_m']:.1f}</th>
<th>{tot['charge_kg']:.0f}</th><th>{tot['volume_m3']:.0f}</th><th>{tot['powder_factor_kg_m3']:.2f}</th>
<th>{tot['weighted_mean_size_cm']:.1f}</th></tr></table>
<div class="f"><img src="data:image/png;base64,{_png_b64(plot_pattern(result, stope, params=p))}" height="470">
<img src="data:image/png;base64,{_png_b64(plot_fragmentation(result))}" height="260"></div>
{details}<h2>Warnings</h2><ul>{warn}</ul></body></html>"""
    path = Path(path)
    path.write_text(html, encoding="utf-8")
    return path


def export_report_docx(path, result: DesignResult, stope: StopeGeometry, rock: Rock, expl: Explosive,
                       p: DesignParams, title: str = "Blast design report", project: str = "") -> Path:
    """Word (.docx) version of the design report: inputs, results by level, ring pattern and
    fragmentation plots, zone and hole tables, warnings.  Needs the python-docx package."""
    from docx import Document
    from docx.shared import Cm, Pt
    s = summary_dict(result, stope, rock, expl, p)
    tot = s["stope_totals"]
    doc = Document()
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = Cm(2)
        sec.top_margin = sec.bottom_margin = Cm(2)
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(10)

    def table(rows, head):
        t = doc.add_table(rows=0, cols=len(head))
        t.style = "Table Grid"
        cells = t.add_row().cells
        for c, h in zip(cells, head):
            c.text = ""
            c.paragraphs[0].add_run(str(h)).bold = True
        for row in rows:
            for c, v in zip(t.add_row().cells, row):
                c.text = str(v)
        for row in t.rows:
            for c in row.cells:
                for par in c.paragraphs:
                    for run in par.runs:
                        run.font.size = Pt(9)
        doc.add_paragraph()

    def figure(fig, width_cm):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        doc.add_picture(buf, width=Cm(width_cm))

    doc.add_heading(title, 0)
    doc.add_paragraph(report_meta(project))
    doc.add_heading("Inputs", 1)
    drifts = (f"{stope.drifts_per_sublevel} drift(s) per sublevel"
              + (f", wall distance {stope.drift_wall_distance_m:g} m" if stope.drifts_per_sublevel == 2
                 and stope.twin_position == "sides" else "")
              + (f", gap between the drifts {stope.twin_gap_m:g} m" if stope.drifts_per_sublevel == 2
                 and stope.twin_position == "gap" else ""))
    table([["Rock", rock.name], ["Explosive", expl.name],
           ["Booster", p.booster.name if p.booster else "none"],
           ["Hole diameter (mm)", f"{p.hole_diameter_mm:g}"],
           ["Stope (width x height, m)", f"{stope.width:g} x {stope.height:g}"],
           ["Sublevels", f"{stope.n_sublevels}" + (" + base drift" if stope.base_drift else "")],
           ["Drift (width x height, m)", f"{stope.drift_width:g} x {stope.drift_height:g}"],
           ["Drifts", drifts], ["Burden method", p.burden_method], ["S/B ratio", f"{p.sb_ratio:g}"],
           ["Burden (m)", f"{s['design']['burden_m']:.2f}"],
           ["Nominal spacing (m)", f"{s['design']['spacing_m']:.2f}"]], ["Input", "Value"])
    doc.add_heading("Results by level", 1)
    rows = [[l["name"], l["drift_position"], l["n_holes"], f"{l['drilled_length_m']:.1f}", f"{l['charge_kg']:.0f}",
             f"{l['volume_m3']:.0f}", f"{l['powder_factor_kg_m3']:.2f}", f"{l['weighted_mean_size_cm']:.1f}"]
            for l in s["levels"]]
    rows.append(["Total", "", tot["n_holes"], f"{tot['drilled_length_m']:.1f}", f"{tot['charge_kg']:.0f}",
                 f"{tot['volume_m3']:.0f}", f"{tot['powder_factor_kg_m3']:.2f}", f"{tot['weighted_mean_size_cm']:.1f}"])
    table(rows, ["Level", "Drift", "Holes", "Drilled (m)", "Explosive (kg)", "Volume (m3)", "PF (kg/m3)", "Mean size (cm)"])
    figure(plot_pattern(result, stope, params=p), 8)
    figure(plot_fragmentation(result), 13)
    for lv in result.levels:
        doc.add_page_break()
        doc.add_heading(lv.spec.name, 1)
        figure(plot_pattern(result, stope, lv.spec.index, params=p), 7)
        figure(plot_fragmentation(result, lv.spec.index), 12)
        doc.add_heading("Fragmentation zones", 2)
        table([[z.index, f"{z.r_in:.1f}-{z.r_out:.1f}", f"{z.area_m2:.1f}", f"{z.charged_length_m:.1f}",
                f"{z.charge_kg:.0f}", f"{z.powder_factor:.2f}", f"{z.mean_size_cm:.1f}", f"{z.uniformity_n:.2f}"]
               for z in lv.zones],
              ["Zone", "r (m)", "Area (m2)", "Charged (m)", "Charge (kg)", "PF (kg/m3)", "X50 (cm)", "n"])
        doc.add_heading("Holes", 2)
        table([[h.index, h.kind, f"{h.length:.2f}", f"{h.stemming_length:.2f}", f"{h.charged_length:.2f}"]
               for h in lv.ring.holes], ["#", "Kind", "Length (m)", "Stemming (m)", "Charged (m)"])
    doc.add_heading("Warnings", 1)
    for w in (result.warnings or ["none"]):
        doc.add_paragraph(w, style="List Bullet")
    path = Path(path)
    doc.save(str(path))
    return path
