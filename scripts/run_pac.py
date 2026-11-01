"""Plasma-assisted combustion (PAC) screening for MFE-280: kinetics, discharge physics, power.

1. PSR extinction residence time of the fuel-rich preburner vs specific plasma energy (nominal and
   optimistic energy branching), compared with the design residence time.
2. Burning branch of a premixed ox-rich preburner (does plasma create one?).
3. Main-chamber kinetic margin (PSR extinction time vs chamber residence time).
4. Breakdown voltage per mm at each location vs the demonstrated pressure range and a 30 kV pulser.
5. Electrical power for the plasma and the mass of each power source over a booster burn.
Writes results/pac.json and figures/fig11_pac.(pdf|png).
"""

import json
import math
import re
import sys
import warnings
from pathlib import Path

import matplotlib.ticker
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")
from ffsc import ROOT  # noqa: E402
from ffsc.plasma import PSR, breakdown_voltage, comp, max_pressure_for_voltage, power_source_mass, tau_extinction  # noqa: E402
from figstyle import C, plt, save  # noqa: E402

NOV = yaml.safe_load(open(ROOT / "config" / "novel.yaml"))
PL = NOV["plasma"]
PL["e_p_J_kg"] = [float(x) for x in PL["e_p_J_kg"]]      # YAML 1.1 reads 1.0e3 as a string
D = json.load(open(ROOT / "results" / "improved" / "design.json"))
cy = D["cycle"]
LHV_CH4 = 50.0e6                                         # J/kg
FPB = {"mr": cy["mr_fpb"], "p": cy["p_fpb_Pa"], "T": D["config"]["cycle"]["T_fpb_K"], "tau": D["fpb"]["tau_s"],
       "mdot": cy["mdot_fpb"], "h_in": cy["fpb_gas"]["h"]}
OPB = {"mr": cy["mr_opb"], "p": cy["p_opb_Pa"], "T": D["config"]["cycle"]["T_opb_K"], "tau": D["opb"]["tau_s"],
       "mdot": cy["mdot_opb"], "h_in": cy["opb_gas"]["h"]}
OPT_MASS = json.load(open(ROOT / "cad" / "output_improved" / "mass_summary.json"))["by_assembly_kg"]
PB_SHELL_KG = next(float(r["mass_kg"]) for r in __import__("csv").DictReader(open(ROOT / "cad" / "output_improved" / "bom.csv"))
                   if r["part"] == "CH4_preburner_shell")
_OPTS = ROOT / "results" / "options.json"
BOOST = next(o["result"] for o in json.load(open(_OPTS))["options"] if o["id"] == "N3")


def main_chamber_residence():
    g, p = D["geometry"], D["performance"]
    At = math.pi * g["Rt_m"] ** 2
    V = D["config"]["chamber"]["Lstar_m"] * At
    rho = p["pc"] * 0.0233 / (8.314 * p["Tc_core"])      # M ~ 23 kg/kmol
    return rho * V / p["mdot"]


def ignition_delay(mr, p, T0, t_max=2.0):
    """Constant-pressure homogeneous ignition delay (s): time to a 15 K rise; None beyond t_max."""
    import cantera as ct
    g = ct.Solution("gri30.yaml")
    g.TPX = T0, p, comp(mr)
    r = ct.IdealGasConstPressureReactor(g, clone=False)
    net = ct.ReactorNet([r])
    t = 0.0
    while t < t_max:
        t = net.step()
        if r.T - T0 > 15.0:
            return t
    return None


def pc_deficit_MW():
    """LOX-shaft power deficit of the improved engine at 400 bar, from the pc sweep."""
    for e in json.load(open(ROOT / "results" / "pc_ceiling.json")):
        if e["enabler"].startswith("I1 improved"):
            for pt in e["points"]:
                m = re.search(r"best balance (-?[\d.]+) MW", pt.get("error", "") or "")
                if m:
                    return pt["pc_bar"], -float(m.group(1))
    return None, None


