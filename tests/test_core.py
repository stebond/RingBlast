"""Validation tests: worked examples of the SIG slides (F. Tinti, 29 May 2026) and the values
stored by the last run of the legacy RingBlast.xlsm macro (rock 10, explosive 1, d = 80 mm,
L = 25 m, H = 80 m, 2 sublevels, drift 5 x 5 m, S/B = 1.25, f = 0.65, c = 0.8, wall angle 55 deg)."""
import math

import numpy as np
import pytest

from ringblast import db
from ringblast.burden import (BurdenInputs, compare_methods, compute_burden, energy_method,
                              hustrulid_powder_factor, konya_1972, langefors_kihlstrom)
from ringblast.charging import decharge, point_segment_distance
from ringblast.design import run_design, sensitivity
from ringblast.fragmentation import (characteristic_size_cm, cunningham_rock_factor,
                                     kuznetsov_mean_size_cm, passing_curve, uniformity_index)
from ringblast.geometry import build_ring
from ringblast.models import DesignParams, Explosive, MissingInput, Rock, StopeGeometry

STOPE = StopeGeometry(width=25, height=80, n_sublevels=2, drift_width=5, drift_height=5,
                      wall_angle_deg=55)
B_MACRO = 3.0179195759102155                     # Input!B10 of the macro (Langefors, c = 0.8)


def _inputs(rock, expl, **kw):
    return BurdenInputs(rock, expl, DesignParams(**kw), mean_hole_length_m=10.0)


# ------------------------------------------------------------------ burden
def test_langefors_slide_example():
    expl = Explosive("slide", density=0.75, energy_mj_kg=3.1, vod_ms=3000, rws_anfo=97.3)
    x = _inputs(Rock("r"), expl, hole_diameter_mm=100, fixation=0.65, sb_ratio=1.3, c_langefors=0.80)
    assert langefors_kihlstrom(x) == pytest.approx(3.05, abs=0.01)     # slide: B = 3.05 m


def test_langefors_reproduces_macro_value():
    expl = Explosive("anfo77", 1.1, 3.11, 2600, rws_anfo=97.3)         # macro: s = 70 * 1.39 / 100
    x = _inputs(Rock("r"), expl, hole_diameter_mm=80, fixation=0.65, sb_ratio=1.25, c_langefors=0.80)
    assert langefors_kihlstrom(x, "fixed") == pytest.approx(B_MACRO, rel=1e-9)


def test_hustrulid_slide_example():
    rho = 9.64 / (math.pi * 0.1 ** 2 / 4 * 1000)                       # Mc = 9.64 kg/m
    expl = Explosive("slide", rho, 3.1, 3000, 100)
    x = BurdenInputs(Rock("r"), expl, DesignParams(hole_diameter_mm=100, sb_ratio=1.3,
                                                   powder_factor_target=0.8,
                                                   stemming_diameters=20), mean_hole_length_m=10.0)
    assert hustrulid_powder_factor(x) == pytest.approx(2.72, abs=0.01)  # slide: B = 2.72 m


def test_konya_and_energy_match_macro():
    rock = Rock("legacy", density=2.6, vp_ms=4000, frag_energy_kj_m2=1.47)
    expl = Explosive("anfo77", 1.1, 3.11, 2600, 100)
    x = _inputs(rock, expl, hole_diameter_mm=80)
    assert konya_1972(x) == pytest.approx(2.278164, rel=0.01)           # macro Burdens!C10
    assert energy_method(x) == pytest.approx(4.307196, rel=1e-3)        # macro Burdens!C15


def test_missing_property_is_reported_not_guessed():
    x = _inputs(Rock("no data"), Explosive("e", 1.1, 3.1, 2600, 100))
    with pytest.raises(MissingInput):
        energy_method(x)
    res = compare_methods(x)
    assert res["energy"] is None and res["langefors_kihlstrom"] > 0


# ------------------------------------------------------------------ geometry
@pytest.fixture(scope="module")
def ring():
    return build_ring(STOPE, B_MACRO, B_MACRO * 1.25, 1.6)


