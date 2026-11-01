"""Economics layer: unit cost, learning curve and development cost for the two build strategies,
cost of every option in the register, and the component selection log.

Reads cad/output_improved/bom.csv (the iteration-1 improved engine), results/options.json and the
variant builds in cad/variants/. Writes results/economics.json, figures fig12_cost and fig13_nre_options,
and docs/COMPONENT_SELECTION.md.
"""

import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ffsc import ROOT  # noqa: E402
from ffsc.economics import CostModel, Sampler, load, pct, read_bom, top_down  # noqa: E402
from figstyle import C, plt, save  # noqa: E402

N_MC = 4000
SCEN = {"conventional": "Conventional, buy to print", "inhouse_am": "In-house AM",
        "hybrid": "Hybrid (cheaper route per group)"}
HYBRID_ROUTES = {}
BOM0 = read_bom(ROOT / "cad" / "output_improved" / "bom.csv")
D0 = json.load(open(ROOT / "results" / "improved" / "design.json"))
COST = load("costs.yaml")
OPTCFG = {o["id"]: o for o in load("options.yaml")["options"]}
OPTRES = json.load(open(ROOT / "results" / "options.json"))
SUPER = {"Thrust chamber": ["chamber_liner", "nozzle", "coolant_manifolds", "jumpers"],
         "Injector": ["injector_structure", "injector_posts", "tvc_lugs"],
         "Turbomachinery": ["turbine_rotor", "turbine_stator", "hot_gas_housings", "pump_housings",
                            "impellers_inducers", "shafts", "bearings"],
         "Preburners, igniters": ["preburners", "igniters"], "Valves": ["valves"],
         "Ducts, flanges": ["ducts", "flanges"], "Fasteners, seals, sensors": ["fasteners", "seals", "instrumentation"],
         "Gimbal": ["gimbal"]}


def mass(bom):
    return sum(float(r["mass_kg"]) for r in bom)


# ------------------------------------------------------------------ BOM edits for the options
def modify_bom(bom, ev):
    rows = [dict(r) for r in bom if not any(re.search(p, r["part"]) for p in ev.get("remove", []))]
    for pat, f in ev.get("scale", {}).items():
        for r in rows:
            if re.search(pat, r["part"]):
                r["mass_kg"] = str(float(r["mass_kg"]) * f)
    for pat in ev.get("merge_parts", []):
        grp = [r for r in rows if re.search(pat, r["part"])]
        if len(grp) > 1:
            keep = dict(grp[0], qty="1", mass_kg=str(sum(float(r["mass_kg"]) for r in grp)))
            rows = [r for r in rows if r not in grp] + [keep]
    if ev.get("flange_joint"):
        j = next(j for j in D0["joints"] if j["name"] == ev["flange_joint"])
        ring = math.pi / 4 * (j["flange_od_m"] ** 2 - j["D_seal_m"] ** 2) * j["flange_t_m"] * 8190.0
        for r in rows:
            if r["part"] in ("Chamber_GRCop42_regen", "Nozzle_In718_regen"):
                r["mass_kg"] = str(float(r["mass_kg"]) - ring)
    return rows


def group_cost(uc, ids):
    return sum(uc["groups"].get(g, 0.0) for g in ids)


