"""Project files: all the inputs of a blast design, the rock/explosive rows used (and every
user-modified row, so the project opens identically on another machine) and the photo records.

A project is ONE file (extension .ringblast): a zip container holding project.json (inputs,
database rows, photo records), a copy of every photo (images/NNN/<name>) and the measured
fragment sizes of every analysed photo (results/NNN.json).  It can be copied to another computer
and opened there with everything inside.  Plain-JSON projects of earlier versions still open
(their photos are found by path).  When a project is opened its photos are extracted to
<user folder>/project_images/<project id>/.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
import zipfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Optional

FORMAT = "ringblast-project"
VERSION = 1
EXTENSION = ".ringblast"

# One place for every default value of the GUI inputs (also used by the Reset button)
DEFAULT_INPUTS = {
    "rock": "Limestone", "explosive": "anfo77", "burden_method": "langefors_kihlstrom",
    "drift_position": "center", "base_drift": True,
    "width": 25.0, "height": 80.0, "n_sub": 2, "dw": 5.0, "dh": 5.0, "angle": 55.0,
    "drifts": 1, "twin_position": "sides", "show_zones": True, "log_x": True, "booster": "", "bcl": 0.5,
    "drift_vertical": "top", "dtop": 0.0, "arch": 0.0,
    "wd": 0.0, "gap": 5.0, "vg": 2.0, "hg": 1.0, "d": 80.0, "sb": 1.25, "f": 0.65, "c": 0.8, "A": 10.0, "zone": 5.0, "manual": 0.0,
}


@dataclass
class ImageRecord:
    """One muck-pile photograph with the information needed to trace it back to the site."""
    path: str
    date: str = ""                      # date of the photo / site visit, YYYY-MM-DD
    location: str = ""                  # where it was taken (level, ring, position in the pile ...)
    notes: str = ""
    scale_px_per_cm: Optional[float] = None
    scale_points: list = field(default_factory=list)      # two (x, y) pixel points of the reference
    scale_length_cm: Optional[float] = None               # real length between those points
    roi: list = field(default_factory=list)              # area of interest [x0, y0, x1, y1] in photo pixels; empty = whole photo
    min_size_cm: float = 3.0
    sensitivity: float = 0.5
    seg: dict = field(default_factory=dict)       # segmentation options (see imageanalysis.SEG_DEFAULTS)
    analysed_with: dict = field(default_factory=dict)   # all parameters used for the stored results
    summary: dict = field(default_factory=dict)           # last analysis results (D10, D50, n ...)

    @property
    def name(self) -> str:
        return Path(self.path).name


def _seg_defaults() -> dict:
    from .imageanalysis import SEG_DEFAULTS
    return dict(SEG_DEFAULTS)


def _rel(path: str, base: Path) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:                  # different drive on Windows
        return ""


def image_cache_dir(project_id: str) -> Path:
    from . import db
    return db.USER_DIR / "project_images" / project_id


def new_project_id() -> str:
    return uuid.uuid4().hex[:12]


def save_project(path, name: str, notes: str, inputs: dict, images: list[ImageRecord],
                 database: dict | None = None, fragment_sizes: list | None = None,
                 project_id: str | None = None) -> tuple[Path, list[str]]:
    """Write the project file.  Returns (path, warnings); a photo whose file cannot be found is
    kept as a record but cannot be embedded (reported in the warnings)."""
    path = Path(path)
    warnings: list[str] = []
    project_id = project_id or new_project_id()
    sizes = fragment_sizes or [None] * len(images)
    imgs, payload = [], []
    for i, r in enumerate(images):
        d = asdict(r)
        d["seg"] = {**_seg_defaults(), **r.seg}               # always store every segmentation parameter
        src = Path(r.path)
        if src.is_file():
            d["embedded"] = f"images/{i:03d}/{src.name}"
            payload.append((src, d["embedded"]))
        else:
            d["embedded"] = ""
            warnings.append(f"{src.name}: file not found, the photo could not be stored in the project")
        d["results"] = ""
        if sizes[i] is not None and len(sizes[i]):
            d["results"] = f"results/{i:03d}.json"
        imgs.append(d)
    doc = {"format": FORMAT, "version": VERSION, "project_id": project_id, "name": name, "notes": notes,
           "saved_at": datetime.now().isoformat(timespec="seconds"), "inputs": inputs,
           "database": database or {}, "images": imgs}
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w") as z:
        z.writestr("project.json", json.dumps(doc, indent=2, ensure_ascii=False, default=float),
                   compress_type=zipfile.ZIP_DEFLATED)
        for src, arc in payload:
            z.write(src, arc, compress_type=zipfile.ZIP_STORED)       # photos are already compressed
        for d, sz in zip(imgs, sizes):
            if d["results"]:
                z.writestr(d["results"], json.dumps([round(float(v), 4) for v in sz]),
                           compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, path)
    return path, warnings


def load_project(path) -> dict:
    """Returns {"name", "notes", "saved_at", "project_id", "inputs", "database", "images": [ImageRecord],
    "fragment_sizes": [list | None]}; missing keys get defaults.  Embedded photos are extracted."""
    path = Path(path)
    sizes_by_image: list = []
    if zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        doc = json.loads(z.read("project.json").decode("utf-8"))
    else:                                                   # plain JSON of earlier versions
        z = None
        doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != FORMAT:
        raise ValueError("not a RingBlast project file")
    pid = doc.get("project_id") or new_project_id()
    names = {f.name for f in fields(ImageRecord)}
    images = []
    for d in doc.get("images", []):
        p = d.get("path", "")
        emb = d.get("embedded", "")
        if z is not None and emb:
            out = image_cache_dir(pid) / emb
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(emb) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            p = str(out)
        elif not Path(p).exists() and d.get("path_rel"):
            alt = (path.resolve().parent / d["path_rel"]).resolve()
            if alt.exists():
                p = str(alt)
        sizes = None
        if z is not None and d.get("results"):
            sizes = json.loads(z.read(d["results"]).decode("utf-8"))
        sizes_by_image.append(sizes)
        rec = ImageRecord(**{k: v for k, v in d.items() if k in names and k != "path"}, path=p)
        rec.seg = {**_seg_defaults(), **rec.seg}              # older projects: fill in new parameters
        images.append(rec)
    if z is not None:
        z.close()
    inputs = dict(DEFAULT_INPUTS)
    inputs.update({k: v for k, v in doc.get("inputs", {}).items() if k in DEFAULT_INPUTS})
    return {"name": doc.get("name", ""), "notes": doc.get("notes", ""), "saved_at": doc.get("saved_at", ""),
            "project_id": pid, "inputs": inputs, "database": doc.get("database", {}), "images": images,
            "fragment_sizes": sizes_by_image}
