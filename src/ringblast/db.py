"""Rock and explosive databases: built-in CSV files + optional user files.

User files live in ~/.ringblast/rocks.csv and ~/.ringblast/explosives.csv (same columns as the
built-in ones) and override/extend the built-ins by name.  Custom items can also be created in
code or in the GUI and saved with `save_user_rock` / `save_user_explosive`.
"""
from __future__ import annotations

from . import paths

import csv
import os
import sys
from pathlib import Path
from typing import Optional

from .models import Explosive, Rock

USER_DIR = paths.user_dir()
ROCK_FIELDS = ["name", "name_it", "density_t_m3", "ucs_mpa", "shear_mpa", "tensile_mpa", "vp_ms",
               "frag_energy_kj_m2", "c_langefors", "rock_factor_A", "youngs_gpa", "source", "notes"]
EXPL_FIELDS = ["name", "density_kg_dm3", "energy_mj_kg", "vod_ms", "rws_anfo",
               "det_pressure_gpa", "source", "notes"]


def _f(v: str) -> Optional[float]:
    v = (v or "").strip()
    return float(v) if v else None


def _read(path_or_text) -> list[dict]:
    if isinstance(path_or_text, Path):
        with open(path_or_text, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    return list(csv.DictReader(path_or_text.splitlines()))


def database_dir() -> Path:
    """Folder of the built-in databases: $RINGBLAST_DB, else <project>/database, else the
    copy bundled by PyInstaller."""
    env = os.environ.get("RINGBLAST_DB")
    if env:
        return Path(env)
    return paths.resource_root() / "database"


def _builtin(name: str) -> list[dict]:
    return _read(database_dir() / name)


def _rock(r: dict) -> Rock:
    g = lambda k: _f(r.get(k, ""))
    return Rock(name=r["name"], name_it=r.get("name_it", ""), density=g("density_t_m3"),
                ucs_mpa=g("ucs_mpa"), shear_mpa=g("shear_mpa"), tensile_mpa=g("tensile_mpa"),
                vp_ms=g("vp_ms"), frag_energy_kj_m2=g("frag_energy_kj_m2"),
                c_langefors=g("c_langefors") or 0.4, rock_factor_A=g("rock_factor_A"),
                youngs_gpa=g("youngs_gpa"), source=r.get("source", ""), notes=r.get("notes", ""))


def _expl(r: dict) -> Explosive:
    return Explosive(name=r["name"], density=float(r["density_kg_dm3"]),
                     energy_mj_kg=float(r["energy_mj_kg"]), vod_ms=float(r["vod_ms"]),
                     rws_anfo=float(r["rws_anfo"]), det_pressure_gpa=_f(r.get("det_pressure_gpa", "")),
                     source=r.get("source", ""), notes=r.get("notes", ""))


# ---------------------------------------------------------------- row level access (tables)
KINDS = {"rocks": (ROCK_FIELDS, _rock, "rocks.csv"), "explosives": (EXPL_FIELDS, _expl, "explosives.csv")}
REQUIRED = {"rocks": ["name"], "explosives": ["name", "density_kg_dm3", "energy_mj_kg", "vod_ms", "rws_anfo"]}
NUMERIC = {"rocks": ["density_t_m3", "ucs_mpa", "shear_mpa", "tensile_mpa", "vp_ms", "frag_energy_kj_m2",
                     "c_langefors", "rock_factor_A", "youngs_gpa"],
           "explosives": ["density_kg_dm3", "energy_mj_kg", "vod_ms", "rws_anfo", "det_pressure_gpa"]}
ROW_ERRORS: list[str] = []          # rows skipped by the last load (invalid numbers, missing fields)


def _clean(row: dict) -> dict:
    return {k: ("" if v is None else str(v)) for k, v in row.items() if k is not None}


_BUILTIN_CACHE: dict = {}


def builtin_rows(kind: str) -> list[dict]:
    """Rows of the original database (cached; returns copies)."""
    f = database_dir() / KINDS[kind][2]
    key = (str(f), f.stat().st_mtime_ns)
    if key not in _BUILTIN_CACHE:
        _BUILTIN_CACHE[key] = [_clean(r) for r in _read(f)]
    return [dict(r) for r in _BUILTIN_CACHE[key]]


def user_rows(kind: str) -> list[dict]:
    p = USER_DIR / KINDS[kind][2]
    return [_clean(r) for r in _read(p)] if p.exists() else []


def columns(kind: str, rows: list[dict] | None = None) -> list[str]:
    """Standard columns followed by any custom parameter columns found in the data."""
    cols = list(KINDS[kind][0])
    for r in (rows if rows is not None else builtin_rows(kind) + user_rows(kind)):
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


def effective_rows(kind: str, include_user: bool = True) -> list[dict]:
    """Built-in rows with the user's rows applied (same name = replaced, new name = appended)."""
    out = {r["name"]: r for r in builtin_rows(kind)}
    if include_user:
        for r in user_rows(kind):
            out[r["name"]] = r
    return list(out.values())


def row_status(kind: str, row: dict) -> str:
    """'builtin' (unchanged), 'modified' (built-in name, edited values) or 'user' (new item)."""
    base = {r["name"]: r for r in builtin_rows(kind)}
    if row["name"] not in base:
        return "user"
    b = base[row["name"]]
    keys = set(b) | set(row)
    return "builtin" if all((b.get(k, "") or "") == (row.get(k, "") or "") for k in keys) else "modified"


def save_user_rows(kind: str, rows: list[dict]) -> None:
    """Persist the rows that differ from the built-in database (new or modified); the others
    are removed from the user file.  Custom columns are kept."""
    rows = [_clean(r) for r in rows if (r.get("name") or "").strip()]
    diff = [r for r in rows if row_status(kind, r) != "builtin"]
    path = USER_DIR / KINDS[kind][2]
    if not diff:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = columns(kind, diff)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, cols)
        w.writeheader()
        for r in diff:
            w.writerow({k: r.get(k, "") for k in cols})


