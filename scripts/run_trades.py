"""Trade studies around the baseline: every case reruns the full 0-D/1-D design chain
(performance, contour, coupled regen/cycle, injector, joints). Writes results/trades.json
and results/trades/<study>.csv. Infeasible cases (shaft cannot balance, etc.) are kept."""

import copy
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffsc import ROOT, load_config  # noqa: E402
from ffsc.design import design  # noqa: E402

RHO_LOX, RHO_CH4 = 1237.8, 446.1          # kg/m3 at 70 K / 95 K, 6 bar (CoolProp)


def metrics(res):
    p, c, co, g = res["performance"], res["cycle"], res["cooling"], res["geometry"]
    mr = p["mr"]
    rho_bulk = (1 + mr) / (mr / RHO_LOX + 1 / RHO_CH4)
    hg = lambda side: res["ducts"][f"{side}_hot_gas"] / 2 + 0.008
    env = lambda side: c[f"{side}_turbine"]["tip_D_m"] / 2 + 1.55 * hg(side) + 0.015
    return {
        "feasible": True, "isp_sl": p["isp_sl"], "isp_vac": p["isp_vac"], "mdot": p["mdot"],
        "rho_bulk": rho_bulk, "density_isp_sl": p["isp_sl"] * rho_bulk / 1000.0,
        "bl_penalty_s": p["bl_isp_penalty_s"], "Tc": p["Tc_core"],
        "Dt_mm": 2000 * g["Rt_m"], "De_mm": 2000 * g["Re_m"], "L_total_m": g["x_exit_m"],
        "p_ox_dis_bar": c["p_ox_discharge_Pa"] / 1e5, "p_fu_dis_bar": c["p_fuel_discharge_Pa"] / 1e5,
        "p_opb_bar": c["p_opb_Pa"] / 1e5, "p_fpb_bar": c["p_fpb_Pa"] / 1e5,
        "PR_ox": c["PR_ox_turbine"], "PR_fu": c["PR_fuel_turbine"],
        "P_ox_MW": c["ox_pump"]["power_W"] / 1e6, "P_fu_MW": c["fuel_pump"]["power_W"] / 1e6,
        "N_ox_rpm": c["ox_pump"]["N_rpm"], "N_fu_rpm": c["fuel_pump"]["N_rpm"],
        "eta_t_ox": c["ox_turbine"]["eta"], "eta_t_fu": c["fuel_turbine"]["eta"],
        "Dm_ox_mm": 1000 * c["ox_turbine"]["Dm_m"], "Dm_fu_mm": 1000 * c["fuel_turbine"]["Dm_m"],
        "D2_ox_mm": 1000 * c["ox_pump"]["D2_m"], "D2_fu_mm": 1000 * c["fuel_pump"]["D2_m"],
        "R_env_ox_tpa_mm": 1000 * env("ox"), "R_env_fu_tpa_mm": 1000 * env("fuel"),
        "dp_jacket_bar": co["dp_jacket_Pa"] / 1e5, "Q_MW": co["Q_total_W"] / 1e6,
        "Twg_max_K": co["Twg_max_K"], "q_max_MW_m2": co["q_max_W_m2"] / 1e6, "T_jacket_out_K": co["T_out_K"],
        "liner_ratio": co["liner_stress_ratio_max"], "rib_ratio": co["rib_stress_ratio_max"],
        "tca_mass_kg": res["tca_mass"]["total_kg"],
        "sep_margin_100": res["throttle"][0]["margin_schmucker"], "sep_margin_40": res["throttle"][-1]["margin_schmucker"],
        "pe_over_pa_40": res["throttle"][-1]["pe_over_pa"],
    }


def run_case(label, mods):
    cfg = copy.deepcopy(load_config())
    for path, value in mods.items():
        node = cfg
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[int(k)] if k.isdigit() else node[k]
        node[int(keys[-1]) if keys[-1].isdigit() else keys[-1]] = value
    try:
        res, _, _ = design(cfg, verbose=False, write=False)
        out = metrics(res)
    except Exception as err:            # infeasible design point
        out = {"feasible": False, "error": str(err)[:160]}
    return {"label": label, **mods, **out}


STUDIES = {
    "mixture_ratio": [(f"O/F {v}", {"requirements.mixture_ratio": v}) for v in [3.0, 3.2, 3.4, 3.6, 3.8, 4.0]],
    "expansion_ratio": [(f"eps {v}", {"nozzle.expansion_ratio": v}) for v in [25.0, 30.0, 34.0, 38.0, 42.0, 46.0]],
    "chamber_pressure": [(f"pc {v}", {"requirements.pc_bar": v}) for v in [250.0, 300.0, 350.0, 400.0]],
    "wall_bias": [(f"phi {f} MRw {m}", {"injector.bl_mass_fraction": f, "injector.bl_mixture_ratio": m})
                  for m in [1.6, 2.0, 2.4] for f in [0.04, 0.06, 0.08, 0.10, 0.12]],
    "opb_temperature": [(f"T_opb {v}", {"cycle.T_opb_K": v}) for v in [800.0, 820.0, 860.0, 900.0]],
    "fpb_temperature": [(f"T_fpb {v}", {"cycle.T_fpb_K": v}) for v in [1050.0, 1100.0, 1200.0, 1300.0]],
    "pump_inlet_pressure": [(f"p_in {v} bar", {"propellants.lox.p_inlet_bar": v, "propellants.lch4.p_inlet_bar": v})
                            for v in [5.0, 6.0, 8.0, 10.0]],
    "channel_roughness": [(f"Ra {v} um", {"cooling.roughness_um": v}) for v in [3.0, 5.0, 8.0, 15.0]],
    "bartz_factor": [(f"Bartz x{v}", {"cooling.bartz_factor": v}) for v in [0.8, 1.0, 1.2]],
    "tip_clearance": [(f"clearance {v} mm", {"cycle.tip_clearance_mm": v}) for v in [0.15, 0.25, 0.40]],
    "nozzle_circuit_fraction": [(f"phi_B {v}", {"cooling.nozzle_circuit_fraction": v}) for v in [0.2, 0.3, 0.4, 0.5]],
}


if __name__ == "__main__":
    only = sys.argv[1:]
    out_dir = ROOT / "results" / "trades"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = ROOT / "results" / "trades.json"
    allres = json.load(open(path)) if path.exists() else {}
    t0 = time.time()
    for name, cases in STUDIES.items():
        if only and name not in only:
            continue
        rows = [run_case(lbl, mods) for lbl, mods in cases]
        allres[name] = rows
        keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("label", "feasible"), k))
        with open(out_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        ok = sum(r["feasible"] for r in rows)
        print(f"[{name}] {ok}/{len(rows)} feasible ({time.time() - t0:.0f} s)")
    json.dump(allres, open(path, "w"), indent=1)
