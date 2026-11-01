"""Iteration registry: frozen iterations and iteration-2 candidates assembled from the options.

Reads config/iterations.yaml, results/options.json and results/economics.json. Writes
results/iterations.json and docs/ITERATIONS.md.
"""

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffsc import ROOT  # noqa: E402

G0 = 9.80665
IT = yaml.safe_load(open(ROOT / "config" / "iterations.yaml"))
OPT = json.load(open(ROOT / "results" / "options.json"))
ECO = json.load(open(ROOT / "results" / "economics.json"))
OPTS = {o["id"]: o for o in OPT["options"]}
THRUST = 2746e3
RAPTOR3 = {"mass_kg": 1525.0, "thrust_to_weight": THRUST / (1525.0 * G0)}
CANDS = []


def frozen():
    base = json.load(open(ROOT / "cad" / "output" / "mass_summary.json"))["total_modelled_kg"]
    imp = OPT["baseline"]
    d0 = json.load(open(ROOT / "results" / "design.json"))
    return [
        {"id": "I1", "mass_kg": base, "thrust_to_weight": THRUST / (base * G0), "isp_sl_s": d0["performance"]["isp_sl"],
         "pc_bar": d0["performance"]["pc"] / 1e5, "p_ox_bar": d0["cycle"]["p_ox_discharge_Pa"] / 1e5,
         "p_fu_bar": d0["cycle"]["p_fuel_discharge_Pa"] / 1e5},
        {"id": "I1-imp", "mass_kg": imp["mass_kg"], "thrust_to_weight": imp["thrust_to_weight"], "isp_sl_s": imp["isp_sl"],
         "pc_bar": 350.0, "p_ox_bar": imp["p_ox_dis_bar"], "p_fu_bar": imp["p_fu_dis_bar"],
         "unit_cost_T1_P50": ECO["scenarios"]["hybrid"]["unit_cost_T1"]["P50"],
         "nre_P50": ECO["scenarios"]["hybrid"]["nre"]["total"]["P50"]}]


def candidate(c, base):
    m, isp = base["mass_kg"], base["isp_sl_s"]
    p_ox, p_fu = base["p_ox_bar"], base["p_fu_bar"]
    d_cost, d_cost_lo, d_cost_hi, nre = 0.0, 0.0, 0.0, base["nre_P50"]
    trl, pc = 9, 350.0
    for oid in c["options"]:                             # a cycle variant sets the pump pressures first
        if oid in ("Y1", "Y2"):
            p_ox, p_fu = OPTS[oid]["result"]["p_ox_bar"], OPTS[oid]["result"]["p_fu_bar"]
            pc = 400.0 if oid == "Y2" else pc
    for oid in c["options"]:
        o = OPTS[oid]
        r = o["result"]
        m += r.get("d_mass_kg", 0.0)
        isp += r.get("d_isp_sl_s", 0.0)
        if oid not in ("Y1", "Y2"):
            p_ox += r.get("d_p_ox_bar", 0.0)
            p_fu += r.get("d_p_fu_bar", 0.0)
        e = ECO["options"][oid]
        if e["d_recurring_usd"]:
            d_cost += e["d_recurring_usd"]["P50"]
            d_cost_lo += e["d_recurring_usd"]["P10"]
            d_cost_hi += e["d_recurring_usd"]["P90"]
        nre += e["nre_usd"]["P50"]
        trl = min(trl, o["trl"])
    t1 = base["unit_cost_T1_P50"] + d_cost
    return {"id": c["id"], "name": c["name"], "options": c["options"], "why": " ".join(c["why"].split()),
            "mass_kg": m, "thrust_to_weight": THRUST / (m * G0), "isp_sl_s": isp, "pc_bar": pc,
            "p_ox_bar": p_ox, "p_fu_bar": p_fu, "unit_cost_T1_P50": t1,
            "unit_cost_delta_P10_P90": [d_cost_lo, d_cost_hi], "nre_P50": nre, "min_trl": trl,
            "cost_per_kN_T1": t1 / (THRUST / 1e3)}


def built():
    """Iteration builds with a full CAD roll-up (scripts/build_iteration.py, attribute_iteration.py)."""
    rows = []
    for bid, b in (IT.get("builds") or {}).items():
        d = ROOT / "results" / "iterations" / bid
        if not (d / "attribution.json").exists():
            continue
        at = json.load(open(d / "attribution.json"))
        cs = json.load(open(d / "cad_summary.json"))
        res = json.load(open(d / "design.json"))
        rows.append({"id": bid, "name": b["title"], "options": b["options"], "rev": b["rev"], "mass_kg": at["mass_kg"],
                     "thrust_to_weight": at["thrust_to_weight"], "isp_sl_s": res["performance"]["isp_sl"],
                     "isp_vac_s": res["performance"]["isp_vac"], "pc_bar": res["performance"]["pc"] / 1e5,
                     "p_ox_bar": res["cycle"]["p_ox_discharge_Pa"] / 1e5, "p_fu_bar": res["cycle"]["p_fuel_discharge_Pa"] / 1e5,
                     "unit_cost_T1_P50": at.get("unit_cost_T1_P50_with_adders", at["unit_cost_T1"]["P50"]),
                     "clashes": cs["clashes"], "envelope_mm": cs["envelope_mm"],
                     "bom_items": at["bom_items"][0], "pieces": at["pieces"][0],
                     "nre_P50": ECO["scenarios"]["hybrid"]["nre"]["total"]["P50"]
                     + sum(ECO["options"][o]["nre_usd"]["P50"] for o in b["options"] if o in ECO["options"]),
                     "min_trl": min(OPTS[o]["trl"] for o in b["options"] if o in OPTS),
                     "estimate_mass_kg": next((c["mass_kg"] for c in CANDS if c["id"] == bid), None),
                     "by_option": at["by_option"]})
    return rows