def run():
    out = {"inputs": PL, "anchor": "real inlet enthalpy from the cycle (liquid LOX, jacket-heated CH4)"}
    cases = {"nominal": (PL["alpha_O"], PL["eps_O_eV"]),
             "optimistic": (PL["alpha_O_range"][1], PL["eps_O_eV_range"][0])}
    # 1. FPB extinction vs plasma energy (PSR at the real inlet enthalpy)
    fpb = {}
    for tag, (a, e) in cases.items():
        rows = []
        for ep in PL["e_p_J_kg"]:
            t, s = tau_extinction(FPB["mr"], FPB["p"], FPB["T"], e_p=ep, tau_max=0.05, alpha_O=a, eps_O_eV=e,
                                  rel=0.03, h_in=FPB["h_in"])
            rows.append({"e_p_J_kg": ep, "tau_ext_s": t, "T_K": s["T_K"] if s else None, "power_MW": ep * FPB["mdot"] / 1e6})
            print(f"FPB {tag:10s} e_p {ep / 1e3:6.1f} kJ/kg  tau_ext {t * 1e3 if t else float('nan'):6.3f} ms  "
                  f"P {ep * FPB['mdot'] / 1e6:6.2f} MW")
        fpb[tag] = rows
    t_eq, _ = tau_extinction(FPB["mr"], FPB["p"], FPB["T"], tau_max=0.02, rel=0.02)   # old anchor, for the record
    psr = PSR(FPB["mr"], FPB["p"], FPB["T"], h_in=FPB["h_in"])
    burn = {f"{tau * 1e3:g} ms": psr.solve(tau) for tau in (0.1, 0.03, 0.01, 0.008)}
    out["fpb"] = {"design_tau_s": FPB["tau"], "mdot_kg_s": FPB["mdot"], "sweep": fpb,
                  "tau_ext_equilibrium_anchor_s": t_eq, "burning_branch": burn,
                  "HP_equilibrium_T_K": float(PSR(FPB["mr"], FPB["p"], FPB["T"], h_in=FPB["h_in"]).gas.T)}
    print(f"FPB with the old equilibrium anchor: tau_ext {t_eq * 1e3:.3f} ms (superseded)")

    # 2. OPB premixed burning branch at the real inlet enthalpy
    opb_rows = []
    for ep in (0.0, 1e4, 1e5, 3e5):
        try:
            psr = PSR(OPB["mr"], OPB["p"], OPB["T"], e_p=ep, alpha_O=cases["optimistic"][0],
                      eps_O_eV=cases["optimistic"][1], h_in=OPB["h_in"])
            s = psr.solve(0.1)
        except Exception:
            s = None
        burning = bool(s and s["burning"])
        opb_rows.append({"e_p_J_kg": ep, "burning_at_100ms": burning, "power_MW": ep * OPB["mdot"] / 1e6})
        print(f"OPB e_p {ep / 1e3:6.0f} kJ/kg  burns at 100 ms: {burning}  P {ep * OPB['mdot'] / 1e6:7.1f} MW")
    out["opb"] = {"design_tau_s": OPB["tau"], "premixed_rows": opb_rows}

    # 3. homogeneous ignition delays at the preburner pressures
    ign = {}
    for lab, d in (("OPB", OPB), ("FPB", FPB)):
        ign[lab] = {f"{T0:.0f}": ignition_delay(d["mr"], d["p"], T0) for T0 in (820.0, 900.0, 1000.0, 1100.0)}
        print(lab, "ignition delay ms", {k: (round(v * 1e3, 2) if v else "> 2000") for k, v in ign[lab].items()})
    out["ignition_delay_s"] = ign

    # 4. main chamber (CH4/O2 gas inlet with the sink set for Tc: slower than the real hot-gas inlet, so conservative)
    t_main, _ = tau_extinction(D["performance"]["mr"], D["performance"]["pc"], D["performance"]["Tc_core"], tau_max=1e-3)
    t_res = main_chamber_residence()
    out["main"] = {"tau_ext_s": t_main, "residence_s": t_res, "margin": t_res / t_main}
    print(f"MAIN tau_ext {t_main * 1e9:.0f} ns, residence {t_res * 1e3:.2f} ms, margin {t_res / t_main:.0f}x")

    # 5. breakdown
    T_fpb_real = out["fpb"]["HP_equilibrium_T_K"]
    locs = {"Start transient (5 bar, 300 K)": (5e5, 300.0), "NRP limit shown (12 bar, 300 K)": (12e5, 300.0),
            "Main chamber": (D["performance"]["pc"], 1000.0), "FPB": (FPB["p"], T_fpb_real), "OPB": (OPB["p"], OPB["T"])}
    gap = PL["gap_mm"] * 1e-3
    out["breakdown"] = {k: {"p_bar": p / 1e5, "T_K": T, "V_kV_per_mm": breakdown_voltage(p, T, gap, PL["EN_breakdown_Td"]) / 1e3}
                        for k, (p, T) in locs.items()}
    out["pulser_max_p_bar_300K"] = max_pressure_for_voltage(PL["pulser_kV"] * 1e3, 300.0, gap, PL["EN_breakdown_Td"]) / 1e5
    for k, v in out["breakdown"].items():
        print(f"  {k:36s} {v['p_bar']:6.0f} bar {v['T_K']:6.0f} K {v['V_kV_per_mm']:7.0f} kV/mm")

    # 6. physical fix for the FPB margin: longer residence time; pressure-vessel mass ~ p V
    tau_ext0 = fpb["nominal"][0]["tau_ext_s"]
    out["fpb_fix"] = {"tau_ext_s": tau_ext0, "design_tau_s": FPB["tau"], "margin_now": FPB["tau"] / tau_ext0,
                      "tau_new_s": 0.008, "margin_new": 0.008 / tau_ext0,
                      "shell_mass_added_kg": PB_SHELL_KG * (0.008 / FPB["tau"] - 1.0)}

    # 7. power density: what a plasma or electric concept needs from its power source
    srcs = NOV["power_sources"]
    turb_W = cy["ox_turbine"]["power_W"] + cy["fuel_turbine"]["power_W"]
    tpa_kg = sum(OPT_MASS.get(k, 0.0) for k in ("LOX_Turbopump", "CH4_Turbopump"))
    pc_def, P_def = pc_deficit_MW()
    p100 = next(r for r in fpb["nominal"] if r["e_p_J_kg"] == max(PL["e_p_J_kg"]))
    concepts = [
        {"name": "Plasma in the FPB to double its kinetic margin", "P_W": p100["power_MW"] * 1e6, "t_s": NOV["burn_s"],
         "budget_kg": out["fpb_fix"]["shell_mass_added_kg"], "alternative": "8 ms FPB residence time"},
        {"name": f"Electric drive on the LOX shaft to reach {pc_def:.0f} bar", "P_W": (P_def or 0) * 1e6,
         "t_s": NOV["burn_s"], "budget_kg": OPT_MASS.get("LOX_Turbopump", 0.0), "alternative": "options C3-C5 + Y1 (Y2)"},
        {"name": "Electric boost pumps, inlet 6 -> 10 bar", "P_W": BOOST["electric_power_kW"] * 1e3, "t_s": NOV["burn_s"],
         "budget_kg": BOOST["turbopump_mass_saved_kg"] - BOOST["motor_inverter_kg"] - BOOST["pump_hardware_kg"],
         "alternative": "tank pressure (Y1)"},
        {"name": "Plasma or laser start ignition", "P_W": 4.0e3, "t_s": 5.0, "budget_kg": 3.4, "alternative": "torch igniters"},
    ]
    for c in concepts:
        c["req_kW_per_kg"] = c["P_W"] / 1e3 / c["budget_kg"] if c["budget_kg"] > 0 else None
        c["req_Wh_per_kg"] = c["P_W"] * c["t_s"] / 3600.0 / c["budget_kg"] if c["budget_kg"] > 0 else None
        c["feasible_with"] = [k for k, s in srcs.items() if c["budget_kg"] > 0
                              and power_source_mass(c["P_W"], c["t_s"], s) <= c["budget_kg"]]
        print(f"  {c['name']:52s} P {c['P_W'] / 1e6:7.3f} MW budget {c['budget_kg']:7.1f} kg  needs "
              + (f"{c['req_kW_per_kg']:9.1f} kW/kg, {c['req_Wh_per_kg']:9.1f} Wh/kg" if c["req_kW_per_kg"] else "no budget")
              + f"  ok with: {c['feasible_with']}")
    mix_LHV = LHV_CH4 / (1 + D["performance"]["mr"])                # chemical energy per kg of propellant
    out["power_density"] = {
        "sources": {k: {"kW_per_kg": s["kW_per_kg"], "Wh_per_kg": s.get("Wh_per_kg")} for k, s in srcs.items()},
        "kilopower_kW_per_kg": 0.0067,
        "engine_turbines_W": turb_W, "turbopump_mass_kg": tpa_kg, "engine_turbomachinery_kW_per_kg": turb_W / 1e3 / tpa_kg,
        "propellant_chemical_Wh_per_kg": mix_LHV / 3600.0, "concepts": concepts}

    fpb_nom = {r["e_p_J_kg"]: r["tau_ext_s"] for r in fpb["nominal"]}
    fpb_opt = {r["e_p_J_kg"]: r["tau_ext_s"] for r in fpb["optimistic"]}
    out["summary"] = {
        "main_chamber_kinetic_margin": out["main"]["margin"],
        "fpb_tau_ext_ms_no_plasma": fpb_nom[0.0] * 1e3,
        "fpb_tau_ext_ms_10kJkg_optimistic": fpb_opt[1e4] * 1e3,
        "fpb_tau_ext_ms_100kJkg_nominal": fpb_nom[1e5] * 1e3,
        "fpb_design_tau_ms": FPB["tau"] * 1e3,
        "fpb_burning_T_K": T_fpb_real,
        "fpb_power_MW_at_100kJkg": 1e5 * FPB["mdot"] / 1e6,
        "opb_premixed_burns_with_plasma": any(r["burning_at_100ms"] for r in opb_rows),
        "opb_ignition_delay_ms_820K": (ign["OPB"]["820"] or float("nan")) * 1e3,
        "breakdown_kV_per_mm_OPB": out["breakdown"]["OPB"]["V_kV_per_mm"],
        "pulser_30kV_max_p_bar": out["pulser_max_p_bar_300K"],
        "fpb_fix_shell_kg": out["fpb_fix"]["shell_mass_added_kg"],
        "engine_turbomachinery_kW_per_kg": out["power_density"]["engine_turbomachinery_kW_per_kg"],
        "verdict": ("Not viable in steady combustion. The main chamber has a kinetic margin of about 50,000. A premixed "
                    "ox-rich preburner has no burning branch with or without plasma. The fuel-rich preburner is "
                    "kinetically marginal, but plasma needs MW to move it, while a longer residence time fixes it for "
                    "about 18 kg. Breakdown at 600 bar needs hundreds of kV per mm. Viable for start ignition at low "
                    "pressure (N2)."),
    }
    json.dump(out, open(ROOT / "results" / "pac.json", "w"), indent=2, default=float)
    figure(out)
    figure_power(out)
    return out