def test_ring_matches_macro_run(ring):
    assert len(ring.holes) == 20 and (ring.n_lateral_intervals, ring.n_bottom_intervals) == (6, 7)
    assert ring.y_bottom == pytest.approx(52.009, abs=1e-3)
    assert ring.lateral_spacing_eff == pytest.approx(3.4782, abs=0.01)  # macro quantised to 0.1 %
    assert ring.bottom_spacing_eff == pytest.approx(3.4555, abs=0.01)
    assert sum(h.length for h in ring.holes) == pytest.approx(346.1544, abs=0.05)


def test_ring_rules(ring):
    corners = [h for h in ring.holes if h.kind.endswith("corner")]
    assert len(corners) == 4                                            # rule ii
    assert ring.lateral_spacing_eff <= B_MACRO * 1.25 + 1e-9            # rule i
    assert ring.bottom_spacing_eff <= B_MACRO * 1.25 + 1e-9
    xs = [(h.toe[0], h.toe[1]) for h in ring.holes]
    for (x, y), h in zip(xs, ring.holes):    # mirror symmetry (bottom marched from one side: < 1 mm)
        mx, my = ring.holes[len(xs) - h.index].toe
        assert (mx, my) == pytest.approx((-x, y), abs=2e-3)
    assert all(h.stemming_length == pytest.approx(1.6, abs=1e-9) for h in ring.holes)


def test_closing_exactly_on_corners_and_huge_spacing():
    r = build_ring(STOPE, B_MACRO, 80.0, 1.6)
    kinds = [h.kind for h in r.holes]                    # walls/bottom each closed by one interval
    assert kinds.count("roof-corner") == 2 and kinds.count("bottom-corner") == 2
    assert r.holes[0].toe == (-12.5, 80) and r.holes[-1].toe == (12.5, 80)
    assert len(r.holes) == 6 and r.n_bottom_intervals == 1


def test_more_holes_for_smaller_burden():
    p = DesignParams(burden_method="manual", burden_manual_m=3.0)
    rows = sensitivity(Rock("r", density=2.6), Explosive("e", 1.1, 3.1, 2600, 100), STOPE, p,
                       [2.0, 3.0, 4.0])
    n = [r["n_holes"] for r in rows]
    assert n[0] > n[1] > n[2]
    assert rows[0]["powder_factor"] > rows[2]["powder_factor"]


# ------------------------------------------------------------------ charging
def test_decharging_respects_half_spacing_and_corners():
    spacing = B_MACRO * 1.25
    r = build_ring(STOPE, B_MACRO, spacing, 1.6)
    before = [h.charged_length for h in r.holes]
    decharge(r.holes, spacing, levels=2, protect_corners=True)
    after = [h.charged_length for h in r.holes]
    assert all(a <= b + 1e-9 for a, b in zip(after, before))
    assert any(a < b - 0.5 for a, b in zip(after, before))
    for h, a, b in zip(r.holes, after, before):
        if h.kind.endswith("corner"):
            assert a == pytest.approx(b)                                 # rule ii: full charge


def test_decharging_rule_iii_single_pass():
    """After pass 1 every thinned hole is >= S/2 from the charged part of its two neighbours."""
    spacing = B_MACRO * 1.25
    r = build_ring(STOPE, B_MACRO, spacing, 1.6)
    decharge(r.holes, spacing, levels=1)
    n = len(r.holes)
    thinned = [i for i in range(1, n - 1, 2) if r.holes[i].kind not in ("roof-corner", "bottom-corner")]
    assert thinned
    for i in thinned:
        h = r.holes[i]
        if h.charged_length < 1e-9:
            continue
        for k in (i - 1, i + 1):
            n_ = r.holes[k]
            d = point_segment_distance(h.charge_start, n_.charge_start, n_.toe)
            assert d >= spacing / 2 - 0.03


