"""Hybrid build strategy of the selected iteration: manufacturing route, make/buy, quantity, mass
and first-unit (T1) cost of every BOM part and component group, from the cost model.

    CostModel(bom, design, "hybrid", Sampler(n=1, mode="nominal"), routes=HYBRID)

HYBRID = results/economics.json["hybrid_routes"] (the cheaper P50 route of each group);
groups that are not in it (added for later iterations in config/components.yaml) take their
in-house AM route from components.yaml, as scripts/attribute_iteration.py does. With config
cad.integral_manifolds the coolant manifolds are printed onto the jacket, so that group takes its
in-house AM route instead of the fabricated hybrid route (INTEGRAL_OVERRIDE; set it False to price
them exactly as attribute_iteration.py does).

Used by make_mfg_sheet.py (sheet MFG-009) and scripts/render_mfg.py (route-coloured renders).
"""

import csv
import json
import sys

import numpy as np

import itercfg as IT

sys.path.insert(0, str(IT.ROOT))
from ffsc.economics import CostModel, Sampler, load  # noqa: E402

# route class: legend label, colour (sRGB hex), lane of the process flow
CLASSES = {
    "lpbf": ("L-PBF, IN-HOUSE", "#E8833A"),
    "ded": ("LASER-WIRE DED, IN-HOUSE", "#C0392B"),
    "cast": ("VACUUM / INVESTMENT CASTING, BOUGHT", "#8E5DB5"),
    "forging": ("MACHINED FROM FORGING, BOUGHT", "#2F76BE"),
    "fab": ("FABRICATED TUBE AND WELDS, BOUGHT TO PRINT", "#3E9B4F"),
    "custom": ("CUSTOM UNIT: VALVES (MAKE), IGNITERS (BUY)", "#E2B21C"),
    "cots": ("COTS (CATALOGUE PARTS)", "#8C8F96"),
}
ROUTE_CLASS = {"lpbf": "lpbf", "lpbf_liner": "lpbf", "ded_nozzle": "ded", "investment_cast": "cast",
               "cast_superalloy": "cast", "machined_forging": "forging", "forged_ring": "forging",
               "turned_brazed_posts": "forging", "milled_channel_liner": "forging", "milled_channel_nozzle": "forging",
               "fabricated": "fab", "custom_valve": "custom", "custom_igniter": "custom", "cots_fastener": "cots",
               "cots_seal": "cots", "cots_bearing": "cots", "cots_sensor": "cots"}
ROUTE_LABEL = {"lpbf": "L-PBF", "lpbf_liner": "L-PBF LINER + CLOSEOUT", "ded_nozzle": "LASER-WIRE DED",
               "investment_cast": "INVESTMENT CASTING", "cast_superalloy": "VACUUM-CAST SUPERALLOY",
               "machined_forging": "MACHINED FORGING", "forged_ring": "MACHINED RING FORGING",
               "turned_brazed_posts": "TURNED + BRAZED", "milled_channel_liner": "MILLED LINER",
               "milled_channel_nozzle": "MILLED NOZZLE", "fabricated": "FABRICATED TUBE / WELD",
               "custom_valve": "CUSTOM VALVE", "custom_igniter": "CUSTOM IGNITER", "cots_fastener": "COTS FASTENER",
               "cots_seal": "COTS C-SEAL", "cots_bearing": "COTS BEARING (MODIFIED)", "cots_sensor": "COTS SENSOR"}
