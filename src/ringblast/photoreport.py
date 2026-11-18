"""Report of a set of muck-pile photo analyses (HTML or PDF).

For every analysed photo: the photo with the area of interest outlined, the analysed area with the
outlined fragments and a scale bar, the settings used, the size statistics and the size distribution.
Then the pooled distribution of the whole set.  The settings that are the same for all photos are
shown once; if they differ, they are listed photo by photo.

`build(...)` returns an HTML text whose images are referenced by name together with a dict
{name: PNG bytes}; `write_html` embeds them in one self-contained file (the GUI prints the same HTML
to PDF).
"""
from __future__ import annotations

import base64
import html
import io
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import imageanalysis as ia
from .about import NAME, VERSION

PCTS = (10, 20, 50, 80, 90)
SEG_LABELS = {
    "contrast": "Local contrast (CLAHE)", "gamma": "Gamma", "smoothing": "Smoothing",
    "threshold_mode": "Threshold mode", "threshold_shift": "Threshold shift", "fixed_level": "Fixed grey level",
    "window": "Adaptive window", "invert": "Fragments darker than gaps", "erode_iter": "Erosion iterations",
    "open_iter": "Opening iterations", "close_iter": "Closing iterations",
    "max_fragment_fraction": "Largest region (fraction of image)",
    "min_size_cm": "Smallest fragment (cm)", "sensitivity": "Sensitivity",
}