def option_costs(S):
    """Recurring cost change (hybrid strategy) and NRE of every option."""
    sc = "hybrid"

    def CM(bom, d, extra_welds=0):
        return CostModel(bom, d, sc, S, extra_welds=extra_welds, routes=HYBRID_ROUTES)
    base_uc = CM(BOM0, D0).unit_cost()
    base = base_uc["total"]
    oc = COST["option_costs"]
    eng = S("labor_usd_h.engineering", COST["labor_usd_h"]["engineering"])
    test = S("nre.test_cost_usd", COST["nre"]["test_cost_usd"])
    out = {}
    for row in OPTRES["options"]:
        oid = row["id"]
        ev = OPTCFG[oid]["eval"]
        d_rec, note = None, ""
        if ev["type"] == "bom":
            rows = modify_bom(BOM0, ev)
            welds = sum(1 for r in BOM0 if r["part"].endswith("_seal")) - sum(1 for r in rows if r["part"].endswith("_seal"))
            if oid in ("N2", "I5"):
                welds = 0
            d_rec = CM(rows, D0, extra_welds=welds).unit_cost()["total"] - base
            if oid == "I5":
                d_rec = d_rec + S("oc.I5", oc["I5_bimetallic_premium_usd"])
            if oid == "N2":
                d_rec = d_rec + 2 * S("oc.N2", oc["N2_ignition_unit_usd"])
                note = "torch-igniter propellant taps and valves are not in the CAD BOM, so the saving is understated"
        elif ev["type"] == "variant":
            vb = read_bom(ROOT / "cad" / "variants" / ev["name"] / "bom.csv")
            vd = json.load(open(ROOT / "results" / "variants" / ev["name"] / "design.json"))
            rb = read_bom(ROOT / "cad" / "variants" / ev["ref"] / "bom.csv")
            rd = json.load(open(ROOT / "results" / "variants" / ev["ref"] / "design.json"))
            d_rec = CM(vb, vd).unit_cost()["total"] - CM(rb, rd).unit_cost()["total"]
            if oid == "Y2":                                  # carries the C3, C4 and C5 hardware with it
                d_rec = d_rec + 84 * S("oc.C3", oc["C3_sx_blade_usd"]) \
                    + S("oc.C4", oc["C4_ox_hot_section_premium"]) * sum(r["cost"] for r in base_uc["rows"] if r["part"].startswith("LOX_") and r["group"] in ("turbine_rotor", "turbine_stator", "hot_gas_housings", "preburners")) \
                    + S("oc.C5", oc["C5_second_stage_premium"]) * group_cost(base_uc, ["turbine_rotor", "turbine_stator"])
        elif oid == "C1":
            d_rec = (S("oc.C1", oc["C1_bearing_premium"]) - 1) * sum(r["cost"] for r in base_uc["rows"] if r["part"].startswith("CH4_bearing"))
        elif oid == "C2":
            d_rec = 2 * S("oc.C2", oc["C2_hydrostatic_usd_per_position"]) - sum(r["cost"] for r in base_uc["rows"] if r["part"].startswith("CH4_bearing"))
        elif oid == "C3":
            d_rec = 84 * S("oc.C3", oc["C3_sx_blade_usd"])
        elif oid == "C4":
            d_rec = S("oc.C4", oc["C4_ox_hot_section_premium"]) * sum(
                r["cost"] for r in base_uc["rows"] if r["part"].startswith("LOX_") and r["group"] in ("turbine_rotor", "turbine_stator", "hot_gas_housings", "preburners"))
        elif oid == "C5":
            d_rec = S("oc.C5", oc["C5_second_stage_premium"]) * group_cost(base_uc, ["turbine_rotor", "turbine_stator"])
        elif oid == "N3":
            r = row["result"]
            kwh = r["electric_power_kW"] * r["burn_s"] / 3600.0
            d_rec = r["electric_power_kW"] * S("oc.N3m", oc["N3_motor_inverter_usd_per_kW"]) + kwh * S("oc.N3b", oc["N3_battery_usd_per_kWh"])
            note = "plus the turbopump saving of variant Y1; battery recharge per flight not costed"
        elif oid == "N4":
            d_rec = row["result"]["power_kW"] * S("oc.N4", oc["N4_alternator_usd_per_kW"])
        elif oid == "N1":
            note = "not viable at preburner pressure (see results/pac.json); no recurring cost estimated"
        elif oid == "N5":
            d_rec = np.zeros(S.n)
            note = "injector development only"
        nre = COST["nre"]["option_class_hours"][OPTCFG[oid]["nre"]] * eng + COST["nre"]["option_class_tests"][OPTCFG[oid]["nre"]] * test
        out[oid] = {"d_recurring_usd": pct(d_rec) if d_rec is not None else None, "nre_usd": pct(nre), "note": note}
        print(f"{oid:3s} d_rec P50 {np.median(d_rec) / 1e3 if d_rec is not None else float('nan'):9.1f} k$   NRE P50 {np.median(nre) / 1e6:6.1f} M$")
    return out, pct(base)


