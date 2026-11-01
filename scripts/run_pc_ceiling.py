"""Chamber-pressure ceiling of the FFSC cycle and what raises it.

Starts from the iteration-1 improved configuration (results/improved/config_improved.json)
and sweeps pc for each set of enabling options. A point is feasible when the cycle closes
and the hot-wall temperature stays within the copper limit. Writes results/pc_ceiling.json.
"""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ffsc import ROOT  # noqa: E402
from ffsc.design import _jsonable  # noqa: E402
from run_improved import apply, evaluate  # noqa: E402

ENABLERS = [
    ("I1 improved (reference)", "-", {}),
    ("Pump inlet 6 -> 10 bar", "vehicle tank pressure or electric boost pumps",
     {"propellants.lox.p_inlet_bar": 10.0, "propellants.lch4.p_inlet_bar": 10.0}),
    ("OPB 820 -> 900 K", "ox-rich turbine alloy / coating qualified to 900 K", {"cycle.T_opb_K": 900.0}),
    ("Turbine peak eta 0.82 -> 0.87", "two-stage or higher-reaction turbine; more parts", {"cycle.eta_turbine_max": 0.87}),
    ("FPB 1100 -> 1200 K", "SX turbine blades instead of cast MAR-M-247", {"cycle.T_fpb_K": 1200.0}),
    ("All four", "combined", {"propellants.lox.p_inlet_bar": 10.0, "propellants.lch4.p_inlet_bar": 10.0,
                              "cycle.T_opb_K": 900.0, "cycle.eta_turbine_max": 0.87, "cycle.T_fpb_K": 1200.0}),
]
PCS = [350.0, 375.0, 400.0, 425.0, 450.0, 475.0, 500.0]
TWG_LIMIT = 880.0 * 1.005      # the cooling model sizes channels to Twg = 880 K; allow 0.5 % tolerance
P_PUMP_LIMIT = 1000.0         # bar, assumed design limit on pump discharge (housings, seals, ducts)


def run():
    base = json.load(open(ROOT / "results" / "improved" / "config_improved.json"))
    out = []
    for name, how, mods in ENABLERS:
        rows, ceiling = [], None
        for pc in PCS:
            cfg = copy.deepcopy(base)
            apply(cfg, mods)
            cfg["requirements"]["pc_bar"] = pc
            _, m = evaluate(cfg)
            ok = bool(m.get("feasible")) and m.get("Twg_max_K", 1e9) <= TWG_LIMIT \
                and max(m.get("p_ox_dis_bar", 1e9), m.get("p_fu_dis_bar", 1e9)) <= P_PUMP_LIMIT
            rows.append({"pc_bar": pc, "ok": ok, **m})
            print(f"{name:32s} pc {pc:5.0f}  {'OK ' if ok else 'no '} "
                  + (f"Isp_sl {m['isp_sl']:6.1f}  p_ox {m['p_ox_dis_bar']:5.0f}  p_fu {m['p_fu_dis_bar']:5.0f}  "
                     f"N_ox {m['N_ox_rpm']:6.0f}  Twg {m['Twg_max_K']:4.0f}  R_ox {m['R_env_ox_tpa_mm']:4.0f}"
                     if m.get("feasible") else m.get("error", "")[:90]))
            if ok:
                ceiling = pc
            elif ceiling is not None:
                break
        out.append({"enabler": name, "how": how, "mods": mods, "pc_ceiling_bar": ceiling, "points": rows})
    json.dump(out, open(ROOT / "results" / "pc_ceiling.json", "w"), indent=2, default=_jsonable)
    return out


def figure(out=None):
    from figstyle import C, plt, save
    out = out or json.load(open(ROOT / "results" / "pc_ceiling.json"))
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.7), sharex=True)
    cols = [C["k"], C["ox"], C["r"], C["g"], C["fu"], C["p"]]
    for e, col in zip(out, cols):
        pts = [p for p in e["points"] if p.get("feasible")]
        pc = [p["pc_bar"] for p in pts]
        for a, key in zip(ax, ("p_ox_dis_bar", "p_fu_dis_bar")):
            a.plot(pc, [p[key] for p in pts], "-o", color=col, ms=3, lw=1.0, label=e["enabler"])
    for a, t in zip(ax, ("(a) LOX pump discharge", "(b) CH4 pump discharge")):
        a.axhline(P_PUMP_LIMIT, color=C["k"], lw=0.6, ls=":")
        a.set_ylim(top=max(a.get_ylim()[1], P_PUMP_LIMIT + 45))
        a.text(352, P_PUMP_LIMIT + 12, "assumed 1,000 bar limit", fontsize=6)
        a.set_xlabel("chamber pressure (bar)")
        a.set_ylabel("discharge pressure (bar)")
        a.set_title(t)
    h, lab = ax[0].get_legend_handles_labels()
    fig.legend(h, lab, fontsize=6.5, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.08))
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    save(fig, "fig10_pc_ceiling")


if __name__ == "__main__":
    figure(run())