def figure(out):
    fig, ax = plt.subplots(1, 3, figsize=(7.2, 2.5))
    a = ax[0]
    for tag, col, ls in (("nominal", C["fu"], "-"), ("optimistic", C["p"], "--")):
        rows = [r for r in out["fpb"]["sweep"][tag] if r["tau_ext_s"]]
        a.plot([max(r["e_p_J_kg"], 300) / 1e3 for r in rows], [r["tau_ext_s"] * 1e3 for r in rows], ls, color=col,
               marker="o", ms=3, label=f"FPB, {tag} branching")
    a.axhline(out["fpb"]["design_tau_s"] * 1e3, color=C["k"], lw=0.8, ls=":")
    a.text(0.35, out["fpb"]["design_tau_s"] * 1e3 * 1.06, "design residence time", fontsize=7)
    a.set_xscale("log")
    a.set_yscale("log")
    a.set_ylim(1.5, 6.0)
    a.set_yticks([2, 3, 4, 5])
    a.yaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter("%g"))
    a.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    a.set_xlabel("specific plasma energy (kJ/kg)  [0 plotted at 0.3]")
    a.set_ylabel(r"PSR extinction time $\tau_{ext}$ (ms)")
    a.legend(loc="lower left", fontsize=7)
    a.set_title("(a) fuel-rich preburner kinetics")
    b = ax[1]
    p = np.logspace(0, 3, 100)
    for T, col in ((300.0, C["ox"]), (1000.0, C["r"])):
        b.plot(p, breakdown_voltage(p * 1e5, T, 1e-3, out["inputs"]["EN_breakdown_Td"]) / 1e3, color=col, label=f"{T:.0f} K")
    b.axhline(out["inputs"]["pulser_kV"], color=C["k"], lw=0.8, ls=":")
    b.text(1.2, out["inputs"]["pulser_kV"] * 1.15, "30 kV pulser", fontsize=7)
    b.axvspan(1, out["inputs"]["demonstrated_NRP_bar"], color=C["g"], alpha=0.12, lw=0)
    b.text(1.3, 900, "NRP shown", fontsize=7, color=C["g"])
    offs = {"Main chamber": (-62, -3), "FPB": (-26, -11), "OPB": (-30, 5)}
    for k, v in out["breakdown"].items():
        if v["p_bar"] > 100:
            lab = k.split(" (")[0]
            b.plot(v["p_bar"], v["V_kV_per_mm"], "s", color=C["k"], ms=3)
            b.annotate(lab, (v["p_bar"], v["V_kV_per_mm"]), fontsize=6, xytext=offs.get(lab, (-30, 6)),
                       textcoords="offset points")
    b.set_xscale("log")
    b.set_yscale("log")
    b.set_xlabel("pressure (bar)")
    b.set_ylabel("breakdown voltage, 1 mm gap (kV)")
    b.legend(loc="lower right", fontsize=7)
    b.set_title(r"(b) discharge at $E/N$ = 100 Td")
    c = ax[2]
    P = np.logspace(-1, 1, 50)
    names = {"li_ion_high_power": "Li-ion pack", "next_gen_cells": "next-gen cells", "shaft_alternator": "shaft alternator",
             "fission_microreactor": "fission reactor"}
    cols = [C["ox"], C["g"], C["fu"], C["r"]]
    srcs = yaml.safe_load(open(ROOT / "config" / "novel.yaml"))["power_sources"]
    for (k, lab), col in zip(names.items(), cols):
        c.plot(P, [power_source_mass(x * 1e6, NOV["burn_s"], srcs[k]) for x in P], color=col, label=lab)
    c.axhline(1796, color=C["k"], lw=0.8, ls=":")
    c.text(0.12, 2100, "engine mass", fontsize=7)
    c.set_xscale("log")
    c.set_yscale("log")
    c.set_xlabel("electrical power (MW)")
    c.set_ylabel(f"source mass for {NOV['burn_s']:.0f} s (kg)")
    c.legend(loc="upper left", fontsize=7)
    c.set_title("(c) power source")
    fig.tight_layout()
    save(fig, "fig11_pac")


