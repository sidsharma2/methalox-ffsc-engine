"""Journal-style figures (STIX serif, PDF + PNG) from results/*.json and *.csv."""

import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["STIXGeneral"], "mathtext.fontset": "stix",
    "font.size": 9, "axes.labelsize": 9, "axes.titlesize": 9, "legend.fontsize": 8,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.linewidth": 0.7, "lines.linewidth": 1.2,
    "xtick.direction": "in", "ytick.direction": "in", "xtick.top": True, "ytick.right": True,
    "savefig.dpi": 300, "figure.dpi": 110, "legend.frameon": False,
})
C = {"cu": "#b5651d", "in": "#6b6f7a", "ox": "#1f5fa8", "fu": "#a8641f", "k": "#222222", "g": "#2e7d32", "r": "#b71c1c"}

D = json.load(open(ROOT / "results" / "design.json"))
P = list(csv.DictReader(open(ROOT / "results" / "cooling_profile.csv")))
col = lambda k: np.array([float(r[k]) for r in P])
x = col("x")
T = json.load(open(ROOT / "results" / "trades.json"))
IMP = json.load(open(ROOT / "results" / "improvements.json"))


def save(fig, name):
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(FIG / f"{name}.png", bbox_inches="tight")
    plt.close(fig)


def ok(rows, key):
    return [r for r in rows if r.get("feasible") and key in r]


# ---------------------------------------------------------------- 1 contour and channels
fig, ax = plt.subplots(2, 1, figsize=(6.7, 5.0), sharex=True, gridspec_kw={"height_ratios": [1.3, 1]})
r, th, H, tc = col("r"), col("t_hot"), col("H"), col("t_closeout")
zone = col("zone")
for z, c, lab in [(0, C["cu"], "GRCop-42 liner (L-PBF)"), (1, C["in"], "Inconel 718 liner")]:
    m = zone == z
    ax[0].fill_between(x[m] * 1e3, r[m] * 1e3, (r[m] + th[m] + H[m]) * 1e3, color=c, alpha=0.55, lw=0, label=lab + " + channels")
ax[0].fill_between(x * 1e3, (r + th + H) * 1e3, (r + th + H + tc) * 1e3, color="#9aa0aa", alpha=0.8, lw=0, label="Inconel 718 closeout")
ax[0].plot(x * 1e3, r * 1e3, color=C["k"], lw=1.0, label="gas-side contour")
xj = D["geometry"]["x_joint_m"] * 1e3
ax[0].axvline(xj, color=C["k"], ls=":", lw=0.8)
ax[0].text(xj + 15, 120, f"bolted joint, $\\varepsilon$ = {D['geometry']['eps_joint']:.0f}", fontsize=8)
ax[0].axvline(D["geometry"]["x_throat_m"] * 1e3, color=C["k"], ls="--", lw=0.6)
ax[0].text(D["geometry"]["x_throat_m"] * 1e3 + 15, 40, f"throat, $D_t$ = {2 * D['geometry']['Rt_m'] * 1e3:.0f} mm", fontsize=8)
ax[0].set_ylabel("radius (mm)")
ax[0].set_ylim(0, 760)
ax[0].legend(loc="upper left", ncol=1)
ax[1].plot(x * 1e3, col("H_sized") * 1e3, color=C["k"], lw=0.6, alpha=0.5, label="height, sized per station")
ax[1].plot(x * 1e3, H * 1e3, color=C["k"], label="height, smoothed (built)")
ax[1].plot(x * 1e3, col("W") * 1e3, color=C["ox"], label="width")
ax[1].plot(x * 1e3, col("rib") * 1e3, color=C["fu"], label="rib")
ax[1].set_ylabel("channel size (mm)")
ax[1].set_xlabel("axial distance from injector face (mm)")
a2 = ax[1].twinx()
a2.step(x * 1e3, col("N"), color=C["g"], where="mid", lw=0.9, label="channel count")
a2.set_ylabel("channels", color=C["g"])
a2.tick_params(axis="y", colors=C["g"])
ax[1].legend(loc="center left", bbox_to_anchor=(0.0, 0.55))
save(fig, "fig01_contour_channels")

