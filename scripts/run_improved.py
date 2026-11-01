"""Cumulative improvement chain on the baseline (low-complexity changes only), then the
chamber-pressure uprate that the recovered margin allows. Writes results/improvements.json
and results/design_improved.json (input for the improved CAD build)."""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffsc import ROOT, load_config  # noqa: E402
from ffsc.design import design, _jsonable  # noqa: E402
from run_trades import metrics  # noqa: E402

STEPS = [
    ("Baseline", "-", {}),
    ("Polish AM channels (Ra 8 -> 3 um)", "abrasive-flow finish of the L-PBF channels; process change only",
     {"cooling.roughness_um": 3.0}),
    ("Coolant split 30/70 -> 50/50", "re-size the circuit-B orifice; no new parts",
     {"cooling.nozzle_circuit_fraction": 0.5}),
    ("Shrouded turbine rotors (clearance 0.25 -> 0.15 mm)", "integral tip shroud on the AM blisk",
     {"cycle.tip_clearance_mm": 0.15}),
    ("Close-coupled hot-gas path (dP 3 -> 1.5 % pc)", "collector welded to the injector inlet, no spool or flange pair",
     {"cycle.dp_hot_gas_duct_frac": 0.015}),
]
OPTIONS = [   # evaluated on top of the chain, reported separately (each has a real cost)
    ("Outer-row bias O/F 2.0 -> 1.8, share 8 -> 7 %", "costs ~0.5 s Isp, halves jacket dP",
     {"injector.bl_mixture_ratio": 1.8, "injector.bl_mass_fraction": 0.07}),
    ("Pump inlet 6 -> 8 bar", "vehicle tank pressure; faster, smaller turbopumps",
     {"propellants.lox.p_inlet_bar": 8.0, "propellants.lch4.p_inlet_bar": 8.0}),
    ("OPB 820 -> 860 K", "needs ox-rich alloy qualification at 860 K", {"cycle.T_opb_K": 860.0}),
]


def apply(cfg, mods):
    for path, value in mods.items():
        node = cfg
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value


def evaluate(cfg):
    try:
        res, _, _ = design(cfg, verbose=False, write=False)
        return res, metrics(res)
    except Exception as err:
        return None, {"feasible": False, "error": str(err)[:160]}


if __name__ == "__main__":
    cfg = copy.deepcopy(load_config())
    chain = []
    for name, how, mods in STEPS:
        apply(cfg, mods)
        res, m = evaluate(cfg)
        chain.append({"step": name, "how": how, **mods, **m})
        print(f"{name:52s} Isp {m.get('isp_sl', 0):6.1f} s  p_ox {m.get('p_ox_dis_bar', 0):6.0f}  "
              f"p_fu {m.get('p_fu_dis_bar', 0):6.0f} bar  dP_jk {m.get('dp_jacket_bar', 0):5.0f}  Twg {m.get('Twg_max_K', 0):4.0f} K")
    base = chain[0]
    options = []
    for name, how, mods in OPTIONS:
        c2 = copy.deepcopy(cfg)
        apply(c2, mods)
        _, m = evaluate(c2)
        options.append({"option": name, "how": how, **mods, **m})
        print(f"  option {name:44s} Isp {m.get('isp_sl', 0):6.1f}  p_ox {m.get('p_ox_dis_bar', 0):5.0f}  p_fu {m.get('p_fu_dis_bar', 0):5.0f}  "
              f"N_ox {m.get('N_ox_rpm', 0):6.0f}  R_env_ox {m.get('R_env_ox_tpa_mm', 0):4.0f} mm")
    # uprate: highest chamber pressure whose pump discharge pressures stay at or below the baseline's
    uprate = []
    best = None
    for pc in [355.0, 360.0, 365.0, 370.0, 375.0, 380.0, 390.0]:
        c2 = copy.deepcopy(cfg)
        c2["requirements"]["pc_bar"] = pc
        res, m = evaluate(c2)
        ok = m.get("feasible") and m["p_fu_dis_bar"] <= base["p_fu_dis_bar"] + 1 and m["p_ox_dis_bar"] <= base["p_ox_dis_bar"] + 1 \
            and m["Twg_max_K"] <= 881
        uprate.append({"pc_bar": pc, "within_baseline_pressures": bool(ok), **m})
        print(f"  uprate pc {pc:.0f}: {'OK ' if ok else 'no '} Isp {m.get('isp_sl', 0):.1f}  p_ox {m.get('p_ox_dis_bar', 0):.0f}  p_fu {m.get('p_fu_dis_bar', 0):.0f}")
        if ok:
            best = (pc, res, c2)
    out = {"chain": chain, "options": options, "uprate": uprate}
    if best:
        pc, res, c2 = best
        out["improved_pc_bar"] = pc
        json.dump(res, open(ROOT / "results" / "design_improved.json", "w"), indent=2, default=_jsonable)
    # keep the improved design at the baseline chamber pressure too (same thrust, lower loads)
    design(cfg, verbose=False, write=True, out_dir=ROOT / "results" / "improved")   # CAD input for the improved engine
    json.dump(cfg, open(ROOT / "results" / "improved" / "config_improved.json", "w"), indent=2)
    json.dump(out, open(ROOT / "results" / "improvements.json", "w"), indent=2, default=_jsonable)
