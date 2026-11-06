"""Final figures of the PINN study, in pgfplots, with the style of the report figures.

usage: python -m pinn.make_figures
Writes figures/pinn/pinn_fig*.(tex|pdf|png) and their data in figures/pinn/data/. Line data are cell values on the real
meshes, and the PINN is evaluated at the same cell centres, so no griddata is involved.
"""

import json
import subprocess
from pathlib import Path

import numpy as np
import torch

from .ensemble import RES, ROOT, ROWS, columns, load_seeds, reference
from .quasi1d import Nozzle
from .score import CFD

OUT = ROOT / "figures" / "pinn"
DATA = OUT / "data"
MIKTEX = Path(r"C:\Users\siddh\AppData\Local\Programs\MiKTeX\miktex\bin\x64")
GS = Path(r"C:\Users\siddh\AppData\Local\Programs\Ghostscript\gs10.05.1\bin\gswin64c.exe")
HEAD = "\\documentclass[border=1.5pt]{standalone}\n\\input{../pgf/style.tex}\n\\begin{document}\n\\begin{tikzpicture}\n"
TAIL = "\n\\end{tikzpicture}\n\\end{document}\n"
TAB = "col sep=comma"
FINE, COARSE = "Euler CFD, 91,935 cells", "Euler CFD, 40,860 cells"


def table(name, **cols):
    keys = list(cols)
    rows = np.column_stack([np.asarray(cols[k], float) for k in keys])
    np.savetxt(DATA / f"{name}.csv", rows, delimiter=",", header=",".join(keys), comments="", fmt="%.7g")


def build(name, body):
    f = OUT / f"{name}.tex"
    f.write_text(HEAD + body + TAIL, encoding="utf-8")
    r = subprocess.run([str(MIKTEX / "pdflatex.exe"), "-interaction=nonstopmode", "-halt-on-error", "--disable-installer", f.name],
                       cwd=OUT, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-1500:])
        raise SystemExit(f"pdflatex failed on {name}")
    subprocess.run([str(GS), "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m", "-r300", "-dTextAlphaBits=4", "-dGraphicsAlphaBits=4",
                    f"-sOutputFile={OUT / (name + '.png')}", str(OUT / f"{name}.pdf")], check=True)
    for ext in (".aux", ".log"):
        (OUT / f"{name}{ext}").unlink(missing_ok=True)
    print(name)


def seed_lines(csv, xcol, seeds, legend=True):
    """All seeds in one colour: only their first line takes a legend entry."""
    out = []
    for i, s in enumerate(seeds):
        last = "" if i == 0 and legend else ", forget plot"
        out.append(f"  \\addplot[cOx, line width=0.55pt{last}] table[x={xcol}, y=s{s}, {TAB}] {{data/{csv}.csv}};")
        if i == 0 and legend:
            out.append(f"  \\addlegendentry{{PINN, {len(seeds)} seeds}}")
    return "\n".join(out)


def quasi1d():
    d = np.load(RES / "step2_lines.npz")
    k = np.arange(0, len(d["xi"]), 4)
    table("fig1", xi=d["xi"][k], M=d["M"][k], eM_s=(d["M_s"] - d["M"])[k], eM_w=(d["M_w"] - d["M"])[k], M_s=d["M_s"][k], M_w=d["M_w"][k], lnp0_s=d["lnp0_s"][k], lnp0_w=d["lnp0_w"][k])
    line = lambda y, sty, leg=None: f"  \\addplot[{sty}] table[x=xi, y={y}, {TAB}] {{data/fig1.csv}};" + (f" \\addlegendentry{{{leg}}}" if leg else "")
    S, W = "cFu, densely dashed, line width=0.8pt", "cOx, line width=0.8pt"
    build("pinn_fig1_quasi1d", "\n".join([
        r"\begin{groupplot}[group style={group size=3 by 1, horizontal sep=1.45cm}, width=5.25cm, height=4.5cm, xlabel={$x/R_t$}, xmin=-3, xmax=15]",
        r"\nextgroupplot[title={(a) Mach number}, ylabel={Mach number}, legend pos=south east, legend style={font=\footnotesize}]",
        line("M", "cIn, line width=2.0pt", "exact"), line("M_s", S, "strong form"), line("M_w", W, "impulse balance"),
        r"\nextgroupplot[title={(b) Mach number error}, ylabel={PINN minus exact}, scaled y ticks=false, yticklabel style={/pgf/number format/.cd, fixed, fixed zerofill, precision=2}]",
        line("eM_s", S), line("eM_w", W),
        r"\nextgroupplot[title={(c) stagnation pressure drift}, ylabel={$\ln(p_0/p_{0,c})$}, scaled y ticks=false, yticklabel style={/pgf/number format/.cd, fixed, fixed zerofill, precision=2}]",
        line("lnp0_s", S), line("lnp0_w", W), r"\end{groupplot}"]))


