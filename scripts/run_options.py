"""Evaluate the design-options register (config/options.yaml) against the iteration-1 improved engine.

Physics and mass only; costs are added by scripts/run_economics.py. Writes results/options.json.
"""

import copy
import csv
import json
import math
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ffsc import ROOT  # noqa: E402
from ffsc.design import _jsonable  # noqa: E402
from ffsc.plasma import power_source_mass  # noqa: E402
from run_improved import apply, evaluate  # noqa: E402

G0 = 9.80665
OPT = yaml.safe_load(open(ROOT / "config" / "options.yaml"))["options"]
NOVEL = yaml.safe_load(open(ROOT / "config" / "novel.yaml"))
BOM = list(csv.DictReader(open(ROOT / "cad" / "output_improved" / "bom.csv")))
MASS0 = sum(float(r["mass_kg"]) for r in BOM)
RES0 = json.load(open(ROOT / "results" / "improved" / "design.json"))
CFG0 = json.load(open(ROOT / "results" / "improved" / "config_improved.json"))
THRUST = CFG0["requirements"]["thrust_sl_kN"] * 1e3
_, M0 = evaluate(copy.deepcopy(CFG0))


def tw(mass):
    return THRUST / (mass * G0)


def match(patterns, name):
    return any(re.search(p, name) for p in patterns)


def is_fastener(name):
    return bool(re.search(r"(bolts|nuts_washers|washers|screws)$", name))


def flange_pair_mass(joint_name):
    j = next(j for j in RES0["joints"] if j["name"] == joint_name)
    rho = 8190.0                                         # Inconel 718; the eps-12 flanges are on the nozzle side
    ring = math.pi / 4 * (j["flange_od_m"] ** 2 - j["D_seal_m"] ** 2) * j["flange_t_m"] * rho
    return 2 * ring


def eval_bom(ev):
    removed = [r for r in BOM if match(ev.get("remove", []), r["part"])]
    dm = -sum(float(r["mass_kg"]) for r in removed)
    for pat, f in ev.get("scale", {}).items():
        dm += sum(float(r["mass_kg"]) * (f - 1.0) for r in BOM if re.search(pat, r["part"]))
    if ev.get("flange_joint"):
        dm -= flange_pair_mass(ev["flange_joint"])
    parts = -sum(int(r["qty"]) for r in removed if not is_fastener(r["part"]))
    fasteners = -sum(int(r["qty"]) for r in removed if is_fastener(r["part"]))
    joints = -sum(1 for r in removed if r["part"].endswith("_seal"))
    if ev.get("flange_joint"):
        joints -= 1
    for pat in ev.get("merge_parts", []):
        n = sum(int(r["qty"]) for r in BOM if re.search(pat, r["part"]))
        parts -= n - 1
    return {"d_mass_kg": dm, "d_parts": parts, "d_fasteners": fasteners, "d_bolted_joints": joints,
            "removed": [r["part"] for r in removed]}


def eval_cycle(ev):
    cfg = copy.deepcopy(CFG0)
    apply(cfg, ev["mods"])
    _, m = evaluate(cfg)
    if not m.get("feasible"):
        return {"feasible": False, "error": m.get("error")}
    return {"d_isp_sl_s": m["isp_sl"] - M0["isp_sl"], "d_p_ox_bar": m["p_ox_dis_bar"] - M0["p_ox_dis_bar"],
            "d_p_fu_bar": m["p_fu_dis_bar"] - M0["p_fu_dis_bar"], "p_ox_bar": m["p_ox_dis_bar"],
            "p_fu_bar": m["p_fu_dis_bar"], "N_ox_rpm": m["N_ox_rpm"], "N_fu_rpm": m["N_fu_rpm"]}


def variant(name):
    d = ROOT / "results" / "variants" / name
    cad = json.load(open(d / "cad_summary.json"))
    res = json.load(open(d / "design.json"))
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_trades import metrics
    return cad, metrics(res), res


def eval_variant(ev):
    cad, m, _ = variant(ev["name"])
    cad0, m0, _ = variant(ev["ref"])
    return {"d_mass_kg": cad["mass_kg"] - cad0["mass_kg"], "mass_kg": cad["mass_kg"], "clashes": cad["clashes"],
            "d_isp_sl_s": m["isp_sl"] - m0["isp_sl"], "p_ox_bar": m["p_ox_dis_bar"], "p_fu_bar": m["p_fu_dis_bar"],
            "d_p_ox_bar": m["p_ox_dis_bar"] - m0["p_ox_dis_bar"], "d_p_fu_bar": m["p_fu_dis_bar"] - m0["p_fu_dis_bar"],
            "N_ox_rpm": m["N_ox_rpm"], "N_fu_rpm": m["N_fu_rpm"], "Dt_mm": m["Dt_mm"],
            "by_assembly_d_kg": {k: cad["by_assembly_kg"][k] - cad0["by_assembly_kg"][k] for k in cad["by_assembly_kg"]},
            "envelope_mm": cad["envelope_mm"], "ref_envelope_mm": cad0["envelope_mm"]}


