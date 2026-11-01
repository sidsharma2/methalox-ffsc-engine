"""Checks on the iteration-2 models: plasma PSR, cost model, casing bolt-circle rule."""

import copy
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")

from ffsc import plasma  # noqa: E402
from ffsc.economics import CostModel, Sampler, read_bom  # noqa: E402

BOM = ROOT / "cad" / "output_improved" / "bom.csv"
DES = ROOT / "results" / "improved" / "design.json"


def test_plasma_inlet_conserves_energy():
    g0 = plasma.seeded_inlet(0.268, 697e5, 0.0)
    g1 = plasma.seeded_inlet(0.268, 697e5, 3e4)
    assert g1.enthalpy_mass - g0.enthalpy_mass == pytest.approx(3e4, rel=1e-6)
    assert g1.Y[g1.species_index("O")] > 0


def test_breakdown_voltage_scales_with_density():
    v1 = plasma.breakdown_voltage(10e5, 300.0, 1e-3)
    assert plasma.breakdown_voltage(20e5, 300.0, 1e-3) == pytest.approx(2 * v1)
    assert plasma.breakdown_voltage(10e5, 600.0, 1e-3) == pytest.approx(v1 / 2)
    assert plasma.max_pressure_for_voltage(v1, 300.0, 1e-3) == pytest.approx(10e5)


def test_fpb_psr_at_real_inlet_enthalpy():
    """Anchored to the cycle's inlet enthalpy, the FPB burns near 1,000 K and needs the 8 ms option (K1)."""
    c = json.load(open(DES))["cycle"]
    psr = plasma.PSR(c["mr_fpb"], c["p_fpb_Pa"], 1100.0, h_in=c["fpb_gas"]["h"])
    s = psr.solve(8e-3)
    assert s["burning"] and 950.0 < s["T_K"] < 1100.0
    t, _ = plasma.tau_extinction(c["mr_fpb"], c["p_fpb_Pa"], 1100.0, tau_max=0.05, h_in=c["fpb_gas"]["h"])
    assert 2e-3 < t < 4e-3                               # the 4 ms design has almost no kinetic margin


@pytest.mark.skipif(not BOM.exists(), reason="needs the improved CAD build")
def test_cost_model_covers_bom_and_ranks_strategies():
    bom, d = read_bom(BOM), json.load(open(DES))
    S = Sampler(n=1, mode="nominal")
    uc = {sc: CostModel(bom, d, sc, S).unit_cost() for sc in ("conventional", "inhouse_am")}
    for u in uc.values():
        assert all(float(np.ravel(r["cost"])[0]) > 0 for r in u["rows"])
        assert len(u["rows"]) == len(bom)
    assert uc["conventional"]["total"][0] > uc["inhouse_am"]["total"][0]


@pytest.mark.skipif(not BOM.exists(), reason="needs the improved CAD build")
def test_learning_curve_falls():
    bom, d = read_bom(BOM), json.load(open(DES))
    cm = CostModel(bom, d, "inhouse_am", Sampler(n=1, mode="nominal"))
    lr = cm.learning(cm.unit_cost(), [1, 10, 100])
    assert lr[1]["unit"][0] > lr[10]["unit"][0] > lr[100]["unit"][0]
    assert lr[100]["average"][0] > lr[100]["unit"][0]


def test_casing_bolt_circles_clear_each_other():
    from ffsc.design import design
    from run_improved import apply
    cfg = json.load(open(ROOT / "results" / "improved" / "config_improved.json"))
    cfg = copy.deepcopy(cfg)
    apply(cfg, {"propellants.lox.p_inlet_bar": 10.0, "propellants.lch4.p_inlet_bar": 10.0})
    res, _, _ = design(cfg, verbose=False, write=False)
    J = {j["name"]: j for j in res["internal_joints"]}
    for side in ("ox", "fuel"):
        ji, jc = J[f"{side}_pump_inlet_housing"], J[f"{side}_pump_volute_cover"]
        if ji["welded"] or jc["welded"]:
            continue
        assert jc["bcd_m"] / 2 - jc["d_m"] >= ji["bcd_m"] / 2 + ji["d_m"] + 2.9e-3