def lines(nz, seeds):
    fine, coarse = reference("euler_r15", nz), reference("euler", nz)
    gf, gc = columns(fine, ROWS["euler_r15"]), columns(coarse, ROWS["euler"])
    xi = lambda d, c: (d["x"][c] - nz.x_t) / nz.Rt
    cf = gf[int(np.argmin(np.abs(xi(fine, gf).mean(1))))]
    cc = gc[int(np.argmin(np.abs(xi(coarse, gc).mean(1))))]
    x0 = float(xi(fine, cf).mean())
    pred = lambda c: {f"s{s}": m.predict(fine["x"][c], fine["r"][c])["Ma"] for s, m in seeds.items()}
    table("fig2_axis", xi=xi(fine, gf[:, 0]), cfd=fine["Ma"][gf[:, 0]], **pred(gf[:, 0]))
    table("fig2_wall", xi=xi(fine, gf[:, -1]), cfd=fine["Ma"][gf[:, -1]], **pred(gf[:, -1]))
    table("fig2_axis_c", xi=xi(coarse, gc[:, 0]), cfd=coarse["Ma"][gc[:, 0]])
    table("fig2_wall_c", xi=xi(coarse, gc[:, -1]), cfd=coarse["Ma"][gc[:, -1]])
    table("fig2_throat", r=fine["r"][cf] / nz.Rt, cfd=fine["Ma"][cf], **pred(cf))
    table("fig2_throat_c", r=coarse["r"][cc] / nz.Rt, cfd=coarse["Ma"][cc])
    m0 = next(iter(seeds.values()))
    table("fig2_1d", xi=m0.fine, M=m0.ref1d["M"])
    n = list(seeds)
    cfd = lambda f, x="xi", lw="0.7pt": f"  \\addplot[cK, line width={lw}] table[x={x}, y=cfd, {TAB}] {{data/{f}.csv}}; \\addlegendentry{{{FINE}}}"
    crs = lambda f, x="xi": f"  \\addplot[cIn, line width=0.8pt] table[x={x}, y=cfd, {TAB}] {{data/{f}.csv}}; \\addlegendentry{{{COARSE}}}"
    legend = r"legend style={font=\footnotesize}"
    build("pinn_fig2_lines", "\n".join([
        r"\begin{groupplot}[group style={group size=2 by 2, horizontal sep=1.45cm, vertical sep=1.55cm}, width=7.3cm, height=5.0cm]",
        rf"\nextgroupplot[title={{(a) Mach number on the axis}}, xlabel={{$x/R_t$}}, ylabel={{Mach number}}, xmin=-3, xmax=15, legend pos=south east, {legend}]",
        cfd("fig2_axis"), seed_lines("fig2_axis", "xi", n),
        f"  \\addplot[cFu, densely dashed, line width=0.8pt] table[x=xi, y=M, {TAB}] {{data/fig2_1d.csv}}; \\addlegendentry{{1-D exact}}",
        rf"\nextgroupplot[title={{(b) internal shock on the axis}}, xlabel={{$x/R_t$}}, ylabel={{Mach number}}, xmin=8.5, xmax=11.5, ymin=3.0, ymax=4.3, legend pos=south west, {legend}]",
        crs("fig2_axis_c"), cfd("fig2_axis", lw="0.9pt"), seed_lines("fig2_axis", "xi", n),
        rf"\nextgroupplot[title={{(c) Mach number across the throat, $x/R_t = {x0:.3f}$}}, xlabel={{$r/R_t$}}, ylabel={{Mach number}}, xmin=0, xmax=1.0, legend pos=north west, {legend}]",
        crs("fig2_throat_c", "r"), cfd("fig2_throat", "r", "0.9pt"), seed_lines("fig2_throat", "r", n),
        rf"\nextgroupplot[title={{(d) Mach number at the wall near the throat}}, xlabel={{$x/R_t$}}, ylabel={{Mach number}}, xmin=-1, xmax=3, ymin=0.4, ymax=2.8, legend pos=south east, {legend}]",
        crs("fig2_wall_c"), cfd("fig2_wall", lw="0.9pt"), seed_lines("fig2_wall", "xi", n), r"\end{groupplot}"]))