# ------------------------------------------------------------------ fragmentation
def test_kuznetsov_and_rosin_rammler():
    x50 = kuznetsov_mean_size_cm(10, 0.65, 20, 100)
    assert x50 == pytest.approx(10 * 0.65 ** -0.8 * 20 ** (1 / 6) * 1.15 ** (19 / 30))
    n = 1.3
    xc = characteristic_size_cm(x50, n)
    assert passing_curve([x50], xc, n)[0] == pytest.approx(0.5)


def test_uniformity_index_value():
    n = uniformity_index(B=3.0, S=3.75, d_mm=80, W=0.1, L_over_H=1.0)
    assert n == pytest.approx((2.2 - 14 * 3 / 80) * math.sqrt(1.125) * (1 - 0.1 / 3) * 0.1 ** 0.1,
                              rel=1e-12)
    assert n == pytest.approx(1.364, abs=0.005)


def test_legacy_macro_zone1_size_is_reproduced_by_its_two_bugs():
    """Macro zone 1: K = 1.284 kg/m3 -> 7.0501 cm.  This number follows only if Q is the mass
    in a 0.1 m column (cell 'incremental spacing' read instead of R = 5 m) and RWS = 70 * 1.78.
    With the intended R = 5 m the same formula gives ~2x larger fragments."""
    section = math.pi * 0.08 ** 2 / 4 * 1100                            # kg/m
    legacy = kuznetsov_mean_size_cm(10, 1.284, section * 0.1, 70 * 1.78)
    assert legacy == pytest.approx(7.0501, abs=0.005)
    intended = kuznetsov_mean_size_cm(10, 1.284, section * 5.0, 70 * 1.78)
    assert intended / legacy > 1.8


def test_rock_factor_structure():
    a_light = cunningham_rock_factor(2.0, 50, 20, "massive")
    a_dense = cunningham_rock_factor(2.9, 50, 20, "massive")
    assert a_dense > a_light
    assert cunningham_rock_factor(2.6, 100, 60, "massive") > cunningham_rock_factor(2.6, 100, 40, "massive") - 100
    with pytest.raises(ValueError):
        cunningham_rock_factor(2.6, 100, 40, "unknown")


# ------------------------------------------------------------------ whole design
@pytest.fixture(scope="module")
def result():
    rocks, expl = db.load_rocks(False), db.load_explosives(False)
    p = DesignParams(hole_diameter_mm=80, burden_method="langefors_kihlstrom", c_langefors=0.8,
                     rock_factor_A=10)
    return run_design(rocks["Limestone"], expl["anfo77"], STOPE, p)


def test_design_consistency(result):
    assert result.burden_m == pytest.approx(3.06, abs=0.01)
    assert len(result.levels) == 3                                       # 2 sublevels + base
    lv = result.levels[0]
    region = 25 * (80 - lv.ring.y_bottom) - 25                           # minus drift
    assert sum(z.area_m2 for z in lv.zones) == pytest.approx(region, rel=0.01)
    assert lv.n_holes == 20 and lv.weighted_mean_size_cm == pytest.approx(27.1, abs=0.3)
    assert sum(z.charge_kg for z in result.zones) == pytest.approx(result.charge_kg, rel=1e-3)
    assert 0.4 < result.powder_factor < 1.0
    assert all(z.mean_size_cm > 0 for z in result.zones)
    assert not np.isnan(result.weighted_mean_size_cm)


# ------------------------------------------------------------------ database
def test_database_content_and_user_override(tmp_path, monkeypatch):
    rocks, expl = db.load_rocks(False), db.load_explosives(False)
    assert len(rocks) >= 60 and len(expl) == 14
    lim = rocks["Limestone"]
    assert lim.vp_ms == 4000 and lim.frag_energy_kj_m2 == 1.47 and lim.ucs_mpa == 115
    assert expl["anfo77"].rws_anfo == 100
    path = tmp_path / "rocks.csv"
    db.save_user_rock(Rock("My dolomite", density=2.75, ucs_mpa=150), path)
    monkeypatch.setattr(db, "USER_DIR", tmp_path)
    assert "My dolomite" in db.load_rocks(True) and "My dolomite" not in db.load_rocks(False)


