"""Convert the legacy RingBlast.xlsm tables and the user's rock-properties
workbook into the CSV databases shipped with the new software.

Usage:
    python tools/convert_legacy_data.py RingBlast.xlsm "rock_properties_for_RingBlast.xlsx"

Design choices (documented in docs/DESIGN.md):
* one record per rock; legacy macro rows are merged into the rock table by an
  explicit name map, so Vp / fragmentation energy / tensile strength survive;
* conflicting densities are kept from the rock table and the legacy value is
  written to `notes`;
* soils (clays, silt, sand, gravel, peat) are not blastable rocks: they are
  written to legacy_soils.csv and excluded from rocks.csv;
* duplicated names in the source table are kept, suffixed "(alt)";
* explosives: `rws_anfo` (ANFO = 100) is derived from the legacy "strength NGL"
  column by scaling so that anfo77 = 100 (legacy-derived, to be verified).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import openpyxl

OUT = Path(__file__).resolve().parents[1] / "database"
KGCM2_TO_MPA = 0.0980665

# legacy macro rock name -> (English name, name in the rock-properties table or None)
LEGACY_ROCKS = {
    "graniti": ("Granite", "Granite"),
    "sienite": ("Syenite", "Syenite"),
    "gabbri": ("Gabbro", "Gabbro"),
    "peridot.": ("Peridotite", None),
    "porfidi": ("Porphyry", "Porphyry"),
    "basalti": ("Basalt", "Basalt"),
    "diabasi": ("Diabase (dolerite)", "Diabase (dolerite)"),
    "arenarie": ("Sandstone", "Sandstone"),
    "quarziti": ("Quartzite", "Quartzite"),
    "calcari": ("Limestone", "Limestone"),
    "dolomie": ("Dolomite", "Dolomite"),
    "marne": ("Marl", "Marl"),
    "tufi": ("Tuff", "Tuff"),
    "gessi": ("Gypsum", "Gypsum"),
    "salgemma": ("Rock salt (Halite)", "Rock salt (Halite)"),
    "travert.": ("Travertine", "Travertine"),
    "gneiss a": ("Amphibolitic gneiss", "Amphibolitic gneiss"),
    "gneiss g": ("Granite gneiss", "Granite gneiss"),
    "serpent.": ("Serpentinite", "Serpentinite"),
    "calcesc.": ("Calc-schist", None),
}
SOILS = {"Very soft clay", "Soft clay", "Firm clay", "Stiff clay", "Hard clay",
         "Silt", "Gravel", "Dense sand", "Undense sand", "Peat"}

ROCK_FIELDS = ["name", "name_it", "density_t_m3", "ucs_mpa", "shear_mpa", "tensile_mpa",
               "vp_ms", "frag_energy_kj_m2", "c_langefors", "rock_factor_A", "youngs_gpa",
               "source", "notes"]
EXPL_FIELDS = ["name", "density_kg_dm3", "energy_mj_kg", "vod_ms", "rws_anfo",
               "det_pressure_gpa", "source", "notes"]


def num(x):
    return None if x in (None, "") else float(x)


def read_rock_table(path):
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        name, ucs, shear, dens = r[6], r[7], r[8], r[9]
        if name:
            rows.append((str(name).strip(), num(ucs), num(shear), num(dens)))
    return rows


def read_legacy(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    rocks = {}
    for r in wb["RockData"].iter_rows(min_row=3, max_row=22, values_only=True):
        rocks[str(r[1]).strip()] = dict(density=num(r[2]), vp=num(r[3]), es=num(r[4]),
                                        rt=num(r[5]), c=num(r[6]), A=num(r[7]))
    expl = []
    for r in wb["ExplData"].iter_rows(min_row=3, max_row=9, values_only=True):
        expl.append(dict(name=r[1], energy=num(r[2]), density=num(r[3]), vod=num(r[4]),
                         ngl=num(r[5]), pd=num(r[6])))
    return rocks, expl


def _round_csv_files():
    """Keep 6 significant digits in the generated CSV files (no float noise in the tables)."""
    for name in ("rocks.csv", "explosives.csv", "legacy_soils.csv"):
        with open(OUT / name, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            for k, v in r.items():
                if k not in ("name", "name_it", "source", "notes") and v not in ("", None):
                    try:
                        r[k] = "%.6g" % float(v)
                    except ValueError:
                        pass
        with open(OUT / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, list(rows[0]))
            w.writeheader()
            w.writerows(rows)


def main(xlsm, xlsx):
    OUT.mkdir(parents=True, exist_ok=True)
    table = read_rock_table(xlsx)
    legacy, expl = read_legacy(xlsm)
    by_table_name = {en: (it, legacy[it]) for it, (en, tn) in LEGACY_ROCKS.items()
                     if tn and it in legacy}
    seen, rocks, soils, report = {}, [], [], []
    for name, ucs, shear, dens in table:
        key = name
        if name in seen:
            key = f"{name} (alt)"
            report.append(f"duplicate name in source table: {name} -> kept as '{key}'")
        seen[name] = True
        if name in SOILS:
            soils.append(dict(name=name, ucs_mpa=ucs, shear_mpa=shear, density_t_m3=dens))
            continue
        rec = dict(name=key, name_it="", density_t_m3=dens, ucs_mpa=ucs, shear_mpa=shear,
                   tensile_mpa=None, vp_ms=None, frag_energy_kj_m2=None, c_langefors=0.4,
                   rock_factor_A=None, youngs_gpa=None,
                   source="rock_properties_for_RingBlast.xlsx", notes="")
        if key in by_table_name and name == key:
            it, leg = by_table_name[key]
            rec.update(name_it=it, vp_ms=leg["vp"], frag_energy_kj_m2=leg["es"],
                       tensile_mpa=None if leg["rt"] is None else round(leg["rt"] * KGCM2_TO_MPA, 4),
                       c_langefors=leg["c"] or 0.4,
                       source="rock_properties_for_RingBlast.xlsx + RingBlast.xlsm RockData")
            if dens is None:
                rec["density_t_m3"] = leg["density"]
            elif leg["density"] and abs(leg["density"] - dens) > 1e-9:
                rec["notes"] = f"legacy macro density {leg['density']} t/m3 differs"
        if shear is not None and ucs is not None and shear > ucs:
            rec["notes"] = (rec["notes"] + "; " if rec["notes"] else "") + \
                "source shear strength > UCS: check data"
        rocks.append(rec)
    # legacy-only rocks (not in the user's table)
    for it, (en, tn) in LEGACY_ROCKS.items():
        if tn is None:
            leg = legacy[it]
            rocks.append(dict(name=en, name_it=it, density_t_m3=leg["density"], ucs_mpa=None,
                              shear_mpa=None,
                              tensile_mpa=None if leg["rt"] is None else round(leg["rt"] * KGCM2_TO_MPA, 4),
                              vp_ms=leg["vp"], frag_energy_kj_m2=leg["es"],
                              c_langefors=leg["c"] or 0.4, rock_factor_A=None, youngs_gpa=None,
                              source="RingBlast.xlsm RockData", notes="legacy macro only"))
    with open(OUT / "rocks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ROCK_FIELDS)
        w.writeheader()
        w.writerows(rocks)
    with open(OUT / "legacy_soils.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["name", "ucs_mpa", "shear_mpa", "density_t_m3"])
        w.writeheader()
        w.writerows(soils)
    ngl_ref = next(e["ngl"] for e in expl if e["name"] == "anfo77")
    with open(OUT / "explosives.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, EXPL_FIELDS)
        w.writeheader()
        for e in expl:
            w.writerow(dict(name=e["name"], density_kg_dm3=e["density"], energy_mj_kg=e["energy"],
                            vod_ms=e["vod"], rws_anfo=round(100 * e["ngl"] / ngl_ref, 1),
                            det_pressure_gpa=e["pd"], source="RingBlast.xlsm ExplData",
                            notes=f"legacy: strength vs NGL {e['ngl']}%; rws_anfo derived "
                                  f"(anfo77=100), verify against datasheet"))
    _round_csv_files()
    print(f"rocks: {len(rocks)}  soils excluded: {len(soils)}  explosives: {len(expl)}")
    for line in report:
        print(" -", line)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

