"""Appearance of all plots (colours, background, fonts, sizes).

One global `PlotStyle` is used by every plot function; the Settings tab of the GUI edits it.
It is stored in ~/.ringblast/plot_style.json so it persists between sessions.
"""
from __future__ import annotations

from . import paths

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from pathlib import Path

STYLE_FILE = paths.user_dir() / "plot_style.json"
PALETTES = ["tab10", "Set1", "Dark2", "viridis", "plasma", "cividis", "coolwarm"]


@dataclass
class PlotStyle:
    # background and text
    figure_bg: str = "#ffffff"
    axes_bg: str = "#ffffff"
    text_color: str = "#222222"
    axes_color: str = "#222222"
    grid: bool = True
    grid_color: str = "#cccccc"
    # fonts
    font_family: str = "DejaVu Sans"
    font_size: float = 9.0
    title_size: float = 10.0
    label_size: float = 9.0
    tick_size: float = 8.0
    legend_size: float = 7.0
    line_width: float = 1.0
    # stope drawing
    stope_outline: str = "#000000"
    stope_fill: str = "#eeeeee"
    drift_color: str = "#1f77b4"
    drift_fill: str = "#ffffff"
    block_sublevel_1: str = "#cfe3f6"
    block_sublevel_2: str = "#f6e3cf"
    block_base: str = "#d9efd2"
    # blast pattern
    charged_color: str = "#d62728"
    stemming_color: str = "#999999"
    booster_color: str = "#1f77b4"      # bottom charge (booster), drawn thicker
    zone_color: str = "#2ca02c"
    # curves
    palette: str = "tab10"
    predicted_color: str = "#000000"
    measured_color: str = "#d62728"


PRESETS = {
    "Default": PlotStyle(),
    "Dark": PlotStyle(figure_bg="#1e1f22", axes_bg="#2b2d30", text_color="#e6e6e6", axes_color="#cccccc",
                      grid_color="#444444", stope_outline="#e6e6e6", stope_fill="#33363a",
                      drift_color="#5cb3ff", drift_fill="#1e1f22", block_sublevel_1="#2f4a63",
                      block_sublevel_2="#5e4a33", block_base="#35563a", charged_color="#ff6b6b",
                      stemming_color="#888888", booster_color="#5cb3ff", zone_color="#6fd36f", palette="Set1",
                      predicted_color="#ffffff", measured_color="#ff6b6b"),
    "Publication": PlotStyle(font_family="DejaVu Serif", font_size=10, title_size=11, label_size=10,
                             tick_size=9, legend_size=8, line_width=1.2, grid=False,
                             stope_fill="#f4f4f4", block_sublevel_1="#e6e6e6", block_sublevel_2="#f6f6f6",
                             block_base="#d0d0d0", drift_color="#000000", charged_color="#000000",
                             stemming_color="#888888", booster_color="#000000", zone_color="#555555", palette="Dark2",
                             measured_color="#000000"),
}

_current = PlotStyle()


def get() -> PlotStyle:
    return _current


def set_style(style: PlotStyle) -> None:
    global _current
    _current = style


def defaults() -> PlotStyle:
    return PlotStyle()


def from_dict(d: dict) -> PlotStyle:
    names = {f.name for f in fields(PlotStyle)}
    return PlotStyle(**{k: v for k, v in d.items() if k in names})


def save(style: PlotStyle | None = None, path: Path | None = None) -> None:
    path = path or STYLE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(style or _current), indent=2), encoding="utf-8")


def load(path: Path | None = None) -> PlotStyle:
    """Load the saved style (if any) and make it the current one."""
    path = path or STYLE_FILE
    try:
        set_style(from_dict(json.loads(path.read_text(encoding="utf-8"))))
    except (OSError, ValueError, TypeError):
        set_style(PlotStyle())
    return _current


def rc(style: PlotStyle | None = None) -> dict:
    s = style or _current
    return {
        "figure.facecolor": s.figure_bg, "savefig.facecolor": s.figure_bg, "axes.facecolor": s.axes_bg,
        "text.color": s.text_color, "axes.edgecolor": s.axes_color, "axes.labelcolor": s.text_color,
        "xtick.color": s.axes_color, "ytick.color": s.axes_color, "axes.grid": s.grid,
        "grid.color": s.grid_color, "font.family": s.font_family, "font.size": s.font_size,
        "axes.titlesize": s.title_size, "axes.labelsize": s.label_size, "xtick.labelsize": s.tick_size,
        "ytick.labelsize": s.tick_size, "legend.fontsize": s.legend_size, "lines.linewidth": s.line_width,
        "legend.facecolor": s.axes_bg, "legend.edgecolor": s.axes_color,
    }


@contextmanager
def context(style: PlotStyle | None = None):
    import matplotlib
    with matplotlib.rc_context(rc(style)):
        yield style or _current


def palette_colors(n: int, style: PlotStyle | None = None) -> list:
    import matplotlib
    cmap = matplotlib.colormaps[(style or _current).palette]
    if getattr(cmap, "N", 256) <= 12:                      # qualitative map: cycle its colours
        return [cmap(i % cmap.N) for i in range(n)]
    return [cmap(i / max(1, n - 1)) for i in range(n)]    # continuous map: spread


def available_fonts() -> list[str]:
    from matplotlib import font_manager
    return sorted({f.name for f in font_manager.fontManager.ttflist})