# ------------------------------------------------------------------ multi-level / side drifts
from ringblast.geometry import level_specs                # noqa: E402


def test_levels_cover_sublevels_and_trapezoid_base():
    specs = level_specs(STOPE, B_MACRO)
    assert [s.kind for s in specs] == ["sublevel", "sublevel", "base"]
    assert specs[0].centre == (0.0, 77.5) and specs[1].centre == (0.0, 48.0)
    base = specs[2]                                   # base drift: bottom centre, in the hopper neck
    assert base.polygon == [(-12.5, 21), (-2.5, 5), (2.5, 5), (12.5, 21)]
    assert base.centre == (0.0, 2.5) and base.drift_rect == (-2.5, 0, 2.5, 5)
    assert level_specs(StopeGeometry(25, 80, 1, 5, 5, 55, base_drift=False), B_MACRO)[0].kind == "sublevel"
    assert len(level_specs(StopeGeometry(25, 80, 1, 5, 5, 55, base_drift=False), B_MACRO)) == 1
    assert len(level_specs(StopeGeometry(25, 120, 4, 5, 5, 55), B_MACRO)) == 5


@pytest.mark.parametrize("pos", ["center", "left", "right"])
def test_every_level_closes_on_its_corners(pos):
    s = StopeGeometry(25, 80, 3, 5, 5, 55, drift_position=pos)
    for spec in level_specs(s, B_MACRO):
        r = build_ring(spec, B_MACRO, B_MACRO * 1.25, 1.6)
        toes = {h.toe for h in r.holes}
        assert all(h.length >= 1.0 for h in r.holes)            # no zero-length holes at a flush drift
        if spec.kind == "base":
            assert {spec.tl, spec.tr} <= toes and r.bottom_spacing_eff <= B_MACRO * 1.25 + 1e-9
            assert all(h.toe[1] == 21 for h in r.holes)         # toes on the top line
        else:
            assert {spec.bl, spec.br} <= toes
            for sp in (r.lateral_spacing_eff, r.bottom_spacing_eff, r.right_spacing_eff):
                assert 0 < sp <= B_MACRO * 1.25 + 1e-9
            n_corner = sum(h.kind.endswith("corner") for h in r.holes)
            assert n_corner == (4 if pos == "center" else 3)    # flush drift sits on one roof corner


def test_side_drift_is_flush_with_wall_and_mixed_positions():
    s = StopeGeometry(25, 80, 2, 5, 5, 55, drift_positions=["left", "right"])
    specs = level_specs(s, B_MACRO)
    assert [sp.centre[0] for sp in specs] == [-10.0, 10.0, 0.0]      # drift edge on the wall
    assert specs[0].drift_rect[0] == -12.5 and specs[1].drift_rect[2] == 12.5
    assert specs[2].position == "center"                             # base always central
    with pytest.raises(ValueError):
        StopeGeometry(25, 80, 2, 5, 5, 55, drift_positions=["left"]).validate()


def test_totals_are_sum_of_levels_and_region_areas():
    rocks, expl = db.load_rocks(False), db.load_explosives(False)
    p = DesignParams(c_langefors=0.8, rock_factor_A=10)
    for pos in ("center", "left"):
        s = StopeGeometry(25, 80, 2, 5, 5, 55, drift_position=pos)
        res = run_design(rocks["Limestone"], expl["anfo77"], s, p)
        assert res.n_holes == sum(l.n_holes for l in res.levels)
        assert res.charge_kg == pytest.approx(sum(l.charge_kg for l in res.levels))
        base = res.levels[2]
        trap = (25 + 5) / 2 * (21 - 5)                                   # hopper block, drift below it
        assert sum(z.area_m2 for z in base.zones) == pytest.approx(trap, rel=0.01)
        assert base.volume_m3 == pytest.approx(trap * res.burden_m, rel=0.01)
        assert all(l.n_holes > 0 for l in res.levels)