# ---------------------------------------------------------------- 2 cooling solution
fig, ax = plt.subplots(3, 1, figsize=(6.7, 6.2), sharex=True)
ax[0].plot(x * 1e3, col("q") / 1e6, color=C["r"])
ax[0].set_ylabel("heat flux (MW m$^{-2}$)")
ax[1].plot(x * 1e3, col("Twg"), color=C["r"], label="$T_{wg}$ hot wall")
ax[1].plot(x * 1e3, col("Twc"), color=C["fu"], label="$T_{wc}$ coolant-side wall")
ax[1].plot(x * 1e3, col("Tb"), color=C["ox"], label="$T_b$ methane bulk")
for zz in D["config"]["cooling"]["zones"]:
    ax[1].axhline(zz["Twg_target_K"], color=C["k"], ls=":", lw=0.6)
ax[1].set_ylabel("temperature (K)")
ax[1].legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3)
ax[2].plot(x * 1e3, col("p") / 1e5, color=C["k"], label="coolant pressure")
ax[2].set_ylabel("pressure (bar)")
a2 = ax[2].twinx()
a2.plot(x * 1e3, col("v"), color=C["g"], lw=0.9)
a2.set_ylabel("velocity (m s$^{-1}$)", color=C["g"])
a2.tick_params(axis="y", colors=C["g"])
for a in ax:
    a.axvline(xj, color=C["k"], ls=":", lw=0.6)
ax[2].set_xlabel("axial distance from injector face (mm)")
ax[0].text(0.99, 0.82, "coolant enters at the joint: circuit A runs up, circuit B runs down", transform=ax[0].transAxes, ha="right", fontsize=8)
save(fig, "fig02_cooling")

# ---------------------------------------------------------------- 3 pressure ladder
c = D["cycle"]
pc = D["performance"]["pc"] / 1e5
ox = [("pump inlet", c["ox_pump"]["p_in"] / 1e5), ("LOX pump", c["p_ox_discharge_Pa"] / 1e5),
      ("OPB", c["p_opb_Pa"] / 1e5), ("ox turbine exit", c["p_turbine_exit_Pa"] / 1e5), ("chamber", pc)]
fu = [("pump inlet", c["fuel_pump"]["p_in"] / 1e5), ("CH4 pump", c["p_fuel_discharge_Pa"] / 1e5),
      ("jacket out", D["cooling"]["p_out_Pa"] / 1e5), ("FPB", c["p_fpb_Pa"] / 1e5),
      ("fuel turbine exit", c["p_turbine_exit_Pa"] / 1e5), ("chamber", pc)]
fig, ax = plt.subplots(figsize=(6.7, 3.2))
ax.plot(range(len(ox)), [v for _, v in ox], "o-", color=C["ox"], label="oxidiser side")
ax.plot(np.arange(len(fu)) + 0.15, [v for _, v in fu], "s-", color=C["fu"], label="fuel side")
for i, (n, v) in enumerate(ox):
    ax.annotate(f"{n}\n{v:.0f}", (i, v), textcoords="offset points", xytext=(-4, 7), fontsize=7, color=C["ox"], ha="right")
for i, (n, v) in enumerate(fu):
    ax.annotate(f"{n}\n{v:.0f}", (i + 0.15, v), textcoords="offset points", xytext=(4, -22), fontsize=7, color=C["fu"])
ax.set_xticks([])
ax.set_ylabel("pressure (bar)")
ax.set_ylim(0, 1050)
ax.legend(loc="upper right")
save(fig, "fig03_pressure_ladder")