def reset_user_rows(kind: str) -> None:
    """Back to the original database: delete the user's rows."""
    (USER_DIR / KINDS[kind][2]).unlink(missing_ok=True)


def import_rows(kind: str, rows: list[dict]) -> list[str]:
    """Merge rows (e.g. stored in a project file) into the user's database.
    Returns messages about the items added or replaced."""
    cur = {r["name"]: r for r in effective_rows(kind)}
    msgs, merged = [], dict(cur)
    for r in map(_clean, rows):
        n = r.get("name", "")
        if not n:
            continue
        old = cur.get(n)
        if old is None:
            msgs.append(f"{kind[:-1]} '{n}' added from the project")
        elif any((old.get(k, "") or "") != (r.get(k, "") or "") for k in set(old) | set(r)):
            msgs.append(f"{kind[:-1]} '{n}' replaced by the version stored in the project")
        else:
            continue
        merged[n] = r
    if msgs:
        save_user_rows(kind, list(merged.values()))
    return msgs


def _load(kind: str, include_user: bool) -> dict:
    ROW_ERRORS[:] = [e for e in ROW_ERRORS if not e.startswith(kind)]
    out = {}
    for r in effective_rows(kind, include_user):
        try:
            for k in REQUIRED[kind]:
                if not (r.get(k) or "").strip():
                    raise ValueError(f"missing '{k}'")
            out[r["name"]] = KINDS[kind][1](r)
        except (ValueError, KeyError) as exc:
            ROW_ERRORS.append(f"{kind}: row '{r.get('name', '?')}' skipped ({exc})")
    return out


def load_rocks(include_user: bool = True) -> dict[str, Rock]:
    return _load("rocks", include_user)


def load_explosives(include_user: bool = True) -> dict[str, Explosive]:
    return _load("explosives", include_user)


def _append(path: Path, fields: list[str], row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fields)
        if new:
            w.writeheader()
        w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})


def save_user_rock(rock: Rock, path: Path = USER_DIR / "rocks.csv") -> None:
    _append(path, ROCK_FIELDS, dict(
        name=rock.name, name_it=rock.name_it, density_t_m3=rock.density, ucs_mpa=rock.ucs_mpa,
        shear_mpa=rock.shear_mpa, tensile_mpa=rock.tensile_mpa, vp_ms=rock.vp_ms,
        frag_energy_kj_m2=rock.frag_energy_kj_m2, c_langefors=rock.c_langefors,
        rock_factor_A=rock.rock_factor_A, youngs_gpa=rock.youngs_gpa, source=rock.source or "user",
        notes=rock.notes))


def save_user_explosive(e: Explosive, path: Path = USER_DIR / "explosives.csv") -> None:
    _append(path, EXPL_FIELDS, dict(
        name=e.name, density_kg_dm3=e.density, energy_mj_kg=e.energy_mj_kg, vod_ms=e.vod_ms,
        rws_anfo=e.rws_anfo, det_pressure_gpa=e.det_pressure_gpa, source=e.source or "user",
        notes=e.notes))