def rans(nz, seeds):
    """What the inviscid comparison leaves out: the RANS run has the same inlet and walls, with viscosity."""
    fine, visc = reference("euler_r15", nz), reference("nozzle", nz)
    gf, gv = columns(fine, ROWS["euler_r15"]), columns(visc, ROWS["nozzle"])
    xi = lambda d, c: (d["x"][c] - nz.x_t) / nz.Rt
    mean = lambda c, key: np.mean([m.predict(fine["x"][c], fine["r"][c])[key] for m in seeds.values()], 0)
    table("fig3_wall", xi=xi(fine, gf[:, -1]), cfd=fine["p"][gf[:, -1]], pinn=mean(gf[:, -1], "p"))
    table("fig3_wall_v", xi=xi(visc, gv[:, -1]), cfd=visc["p"][gv[:, -1]])
    Re = float(nz.r(nz.phys(nz.xie)))
    table("fig3_exit", r=fine["r"][gf[-1]] / Re, cfd=fine["Ma"][gf[-1]], pinn=mean(gf[-1], "Ma"))
    table("fig3_exit_v", r=visc["r"][gv[-1]] / Re, cfd=visc["Ma"][gv[-1]])
    legend = r"legend style={font=\footnotesize}"
    add = lambda sty, y, f, x, leg: f"  \\addplot[{sty}] table[x={x}, y={y}, {TAB}] {{data/{f}.csv}}; \\addlegendentry{{{leg}}}"
    V, E, P = "cR, line width=0.9pt", "cK, line width=0.9pt", "cOx, line width=0.9pt"
    build("pinn_fig3_rans", "\n".join([
        r"\begin{groupplot}[group style={group size=2 by 1, horizontal sep=1.45cm}, width=7.3cm, height=5.0cm]",
        rf"\nextgroupplot[title={{(a) pressure at the wall}}, xlabel={{$x/R_t$}}, ylabel={{$p/p_0$}}, ymode=log, xmin=0, xmax=14.5, legend pos=north east, {legend}]",
        add(V, "cfd", "fig3_wall_v", "xi", "RANS CFD"), add(E, "cfd", "fig3_wall", "xi", "Euler CFD"), add(P, "pinn", "fig3_wall", "xi", "PINN, seed mean"),
        rf"\nextgroupplot[title={{(b) Mach number across the exit plane}}, xlabel={{$r/R_e$}}, ylabel={{Mach number}}, xmin=0, xmax=1, ymin=1.5, ymax=4.1, legend pos=south west, {legend}]",
        add(V, "cfd", "fig3_exit_v", "r", "RANS CFD"), add(E, "cfd", "fig3_exit", "r", "Euler CFD"), add(P, "pinn", "fig3_exit", "r", "PINN, seed mean"), r"\end{groupplot}"]))


def seeds_loss(seeds):
    sc = json.loads((RES / "step3_axisym_scores.json").read_text())
    ref = CFD["euler_r15"]
    n = list(seeds)
    table("fig4_seeds", seed=n, dCd=[100 * (sc["runs"][str(s)]["Cd"] / ref["Cd"] - 1) for s in n], dCf=[100 * (sc["runs"][str(s)]["eta_cf_vac"] / ref["eta_cf_vac"] - 1) for s in n])
    d = json.loads((RES / "step3_axisym_seed0.json").read_text())
    h = d["history"] + [d["runs"][0]["final"]]
    table("fig4_loss", step=[r["step"] + 1 for r in h], total=[r["total"] for r in h], Mr=[r["Mr"] for r in h], Mx=[r["Mx"] for r in h], s=[r["s"] for r in h])
    pts = lambda y, sty, leg: f"  \\addplot[only marks, {sty}] table[x=seed, y={y}, {TAB}] {{data/fig4_seeds.csv}}; \\addlegendentry{{{leg}}}"
    loss = lambda y, c, leg: f"  \\addplot[{c}, line width=0.8pt, mark=*, mark size=1pt] table[x=step, y={y}, {TAB}] {{data/fig4_loss.csv}}; \\addlegendentry{{{leg}}}"
    legend = r"legend style={font=\footnotesize}"
    build("pinn_fig4_seeds", "\n".join([
        r"\begin{groupplot}[group style={group size=2 by 1, horizontal sep=1.45cm}, width=7.3cm, height=4.8cm]",
        rf"\nextgroupplot[title={{(a) error against the 91,935-cell Euler run}}, xlabel={{seed}}, ylabel={{PINN minus CFD (\%)}}, xmin=-0.5, xmax={len(n) - 0.5}, ymin=0, ymax=0.3, scaled y ticks=false, yticklabel style={{/pgf/number format/.cd, fixed, fixed zerofill, precision=2}}, xtick={{{','.join(map(str, n))}}}, legend pos=north east, legend columns=2, {legend}]",
        pts("dCd", "mark=*, mark size=2pt, cOx", "$C_d$"), pts("dCf", "mark=square*, mark size=1.8pt, cFu", "$C_f$ ratio"),
        r"  \draw[cK, refline] (axis cs:-0.5,0.2) -- (axis cs:4.5,0.2) node[ann, pos=0.12, above] {gate, 0.2 \%};",
        rf"\nextgroupplot[title={{(b) loss terms, seed 0}}, xlabel={{training step}}, ylabel={{loss term}}, ymode=log, xmin=0, xmax=34000, ymin=2e-6, ymax=10, scaled x ticks=false, legend pos=north east, {legend}]",
        loss("total", "cK", "total"), loss("Mr", "cOx", "radial momentum"), loss("s", "cFu", "second law"), loss("Mx", "cIn", "axial momentum"),
        r"  \draw[cK, refline] (axis cs:20000,2e-6) -- (axis cs:20000,10) node[ann, pos=0.08, left] {L-BFGS starts};", r"\end{groupplot}"]))


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    nz = Nozzle()
    seeds = load_seeds(nz)
    quasi1d()
    lines(nz, seeds)
    rans(nz, seeds)
    seeds_loss(seeds)


if __name__ == "__main__":
    main()