def run():
    global CANDS
    fz = frozen()
    base = fz[1]
    cands = [candidate(c, base) for c in IT["candidates"]]
    CANDS = cands
    blt = built()
    out = {"frozen": fz, "candidates": cands, "built": blt, "raptor3_public": RAPTOR3}
    json.dump(out, open(ROOT / "results" / "iterations.json", "w"), indent=2)
    for r in fz + cands + blt:
        print(f"{r['id']:7s} mass {r['mass_kg']:7.0f} kg  T/W {r['thrust_to_weight']:5.1f}  Isp_sl {r['isp_sl_s']:5.1f}  "
              f"p_ox {r['p_ox_bar']:4.0f}  p_fu {r['p_fu_bar']:4.0f}  "
              + (f"T1 ${r['unit_cost_T1_P50'] / 1e6:4.2f}M  NRE ${r['nre_P50'] / 1e9:4.2f}B" if "unit_cost_T1_P50" in r else ""))
    write_log(out)
    return out


def write_log(out):
    L = ["# Design iterations", "",
         "Each iteration is frozen with a git tag before the next one starts. Candidates are assembled from the "
         "options register (`config/options.yaml`, evaluated by `scripts/run_options.py`, costed by "
         "`scripts/run_economics.py`). Generated by `scripts/run_iterations.py`.", "",
         "## Frozen", "",
         "| Iteration | Git tag | Mass (kg) | T/W | Isp SL (s) | pc (bar) | LOX / CH4 pump (bar) |",
         "|---|---|---|---|---|---|---|"]
    tags = {f["id"]: f for f in IT["frozen"]}
    for r in out["frozen"]:
        L.append(f"| {r['id']} ({tags[r['id']]['name']}) | `{tags[r['id']]['git_tag']}` | {r['mass_kg']:.0f} | "
                 f"{r['thrust_to_weight']:.0f} | {r['isp_sl_s']:.1f} | {r['pc_bar']:.0f} | {r['p_ox_bar']:.0f} / {r['p_fu_bar']:.0f} |")
    L += ["", "## Iteration 2 candidates", "",
          "Deltas from the options are added to I1-imp. The candidates are estimates until each one is built as its "
          "own CAD variant. Unit cost is the first engine, hybrid build strategy, P50. Development cost is the "
          "bottom-up programme cost plus the options' development cost.", "",
          "| Candidate | Options | Mass (kg) | T/W | Isp SL (s) | pc (bar) | LOX / CH4 pump (bar) | T1 ($M) | Development ($B) | Lowest TRL |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in out["candidates"]:
        L.append(f"| {r['id']}: {r['name']} | {', '.join(r['options'])} | {r['mass_kg']:.0f} | {r['thrust_to_weight']:.0f} | "
                 f"{r['isp_sl_s']:.1f} | {r['pc_bar']:.0f} | {r['p_ox_bar']:.0f} / {r['p_fu_bar']:.0f} | "
                 f"{r['unit_cost_T1_P50'] / 1e6:.2f} | {r['nre_P50'] / 1e9:.2f} | {r['min_trl']} |")
    rp = out["raptor3_public"]
    L += [f"| Raptor 3 (public) | | {rp['mass_kg']:.0f} | {rp['thrust_to_weight']:.0f} | | ~350 | | | | |", ""]
    for r in out["candidates"]:
        L += [f"- {r['id']}: {r['why']}"]
    if out.get("built"):
        L += ["", "## Built iterations (full CAD)", "",
              "Built by `scripts/build_iteration.py`, attributed by `scripts/attribute_iteration.py` against the CAD variant "
              "with the same cycle and the iteration-1 layout. Drawings in `drawings/<ID>/`.", "",
              "| Build | Rev | Mass (kg) | Linear estimate (kg) | T/W | Isp SL / vac (s) | pc (bar) | LOX / CH4 pump (bar) | BOM lines / pieces | Clashes | T1 ($M) |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in out["built"]:
            est = f"{r['estimate_mass_kg']:.0f}" if r["estimate_mass_kg"] else "-"
            L.append(f"| {r['id']}: {r['name']} | {r['rev']} | {r['mass_kg']:.0f} | {est} | {r['thrust_to_weight']:.0f} | "
                     f"{r['isp_sl_s']:.1f} / {r['isp_vac_s']:.1f} | {r['pc_bar']:.0f} | {r['p_ox_bar']:.0f} / {r['p_fu_bar']:.0f} | "
                     f"{r['bom_items']} / {r['pieces']} | {r['clashes']} | {r['unit_cost_T1_P50'] / 1e6:.2f} |")
        L += [""]
        for r in out["built"]:
            L += [f"Measured effect of each option in {r['id']} (mass change against the same cycle with the iteration-1 layout):", ""]
            for k, v in r["by_option"].items():
                L.append(f"- {k}: {v['d_mass_kg']:+.1f} kg, {v['d_items']:+d} BOM lines, {v['d_pieces']:+d} pieces")
            L += [""]
    L += ["", "## Next step", "",
          "Post-process the I1 and I2-C OpenFOAM runs (`cfd/post_compare.py`), feed the measured nozzle efficiency back "
          "into the cycle model, and tag `iter-2` once the I2-C drawings are released.", ""]
    (ROOT / "docs" / "ITERATIONS.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    run()
