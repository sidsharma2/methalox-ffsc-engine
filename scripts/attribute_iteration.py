"""CAD-measured effect of each integration option in an iteration build.

Compares the bill of materials of an iteration build with a CAD variant that has the same cycle but
the iteration-1 layout (I2-C against I2_uprate400), group by group (config/components.yaml), and
prices both with the hybrid cost model. Writes results/iterations/<ID>/attribution.json.

    .venv/Scripts/python.exe scripts/attribute_iteration.py I2-C I2_uprate400
"""

import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffsc import ROOT  # noqa: E402
from ffsc.economics import CostModel, Sampler, load, pct, read_bom  # noqa: E402

G0 = 9.80665
# component groups -> the option that changes them
GROUP_OPTION = {"coolant_manifolds": "I2", "injector_structure": "I4", "injector_posts": "I4", "injector_single_piece": "I4",
                "flanges": "I1/I3", "seals": "I1/I3", "welds": "I1/I3", "fasteners": "I1/I3",
                "igniters": "N2", "laser_igniters": "N2", "bearings": "C1/C2", "hydrostatic_bearings": "C1/C2",
                "preburners": "K1", "ducts": "I1/I3"}


def group_of(groups, part):
    return next(g["id"] for g in groups if re.search(g["pattern"], part))


def by_group(bom, groups):
    out = {}
    for r in bom:
        g = group_of(groups, r["part"])
        out.setdefault(g, {"mass_kg": 0.0, "items": 0, "pieces": 0})
        out[g]["mass_kg"] += float(r["mass_kg"])
        out[g]["items"] += 1
        out[g]["pieces"] += int(r["qty"])
    return out


def main(bid, ref):
    groups = load("components.yaml")["groups"]
    b_new = read_bom(ROOT / "cad" / "iterations" / bid / "bom.csv")
    b_ref = read_bom(ROOT / "cad" / "variants" / ref / "bom.csv")
    d_new = json.load(open(ROOT / "results" / "iterations" / bid / "design.json"))
    d_ref = json.load(open(ROOT / "results" / "variants" / ref / "design.json"))
    gn, gr = by_group(b_new, groups), by_group(b_ref, groups)
    rows, per_option = [], {}
    for g in sorted(set(gn) | set(gr)):
        a, b = gn.get(g, {"mass_kg": 0, "items": 0, "pieces": 0}), gr.get(g, {"mass_kg": 0, "items": 0, "pieces": 0})
        dm = a["mass_kg"] - b["mass_kg"]
        if abs(dm) < 0.05 and a["pieces"] == b["pieces"]:
            continue
        opt = GROUP_OPTION.get(g, "cycle/other")
        rows.append({"group": g, "option": opt, "d_mass_kg": dm, "d_items": a["items"] - b["items"], "d_pieces": a["pieces"] - b["pieces"]})
        po = per_option.setdefault(opt, {"d_mass_kg": 0.0, "d_items": 0, "d_pieces": 0})
        po["d_mass_kg"] += dm
        po["d_items"] += a["items"] - b["items"]
        po["d_pieces"] += a["pieces"] - b["pieces"]
    hybrid = json.load(open(ROOT / "results" / "economics.json"))["hybrid_routes"]
    for g in ("hydrostatic_bearings", "laser_igniters", "welds", "injector_single_piece"):
        hybrid.setdefault(g, next(x for x in groups if x["id"] == g)["routes"]["inhouse_am"])
    S = Sampler(4000)
    welded = len(d_new["config"].get("cad", {}).get("welded_joints", []))
    routes_new = dict(hybrid)
    if d_new["config"].get("cad", {}).get("integral_manifolds"):     # printed onto the jacket: L-PBF, not fabricated
        routes_new["coolant_manifolds"] = next(x for x in groups if x["id"] == "coolant_manifolds")["routes"]["inhouse_am"]
    c_new = CostModel(b_new, d_new, "hybrid", S, routes=routes_new, extra_welds=2 * welded).unit_cost()
    c_ref = CostModel(b_ref, d_ref, "hybrid", S, routes=hybrid).unit_cost()
    m_new, m_ref = sum(float(r["mass_kg"]) for r in b_new), sum(float(r["mass_kg"]) for r in b_ref)
    # options the BOM does not show (blade alloy, hot-section alloy, second turbine stage): add their recurring cost
    eco = json.load(open(ROOT / "results" / "economics.json"))["options"]
    opts = d_new["config"].get("iteration", {}).get("options", [])
    adders = {o: eco[o]["d_recurring_usd"]["P50"] for o in ("C3", "C4", "C5") if o in opts or "Y2" in opts}
    thrust = d_new["config"]["requirements"]["thrust_sl_kN"] * 1e3
    out = {"build": bid, "reference": ref, "mass_kg": m_new, "ref_mass_kg": m_ref, "d_mass_kg": m_new - m_ref,
           "thrust_to_weight": thrust / (m_new * G0), "ref_thrust_to_weight": thrust / (m_ref * G0),
           "bom_items": [len(b_new), len(b_ref)], "pieces": [sum(int(r["qty"]) for r in b_new), sum(int(r["qty"]) for r in b_ref)],
           "unit_cost_T1": pct(c_new["total"]), "ref_unit_cost_T1": pct(c_ref["total"]),
           "non_bom_adders_P50": adders, "unit_cost_T1_P50_with_adders": float(np.median(c_new["total"])) + sum(adders.values()),
           "d_unit_cost_P50": float(np.median(c_new["total"] - c_ref["total"])),
           "assembly_hours": [c_new["assembly_hours"], c_ref["assembly_hours"]],
           "by_group": rows, "by_option": per_option}
    json.dump(out, open(ROOT / "results" / "iterations" / bid / "attribution.json", "w"), indent=2, default=float)
    print(f"{bid}: {m_new:.1f} kg vs {ref} {m_ref:.1f} kg (d {m_new - m_ref:+.1f}); T/W {out['thrust_to_weight']:.1f}; "
          f"T1 P50 ${np.median(c_new['total']) / 1e6:.2f}M vs ${np.median(c_ref['total']) / 1e6:.2f}M; "
          f"items {len(b_new)} vs {len(b_ref)}, pieces {out['pieces'][0]} vs {out['pieces'][1]}")
    for k, v in per_option.items():
        print(f"  {k:12s} d_mass {v['d_mass_kg']:+7.1f} kg  d_items {v['d_items']:+4d}  d_pieces {v['d_pieces']:+5d}")
    return out


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
