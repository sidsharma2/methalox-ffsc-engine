"""Compare the OpenFOAM runs with the 1-D model: mass flow, thrust and Isp from the exit-plane monitors.

For each case it reads postProcessing/ from the WSL run directory (or the copy in cfd/cases/), scales
the 5-degree wedge by case_info["wedge_factor"], and computes
    F   = W [ int rho u u_x dA + int (p - p_amb) dA ]   at the nozzle exit plane
    Isp = F / (mdot_in g0)
against the ideal 1-D flow of the same equivalent gas (case_info["reference_1d"]["ideal_chosen_gas"]).
Both have the same chamber state and throat area, so mdot_cfd / mdot_1d is the discharge coefficient Cd, and
Cd x Isp_vac,cfd / Isp_vac,1d is the vacuum thrust-coefficient ratio that the cycle model applies as eta_Cf = 0.98.
The nozzle-only runs (cfd/nozzle_only.sh) give the thrust; the plume runs give the external flow and
must reproduce the same exit plane, since the exit is supersonic.
Writes results/cfd_compare.json and figures/pgf/fig15_cfd_convergence.(tex|pdf|png).

    .venv/Scripts/python.exe cfd/post_compare.py
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WSL_HOME = Path(r"\\wsl.localhost\Ubuntu-22.04\root\runs")
CASES = [("I1 nozzle", "mfe280_sl_axi_nozzle"), ("I2-C nozzle", "mfe280_I2C_sl_axi_nozzle"),
         ("I1 hisa", "mfe280_sl_axi_hisa"),          # same nozzle case and start, implicit solver
         ("I1 plume", "mfe280_sl_axi"), ("I2-C plume", "mfe280_I2C_sl_axi")]
G0 = 9.80665
P_AMB = 101325.0
PGF = ROOT / "figures" / "pgf"
MIKTEX = Path(r"C:\Users\siddh\AppData\Local\Programs\MiKTeX\miktex\bin\x64")
GS = Path(r"C:\Users\siddh\AppData\Local\Programs\Ghostscript\gs10.05.1\bin\gswin64c.exe")


def series(pp, name, col=1, vector=False):
    """Concatenate all restart folders of one surfaceFieldValue/force monitor; returns (iter, value)."""
    rows = {}
    for d in sorted((pp / name).iterdir(), key=lambda q: float(q.name)):
        for f in d.glob("*.dat"):
            for line in f.read_text().splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.replace("(", " ").replace(")", " ").split()
                rows[float(parts[0])] = float(parts[col])
    it = np.array(sorted(rows))
    return it, np.array([rows[k] for k in it])


def case_dir(name):
    for base in (WSL_HOME / name, ROOT / "cfd" / "cases" / name):
        if (base / "postProcessing").exists():
            return base
    return None


def analyse(tag, name):
    base = case_dir(name)
    if base is None:
        return None
    ci = ROOT / "cfd" / "cases" / name / "case_info.json"
    info = json.loads((ci if ci.exists() else base / "case_info.json").read_text())   # nozzle-only runs: run dir
    W = info["wedge_factor"]
    ref = info["reference_1d"]["ideal_chosen_gas"]
    pp = base / "postProcessing"
    it_in, m_in = series(pp, "inletMassFlow")
    it_ex, m_ex = series(pp, "exitMassFlow")
    it_m, mom = series(pp, "exitMomentumFlux", col=1)
    it_p, pint = series(pp, "exitPressureForce")
    Re = info.get("geometry", {}).get("Re_m") or math.sqrt(ref["mdot"] / (ref["rho_e"] * ref["ue"]) / math.pi)
    A_w = math.pi * Re ** 2 / W                     # exit area of the wedge
    n = min(len(it_in), len(it_ex), len(it_m), len(it_p))
    it = it_in[:n]
    mdot = -W * m_in[:n]
    F = W * (mom[:n] + pint[:n] - P_AMB * A_w)
    isp = F / (np.maximum(mdot, 1e-9) * G0)
    # vacuum Isp from the exit plane alone: (momentum + pressure) / exit mass flow. For a fixed T0 and
    # area ratio it does not depend on the chamber pressure, so it stays meaningful while the chamber settles.
    isp_vac = (mom[:n] + pint[:n]) / (np.maximum(m_ex[:n], 1e-9) * G0)
    k = slice(max(0, n - 100), n)                    # last 100 samples = 2,000 iterations
    out = {"case": name, "iterations": int(it[-1]), "mdot_in": float(np.mean(mdot[k])), "mdot_out": float(-W * np.mean(-m_ex[k])),
           "thrust_N": float(np.mean(F[k])), "isp_s": float(np.mean(isp[k])), "isp_drift_window_s": float(np.ptp(isp[k])),
           "isp_vac_exit_s": float(np.mean(isp_vac[k])), "isp_vac_drift_window_s": float(np.ptp(isp_vac[k])),
           "mass_imbalance": float(abs(np.mean(W * m_ex[k]) - np.mean(mdot[k])) / np.mean(mdot[k])),
           "ref_1d": {"mdot": ref["mdot"], "F_amb": ref["F_amb"], "isp_amb": ref["isp_amb"], "isp_vac": ref["isp_vac"]},
           "eta_F": float(np.mean(F[k]) / ref["F_amb"]), "eta_isp": float(np.mean(isp[k]) / ref["isp_amb"]),
           "eta_isp_vac": float(np.mean(isp_vac[k]) / ref["isp_vac"]),
           # same chamber state and throat as the 1-D flow: Cd = mdot ratio, and Cf_vac ratio = Cd x Isp_vac ratio,
           # the number the cycle model applies as eta_Cf
           "Cd": float(np.mean(mdot[k]) / ref["mdot"]),
           "eta_cf_vac": float(np.mean(mdot[k]) / ref["mdot"] * np.mean(isp_vac[k]) / ref["isp_vac"]),
           "history": {"it": it.tolist()[::20], "isp": isp.tolist()[::20], "mdot_ratio": (mdot / ref["mdot"]).tolist()[::20]}}
    return out


def figure(res):
    data = PGF / "data"
    data.mkdir(parents=True, exist_ok=True)
    plots_a, plots_b = [], []
    cols = {"I1": "cK", "I2-C": "cFu"}
    for tag, r in res.items():
        it_, kind = tag.split()
        sty = f"{cols[it_]}, line width=0.8pt" + {"plume": ", densely dotted", "hisa": ", dashed"}.get(kind, "")
        f = data / f"fig15_{it_.replace('-', '')}_{kind}.csv"
        f.write_text("it,isp,mr\n" + "\n".join(f"{a},{b},{c}" for a, b, c in zip(r["history"]["it"], r["history"]["isp"],
                                                                            r["history"]["mdot_ratio"])), encoding="utf-8")
        plots_a.append(f"  \\addplot[{sty}] table[x=it, y=isp, col sep=comma] {{data/{f.name}}};\n"
                       f"  \\addlegendentry{{{tag}}}\n"
                       f"  \\draw[{cols[it_]}, refline] (axis cs:0,{r['ref_1d']['isp_amb']:.2f}) -- (axis cs:{r['iterations']},{r['ref_1d']['isp_amb']:.2f});")
        plots_b.append(f"  \\addplot[{sty}] table[x=it, y=mr, col sep=comma] {{data/{f.name}}};")
    tex = (r"""\documentclass[border=1.5pt]{standalone}