def run():
    S = Sampler(N_MC)
    out = {"n_samples": N_MC, "engine": "I1 improved (cad/output_improved)", "mass_kg": mass(BOM0), "scenarios": {}}
    models = {}
    for sc, lab in SCEN.items():
        if sc == "hybrid":                                   # cheaper P50 route of the two pure strategies, per group
            for g in load("components.yaml")["groups"]:
                cc = np.median(models["conventional"][1]["groups"].get(g["id"], 0.0))
                ca = np.median(models["inhouse_am"][1]["groups"].get(g["id"], 0.0))
                HYBRID_ROUTES[g["id"]] = g["routes"]["inhouse_am"] if ca < cc else g["routes"]["conventional"]
            out["hybrid_routes"] = dict(HYBRID_ROUTES)
        cm = CostModel(BOM0, D0, sc, S, routes=HYBRID_ROUTES if sc == "hybrid" else None)
        uc = cm.unit_cost()
        lr = cm.learning(uc, [1, 10, 100, 1000])
        nre = cm.nre(uc)
        models[sc] = (cm, uc, lr, nre)
        n_items = len(BOM0)
        cots_items = sum(1 for r in uc["rows"] if r["category"] == "COTS")
        cots_pieces = sum(r["qty"] for r in uc["rows"] if r["category"] == "COTS")
        out["scenarios"][sc] = {
            "label": lab, "unit_cost_T1": pct(uc["total"]),
            "categories": {k: pct(v) for k, v in uc["categories"].items()},
            "assembly_test": pct(uc["assembly_test"]), "assembly_hours": uc["assembly_hours"],
            "groups_P50": {k: float(np.median(v)) for k, v in uc["groups"].items()},
            "cots_share_of_cost_P50": float(np.median(uc["categories"]["COTS"] / uc["total"])),
            "cots_line_items": [cots_items, n_items], "cots_pieces": [cots_pieces, sum(int(r["qty"]) for r in BOM0)],
            "learning": {str(N): {"unit": pct(v["unit"]), "average": pct(v["average"])} for N, v in lr.items()},
            "nre": {k: pct(v) for k, v in nre.items()},
            "cost_per_kN_T1_P50": float(np.median(uc["total"])) / (D0["config"]["requirements"]["thrust_sl_kN"]),
        }
        s = out["scenarios"][sc]
        print(f"{lab:28s} T1 P50 ${s['unit_cost_T1']['P50'] / 1e6:5.2f}M (P10 {s['unit_cost_T1']['P10'] / 1e6:4.2f}, "
              f"P90 {s['unit_cost_T1']['P90'] / 1e6:4.2f})  unit@100 ${s['learning']['100']['unit']['P50'] / 1e6:4.2f}M  "
              f"unit@1000 ${s['learning']['1000']['unit']['P50'] / 1e6:4.2f}M  NRE ${s['nre']['total']['P50'] / 1e9:4.2f}B  "
              f"COTS {100 * s['cots_share_of_cost_P50']:.1f} % of cost")
    td = top_down(mass(BOM0), S)
    out["top_down"] = {k: pct(v) for k, v in td.items()}
    out["benchmarks_usd"] = COST["benchmarks_usd"]
    print("TRANSCOST dev P50 $%.2fB, T1 A $%.1fM, B $%.1fM; SVLCM NRE $%.2fB, T1 $%.1fM" % (
        np.median(td["transcost_dev"]) / 1e9, td["transcost_t1_A"] / 1e6, td["transcost_t1_B"] / 1e6,
        td["svlcm_nre"] / 1e9, td["svlcm_t1"] / 1e6))
    out["options"], out["options_base_hybrid_T1"] = option_costs(S)
    json.dump(out, open(ROOT / "results" / "economics.json", "w"), indent=2, default=float)
    fig_cost(out, models)
    fig_nre_options(out)
    write_selection_log(models)
    return out