def figure_power(out):
    pdn = out["power_density"]
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.3))
    names = {"fission_microreactor": "fission reactor (SP-100 *, Kilopower o)", "li_ion_high_power": "Li-ion pack",
             "next_gen_cells": "next-gen cells", "shaft_alternator": "shaft alternator + inverter"}
    cols = {"fission_microreactor": C["r"], "li_ion_high_power": C["ox"], "next_gen_cells": C["g"], "shaft_alternator": C["fu"]}
    a = ax[0]
    y = 0
    labels = []
    for k, lab in names.items():
        a.plot(pdn["sources"][k]["kW_per_kg"], y, "o", color=cols[k], ms=5)
        labels.append(lab)
        y += 1
    a.plot(pdn["kilopower_kW_per_kg"], 0, "o", mfc="none", color=C["r"], ms=5)
    a.plot(pdn["engine_turbomachinery_kW_per_kg"], y, "s", color=C["k"], ms=5)
    labels.append("engine turbopumps (this design)")
    y += 1
    for c in pdn["concepts"]:
        if c["req_kW_per_kg"]:
            a.plot(c["req_kW_per_kg"], y, "v", color=C["p"], ms=5)
        else:
            a.text(0.005, y, "no mass budget left", fontsize=6, va="center", color=C["p"])
        labels.append(c["name"].replace(" to reach", "\nto reach").replace(" to double", "\nto double"))
        y += 1
    a.set_yticks(range(len(labels)), labels, fontsize=6)
    a.set_ylim(-0.6, len(labels) - 0.4)
    a.set_xscale("log")
    a.set_xlim(0.003, 3e4)
    a.axhline(len(names) + 0.5, color=C["k"], lw=0.5)
    a.set_xlabel("specific power (kW/kg)")
    a.set_title("(a) power: sources (o) and what each concept needs (v)")
    b = ax[1]
    y = 0
    for k, lab in names.items():
        wh = pdn["sources"][k]["Wh_per_kg"]
        if wh:
            b.plot(wh, y, "o", color=cols[k], ms=5)
        else:
            b.text(1.3, y, "energy not limiting (turbines)" if k == "shaft_alternator" else "energy not limiting (fission fuel)",
                   fontsize=6, va="center", color=cols[k])
        y += 1
    b.plot(pdn["propellant_chemical_Wh_per_kg"], y, "s", color=C["k"], ms=5)
    blabels = list(names.values()) + ["CH4/O2 propellant, chemical"]
    y += 1
    for c in pdn["concepts"]:
        if c["req_Wh_per_kg"]:
            b.plot(c["req_Wh_per_kg"], y, "v", color=C["p"], ms=5)
        else:
            b.text(1.3, y, "no mass budget left", fontsize=6, va="center", color=C["p"])
        blabels.append(c["name"].replace(" to reach", "\nto reach").replace(" to double", "\nto double"))
        y += 1
    b.set_yticks(range(len(blabels)), blabels, fontsize=6)
    b.set_ylim(-0.6, len(blabels) - 0.4)
    b.set_xscale("log")
    b.set_xlim(1, 1e6)
    b.axhline(len(names) + 0.5, color=C["k"], lw=0.5)
    b.set_xlabel(f"specific energy over a {NOV['burn_s']:.0f} s burn (Wh/kg)")
    b.set_title("(b) energy")
    fig.tight_layout()
    save(fig, "fig14_power_density")


if __name__ == "__main__":
    run()
