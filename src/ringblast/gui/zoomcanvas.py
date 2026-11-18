"""Matplotlib canvas with mouse-wheel zoom (used for all the plots of the program).

Wheel over a plot: zoom in/out around the cursor (the point under the cursor stays where it is).
Left-button drag: move the zoomed plot.  Double-click: back to the whole plot.
Zooming out never goes beyond the original view.  Log axes are zoomed in log space."""
from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

STEP = 1.25          # zoom factor of one wheel notch
MAX_IN = 60.0        # largest zoom (original range / current range)


class ZoomCanvas(FigureCanvasQTAgg):
    def __init__(self, fig) -> None:
        super().__init__(fig)
        self._panning = None
        self.mpl_connect("scroll_event", self._scroll)
        self.mpl_connect("button_press_event", self._press)
        self.mpl_connect("motion_notify_event", self._move)
        self.mpl_connect("button_release_event", self._release)

    def wheelEvent(self, ev):
        super().wheelEvent(ev)
        ev.accept()                       # the wheel is for the plot: do not also scroll the page behind it

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _home(ax):
        if not hasattr(ax, "_rb_home"):
            ax._rb_home = (ax.get_xlim(), ax.get_ylim())
        return ax._rb_home

    @staticmethod
    def _zoomed_axis(lim, home, centre, f, log: bool):
        t = (lambda v: np.log10(v)) if log else (lambda v: v)
        u = (lambda v: 10.0 ** v) if log else (lambda v: v)
        lo, hi, c = t(lim[0]), t(lim[1]), t(centre)
        h0, h1 = t(home[0]), t(home[1])
        new_lo, new_hi = c - (c - lo) * f, c + (hi - c) * f
        span, hspan = abs(new_hi - new_lo), abs(h1 - h0)
        if span >= hspan:                                   # zoomed out as far as the original view
            return home
        if span < hspan / MAX_IN:
            return lim
        return u(new_lo), u(new_hi)

    def _scroll(self, ev):
        ax = ev.inaxes
        if ax is None or ev.xdata is None or ev.ydata is None:
            return
        f = STEP ** (-ev.step)                              # wheel forward: zoom in
        hx, hy = self._home(ax)
        ax.set_xlim(self._zoomed_axis(ax.get_xlim(), hx, ev.xdata, f, ax.get_xscale() == "log"))
        ax.set_ylim(self._zoomed_axis(ax.get_ylim(), hy, ev.ydata, f, ax.get_yscale() == "log"))
        self.draw_idle()

    def _is_zoomed(self, ax) -> bool:
        if not hasattr(ax, "_rb_home"):
            return False
        hx, hy = ax._rb_home
        return not (np.allclose(ax.get_xlim(), hx) and np.allclose(ax.get_ylim(), hy))

    def _press(self, ev):
        ax = ev.inaxes
        if ax is None or ev.button != 1:
            return
        if ev.dblclick:                                     # back to the whole plot
            if hasattr(ax, "_rb_home"):
                ax.set_xlim(ax._rb_home[0])
                ax.set_ylim(ax._rb_home[1])
                self.draw_idle()
            return
        if self._is_zoomed(ax):
            ax.start_pan(ev.x, ev.y, 1)
            self._panning = ax

    def _move(self, ev):
        if self._panning is not None:
            self._panning.drag_pan(1, None, ev.x, ev.y)
            self.draw_idle()

    def _release(self, ev):
        if self._panning is not None:
            self._panning.end_pan()
            self._panning = None