# ------------------------------------------------------------------ figures
def fig_cost(out, models):
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.2), gridspec_kw={"width_ratios": [1.15, 1]})
    a = ax[0]
    cols = ["#b5651d", "#6b6f7a", "#1f5fa8", "#e0a030", "#6a3d9a", "#2e7d32", "#9e9e9e", "#c9b38a", "#222222"]
    y = np.arange(len(SCEN))
    for i, (sc, lab) in enumerate(SCEN.items()):
        _, uc, _, _ = models[sc]
        left = 0.0
        for (name, ids), col in zip(list(SUPER.items()) + [("Assembly, acceptance test", None)], cols):
            v = np.median(uc["assembly_test"]) if ids is None else sum(np.median(uc["groups"].get(g, 0.0)) for g in ids)
            a.barh(i, v / 1e6, left=left, color=col, edgecolor="white", lw=0.4, label=name if i == 0 else None)
            left += v / 1e6
        t = out["scenarios"][sc]["unit_cost_T1"]
        a.errorbar(t["P50"] / 1e6, i, xerr=[[(t["P50"] - t["P10"]) / 1e6], [(t["P90"] - t["P50"]) / 1e6]], color="k",
                   capsize=2, lw=0.8, fmt="none")
    a.set_yticks(y, ["Conventional,\nbuy to print", "In-house AM", "Hybrid"])
    a.set_xlabel("first-unit cost T1 (USD million)")
    a.legend(fontsize=6, loc="upper center", bbox_to_anchor=(0.5, -0.25), ncol=3)
    a.set_title("(a) first engine, P50 by subsystem (bar: P10-P90 of total)")
    b = ax[1]
    n = np.array([1, 2, 5, 10, 20, 50, 100, 200, 500, 1000])
    for (sc, lab), col in zip(SCEN.items(), (C["in"], C["cu"], C["g"])):
        cm, uc, _, _ = models[sc]
        lr = cm.learning(uc, list(n))
        u = np.array([lr[k]["unit"] for k in n])
        b.fill_between(n, np.percentile(u, 10, axis=1) / 1e6, np.percentile(u, 90, axis=1) / 1e6, color=col, alpha=0.2, lw=0)
        b.plot(n, np.median(u, axis=1) / 1e6, color=col, label=lab)
    for lab, v in out["benchmarks_usd"].items():
        if v < 3e7:
            b.axhline(v / 1e6, color=C["k"], lw=0.5, ls=":")
            b.text(950, v / 1e6 * 1.07, lab, fontsize=6, ha="right")
    for k, lab, m, dy in (("transcost_t1_A", "TRANSCOST T1", "v", 0.80), ("svlcm_t1", "SVLCM T1", "^", 1.15)):
        b.plot(1, out["top_down"][k]["P50"] / 1e6, m, color=C["r"], ms=4)
        b.text(1.35, out["top_down"][k]["P50"] / 1e6 * dy, lab, fontsize=6, color=C["r"], va="center")
    b.set_xscale("log")
    b.set_yscale("log")
    b.set_ylim(0.15, 90)
    b.set_xlabel("unit number")
    b.set_ylabel("unit cost (USD million)")
    b.legend(fontsize=6.5, loc="upper right", bbox_to_anchor=(1.0, 0.78))
    b.set_title("(b) learning curve vs public figures")
    fig.tight_layout()
    save(fig, "fig12_cost")


def fig_nre_options(out):
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.0))
    a = ax[0]
    comps = ["design", "dev_hardware", "hot_fire_tests", "test_stand", "tooling_or_am_capex"]
    labs = ["design hours", "development engines", "hot-fire tests", "test stand", "tooling / AM capital"]
    cols = [C["ox"], C["in"], C["r"], C["k"], C["cu"]]
    for i, sc in enumerate(SCEN):
        left = 0.0
        for k, lab, col in zip(comps, labs, cols):
            v = out["scenarios"][sc]["nre"][k]["P50"] / 1e9
            a.barh(i, v, left=left, color=col, edgecolor="white", lw=0.4, label=lab if i == 0 else None)
            left += v
    td = out["top_down"]
    a.barh(3, td["svlcm_nre"]["P50"] / 1e9, color="#bbbbbb")
    t = td["transcost_dev"]
    a.barh(4, t["P50"] / 1e9, color="#bbbbbb", xerr=[[(t["P50"] - t["P10"]) / 1e9], [(t["P90"] - t["P50"]) / 1e9]],
           error_kw={"lw": 0.8, "capsize": 2})
    a.set_yticks(range(5), ["Conventional\n(bottom-up)", "In-house AM\n(bottom-up)", "Hybrid\n(bottom-up)",
                            "NASA SVLCM", "TRANSCOST 8.2"])
    a.set_xlabel("development cost (USD billion, P50)")
    a.legend(fontsize=6, loc="lower right")
    a.set_title("(a) development cost")
    b = ax[1]
    trl_c = {2: "#b71c1c", 4: "#e65100", 5: "#f9a825", 6: "#7cb342", 7: "#2e7d32", 8: "#1b5e20"}
    mk = {"component": "o", "integration": "s", "cycle": "D", "novel": "^"}
    tw0 = OPTRES["baseline"]["thrust_to_weight"]
    for row in OPTRES["options"]:
        r = row["result"]
        if "thrust_to_weight" not in r or row["id"] not in out["options"]:
            continue
        x = out["options"][row["id"]]["nre_usd"]["P50"] / 1e6
        yv = r["thrust_to_weight"] - tw0
        b.scatter(x, yv, marker=mk[row["category"]], color=trl_c.get(row["trl"], "#999999"), s=22, zorder=3)
        b.annotate(row["id"], (x, yv), fontsize=6, xytext=(3, 2), textcoords="offset points")
    for cat, m in mk.items():
        b.scatter([], [], marker=m, color="#777777", s=14, label=cat)
    b.set_xscale("log")
    b.set_xlabel("development cost of the option (USD million, P50)")
    b.set_ylabel("change in thrust-to-weight")
    b.axhline(0, color=C["k"], lw=0.5)
    b.legend(fontsize=6, loc="center right")
    b.set_title("(b) options: benefit vs development cost (colour: TRL)")
    fig.tight_layout()
    save(fig, "fig13_nre_options")