# ---------------------------------------------------------------- 4 mixture ratio and expansion ratio
fig, ax = plt.subplots(1, 2, figsize=(6.7, 2.7))
rows = ok(T["mixture_ratio"], "isp_sl")
mr = [r["requirements.mixture_ratio"] for r in rows]
ax[0].plot(mr, [r["isp_sl"] for r in rows], "o-", color=C["k"], label="$I_{sp}$ sea level")
ax[0].plot(mr, [r["isp_vac"] for r in rows], "s--", color=C["k"], label="$I_{sp}$ vacuum")
ax[0].set_xlabel("mixture ratio O/F")
ax[0].set_ylabel("$I_{sp}$ (s)")
b = ax[0].twinx()
b.plot(mr, [r["density_isp_sl"] for r in rows], "^-", color=C["g"])
b.set_ylabel(r"$\rho_{bulk} I_{sp}$ (t s m$^{-3}$)", color=C["g"])
b.tick_params(axis="y", colors=C["g"])
ax[0].axvline(3.6, color=C["k"], ls=":", lw=0.6)
ax[0].legend(loc="lower left")
rows = ok(T["expansion_ratio"], "isp_sl")
eps = [r["nozzle.expansion_ratio"] for r in rows]
ax[1].plot(eps, [r["isp_sl"] for r in rows], "o-", color=C["k"], label="$I_{sp}$ sea level")
ax[1].set_xlabel(r"expansion ratio $\varepsilon$")
ax[1].set_ylabel("$I_{sp}$ sea level (s)")
b = ax[1].twinx()
b.plot(eps, [r["sep_margin_40"] for r in rows], "s-", color=C["r"], label="separation margin, 40 % throttle")
b.axhline(1.0, color=C["r"], ls=":", lw=0.6)
b.set_ylabel("Schmucker margin at 40 %", color=C["r"])
b.tick_params(axis="y", colors=C["r"])
ax[1].axvline(34, color=C["k"], ls=":", lw=0.6)
save(fig, "fig04_mr_eps")

# ---------------------------------------------------------------- 5 sensitivities (tornado on fuel-pump discharge)
base_pf = D["cycle"]["p_fuel_discharge_Pa"] / 1e5
base_po = D["cycle"]["p_ox_discharge_Pa"] / 1e5
tor = []
for study, label in [("channel_roughness", "channel roughness 3-15 um"), ("nozzle_circuit_fraction", "coolant split 0.2-0.5"),
                     ("tip_clearance", "turbine tip clearance 0.15-0.25 mm"), ("bartz_factor", "Bartz heat flux x0.8-1.2"),
                     ("opb_temperature", "OPB 800-900 K"), ("fpb_temperature", "FPB 1050-1300 K"),
                     ("pump_inlet_pressure", "pump inlet 5-10 bar")]:
    rows = ok(T[study], "p_fu_dis_bar")
    vf = [r["p_fu_dis_bar"] for r in rows]
    vo = [r["p_ox_dis_bar"] for r in rows]
    tor.append((label, min(vf) - base_pf, max(vf) - base_pf, min(vo) - base_po, max(vo) - base_po))
tor.sort(key=lambda t: t[2] - t[1])
fig, ax = plt.subplots(figsize=(6.7, 3.0))
yy = np.arange(len(tor))
ax.barh(yy + 0.18, [t[2] - t[1] for t in tor], left=[t[1] for t in tor], height=0.34, color=C["fu"], label="CH4 pump discharge")
ax.barh(yy - 0.18, [t[4] - t[3] for t in tor], left=[t[3] for t in tor], height=0.34, color=C["ox"], label="LOX pump discharge")
ax.set_yticks(yy)
ax.set_yticklabels([t[0] for t in tor])
ax.axvline(0, color=C["k"], lw=0.7)
ax.set_xlabel(f"change in pump discharge pressure from baseline (bar); baseline LOX {base_po:.0f}, CH4 {base_pf:.0f} bar")
ax.legend(loc="lower right")
save(fig, "fig05_sensitivity_tornado")

# ---------------------------------------------------------------- 6 wall bias
fig, ax = plt.subplots(1, 2, figsize=(6.7, 2.7))
for mrw, mk in [(1.6, "o"), (2.0, "s")]:
    rows = [r for r in ok(T["wall_bias"], "isp_sl") if abs(r["injector.bl_mixture_ratio"] - mrw) < 1e-6]
    ph = [100 * r["injector.bl_mass_fraction"] for r in rows]
    ax[0].plot(ph, [r["bl_penalty_s"] for r in rows], mk + "-", color=C["k"], label=f"wall O/F {mrw}")
    ax[1].plot(ph, [r["dp_jacket_bar"] for r in rows], mk + "-", color=C["k"], label=f"wall O/F {mrw}")