\input{style.tex}
\begin{document}
\begin{tikzpicture}
\begin{groupplot}[group style={group size=2 by 1, horizontal sep=1.6cm}, width=7.0cm, height=4.6cm,
    xlabel={iteration (local time step)}]
\nextgroupplot[ylabel={sea-level $I_{sp}$ from exit plane (s)}, title={(a) thrust convergence (dashed: ideal 1-D)},
    legend pos=south east]
""" + "\n".join(plots_a) + r"""
\nextgroupplot[ylabel={$\dot m_{in} / \dot m_{1\text{-}D}$}, title={(b) inlet mass flow}]
""" + "\n".join(plots_b) + r"""
  \draw[cK, refline] (rel axis cs:0,0.5) -- (rel axis cs:1,0.5);
\end{groupplot}
\end{tikzpicture}
\end{document}
""")
    texf = PGF / "fig15_cfd_convergence.tex"
    texf.write_text(tex, encoding="utf-8")
    r = subprocess.run([str(MIKTEX / "pdflatex.exe"), "-interaction=nonstopmode", "-halt-on-error", "--disable-installer",
                        texf.name], cwd=PGF, capture_output=True, text=True)
    if r.returncode == 0:
        subprocess.run([str(GS), "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m", "-r300", "-dTextAlphaBits=4",
                        "-dGraphicsAlphaBits=4", f"-sOutputFile={PGF / 'fig15_cfd_convergence.png'}",
                        str(PGF / "fig15_cfd_convergence.pdf")], check=True)
    for ext in (".aux", ".log"):
        (PGF / f"fig15_cfd_convergence{ext}").unlink(missing_ok=True)
    return r.returncode == 0


def main():
    res = {}
    for tag, name in CASES:
        r = analyse(tag, name)
        if r:
            res[tag] = r
            print(f"{tag:11s} it {r['iterations']:6d}  mdot {r['mdot_in']:6.1f} kg/s (1-D {r['ref_1d']['mdot']:.1f})  "
                  f"F {r['thrust_N'] / 1e6:6.3f} MN (1-D {r['ref_1d']['F_amb'] / 1e6:.3f})  Isp {r['isp_s']:6.1f} s "
                  f"(1-D {r['ref_1d']['isp_amb']:.1f})  eta_F {r['eta_F']:.3f}  drift {r['isp_drift_window_s']:.2f} s  "
                  f"mass imbalance {100 * r['mass_imbalance']:.2f} %  |  Isp_vac(exit) {r['isp_vac_exit_s']:.1f} s "
                  f"(1-D {r['ref_1d']['isp_vac']:.1f}, ratio {r['eta_isp_vac']:.4f}, drift {r['isp_vac_drift_window_s']:.2f} s)"
                  f"  Cd {r['Cd']:.4f}  eta_Cf,vac {r['eta_cf_vac']:.4f}")
    json.dump({k: {kk: vv for kk, vv in v.items() if kk != "history"} for k, v in res.items()},
              open(ROOT / "results" / "cfd_compare.json", "w"), indent=2)
    if res:
        print("figure:", "ok" if figure(res) else "pdflatex failed")


if __name__ == "__main__":
    main()