GROUP_LABEL = {"fasteners": "FASTENERS", "seals": "STATIC SEALS", "instrumentation": "TRANSDUCERS, SPEED PICK-UPS",
               "valves": "MAIN + PREBURNER VALVES", "bearings": "ROLLING BEARINGS",
               "hydrostatic_bearings": "HYDROSTATIC BEARINGS", "laser_igniters": "LASER IGNITERS",
               "welds": "DUCT BUTT WELDS", "igniters": "TORCH IGNITERS", "chamber_liner": "CHAMBER, LINER + CLOSEOUT",
               "nozzle": "NOZZLE, CHANNEL WALL", "coolant_manifolds": "COOLANT MANIFOLDS",
               "jumpers": "COOLANT JUMPERS", "flanges": "FLANGES", "injector_single_piece": "INJECTOR, SINGLE PIECE",
               "injector_structure": "INJECTOR BODY / FACE / DOME", "injector_posts": "INJECTOR POSTS",
               "tvc_lugs": "TVC LUGS", "gimbal": "GIMBAL", "turbine_rotor": "TURBINE BLISKS",
               "turbine_stator": "TURBINE NOZZLE RINGS", "hot_gas_housings": "TURBINE HOUSINGS, COLLECTORS",
               "pump_housings": "PUMP HOUSINGS, VOLUTES", "impellers_inducers": "IMPELLERS, INDUCERS",
               "shafts": "SHAFTS", "preburners": "PREBURNERS", "ducts": "DUCTS"}
MAKE_BUY = {"in-house": "MAKE", "buy-to-print": "BUY", "COTS": "COTS"}
INTEGRAL_OVERRIDE = True


def _val(x):
    return float(np.mean(x))


def evaluate():
    """Route, class, make/buy and T1 cost per part and per group (groups in components.yaml order)."""
    bom = list(csv.DictReader(open(IT.CAD / "bom.csv", encoding="utf-8")))
    eco = json.load(open(IT.ROOT / "results" / "economics.json", encoding="utf-8"))
    comp = load("components.yaml")["groups"]
    gdef = {g["id"]: g for g in comp}
    routes = dict(eco["hybrid_routes"])
    new_groups = [g["id"] for g in comp if g["id"] not in routes]
    for g in new_groups:                      # same rule as scripts/attribute_iteration.py
        routes[g] = gdef[g]["routes"]["inhouse_am"]
    overrides = []
    if INTEGRAL_OVERRIDE and IT.INTEGRAL_MAN and "coolant_manifolds" in gdef:
        am = gdef["coolant_manifolds"]["routes"]["inhouse_am"]
        if routes.get("coolant_manifolds") != am:
            routes["coolant_manifolds"] = am
            overrides.append("coolant_manifolds")
    # two extra welds per welded duct joint (bead at each end), as in scripts/attribute_iteration.py
    cm = CostModel(bom, IT.DESIGN, "hybrid", Sampler(n=1, mode="nominal"), routes=routes,
                   extra_welds=2 * len(IT.WELDED))
    uc = cm.unit_cost()
    parts, groups = {}, {}
    for r in uc["rows"]:
        cls = ROUTE_CLASS[r["route"]]
        parts[r["part"]] = {"group": r["group"], "route": r["route"], "cls": cls, "make_buy": MAKE_BUY[r["category"]],
                            "qty": r["qty"], "mass_kg": r["mass_kg"], "cost": _val(r["cost"])}
        g = groups.setdefault(r["group"], {"id": r["group"], "route": r["route"], "cls": cls,
                                           "make_buy": MAKE_BUY[r["category"]], "qty": 0, "mass_kg": 0.0, "cost": 0.0,
                                           "n_items": 0})
        g["qty"] += r["qty"]
        g["mass_kg"] += r["mass_kg"]
        g["cost"] += _val(r["cost"])
        g["n_items"] += 1
    order = [g["id"] for g in comp if g["id"] in groups]
    return {"parts": parts, "groups": [groups[k] for k in order], "total": _val(uc["total"]),
            "assembly_test": _val(uc["assembly_test"]), "assembly_hours": float(uc["assembly_hours"]),
            "categories": {k: _val(v) for k, v in uc["categories"].items()}, "routes": routes, "overrides": overrides,
            "new_groups": [g for g in new_groups if g in groups],
            "n_parts": uc["n_parts"], "n_bolted_joints": uc["n_bolted_joints"]}


if __name__ == "__main__":
    ev = evaluate()
    for g in ev["groups"]:
        print(f"{g['id']:22s} {g['route']:18s} {g['make_buy']:5s} qty {g['qty']:5d} {g['mass_kg']:8.1f} kg "
              f"{g['cost'] / 1e3:9.1f} k$")
    print("assembly + test", ev["assembly_test"] / 1e3, "k$   total", ev["total"] / 1e6, "M$", ev["categories"])
    print("overrides", ev["overrides"])