ax[0].set_xlabel("wall stream-tube share (% of mass flow)")
ax[0].set_ylabel("sea-level $I_{sp}$ loss (s)")
ax[1].set_xlabel("wall stream-tube share (% of mass flow)")
ax[1].set_ylabel("jacket pressure drop (bar)")
ax[0].legend()
ax[1].text(0.03, 0.06, "wall O/F 2.4: cycle does not close", transform=ax[1].transAxes, fontsize=8, color=C["r"])
save(fig, "fig06_wall_bias")

# ---------------------------------------------------------------- 7 improvement chain
ch = IMP["chain"]
fig, ax = plt.subplots(figsize=(6.7, 3.0))
lab = ["baseline", "polish\nchannels", "coolant split\n50/50", "shrouded\nturbines", "close-coupled\nhot gas"]
ax.plot(range(len(ch)), [s["p_fu_dis_bar"] for s in ch], "s-", color=C["fu"], label="CH4 pump discharge")
ax.plot(range(len(ch)), [s["p_ox_dis_bar"] for s in ch], "o-", color=C["ox"], label="LOX pump discharge")
ax.plot(range(len(ch)), [s["dp_jacket_bar"] for s in ch], "^-", color=C["g"], label="jacket pressure drop")
for i, s in enumerate(ch):
    ax.annotate(f"{s['p_fu_dis_bar']:.0f}", (i, s["p_fu_dis_bar"]), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=7)
    ax.annotate(f"{s['p_ox_dis_bar']:.0f}", (i, s["p_ox_dis_bar"]), textcoords="offset points", xytext=(0, -12), ha="center", fontsize=7)
ax.set_xticks(range(len(ch)))
ax.set_xticklabels(lab[:len(ch)])
ax.set_ylabel("pressure (bar)")
ax.set_ylim(0, 1000)
ax.legend(loc="center right")
ax.text(0.01, 0.03, f"sea-level $I_{{sp}}$ unchanged at {ch[-1]['isp_sl']:.1f} s", transform=ax.transAxes, fontsize=8)
save(fig, "fig07_improvement_chain")

# ---------------------------------------------------------------- 8 throttle
th_rows = D["throttle"]
fig, ax = plt.subplots(figsize=(3.3, 2.7))
f = [100 * t["throttle"] for t in th_rows]
ax.plot(f, [t["pe_over_pa"] for t in th_rows], "o-", color=C["k"], label="$p_e/p_a$")
ax.plot(f, [t["schmucker_limit"] for t in th_rows], "--", color=C["r"], label="Schmucker separation")
ax.axhline(0.4, color=C["r"], ls=":", lw=0.7, label="Summerfield 0.4")
ax.set_xlabel("throttle (% thrust)")
ax.set_ylabel("exit / ambient pressure")
ax.set_ylim(0, 1.3)
ax.legend(loc="upper left")
save(fig, "fig08_throttle_separation")

# ---------------------------------------------------------------- 9 mass breakdown
mpath = ROOT / "cad" / "output" / "mass_summary.json"
if mpath.exists():
    ms = json.load(open(mpath))["by_assembly_kg"]
    names = {"Thrust_Chamber": "thrust chamber + manifolds", "Injector_Head": "injector head", "Gimbal": "gimbal",
             "LOX_Turbopump": "LOX turbopump + OPB", "CH4_Turbopump": "CH4 turbopump + FPB", "Plumbing": "ducts, valves, flanges",
             "Instrumentation": "instrumentation"}
    items = sorted(((names.get(k, k), v) for k, v in ms.items() if v > 1), key=lambda t: t[1])
    fig, ax = plt.subplots(figsize=(4.5, 2.6))
    ax.barh([n for n, _ in items], [v for _, v in items], color=C["in"])
    for i, (_, v) in enumerate(items):
        ax.text(v + 8, i, f"{v:.0f}", va="center", fontsize=7)
    ax.set_xlabel("modelled mass (kg)")
    tot = sum(v for _, v in items)
    ax.set_title(f"CAD mass roll-up {tot:.0f} kg (Raptor 3: 1525 kg engine only)", fontsize=8)
    save(fig, "fig09_mass_breakdown")

print("figures written to", FIG)