def _png(img: np.ndarray, max_w: int = 1400) -> bytes:
    import cv2
    h, w = img.shape[:2]
    if w > max_w:
        img = cv2.resize(img, (max_w, round(h * max_w / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def _fig_png(fig) -> bytes:
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=130, bbox_inches="tight")
    return b.getvalue()


def _fmt(v, nd=1) -> str:
    try:
        return "-" if v is None or not np.isfinite(float(v)) else f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return html.escape(str(v))


def settings_of(r) -> dict:
    """Segmentation settings used for the results of one photo (the stored ones, else the current ones)."""
    src = r.analysed_with or {**ia.SEG_DEFAULTS, **r.seg, "min_size_cm": r.min_size_cm, "sensitivity": r.sensitivity}
    return {k: src.get(k, ia.SEG_DEFAULTS.get(k)) for k in SEG_LABELS}


def _table(rows, head=None) -> str:
    h = "".join(f"<th>{html.escape(str(x))}</th>" for x in head) if head else ""
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table border='1' cellspacing='0' cellpadding='4'>{'<tr>' + h + '</tr>' if h else ''}{body}</table>"


def build(records: list, results: dict, load_image: Callable, predicted: Optional[tuple] = None,
          log_x: bool = True, title: str = "Muck-pile photo analysis", img_w: int = 640) -> tuple[str, dict]:
    from .export import plot_image_distributions
    imgs: dict[str, bytes] = {}
    done = [r for r in records if r.path in results]
    parts = [f"<h1>{html.escape(title)}</h1>",
             f"<p>{NAME} {VERSION} &middot; {datetime.now():%Y-%m-%d %H:%M} &middot; "
             f"{len(done)} analysed photo(s) of {len(records)}.</p>"]

    # ---- settings
    sets = [settings_of(r) for r in done]
    same = len({tuple(sorted((k, str(v)) for k, v in s.items())) for s in sets}) <= 1
    parts.append("<h2>Settings</h2>")
    if done and same:
        parts.append("<p>The segmentation settings are the same for all photos:</p>")
        parts.append(_table([[SEG_LABELS[k], html.escape(str(v))] for k, v in sets[0].items()]))
    elif done:
        parts.append("<p>The segmentation settings differ between photos; they are listed with each photo.</p>")
    parts.append("<p>Image scale and area of interest are set for each photo:</p>")
    parts.append(_table([[html.escape(r.name), html.escape(r.date), html.escape(r.location),
                          _fmt(r.analysed_with.get("scale_px_per_cm", r.scale_px_per_cm), 3),
                          ("%d x %d px" % (abs(roi[2] - roi[0]), abs(roi[3] - roi[1])) if len(roi := (r.analysed_with.get("roi") or r.roi)) == 4
                           else "whole photo")] for r in done],
                        ["Photo", "Date", "Location", "Scale (px/cm)", "Analysed area"]))

    # ---- one section per photo
    for i, r in enumerate(done, 1):
        res = results[r.path]
        parts.append(f"<h2 style='page-break-before:always'>{i}. {html.escape(r.name)}</h2>")
        meta = " &middot; ".join(x for x in (html.escape(r.date), html.escape(r.location)) if x)
        if meta:
            parts.append(f"<p>{meta}</p>")
        if r.notes:
            parts.append(f"<p><i>{html.escape(r.notes)}</i></p>")
        roi = r.analysed_with.get("roi") or []
        raw = load_image(r)
        if raw is not None and len(roi) == 4:
            import cv2
            ov = raw.copy()
            x0, y0, x1, y1 = [int(v) for v in roi]
            cv2.rectangle(ov, (x0, y0), (x1, y1), (255, 229, 0), max(3, raw.shape[1] // 200))
            imgs[f"ov{i}"] = _png(ov, 900)
            parts.append(f"<p>Photo and area of interest (cyan):</p><p><img src='ov{i}' width='{img_w // 2}'></p>")
        if res.overlay is not None:
            imgs[f"fr{i}"] = _png(ia.add_scale_bar(res.overlay, res.overlay_px_per_cm))
            parts.append(f"<p>Analysed area with the outlined fragments:</p><p><img src='fr{i}' width='{img_w}'></p>")
        else:
            parts.append("<p><i>Outlined image not available (analyse the photo again to include it).</i></p>")
        if not same:
            parts.append(_table([[SEG_LABELS[k], html.escape(str(v))] for k, v in settings_of(r).items()],
                                ["Setting", "Value"]))
        parts.append(_table([[res.n_fragments, *[_fmt(res.percentiles_cm.get(p)) for p in PCTS], _fmt(res.dmax_cm),
                              _fmt(res.rr_n, 2), _fmt(res.rr_xc_cm), f"{100 * res.unresolved_area_fraction:.0f} %"]],
                            ["n", *[f"D{p} (cm)" for p in PCTS], "Dmax (cm)", "RR n", "RR xc (cm)", "Unresolved area"]))
        fig = plot_image_distributions([{"name": r.name, "sizes_cm": res.sizes_cm}], None, None, log_x)
        imgs[f"cu{i}"] = _fig_png(fig)
        parts.append(f"<p><img src='cu{i}' width='{int(img_w * 0.8)}'></p>")

    # ---- all photos together
    if done:
        pooled = ia.combine([results[r.path] for r in done])
        parts.append("<h2 style='page-break-before:always'>All photos together</h2>")
        rows = [[html.escape(r.name), results[r.path].n_fragments,
                 *[_fmt(results[r.path].percentiles_cm.get(p)) for p in PCTS], _fmt(results[r.path].dmax_cm)] for r in done]
        rows.append(["<b>All photos</b>", pooled["n_fragments"],
                     *[_fmt(pooled["percentiles_cm"].get(p)) for p in PCTS], _fmt(pooled["dmax_cm"])])
        parts.append(_table(rows, ["Photo", "n", *[f"D{p} (cm)" for p in PCTS], "Dmax (cm)"]))
        entries = [{"name": r.name, "sizes_cm": results[r.path].sizes_cm} for r in done]
        fig = plot_image_distributions(entries, pooled["sizes_cm"], predicted, log_x)
        imgs["all"] = _fig_png(fig)
        parts.append(f"<p><img src='all' width='{int(img_w * 0.9)}'></p>")
        parts.append("<p><small>Sizes are equivalent diameters of the visible fragments, volume-weighted; "
                     "the photographed surface may not represent the whole muck pile. Check against sieving.</small></p>")
    else:
        parts.append("<p><i>No photo has been analysed yet.</i></p>")
    return "\n".join(parts), imgs


def write_docx(path, records: list, results: dict, load_image: Callable, predicted: Optional[tuple] = None,
               log_x: bool = True, title: str = "Muck-pile photo analysis") -> Path:
    """Word (.docx) version of the report: same content as the HTML report, editable in Word.
    Needs the python-docx package."""
    import cv2
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Cm, Pt
    from .export import plot_image_distributions

    doc = Document()
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = Cm(2)
        sec.top_margin = sec.bottom_margin = Cm(2)
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(10)

    def table(rows, head=None):
        t = doc.add_table(rows=0, cols=len(head) if head else len(rows[0]))
        t.style = "Table Grid"
        if head:
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

    def picture(data: bytes, width_cm: float):
        doc.add_picture(io.BytesIO(data), width=Cm(width_cm))

    done = [r for r in records if r.path in results]
    doc.add_heading(title, 0)
    doc.add_paragraph(f"{NAME} {VERSION}  |  {datetime.now():%Y-%m-%d %H:%M}  |  "
                      f"{len(done)} analysed photo(s) of {len(records)}")
    sets = [settings_of(r) for r in done]
    same = len({tuple(sorted((k, str(v)) for k, v in s.items())) for s in sets}) <= 1
    doc.add_heading("Settings", 1)
    if done and same:
        doc.add_paragraph("The segmentation settings are the same for all photos:")
        table([[SEG_LABELS[k], v] for k, v in sets[0].items()], ["Setting", "Value"])
    elif done:
        doc.add_paragraph("The segmentation settings differ between photos; they are listed with each photo.")
    doc.add_paragraph("Image scale and area of interest are set for each photo:")
    rows = []
    for r in done:
        roi = r.analysed_with.get("roi") or r.roi
        rows.append([r.name, r.date, r.location, _fmt(r.analysed_with.get("scale_px_per_cm", r.scale_px_per_cm), 3),
                     f"{abs(roi[2] - roi[0])} x {abs(roi[3] - roi[1])} px" if len(roi) == 4 else "whole photo"])
    table(rows, ["Photo", "Date", "Location", "Scale (px/cm)", "Analysed area"])

    for i, r in enumerate(done, 1):
        res = results[r.path]
        doc.add_page_break()
        doc.add_heading(f"{i}. {r.name}", 1)
        meta = "  |  ".join(x for x in (r.date, r.location) if x)
        if meta:
            doc.add_paragraph(meta)
        if r.notes:
            doc.add_paragraph(r.notes).italic = True
        roi = r.analysed_with.get("roi") or []
        raw = load_image(r)
        if raw is not None and len(roi) == 4:
            ov = raw.copy()
            x0, y0, x1, y1 = [int(v) for v in roi]
            cv2.rectangle(ov, (x0, y0), (x1, y1), (255, 229, 0), max(3, raw.shape[1] // 200))
            doc.add_paragraph("Photo and area of interest (cyan):")
            picture(_png(ov, 900), 7)
        if res.overlay is not None:
            doc.add_paragraph("Analysed area with the outlined fragments:")
            picture(_png(ia.add_scale_bar(res.overlay, res.overlay_px_per_cm)), 13)
        else:
            doc.add_paragraph("Outlined image not available (analyse the photo again to include it).")
        if not same:
            table([[SEG_LABELS[k], v] for k, v in settings_of(r).items()], ["Setting", "Value"])
        table([[res.n_fragments, *[_fmt(res.percentiles_cm.get(p)) for p in PCTS], _fmt(res.dmax_cm),
                _fmt(res.rr_n, 2), _fmt(res.rr_xc_cm), f"{100 * res.unresolved_area_fraction:.0f} %"]],
              ["n", *[f"D{p} (cm)" for p in PCTS], "Dmax (cm)", "RR n", "RR xc (cm)", "Unresolved area"])
        picture(_fig_png(plot_image_distributions([{"name": r.name, "sizes_cm": res.sizes_cm}], None, None, log_x)), 9)

    if done:
        pooled = ia.combine([results[r.path] for r in done])
        doc.add_page_break()
        doc.add_heading("All photos together", 1)
        rows = [[r.name, results[r.path].n_fragments, *[_fmt(results[r.path].percentiles_cm.get(p)) for p in PCTS],
                 _fmt(results[r.path].dmax_cm)] for r in done]
        rows.append(["All photos", pooled["n_fragments"], *[_fmt(pooled["percentiles_cm"].get(p)) for p in PCTS],
                     _fmt(pooled["dmax_cm"])])
        table(rows, ["Photo", "n", *[f"D{p} (cm)" for p in PCTS], "Dmax (cm)"])
        entries = [{"name": r.name, "sizes_cm": results[r.path].sizes_cm} for r in done]
        picture(_fig_png(plot_image_distributions(entries, pooled["sizes_cm"], predicted, log_x)), 14)
        doc.add_paragraph("Sizes are equivalent diameters of the visible fragments, volume-weighted; the photographed "
                          "surface may not represent the whole muck pile. Check against sieving.").runs[0].font.size = Pt(8)
    else:
        doc.add_paragraph("No photo has been analysed yet.")
    path = Path(path)
    doc.save(str(path))
    return path


CSS = ("body{font-family:Arial,Helvetica,sans-serif;font-size:10pt;margin:24px auto;max-width:900px;color:#222}"
       "h1{color:#16304f}h2{color:#16304f;border-bottom:2px solid #f0a020;padding-top:10px}"
       "table{border-collapse:collapse;margin:6px 0}th{background:#eef2f7}td,th{border:1px solid #c9d2de;padding:3px 8px;text-align:right}"
       "td:first-child,th:first-child{text-align:left}img{max-width:100%}")


def write_html(path, body: str, imgs: dict, title: str = "RingBlast photo report") -> Path:
    """Self-contained HTML file (images embedded)."""
    for name, data in imgs.items():
        body = body.replace(f"src='{name}'", f"src='data:image/png;base64,{base64.b64encode(data).decode()}'")
    path = Path(path)
    path.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
                    f"<style>{CSS}</style></head><body>{body}</body></html>", encoding="utf-8")
    return path
