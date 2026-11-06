"""Pseudo-time tests against the finer Euler CFD: the axis through the shock, and the history of each run.

usage: python -m pinn.pseudo_figure
Runs on the CPU. Writes figures/pinn/pseudo/pseudo_test and pseudo_viscous (.pdf, .png), and results/pinn/pseudo/summary.json.
Steps count from the smooth seed 4 start: the viscous runs restart from step 50 of the plain run.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch

from . import axisym as a
from .ensemble import RES, axis_shock, columns, reference
from .pseudo import ROWS, diagnostics
from .quasi1d import Nozzle

ROOT = Path(__file__).resolve().parents[1]
PT = RES / "pseudo"
SEED, PLAIN50, PLAIN200 = "Smooth start, seed 4", "Plain, step 50", "Plain, step 200"
WEIGHTED, V10, V05 = "Down-weighted, step 200", r"Viscous, $\ell = 0.10\,R_t$", r"Viscous, $\ell = 0.05\,R_t$"
FILES = {SEED: RES / "weights" / "axisym_seed4.pt", PLAIN50: PT / "seed4_cfl5_k0_outer50.pt", PLAIN200: PT / "seed4_cfl5_k0_outer200.pt",
         WEIGHTED: PT / "seed4_cfl5_k10_b_last.pt", V10: PT / "o50_ell10_cl3_final.pt", V05: PT / "o50_ell05_cl3_b_last.pt"}
COLOR = {SEED: "#8a8f98", PLAIN50: "#0072b2", PLAIN200: "#d55e00", WEIGHTED: "#009e73", V10: "#009e73", V05: "#0072b2"}
ARMS = {"Plain pseudo-time": ([("seed4_cfl5_k0", 0)], "#d55e00"), r"Down-weighted, $k = 10$": ([("seed4_cfl5_k10", 0), ("seed4_cfl5_k10_b", 15)], "#009e73"),
        V10: ([("o50_ell10_cl3", 50)], "#009e73"), V05: ([("o50_ell05_cl3", 50), ("o50_ell05_cl3_b", 130)], "#0072b2")}
CFD_LABEL = "Euler CFD, 91,935 cells"


def history(arm):
    rows = {}
    for tag, off in ARMS[arm][0]:
        for line in (PT / f"{tag}.jsonl").read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            if "peak" in d:
                rows[d["outer"] + off] = d
    return [dict(step=k, **rows[k]) for k in sorted(rows)]


def load(path, nz):
    m = a.Axisym(nz, 0, nx=360, nr=48, width=64, depth=5)
    m.load_state_dict(torch.load(path, weights_only=True, map_location="cpu"))
    return m


def draw(name, states, arms, fields, ref, row, xi, lnp0, mid_cfd, xmax):
    fig, ax = plt.subplots(2, 2, figsize=(7.2, 5.4), constrained_layout=True)
    k = (xi > 8) & (xi < 13)
    for A, f, label in ((ax[0, 0], lambda d: d["Ma"], "Axis Mach number"), (ax[0, 1], lambda d: lnp0(d["p"], d["T"]), r"Axis $\ln(p_0/p_{0,c})$")):
        for s in states:
            A.plot(xi[k], f(fields[s])[row][k], color=COLOR[s], ls=(0, (4, 2)) if s == SEED else "-", lw=1.1, label=s)
        A.plot(xi[k], f(ref)[row][k], color="#111111", lw=1.6, label=CFD_LABEL)
        A.set_xlabel(r"$x/R_t$")
        A.set_ylabel(label)
    handles, labels = ax[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside upper center", ncol=len(labels), fontsize=7.5)
    for arm in arms:
        h, c = history(arm), ARMS[arm][1]
        s = [r["step"] for r in h]
        ax[1, 0].plot(s, [100 * r["l2_Ma"] for r in h], color=c, lw=1.2, label=arm)
        ax[1, 1].plot(s, [0.5 * (r["xi_peak"] + r["xi_trough"]) for r in h], color=c, lw=1.2, label=arm)
    ax[1, 0].set_ylabel(r"Mach $L_2$ error against CFD (%)")
    ax[1, 1].axhline(mid_cfd, color="#111111", lw=1.2)
    ax[1, 1].text(xmax - 2, mid_cfd - 0.03, "CFD", ha="right", va="top", fontsize=8)
    ax[1, 1].set_ylabel(r"Axis shock mid-point $x/R_t$")
    ax[1, 0].legend(fontsize=7.5)
    for A in ax[1]:
        A.set_xlabel("Pseudo-time step")
        A.set_xlim(0, xmax)
    for A, t in zip(ax.ravel(), "abcd", strict=True):
        A.set_title(f"({t})", loc="left", fontsize=9)
    out = ROOT / "figures" / "pinn" / "pseudo"
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{name}.pdf")
    fig.savefig(out / f"{name}.png", dpi=300)
    plt.close(fig)


def main():
    torch.set_num_threads(2)
    nz = Nozzle()
    g = nz.gamma
    ref = reference("euler_r15", nz)
    row = columns(ref, ROWS)[:, 0]
    xi = (ref["x"][row] - nz.x_t) / nz.Rt
    lnp0 = lambda p, T: np.log(p) - g / (g - 1) * np.log(T)
    sh = axis_shock(ref, nz, ROWS)
    mid_cfd = 0.5 * (sh["xi_peak"] + sh["xi_trough"])
    ahead = (xi > 8) & (xi < 9.3)       # upstream of the shock on every run: nothing here can feel the shock in supersonic flow
    fields, summary = {}, {"cfd": sh}
    for name, path in FILES.items():
        m = load(path, nz)
        q = m.predict(ref["x"], ref["r"])
        fields[name] = q
        summary[name] = diagnostics(m, ref, nz)
        summary[name]["ahead_err"] = float(np.abs(q["Ma"][row][ahead] - ref["Ma"][row][ahead]).max())
    plt.rcParams.update({"font.family": "serif", "font.serif": ["STIXGeneral"], "mathtext.fontset": "stix", "font.size": 9,
                         "axes.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
                         "xtick.major.width": 0.6, "ytick.major.width": 0.6, "legend.frameon": False})
    common = (fields, ref, row, xi, lnp0, mid_cfd)
    draw("pseudo_test", (SEED, PLAIN50, PLAIN200, WEIGHTED), ("Plain pseudo-time", r"Down-weighted, $k = 10$"), *common, 200)
    draw("pseudo_viscous", (SEED, PLAIN200, V10, V05), ("Plain pseudo-time", V10, V05), *common, 250)
    best = min(history("Plain pseudo-time"), key=lambda r: r["l2_Ma"])
    summary["best_plain_by_l2"] = {k_: best[k_] for k_ in ("step", "l2_Ma", "max_err_Ma", "peak", "trough", "width", "Cd", "eta_cf_vac")}
    (PT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    keys = ("peak", "trough", "width", "l2_Ma", "max_err_Ma", "ahead_err", "Cd", "eta_cf_vac", "share_above", "sec_lnp0_11.0", "sec_lnp0_12.0", "sec_lnp0_13.0", "sec_lnp0_14.0", "sec_lnp0_14.8")
    for n in FILES:
        d = summary[n]
        print(n, {k_: round(d[k_], 5) for k_ in keys}, "mid", round(0.5 * (d["xi_peak"] + d["xi_trough"]), 3))
        print("    dCd % {:+.3f}  dCf % {:+.3f}  Isp ratio {:.5f}".format(100 * (d["Cd"] / 0.99480 - 1), 100 * (d["eta_cf_vac"] / 0.98787 - 1), d["eta_cf_vac"] / d["Cd"]))
    print("cfd", sh, "mid", round(mid_cfd, 3))


if __name__ == "__main__":
    main()