# ------------------------------------------------------------------ component selection log
def write_selection_log(models):
    groups = load("components.yaml")["groups"]
    routes_txt = {"cots_fastener": "COTS (ISO bolts, nuts, washers)", "cots_seal": "COTS metallic C-seal",
                  "cots_sensor": "COTS transducer", "cots_bearing": "COTS bearing, modified",
                  "custom_valve": "custom valve, COTS actuator parts", "custom_igniter": "custom torch igniter",
                  "lpbf": "L-PBF", "lpbf_liner": "L-PBF GRCop-42 liner, DED closeout", "ded_nozzle": "laser-wire DED",
                  "milled_channel_liner": "forged billet, milled channels, electroformed closeout",
                  "milled_channel_nozzle": "forged jacket, milled channels, brazed closeout",
                  "machined_forging": "machined from forging", "forged_ring": "machined from forged ring",
                  "investment_cast": "investment casting", "cast_superalloy": "vacuum-cast superalloy",
                  "fabricated": "bent tube / formed sheet, welded", "turned_brazed_posts": "turned posts, brazed in"}
    uc_c, uc_a, uc_h = models["conventional"][1], models["inhouse_am"][1], models["hybrid"][1]
    lines = ["# Component selection log", "",
             "Generated by `scripts/run_economics.py` from `config/components.yaml` and `config/costs.yaml`. "
             "Engine: iteration-1 improved design (`cad/output_improved/bom.csv`). Costs are first-unit P50 values "
             "in USD for each build strategy: conventional (buy to print, COTS wherever a catalogue part exists) "
             "and in-house AM (vertically integrated). They include supplier margin and inspection, but not "
             "assembly labour or the acceptance test. The hybrid strategy takes the cheaper route for each group.", "",
             "| Group | Items | Mass (kg) | Conventional route | In-house AM route | COTS | T1 conventional ($k) | T1 in-house AM ($k) | Hybrid picks |",
             "|---|---|---|---|---|---|---|---|---|"]
    tot_c = tot_a = 0.0
    for g in groups:
        rows = [r for r in BOM0 if re.search(g["pattern"], r["part"]) and
                next(gg for gg in groups if re.search(gg["pattern"], r["part"]))["id"] == g["id"]]
        if not rows:
            continue
        m = sum(float(r["mass_kg"]) for r in rows)
        cc, ca = float(np.median(uc_c["groups"].get(g["id"], 0))), float(np.median(uc_a["groups"].get(g["id"], 0)))
        tot_c += cc
        tot_a += ca
        lines.append(f"| {g['id']} | {sum(int(r['qty']) for r in rows)} | {m:.1f} | {routes_txt[g['routes']['conventional']]} | "
                     f"{routes_txt[g['routes']['inhouse_am']]} | {'yes' if g['cots'] else 'no'} | {cc / 1e3:.1f} | {ca / 1e3:.1f} | "
                     f"{'same' if g['routes']['conventional'] == g['routes']['inhouse_am'] else ('AM' if HYBRID_ROUTES.get(g['id']) == g['routes']['inhouse_am'] else 'conventional')} |")
    lines += ["", "## Decisions by group", ""]
    for g in groups:
        lines += [f"### {g['id']}", "", f"- Function: {g['function']}.",
                  f"- Conventional: {routes_txt[g['routes']['conventional']]}. In-house AM: {routes_txt[g['routes']['inhouse_am']]}.",
                  f"- Alternatives considered: {g['alternatives']}.",
                  f"- Why: {' '.join(g['rationale'].split())}", ""]
    (ROOT / "docs" / "COMPONENT_SELECTION.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    run()
