"""Physics and bookkeeping checks for the design models (run: .venv\\Scripts\\python -m pytest -q)."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffsc import G0, load_config  # noqa: E402
from ffsc.design import design, stream_split  # noqa: E402
from ffsc.nozzle import build_contour, mach_from_area, rao_angles  # noqa: E402
from ffsc.structures import size_joint  # noqa: E402
from ffsc.thermo import rocket  # noqa: E402
from ffsc import cooling  # noqa: E402


@pytest.fixture(scope="module")
def base():
    res, contour, cool = design(load_config(), verbose=False, write=False)
    return res, contour, cool


def test_rocket_ideal_values_in_known_range():
    r = rocket(350e5, 3.6, 34.0, T_ox=70.0, T_fu=95.0)
    assert 3700 < r.Tc < 3850                 # CEA-class LOX/CH4 flame temperature at 350 bar
    assert 1820 < r.cstar < 1880
    assert 360 < r.isp_vac < 372
    frozen = rocket(350e5, 3.6, 34.0, T_ox=70.0, T_fu=95.0, shifting=False)
    assert frozen.isp_vac < r.isp_vac         # shifting equilibrium always gains
    # throat found as the max-mass-flux point: local Mach close to 1
    assert abs(r.throat.M - 1.0) < 0.05


def test_matches_nasa_cea():
    cea_mod = pytest.importorskip("rocketcea.cea_obj")
    cea = cea_mod.CEA_Obj(oxName="LOX", fuelName="CH4")
    pc_psi = 350e5 / 6894.757
    r = rocket(350e5, 3.6, 34.0, T_ox=90.17, T_fu=111.643, p_feed=101325.0)
    assert r.isp_vac == pytest.approx(cea.get_Isp(Pc=pc_psi, MR=3.6, eps=34.0), rel=2e-3)
    assert r.cstar == pytest.approx(cea.get_Cstar(Pc=pc_psi, MR=3.6) * 0.3048, rel=2e-3)
    assert r.Tc == pytest.approx(cea.get_Tcomb(Pc=pc_psi, MR=3.6) / 1.8, rel=3e-3)


def test_stream_split_conserves_mixture_ratio():
    mr, phi, mrw = 3.6, 0.08, 2.0
    core = stream_split(mr, phi, mrw)
    fuel = (1 - phi) / (1 + core) + phi / (1 + mrw)
    ox = (1 - phi) * core / (1 + core) + phi * mrw / (1 + mrw)
    assert ox / fuel == pytest.approx(mr, rel=1e-9)


def test_contour_geometry():
    cfg = load_config()
    At = 0.0433
    c = build_contour(At, 34.0, cfg["chamber"])
    assert np.all(np.diff(c.x) > 0)
    assert c.r.min() == pytest.approx(c.Rt, rel=1e-6)
    assert c.r[-1] == pytest.approx(np.sqrt(34.0) * c.Rt, rel=1e-3)
    i_t = np.argmin(c.r)
    vol = np.trapezoid(np.pi * c.r[:i_t + 1] ** 2, c.x[:i_t + 1])
    assert vol == pytest.approx(cfg["chamber"]["Lstar_m"] * At, rel=0.02)
    tn, te = rao_angles(34.0)
    assert 28 < tn < 32 and 7 < te < 10


def test_area_mach_inverse():
    for M in (0.3, 2.0, 3.6):
        g = 1.13
        ar = (1 / M) * ((2 / (g + 1)) * (1 + (g - 1) / 2 * M ** 2)) ** ((g + 1) / (2 * (g - 1)))
        assert mach_from_area(ar, g, M > 1) == pytest.approx(M, rel=1e-6)


def test_thrust_and_mass_flow_consistent(base):
    res, contour, _ = base
    p = res["performance"]
    assert p["mdot"] * p["isp_sl"] * G0 == pytest.approx(p["thrust_sl_N"], rel=1e-9)
    assert p["mdot"] * p["cstar"] / p["pc"] == pytest.approx(np.pi * contour.Rt ** 2, rel=1e-6)


def test_cycle_mass_and_power_balance(base):
    res, _, _ = base
    c = res["cycle"]
    p = res["performance"]
    assert c["mdot_opb"] + c["mdot_fpb"] == pytest.approx(p["mdot"], rel=1e-9)
    # each shaft: turbine power = pump power (+ kick stage on the LOX shaft)
    assert c["fuel_turbine"]["power_W"] == pytest.approx(c["fuel_pump"]["power_W"], rel=2e-3)
    assert c["ox_turbine"]["power_W"] == pytest.approx(c["ox_pump"]["power_W"] + c["kick_stage_power_W"], rel=2e-3)
    # pressure ladder is monotonic: pump discharge > preburner > turbine exit > chamber
    assert c["p_ox_discharge_Pa"] > c["p_opb_Pa"] > c["p_turbine_exit_Pa"] > p["pc"]
    assert c["p_fuel_discharge_Pa"] > c["p_fpb_Pa"] > c["p_turbine_exit_Pa"]


def test_cooling_energy_balance_and_limits(base):
    res, _, cool = base
    co = res["cooling"]
    m_c = res["config"]["cooling"]["coolant_fraction"] * (res["performance"]["mdot_fuel"] - res["cycle"]["mdot_fuel_to_opb"])
    T_in, p_in = res["cycle"]["jacket_in_T_K"], res["cycle"]["jacket_in_p_Pa"]
    h_in = cooling.ch4_props(T_in, p_in)[4]
    h_out = cooling.ch4_props(co["T_out_K"], co["p_out_Pa"])[4]
    assert m_c * (h_out - h_in) == pytest.approx(co["Q_total_W"], rel=0.03)
    for k, z in enumerate(res["config"]["cooling"]["zones"]):
        assert cool["Twg"][cool["zone"] == k].max() <= z["Twg_target_K"] + 1.0
    assert co["liner_stress_ratio_max"] <= 1.0
    assert co["rib_stress_ratio_max"] <= 1.0


def test_bolted_joints_hold_and_fit(base):
    res, _, _ = base
    st = load_config()["structures"]
    for j in res["joints"]:
        clamp = j["n_bolts"] * j["preload_N"]
        assert clamp >= st["separation_safety"] * 0.75 * j["F_sep_proof_N"] * 0.999, j["name"]
        assert 2.5 <= j["spacing_over_d"] <= 6.0 + 1e-9, j["name"]
        assert j["bolt_stress_ratio"] < 1.0, j["name"]


def test_joint_sizing_rejects_impossible_flange():
    with pytest.raises(ValueError):
        size_joint("too_big", 80e6, 0.6, load_config(), "A286")


def test_sea_level_nozzle_attached_at_min_throttle(base):
    res, _, _ = base
    low = res["throttle"][-1]
    assert low["throttle"] == pytest.approx(res["config"]["requirements"]["throttle_min"])
    assert not low["separated_schmucker"]