# ------------------------------------------------------------------ dedicated calculations
def bearing_dn(_ev):
    lim = NOVEL["bearings"]
    rows = []
    for tag, res in [("I1 improved", RES0)] + [(n, variant(n)[2]) for n in ("I2_inlet10", "I2_uprate400")
                                               if (ROOT / "results" / "variants" / n / "design.json").exists()]:
        c = res["cycle"]
        for side in ("ox", "fuel"):
            d_mm = 5.0 * math.ceil(200 * c[f"{side}_shaft"]["D_m"])   # bearing bore = shaft rounded up to 5 mm, as in the CAD
            N = c[f"{side}_pump"]["N_rpm"]
            rows.append({"case": tag, "pump": side, "d_shaft_mm": d_mm, "N_rpm": N, "DN_million": d_mm * N / 1e6})
    return {"rows": rows, "limits_million_DN": lim}


def boost_pump(_ev):
    b = NOVEL["boost_pump"]
    dp = (b["p_inlet_to_bar"] - b["p_inlet_from_bar"]) * 1e5
    c = RES0["cycle"]
    P = sum(c[f"{s}_pump"]["mdot"] * dp / (c[f"{s}_pump"]["rho"] * b["eta_pump"]) for s in ("ox", "fuel"))
    P_el = P / b["eta_motor_inverter"]
    m_motor = P_el / (b["motor_inverter_kW_per_kg"] * 1e3)
    m_pumps = b["pump_hardware_kg"]
    out = {"shaft_power_kW": P / 1e3, "electric_power_kW": P_el / 1e3, "burn_s": NOVEL["burn_s"],
           "motor_inverter_kg": m_motor, "pump_hardware_kg": m_pumps, "sources": {}}
    for k, src in NOVEL["power_sources"].items():
        m_src = power_source_mass(P_el, NOVEL["burn_s"], src)
        out["sources"][k] = {"source_kg": m_src, "total_added_kg": m_src + m_motor + m_pumps}
    try:
        out["turbopump_mass_saved_kg"] = -eval_variant({"name": "I2_inlet10", "ref": "I2_ref350"})["d_mass_kg"]
    except FileNotFoundError:
        out["turbopump_mass_saved_kg"] = None
    return out


def alternator(_ev):
    a = NOVEL["alternator"]
    P = a["power_kW"] * 1e3
    m_alt = P / (a["kW_per_kg"] * 1e3)
    out = {"power_kW": a["power_kW"], "alternator_kg": m_alt, "battery_equivalent": {}}
    for k, src in NOVEL["power_sources"].items():
        out["battery_equivalent"][k] = power_source_mass(P, NOVEL["burn_s"], src)
    return out


def pattern_factor(_ev):
    pf = NOVEL["pattern_factor"]
    T0, Tin = CFG0["cycle"]["T_opb_K"], pf["T_inlet_K"]
    T_peak = T0 + pf["PF_baseline"] * (T0 - Tin)
    T_new = (T_peak + pf["PF_improved"] * Tin) / (1 + pf["PF_improved"])
    r = eval_cycle({"mods": {"cycle.T_opb_K": T_new}})
    return {"T_peak_K": T_peak, "T_mean_baseline_K": T0, "T_mean_allowed_K": T_new, **r}


def plasma(_ev):
    p = ROOT / "results" / "pac.json"
    return json.load(open(p))["summary"] if p.exists() else {"note": "run scripts/run_pac.py first"}


CALC = {"bearing_dn": bearing_dn, "boost_pump": boost_pump, "alternator": alternator,
        "pattern_factor": pattern_factor, "plasma": plasma}


def run():
    out = {"baseline": {"name": "I1 improved", "mass_kg": MASS0, "thrust_to_weight": tw(MASS0), **M0}, "options": []}
    for o in OPT:
        ev = o["eval"]
        if ev["type"] == "bom":
            r = eval_bom(ev)
        elif ev["type"] == "cycle":
            r = eval_cycle(ev)
        elif ev["type"] == "variant":
            r = eval_variant(ev)
        else:
            r = CALC[ev["fn"]](ev)
        if "d_mass_kg" in r:
            r["thrust_to_weight"] = tw(MASS0 + r["d_mass_kg"])
        row = {k: o[k] for k in ("id", "name", "category", "trl", "nre", "make_buy")}
        row["physics"] = " ".join(o["physics"].split())
        row["result"] = r
        out["options"].append(row)
        brief = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items()
                 if k in ("d_mass_kg", "d_isp_sl_s", "d_p_ox_bar", "d_p_fu_bar", "d_parts", "d_fasteners", "thrust_to_weight")}
        print(f"{o['id']:3s} {o['name'][:58]:58s} {brief}")
    json.dump(out, open(ROOT / "results" / "options.json", "w"), indent=2, default=_jsonable)
    return out


if __name__ == "__main__":
    run()
