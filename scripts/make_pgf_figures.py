"""pgfplots versions of the report figures (fig01-fig14).

Reads the same results files as make_figures.py, run_pc_ceiling.py, run_pac.py and run_economics.py,
writes the plotted data to figures/pgf/data/*.csv, one standalone .tex per figure and a shared
figures/pgf/style.tex, then compiles each figure with pdflatex and renders a 300 dpi PNG with Ghostscript.
Nothing in results/ or figures/*.png|pdf is written.

    .venv\\Scripts\\python.exe scripts\\make_pgf_figures.py              # export, compile, PNG
    .venv\\Scripts\\python.exe scripts\\make_pgf_figures.py --only fig03 fig11
    .venv\\Scripts\\python.exe scripts\\make_pgf_figures.py --no-compile # .tex and data only
"""

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "figures" / "pgf"
DATA = OUT / "data"
RES = ROOT / "results"

MIKTEX = Path(r"C:\Users\siddh\AppData\Local\Programs\MiKTeX\miktex\bin\x64")
GS = Path(r"C:\Users\siddh\AppData\Local\Programs\Ghostscript\gs10.05.1\bin\gswin64c.exe")
DPI = 300

# ------------------------------------------------------------------ shared LaTeX style
STYLE = r"""% Shared style for the MFE-280 report figures. Written by scripts/make_pgf_figures.py.
% pdflatex, STIX Two (Type 1) text and maths, pgfplots 1.18.
\usepackage[T1]{fontenc}
\usepackage{stix2}
\usepackage{amsmath}
\usepackage{pgfplots}
\usepackage{pgfplotstable}
\pgfplotsset{compat=1.18}
\usepgfplotslibrary{groupplots}
\usetikzlibrary{calc}

% ---------------------------------------------------------------- colours (as in scripts/figstyle.py)
\definecolor{cK}{HTML}{222222}   % black lines
\definecolor{cCu}{HTML}{B5651D}  % GRCop-42 / copper
\definecolor{cIn}{HTML}{6B6F7A}  % Inconel / neutral grey
\definecolor{cOx}{HTML}{1F5FA8}  % oxidiser side
\definecolor{cFu}{HTML}{A8641F}  % fuel side
\definecolor{cG}{HTML}{2E7D32}   % green
\definecolor{cR}{HTML}{B71C1C}   % red
\definecolor{cP}{HTML}{6A3D9A}   % purple
\definecolor{cCl}{HTML}{9AA0AA}  % closeout grey
\definecolor{cAmber}{HTML}{E0A030}
\definecolor{cGrey}{HTML}{9E9E9E}
\definecolor{cSand}{HTML}{C9B38A}
\definecolor{cBench}{HTML}{BBBBBB}
\definecolor{cKey}{HTML}{777777}
\definecolor{cTRLii}{HTML}{B71C1C}
\definecolor{cTRLiv}{HTML}{E65100}
\definecolor{cTRLv}{HTML}{F9A825}
\definecolor{cTRLvi}{HTML}{7CB342}
\definecolor{cTRLvii}{HTML}{2E7D32}
\definecolor{cTRLviii}{HTML}{1B5E20}
\definecolor{cTRLx}{HTML}{999999}

% ---------------------------------------------------------------- axis style
\pgfplotsset{
  every axis/.append style={
    scale only axis,
    enlargelimits=false,
    clip mode=individual,
    tick align=inside,
    major tick length=3pt,
    minor tick length=1.6pt,
    tick style={line width=0.4pt, black},
    axis line style={line width=0.5pt},
    tick label style={font=\footnotesize},
    label style={font=\small},
    title style={font=\small, yshift=-2pt},
    legend style={font=\footnotesize, draw=none, fill=white, inner sep=1.5pt, row sep=-1.5pt},
    max space between ticks=27,
    legend cell align=left,
    every axis plot/.append style={line width=0.9pt},
    scaled ticks=false,
    /pgf/number format/1000 sep={},
    unbounded coords=jump,
    xlabel shift=-1pt, ylabel shift=-2pt,
  },
  every axis legend/.append style={/tikz/every even column/.append style={column sep=5pt}},
  area/.style={legend image code/.code={\fill[##1] (0cm,-0.09cm) rectangle (0.45cm,0.13cm);}},
  twin/.style={axis x line=none, axis y line*=right, ylabel style={text=#1},
               yticklabel style={text=#1}, ytick style={#1}},
}
\tikzset{
  mk/.style={mark size=1.8pt, mark options={solid}},
  mkt/.style={mark size=2.3pt, mark options={solid}},
  refline/.style={line width=0.45pt, densely dotted},
  ann/.style={font=\footnotesize, inner sep=1pt},
}
"""

DOC = r"""\documentclass[border=1.5pt]{standalone}
\input{style.tex}
\begin{document}
<<body>>
\end{document}
"""


# ------------------------------------------------------------------ helpers
def num(v):
    v = float(v)
    if v == 0:
        return "0"
    return f"{v:.6g}"


def fill(tpl, **kw):
    for k, v in kw.items():
        rep = num(v) if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) else str(v)
        tpl = tpl.replace(f"<<{k}>>", rep)
    left = re.findall(r"<<\w+>>", tpl)
    if left:
        raise ValueError(f"unfilled template keys {left}")
    return tpl


def write_csv(name, cols):
    """cols: dict of column -> sequence (numbers or strings). NaN is written as nan."""
    DATA.mkdir(parents=True, exist_ok=True)
    keys = list(cols)
    n = len(cols[keys[0]])
    with open(DATA / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(keys)
        for i in range(n):
            row = []
            for k in keys:
                v = cols[k][i]
                if isinstance(v, str):
                    row.append(v)
                elif v is None or (isinstance(v, float) and math.isnan(v)):
                    row.append("nan")
                else:
                    row.append(f"{float(v):.8g}")
            w.writerow(row)
    return f"data/{name}.csv"


def tread(path, macro):
    return rf"\pgfplotstableread[col sep=comma]{{{path}}}{{\{macro}}}"


def mlim(vals, margin=0.05, log=False):
    """Matplotlib-style auto limits: data range plus a 5 % margin (in log space for log axes)."""
    v = np.asarray([x for x in np.ravel(vals) if x is not None and np.isfinite(x)], dtype=float)
    if log:
        v = np.log10(v[v > 0])
    lo, hi = float(v.min()), float(v.max())
    d = (hi - lo) * margin if hi > lo else (abs(lo) * margin or 1.0)
    lo, hi = lo - d, hi + d
    return (10 ** lo, 10 ** hi) if log else (lo, hi)


def tex(s):
    """Escape a data string for LaTeX and typeset a few recurring tokens."""
    s = str(s)
    for a, b in (("{", r"\{"), ("}", r"\}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("^", r"\^{}")):
        s = s.replace(a, b)
    s = s.replace("~", r"$\sim$")
    s = s.replace(" -> ", r" $\rightarrow$ ")
    s = re.sub(r"\beta\b", r"$\\eta$", s)
    s = re.sub(r'"([^"]*)"', r"``\1''", s)
    s = re.sub(r"\bCH4\b", r"CH$_4$", s)
    return s


def rect_polys(rects):
    """Rectangles (x0, x1, y0, y1) as one NaN-separated polygon table (filled as separate pieces)."""
    xs, ys = [], []
    for x0, x1, y0, y1 in rects:
        xs += [x0, x1, x1, x0, x0, float("nan")]
        ys += [y0, y0, y1, y1, y0, float("nan")]
    return {"x": xs[:-1], "y": ys[:-1]}


def band_poly(x, lo, hi):
    x = np.asarray(x, float)
    return {"x": list(x) + list(x[::-1]), "y": list(np.asarray(hi, float)) + list(np.asarray(lo, float)[::-1])}


FIGS = {}


def figure(name):
    def deco(fn):
        FIGS[name] = fn
        return fn
    return deco


def load_json(rel):
    return json.load(open(ROOT / rel, encoding="utf-8"))


# ================================================================== fig01 contour and channels
def cooling_profile():
    P = list(csv.DictReader(open(RES / "cooling_profile.csv")))
    return {k: np.array([float(r[k]) for r in P]) for k in P[0]}


@figure("fig01_contour_channels")
def fig01():
    D = load_json("results/design.json")
    c = cooling_profile()
    x = c["x"] * 1e3
    r, th, H, tc = c["r"] * 1e3, c["t_hot"] * 1e3, c["H"] * 1e3, c["t_closeout"] * 1e3
    zone = c["zone"]
    p_prof = write_csv("fig01_profile", {"x": x, "r": r, "H_sized": c["H_sized"] * 1e3, "H": H, "W": c["W"] * 1e3,
                                         "rib": c["rib"] * 1e3, "N": c["N"]})
    m0, m1 = zone == 0, zone == 1
    p_cu = write_csv("fig01_band_grcop", band_poly(x[m0], r[m0], (r + th + H)[m0]))
    p_in = write_csv("fig01_band_inconel", band_poly(x[m1], r[m1], (r + th + H)[m1]))
    p_cl = write_csv("fig01_band_closeout", band_poly(x, r + th + H, r + th + H + tc))
    g = D["geometry"]
    xj, xt = g["x_joint_m"] * 1e3, g["x_throat_m"] * 1e3
    xlo, xhi = mlim(x)
    ylo2, yhi2 = mlim(np.r_[c["H_sized"], c["H"], c["W"], c["rib"]] * 1e3)
    nlo, nhi = mlim(c["N"])
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{groupplot}[group style={group size=1 by 2, vertical sep=0.3cm, x descriptions at=edge bottom},
    width=<<W>>cm, xmin=<<xlo>>, xmax=<<xhi>>]
\nextgroupplot[height=<<H1>>cm, ymin=0, ymax=760, ytick distance=100, ylabel={radius (mm)},
    legend style={at={(0.99,0.30)}, anchor=south east}]
  \addplot[draw=none, fill=cCu, fill opacity=0.55, area] table[x=x, y=y] {\bandCu};
  \addlegendentry{GRCop-42 liner (L-PBF) + channels}
  \addplot[draw=none, fill=cIn, fill opacity=0.55, area] table[x=x, y=y] {\bandIn};
  \addlegendentry{Inconel 718 liner + channels}
  \addplot[draw=none, fill=cCl, fill opacity=0.8, area] table[x=x, y=y] {\bandCl};
  \addlegendentry{Inconel 718 closeout}
  \addplot[cK, line width=0.8pt] table[x=x, y=r] {\prof};
  \addlegendentry{gas-side contour}
  \draw[cK, refline] (axis cs:<<xj>>,0) -- (axis cs:<<xj>>,760);
  \node[ann, anchor=base west] at (axis cs:<<xjt>>,120) {bolted joint, $\varepsilon = <<epsj>>$};
  \draw[cK, line width=0.4pt, dashed] (axis cs:<<xt>>,0) -- (axis cs:<<xt>>,760);
  \node[ann, anchor=base west] at (axis cs:<<xtt>>,40) {throat, $D_t = <<Dt>>$ mm};
\nextgroupplot[height=<<H2>>cm, ymin=<<ylo2>>, ymax=<<yhi2>>, ytick pos=left,
    ylabel={channel size (mm)}, xlabel={axial distance from injector face (mm)},
    legend style={at={(0.01,0.55)}, anchor=west}]
  \addplot[cK, opacity=0.5, line width=0.5pt] table[x=x, y=H_sized] {\prof};
  \addlegendentry{height, sized per station}
  \addplot[cK] table[x=x, y=H] {\prof};
  \addlegendentry{height, smoothed (built)}
  \addplot[cOx] table[x=x, y=W] {\prof};
  \addlegendentry{width}
  \addplot[cFu] table[x=x, y=rib] {\prof};
  \addlegendentry{rib}
\end{groupplot}
\begin{axis}[twin=cG, at={(group c1r2.south west)}, anchor=south west, width=<<W>>cm, height=<<H2>>cm,
    xmin=<<xlo>>, xmax=<<xhi>>, ymin=<<nlo>>, ymax=<<nhi>>, ylabel={channels}]
  \addplot[cG, line width=0.7pt, const plot mark mid] table[x=x, y=N] {\prof};
\end{axis}
\end{tikzpicture}"""
    reads = "\n".join([tread(p_prof, "prof"), tread(p_cu, "bandCu"), tread(p_in, "bandIn"), tread(p_cl, "bandCl")])
    return fill(body, reads=reads, W=14.7, H1=5.6, H2=4.3, xlo=xlo, xhi=xhi, xj=xj, xjt=xj + 15, xt=xt, xtt=xt + 15,
                epsj=f"{g['eps_joint']:.0f}", Dt=f"{2 * g['Rt_m'] * 1e3:.0f}", ylo2=ylo2, yhi2=yhi2, nlo=nlo, nhi=nhi)


# ================================================================== fig02 cooling solution
@figure("fig02_cooling")
def fig02():
    D = load_json("results/design.json")
    c = cooling_profile()
    x = c["x"] * 1e3
    p = write_csv("fig02_cooling", {"x": x, "q": c["q"] / 1e6, "Twg": c["Twg"], "Twc": c["Twc"], "Tb": c["Tb"],
                                    "p": c["p"] / 1e5, "v": c["v"]})
    xj = D["geometry"]["x_joint_m"] * 1e3
    targets = [z["Twg_target_K"] for z in D["config"]["cooling"]["zones"]]
    xlo, xhi = mlim(x)
    q = mlim(c["q"] / 1e6)
    t = mlim(np.r_[c["Twg"], c["Twc"], c["Tb"], targets])
    pp = mlim(c["p"] / 1e5)
    vv = mlim(c["v"])
    hl = "\n".join(rf"  \draw[cK, refline] (axis cs:<<xlo>>,{num(v)}) -- (axis cs:<<xhi>>,{num(v)});" for v in targets)
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{groupplot}[group style={group size=1 by 3, vertical sep=0.72cm, x descriptions at=edge bottom},
    width=<<W>>cm, height=<<H>>cm, xmin=<<xlo>>, xmax=<<xhi>>]
\nextgroupplot[ymin=<<q0>>, ymax=<<q1>>, ylabel={heat flux (MW\,m$^{-2}$)}]
  \addplot[cR] table[x=x, y=q] {\cool};
  \draw[cK, refline] (axis cs:<<xj>>,<<q0>>) -- (axis cs:<<xj>>,<<q1>>);
  \node[ann, anchor=north west, align=left] at (axis cs:<<xjt>>,<<qtext>>) {coolant enters at the joint:\\circuit A runs up, circuit B runs down};
\nextgroupplot[ymin=<<t0>>, ymax=<<t1>>, ylabel={temperature (K)},
    legend style={at={(0.5,1.03)}, anchor=south, legend columns=3, fill=none}]
  \addplot[cR] table[x=x, y=Twg] {\cool};
  \addlegendentry{$T_{wg}$ hot wall}
  \addplot[cFu] table[x=x, y=Twc] {\cool};
  \addlegendentry{$T_{wc}$ coolant-side wall}
  \addplot[cOx] table[x=x, y=Tb] {\cool};
  \addlegendentry{$T_b$ methane bulk}
<<hlines>>
  \draw[cK, refline] (axis cs:<<xj>>,<<t0>>) -- (axis cs:<<xj>>,<<t1>>);
\nextgroupplot[ymin=<<p0>>, ymax=<<p1>>, ytick pos=left, ylabel={pressure (bar)},
    xlabel={axial distance from injector face (mm)}]
  \addplot[cK] table[x=x, y=p] {\cool};
  \draw[cK, refline] (axis cs:<<xj>>,<<p0>>) -- (axis cs:<<xj>>,<<p1>>);
\end{groupplot}
\begin{axis}[twin=cG, at={(group c1r3.south west)}, anchor=south west, width=<<W>>cm, height=<<H>>cm,
    xmin=<<xlo>>, xmax=<<xhi>>, ymin=<<v0>>, ymax=<<v1>>, ylabel={velocity (m\,s$^{-1}$)}]
  \addplot[cG, line width=0.7pt] table[x=x, y=v] {\cool};
\end{axis}
\end{tikzpicture}"""
    body = body.replace("<<hlines>>", hl)
    return fill(body, reads=tread(p, "cool"), W=15.1, H=3.7, xlo=xlo, xhi=xhi, xj=xj, xjt=xj + 15,
                qtext=q[0] + 0.90 * (q[1] - q[0]), q0=q[0], q1=q[1], t0=t[0],
                t1=t[1], p0=pp[0], p1=pp[1], v0=vv[0], v1=vv[1])


# ================================================================== fig03 pressure ladder
# label placement per station: (anchor, xshift pt, yshift pt); text is "name\\value"
LADDER_OX = {"pump inlet": ("south east", -3, 2), "LOX pump": ("south east", -6, 1), "OPB": ("north east", -3, -3),
             "ox turbine exit": ("north east", -3, -3), "chamber": ("north east", -3, -3)}
LADDER_FU = {"pump inlet": ("south west", 9, 1), "CH4 pump": ("south west", 4, 3), "jacket out": ("south west", 4, 3),
             "FPB": ("south west", 4, 3), "fuel turbine exit": ("south west", 4, 3), "chamber": ("north", 0, -4)}


@figure("fig03_pressure_ladder")
def fig03():
    D = load_json("results/design.json")
    c = D["cycle"]
    pc = D["performance"]["pc"] / 1e5
    ox = [("pump inlet", c["ox_pump"]["p_in"] / 1e5), ("LOX pump", c["p_ox_discharge_Pa"] / 1e5),
          ("OPB", c["p_opb_Pa"] / 1e5), ("ox turbine exit", c["p_turbine_exit_Pa"] / 1e5), ("chamber", pc)]
    fu = [("pump inlet", c["fuel_pump"]["p_in"] / 1e5), ("CH4 pump", c["p_fuel_discharge_Pa"] / 1e5),
          ("jacket out", D["cooling"]["p_out_Pa"] / 1e5), ("FPB", c["p_fpb_Pa"] / 1e5),
          ("fuel turbine exit", c["p_turbine_exit_Pa"] / 1e5), ("chamber", pc)]
    p_ox = write_csv("fig03_ox", {"i": list(range(len(ox))), "p": [v for _, v in ox]})
    p_fu = write_csv("fig03_fuel", {"i": [i + 0.15 for i in range(len(fu))], "p": [v for _, v in fu]})
    nodes = []
    for i, (n, v) in enumerate(ox):
        a, dx, dy = LADDER_OX.get(n, ("south east", -3, 2))
        nodes.append(rf"  \node[ann, text=cOx, align=center, anchor={a}, xshift={dx}pt, yshift={dy}pt] "
                     rf"at (axis cs:{num(i)},{num(v)}) {{{tex(n)}\\{v:.0f}}};")
    for i, (n, v) in enumerate(fu):
        a, dx, dy = LADDER_FU.get(n, ("south west", 4, 3))
        nodes.append(rf"  \node[ann, text=cFu, align=center, anchor={a}, xshift={dx}pt, yshift={dy}pt] "
                     rf"at (axis cs:{num(i + 0.15)},{num(v)}) {{{tex(n)}\\{v:.0f}}};")
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{axis}[width=<<W>>cm, height=<<H>>cm, xmin=-0.72, xmax=<<xhi>>, ymin=0, ymax=1050,
    xtick=\empty, ylabel={pressure (bar)}, legend style={at={(0.99,0.98)}, anchor=north east}]
  \addplot[cOx, mark=*, mk] table[x=i, y=p] {\ox};
  \addlegendentry{oxidiser side}
  \addplot[cFu, mark=square*, mk] table[x=i, y=p] {\fu};
  \addlegendentry{fuel side}
<<nodes>>
\end{axis}
\end{tikzpicture}"""
    body = body.replace("<<nodes>>", "\n".join(nodes))
    return fill(body, reads=tread(p_ox, "ox") + "\n" + tread(p_fu, "fu"), W=15.9, H=6.6,
                xhi=mlim([0, len(fu) - 1 + 0.15])[1])


# ================================================================== fig04 mixture ratio and expansion ratio
def ok(rows, key):
    return [r for r in rows if r.get("feasible") and key in r]


@figure("fig04_mr_eps")
def fig04():
    T = load_json("results/trades.json")
    rows = ok(T["mixture_ratio"], "isp_sl")
    mr = [r["requirements.mixture_ratio"] for r in rows]
    a = {"mr": mr, "isp_sl": [r["isp_sl"] for r in rows], "isp_vac": [r["isp_vac"] for r in rows],
         "disp": [r["density_isp_sl"] for r in rows]}
    p_a = write_csv("fig04_mixture_ratio", a)
    rows = ok(T["expansion_ratio"], "isp_sl")
    b = {"eps": [r["nozzle.expansion_ratio"] for r in rows], "isp_sl": [r["isp_sl"] for r in rows],
         "sep40": [r["sep_margin_40"] for r in rows]}
    p_b = write_csv("fig04_expansion_ratio", b)
    ax_ = mlim(a["mr"])
    ay = mlim(a["isp_sl"] + a["isp_vac"])
    ay2 = mlim(a["disp"])
    bx = mlim(b["eps"])
    by = mlim(b["isp_sl"])
    by2 = mlim(b["sep40"] + [1.0])
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{groupplot}[group style={group size=2 by 1, horizontal sep=2.75cm},
    width=<<W>>cm, height=<<H>>cm, ytick pos=left]
\nextgroupplot[xmin=<<ax0>>, xmax=<<ax1>>, ymin=<<ay0>>, ymax=<<ay1>>,
    xlabel={mixture ratio O/F}, ylabel={$I_{sp}$ (s)},
    legend style={at={(0.98,0.35)}, anchor=south east}]
  \addplot[cK, mark=*, mk] table[x=mr, y=isp_sl] {\mr};
  \addlegendentry{$I_{sp}$ sea level}
  \addplot[cK, dashed, mark=square*, mk] table[x=mr, y=isp_vac] {\mr};
  \addlegendentry{$I_{sp}$ vacuum}
  \draw[cK, refline] (axis cs:3.6,<<ay0>>) -- (axis cs:3.6,<<ay1>>);
\nextgroupplot[xmin=<<bx0>>, xmax=<<bx1>>, ymin=<<by0>>, ymax=<<by1>>,
    xlabel={expansion ratio $\varepsilon$}, ylabel={$I_{sp}$ sea level (s)}]
  \addplot[cK, mark=*, mk] table[x=eps, y=isp_sl] {\eps};
  \draw[cK, refline] (axis cs:34,<<by0>>) -- (axis cs:34,<<by1>>);
\end{groupplot}
\begin{axis}[twin=cG, at={(group c1r1.south west)}, anchor=south west, width=<<W>>cm, height=<<H>>cm,
    xmin=<<ax0>>, xmax=<<ax1>>, ymin=<<ay20>>, ymax=<<ay21>>,
    ylabel={$\rho_{\mathrm{bulk}} I_{sp}$ (t\,s\,m$^{-3}$)}]
  \addplot[cG, mark=triangle*, mkt] table[x=mr, y=disp] {\mr};
\end{axis}
\begin{axis}[twin=cR, at={(group c2r1.south west)}, anchor=south west, width=<<W>>cm, height=<<H>>cm,
    xmin=<<bx0>>, xmax=<<bx1>>, ymin=<<by20>>, ymax=<<by21>>, ylabel={Schmucker margin at 40\,\%}]
  \addplot[cR, mark=square*, mk] table[x=eps, y=sep40] {\eps};
  \draw[cR, refline] (axis cs:<<bx0>>,1) -- (axis cs:<<bx1>>,1);
\end{axis}
\end{tikzpicture}"""
    return fill(body, reads=tread(p_a, "mr") + "\n" + tread(p_b, "eps"), W=6.1, H=4.9,
                ax0=ax_[0], ax1=ax_[1], ay0=ay[0], ay1=ay[1], ay20=ay2[0], ay21=ay2[1],
                bx0=bx[0], bx1=bx[1], by0=by[0], by1=by[1], by20=by2[0], by21=by2[1])


# ================================================================== fig05 sensitivity tornado
@figure("fig05_sensitivity_tornado")
def fig05():
    D = load_json("results/design.json")
    T = load_json("results/trades.json")
    base_pf = D["cycle"]["p_fuel_discharge_Pa"] / 1e5
    base_po = D["cycle"]["p_ox_discharge_Pa"] / 1e5
    tor = []
    for study, label in [("channel_roughness", r"channel roughness 3--15\,\textmu m"),
                         ("nozzle_circuit_fraction", "coolant split 0.2--0.5"),
                         ("tip_clearance", "turbine tip clearance 0.15--0.25 mm"),
                         ("bartz_factor", r"Bartz heat flux $\times$0.8--1.2"),
                         ("opb_temperature", "OPB 800--900 K"), ("fpb_temperature", "FPB 1050--1300 K"),
                         ("pump_inlet_pressure", "pump inlet 5--10 bar")]:
        rows = ok(T[study], "p_fu_dis_bar")
        vf = [r["p_fu_dis_bar"] for r in rows]
        vo = [r["p_ox_dis_bar"] for r in rows]
        tor.append((label, min(vf) - base_pf, max(vf) - base_pf, min(vo) - base_po, max(vo) - base_po))
    tor.sort(key=lambda t: t[2] - t[1])
    p_f = write_csv("fig05_bars_ch4", rect_polys([(t[1], t[2], i + 0.01, i + 0.35) for i, t in enumerate(tor)]))
    p_o = write_csv("fig05_bars_lox", rect_polys([(t[3], t[4], i - 0.35, i - 0.01) for i, t in enumerate(tor)]))
    write_csv("fig05_ranges", {"study": [re.sub(r"[\\$]", "", t[0]) for t in tor], "ch4_lo": [t[1] for t in tor],
                               "ch4_hi": [t[2] for t in tor], "lox_lo": [t[3] for t in tor], "lox_hi": [t[4] for t in tor]})
    xl = mlim([v for t in tor for v in t[1:]] + [0.0])
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{axis}[width=<<W>>cm, height=<<H>>cm, xmin=<<x0>>, xmax=<<x1>>, ymin=-0.6, ymax=<<y1>>,
    ytick={0,...,<<n1>>}, yticklabels={<<labels>>}, ytick style={draw=none}, xtick distance=50,
    xlabel={change in pump discharge pressure from baseline (bar); baseline LOX <<bpo>>, CH$_4$ <<bpf>> bar},
    legend style={at={(0.99,0.03)}, anchor=south east}]
  \addplot[draw=none, fill=cFu, area] table[x=x, y=y] {\fu};
  \addlegendentry{CH$_4$ pump discharge}
  \addplot[draw=none, fill=cOx, area] table[x=x, y=y] {\ox};
  \addlegendentry{LOX pump discharge}
  \draw[cK, line width=0.6pt] (axis cs:0,-0.6) -- (axis cs:0,<<y1>>);
\end{axis}
\end{tikzpicture}"""
    labels = ",".join("{" + t[0] + "}" for t in tor)
    return fill(body, reads=tread(p_f, "fu") + "\n" + tread(p_o, "ox"), W=12.75, H=6.0, x0=xl[0], x1=xl[1],
                y1=len(tor) - 0.4, n1=len(tor) - 1, labels=labels, bpo=f"{base_po:.0f}", bpf=f"{base_pf:.0f}")


# ================================================================== fig06 wall bias
@figure("fig06_wall_bias")
def fig06():
    T = load_json("results/trades.json")
    reads, allx, ya, yb = [], [], [], []
    plots_a, plots_b = [], []
    for mrw, mk, tag in [(1.6, "*", "a"), (2.0, "square*", "b")]:
        rows = [r for r in ok(T["wall_bias"], "isp_sl") if abs(r["injector.bl_mixture_ratio"] - mrw) < 1e-6]
        d = {"share": [100 * r["injector.bl_mass_fraction"] for r in rows], "loss": [r["bl_penalty_s"] for r in rows],
             "dp": [r["dp_jacket_bar"] for r in rows]}
        reads.append(tread(write_csv(f"fig06_wall_of_{mrw:.1f}".replace(".", "p"), d), "wb" + tag))
        allx += d["share"]
        ya += d["loss"]
        yb += d["dp"]
        plots_a.append(rf"  \addplot[cK, mark={mk}, mk] table[x=share, y=loss] {{\wb{tag}}};" + "\n"
                       + rf"  \addlegendentry{{wall O/F {mrw}}}")
        plots_b.append(rf"  \addplot[cK, mark={mk}, mk] table[x=share, y=dp] {{\wb{tag}}};")
    x = mlim(allx)
    a = mlim(ya)
    b = mlim(yb)
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{groupplot}[group style={group size=2 by 1, horizontal sep=1.65cm},
    width=<<W>>cm, height=<<H>>cm, xmin=<<x0>>, xmax=<<x1>>,
    xlabel={wall stream-tube share (\% of mass flow)}]
\nextgroupplot[ymin=<<a0>>, ymax=<<a1>>, ylabel={sea-level $I_{sp}$ loss (s)},
    legend style={at={(0.03,0.97)}, anchor=north west}]
<<pa>>
\nextgroupplot[ymin=<<b0>>, ymax=<<b1>>, ylabel={jacket pressure drop (bar)}]
<<pb>>
  \node[ann, text=cR, anchor=south east] at (rel axis cs:0.97,0.04) {wall O/F 2.4: cycle does not close};
\end{groupplot}
\end{tikzpicture}"""
    body = body.replace("<<pa>>", "\n".join(plots_a)).replace("<<pb>>", "\n".join(plots_b))
    return fill(body, reads="\n".join(reads), W=7.27, H=4.9, x0=x[0], x1=x[1], a0=a[0], a1=a[1], b0=b[0], b1=b[1])


# ================================================================== fig07 improvement chain
@figure("fig07_improvement_chain")
def fig07():
    IMP = load_json("results/improvements.json")
    ch = IMP["chain"]
    lab = [r"baseline", r"polish\\channels", r"coolant split\\50/50", r"shrouded\\turbines", r"close-coupled\\hot gas"]
    p = write_csv("fig07_chain", {"step": list(range(len(ch))), "p_fu": [s["p_fu_dis_bar"] for s in ch],
                                  "p_ox": [s["p_ox_dis_bar"] for s in ch], "dp_jacket": [s["dp_jacket_bar"] for s in ch]})
    nodes = []
    for i, s in enumerate(ch):
        nodes.append(rf"  \node[ann, anchor=south, yshift=3pt] at (axis cs:{i},{num(s['p_fu_dis_bar'])}) {{{s['p_fu_dis_bar']:.0f}}};")
        nodes.append(rf"  \node[ann, anchor=north, yshift=-3pt] at (axis cs:{i},{num(s['p_ox_dis_bar'])}) {{{s['p_ox_dis_bar']:.0f}}};")
    x = mlim(range(len(ch)))
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{axis}[width=<<W>>cm, height=<<H>>cm, xmin=<<x0>>, xmax=<<x1>>, ymin=0, ymax=1000,
    xtick={0,...,<<n1>>}, xticklabels={<<labels>>}, xticklabel style={align=center, font=\footnotesize},
    ylabel={pressure (bar)}, legend style={at={(0.98,0.5)}, anchor=east}]
  \addplot[cFu, mark=square*, mk] table[x=step, y=p_fu] {\chain};
  \addlegendentry{CH$_4$ pump discharge}
  \addplot[cOx, mark=*, mk] table[x=step, y=p_ox] {\chain};
  \addlegendentry{LOX pump discharge}
  \addplot[cG, mark=triangle*, mkt] table[x=step, y=dp_jacket] {\chain};
  \addlegendentry{jacket pressure drop}
<<nodes>>
  \node[ann, anchor=base west] at (rel axis cs:0.01,0.03) {sea-level $I_{sp}$ unchanged at <<isp>> s};
\end{axis}
\end{tikzpicture}"""
    body = body.replace("<<nodes>>", "\n".join(nodes))
    return fill(body, reads=tread(p, "chain"), W=15.85, H=6.0, x0=x[0], x1=x[1], n1=len(ch) - 1,
                labels=",".join("{" + l + "}" for l in lab[:len(ch)]), isp=f"{ch[-1]['isp_sl']:.1f}")


# ================================================================== fig08 throttle and separation
@figure("fig08_throttle_separation")
def fig08():
    D = load_json("results/design.json")
    th = D["throttle"]
    d = {"throttle": [100 * t["throttle"] for t in th], "pe_pa": [t["pe_over_pa"] for t in th],
         "schmucker": [t["schmucker_limit"] for t in th]}
    p = write_csv("fig08_throttle", d)
    x = mlim(d["throttle"])
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{axis}[width=<<W>>cm, height=<<H>>cm, xmin=<<x0>>, xmax=<<x1>>, ymin=0, ymax=1.3,
    xlabel={throttle (\% thrust)}, ylabel={exit / ambient pressure},
    legend style={at={(0.03,0.97)}, anchor=north west}]
  \addplot[cK, mark=*, mk] table[x=throttle, y=pe_pa] {\thr};
  \addlegendentry{$p_e/p_a$}
  \addplot[cR, dashed] table[x=throttle, y=schmucker] {\thr};
  \addlegendentry{Schmucker separation}
  \addplot[cR, refline, line width=0.6pt, domain=<<x0>>:<<x1>>, samples=2] {0.4};
  \addlegendentry{Summerfield 0.4}
\end{axis}
\end{tikzpicture}"""
    return fill(body, reads=tread(p, "thr"), W=7.25, H=5.4, x0=x[0], x1=x[1])


# ================================================================== fig09 mass breakdown
@figure("fig09_mass_breakdown")
def fig09():
    ms = load_json("cad/output/mass_summary.json")["by_assembly_kg"]
    names = {"Thrust_Chamber": "thrust chamber + manifolds", "Injector_Head": "injector head", "Gimbal": "gimbal",
             "LOX_Turbopump": "LOX turbopump + OPB", "CH4_Turbopump": "CH4 turbopump + FPB",
             "Plumbing": "ducts, valves, flanges", "Instrumentation": "instrumentation"}
    items = sorted(((names.get(k, k), v) for k, v in ms.items() if v > 1), key=lambda t: t[1])
    p = write_csv("fig09_mass", {"y": list(range(len(items))), "mass": [v for _, v in items]})
    tot = sum(v for _, v in items)
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{axis}[width=<<W>>cm, height=<<H>>cm, xbar, bar width=0.8, xmin=0, xmax=<<x1>>, ymin=-0.6, ymax=<<y1>>,
    xtick distance=100, ytick={0,...,<<n1>>}, yticklabels={<<labels>>}, xlabel={modelled mass (kg)},
    title={CAD mass roll-up <<tot>> kg\\(Raptor 3: 1525 kg engine only)}, title style={font=\footnotesize, align=center},
    nodes near coords={\pgfmathprintnumber[fixed, precision=0]{\pgfplotspointmeta}}, point meta=x,
    nodes near coords style={font=\footnotesize, anchor=west, inner sep=2pt}]
  \addplot[draw=none, fill=cIn] table[x=mass, y=y] {\mass};
\end{axis}
\end{tikzpicture}"""
    labels = ",".join("{" + tex(n) + "}" for n, _ in items)
    return fill(body, reads=tread(p, "mass"), W=4.5, H=4.3, x1=max(v for _, v in items) * 1.17, y1=len(items) - 0.4,
                n1=len(items) - 1, labels=labels, tot=f"{tot:.0f}")


# ================================================================== fig10 chamber-pressure ceiling
P_PUMP_LIMIT = 1000.0


@figure("fig10_pc_ceiling")
def fig10():
    out = load_json("results/pc_ceiling.json")
    cols = ["cK", "cOx", "cR", "cG", "cFu", "cP"]
    reads, pa, pb, allx, ya, yb = [], [], [], [], [], []
    for k, (e, col) in enumerate(zip(out, cols)):
        pts = [q for q in e["points"] if q.get("feasible")]
        d = {"pc": [q["pc_bar"] for q in pts], "p_ox": [q["p_ox_dis_bar"] for q in pts],
             "p_fu": [q["p_fu_dis_bar"] for q in pts]}
        m = "e" + "abcdefghij"[k]
        reads.append(tread(write_csv(f"fig10_enabler_{k}", d), m))
        allx += d["pc"]
        ya += d["p_ox"]
        yb += d["p_fu"]
        pa.append(rf"  \addplot[{col}, mark=*, mark size=1.4pt, line width=0.8pt] table[x=pc, y=p_ox] {{\{m}}};"
                  + "\n" + rf"  \addlegendentry{{{tex(e['enabler'])}}}")
        pb.append(rf"  \addplot[{col}, mark=*, mark size=1.4pt, line width=0.8pt] table[x=pc, y=p_fu] {{\{m}}};")
    x = mlim(allx)
    a = list(mlim(ya))
    b = list(mlim(yb))
    a[1] = max(a[1], P_PUMP_LIMIT + 45)
    b[1] = max(b[1], P_PUMP_LIMIT + 45)
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{groupplot}[group style={group size=2 by 1, horizontal sep=1.65cm},
    width=<<W>>cm, height=<<H>>cm, xmin=<<x0>>, xmax=<<x1>>,
    xlabel={chamber pressure (bar)}, ylabel={discharge pressure (bar)}]
\nextgroupplot[ymin=<<a0>>, ymax=<<a1>>, title={(a) LOX pump discharge},
    legend to name=legPc, legend columns=3, legend style={draw=none, fill=none}]
<<pa>>
  \draw[cK, refline] (axis cs:<<x0>>,1000) -- (axis cs:<<x1>>,1000);
  \node[ann, anchor=base west] at (axis cs:352,1012) {assumed 1,000 bar limit};
\nextgroupplot[ymin=<<b0>>, ymax=<<b1>>, title={(b) CH$_4$ pump discharge}]
<<pb>>
  \draw[cK, refline] (axis cs:<<x0>>,1000) -- (axis cs:<<x1>>,1000);
  \node[ann, anchor=south west, align=left, yshift=1pt] at (axis cs:352,1000) {assumed\\1,000 bar limit};
\end{groupplot}
\node[anchor=north] at ($(group c1r1.south)!0.5!(group c2r1.south) + (0,-1.15cm)$) {\ref{legPc}};
\end{tikzpicture}"""
    body = body.replace("<<pa>>", "\n".join(pa)).replace("<<pb>>", "\n".join(pb))
    return fill(body, reads="\n".join(reads), W=6.98, H=4.6, x0=x[0], x1=x[1], a0=a[0], a1=a[1], b0=b[0], b1=b[1])


# ================================================================== fig11 plasma-assisted combustion
# Panel (b) markers: the three high-pressure locations sit within 0.3 decades of each other on the
# 1000 K line, so they get one marker shape each and a legend entry instead of crowded text labels.
PAC_MARKS = ["square*", "diamond*", "triangle*", "pentagon*"]


@figure("fig11_pac")
def fig11():
    from ffsc.plasma import breakdown_voltage, power_source_mass
    out = load_json("results/pac.json")
    nov = yaml.safe_load(open(ROOT / "config" / "novel.yaml"))
    reads = []
    # (a) extinction time vs specific plasma energy
    pa, ya = [], []
    for tag, col, ls in (("nominal", "cFu", "solid"), ("optimistic", "cP", "dashed")):
        rows = [r for r in out["fpb"]["sweep"][tag] if r["tau_ext_s"]]
        d = {"ep_kJkg": [max(r["e_p_J_kg"], 300) / 1e3 for r in rows], "tau_ms": [r["tau_ext_s"] * 1e3 for r in rows]}
        reads.append(tread(write_csv(f"fig11a_fpb_{tag}", d), "fpb" + tag))
        ya += d["tau_ms"]
        pa.append(rf"  \addplot[{col}, {ls}, mark=*, mark size=1.4pt] table[x=ep_kJkg, y=tau_ms] {{\fpb{tag}}};"
                  + "\n" + rf"  \addlegendentry{{FPB, {tag}\\branching}}")
    tau_d = out["fpb"]["design_tau_s"] * 1e3
    xa = mlim([0.3, 100.0], log=True)
    # (b) breakdown voltage, analytic
    inp = out["inputs"]
    p = np.logspace(0, 3, 100)
    d = {"p_bar": p}
    for T in (300.0, 1000.0):
        d[f"V_{T:.0f}K"] = breakdown_voltage(p * 1e5, T, 1e-3, inp["EN_breakdown_Td"]) / 1e3
    reads.append(tread(write_csv("fig11b_breakdown", d), "bd"))
    mk = [(k.split(" (")[0], v["p_bar"], v["V_kV_per_mm"]) for k, v in out["breakdown"].items() if v["p_bar"] > 100]
    reads.append(tread(write_csv("fig11b_locations", {"p_bar": [m[1] for m in mk], "V_kV": [m[2] for m in mk]}), "loc"))
    xb = mlim(np.r_[p, [m[1] for m in mk]], log=True)
    yb = mlim(np.r_[d["V_300K"], d["V_1000K"], [m[2] for m in mk], [inp["pulser_kV"]]], log=True)
    labs = []
    for i, (name, pb_, vb) in enumerate(mk):        # one marker shape per location, named in the legend
        labs.append(rf"  \addplot[only marks, mark={PAC_MARKS[i % len(PAC_MARKS)]}, mark size=1.9pt, cK, "
                    rf"skip coords between index={{0}}{{{i}}}, skip coords between index={{{i + 1}}}{{999}}] "
                    rf"table[x=p_bar, y=V_kV] {{\loc}};"
                    + "\n" + rf"  \addlegendentry{{{tex(name)}}}")
    # (c) power-source mass, analytic
    P = np.logspace(-1, 1, 50)
    names = {"li_ion_high_power": "Li-ion pack", "next_gen_cells": "next-gen cells", "shaft_alternator": "shaft alternator",
             "fission_microreactor": "fission reactor"}
    srcs = nov["power_sources"]
    dc = {"P_MW": P}
    for k in names:
        dc[k] = [power_source_mass(x * 1e6, nov["burn_s"], srcs[k]) for x in P]
    reads.append(tread(write_csv("fig11c_power_source_mass", dc), "psm"))
    pc_ = []
    for (k, lab), col in zip(names.items(), ["cOx", "cG", "cFu", "cR"]):
        pc_.append(rf"  \addplot[{col}] table[x=P_MW, y={k}] {{\psm}};" + "\n" + rf"  \addlegendentry{{{lab}}}")
    yc = list(mlim(np.concatenate([np.asarray(dc[k], float) for k in names] + [np.array([1796.0])]), log=True))
    yc[1] = 40 * max(max(dc[k]) for k in names)     # headroom keeps the legend clear of the fission line
    xc = mlim(P, log=True)
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{groupplot}[group style={group size=3 by 1, horizontal sep=1.5cm},
    width=<<W>>cm, height=<<H>>cm, xmode=log, ymode=log]
\nextgroupplot[xmin=<<xa0>>, xmax=<<xa1>>, ymin=<<ya0>>, ymax=<<ya1>>,
    ytick={<<yticks>>}, log ticks with fixed point, yminorticks=false,
    xlabel={specific plasma energy (kJ/kg)\\{}[0 plotted at 0.3]}, xlabel style={align=center},
    ylabel={PSR extinction time $\tau_{ext}$ (ms)}, title={(a) fuel-rich preburner kinetics},
    legend style={at={(0.03,0.03)}, anchor=south west, cells={align=left}}]
<<pa>>
  \draw[cK, refline, line width=0.6pt] (axis cs:<<xa0>>,<<taud>>) -- (axis cs:<<xa1>>,<<taud>>);
  \node[ann, anchor=base west] at (axis cs:0.35,<<taudt>>) {design residence time};
\nextgroupplot[xmin=<<xb0>>, xmax=<<xb1>>, ymin=<<yb0>>, ymax=<<yb1>>,
    xlabel={pressure (bar)}, ylabel={breakdown voltage, 1 mm gap (kV)},
    title={(b) discharge at $E/N = <<EN>>$ Td}, legend style={at={(<<legx>>,0.97)}, anchor=north west, fill=none}]
  \fill[cG, opacity=0.12] (axis cs:1,<<yb0>>) rectangle (axis cs:<<nrp>>,<<yb1>>);
  \addplot[cOx] table[x=p_bar, y=V_300K] {\bd};
  \addlegendentry{300 K}
  \addplot[cR] table[x=p_bar, y=V_1000K] {\bd};
  \addlegendentry{1000 K}
  \draw[cK, refline, line width=0.6pt] (axis cs:<<xb0>>,<<pulser>>) -- (axis cs:<<xb1>>,<<pulser>>);
  \node[ann, anchor=north east, yshift=-1pt] at (axis cs:<<pulsx>>,<<pulser>>) {<<pulserlab>> kV pulser};
  \node[ann, text=cG, anchor=north west, align=left, yshift=-3pt] at (axis cs:1.15,<<yb1>>) {NRP\\shown};
\nextgroupplot[xmin=<<xc0>>, xmax=<<xc1>>, ymin=<<yc0>>, ymax=<<yc1>>,
    xlabel={electrical power (MW)}, ylabel={source mass for <<burn>> s (kg)}, title={(c) power source},
    legend style={at={(0.02,0.98)}, anchor=north west},
    legend image code/.code={\draw[#1] (0cm,0cm) -- (0.4cm,0cm);}]
<<pc>>
  \draw[cK, refline, line width=0.6pt] (axis cs:<<xc0>>,1796) -- (axis cs:<<xc1>>,1796);
  \node[ann, anchor=north west] at (axis cs:0.115,1796) {engine mass};
\end{groupplot}
% second legend for panel (b): the three high-pressure locations (overlay axis, no frame)
\begin{axis}[at={(group c2r1.south west)}, anchor=south west, width=<<W>>cm, height=<<H>>cm, hide axis,
    xmode=log, ymode=log, xmin=<<xb0>>, xmax=<<xb1>>, ymin=<<yb0>>, ymax=<<yb1>>,
    legend style={at={(0.97,0.03)}, anchor=south east, fill=none}]
<<labs>>
\end{axis}
\end{tikzpicture}"""
    body = (body.replace("<<pa>>", "\n".join(pa)).replace("<<labs>>", "\n".join(labs))
            .replace("<<pc>>", "\n".join(pc_)))
    # (a) limits and ticks as set in scripts/run_pac.py figure()
    return fill(body, reads="\n".join(reads), W=4.27, H=4.3,
                xa0=xa[0], xa1=xa[1], ya0=1.5, ya1=6.0, yticks="2,3,4,5", taud=tau_d, taudt=tau_d * 1.06,
                xb0=xb[0], xb1=xb[1], yb0=yb[0], yb1=yb[1], EN=f"{inp['EN_breakdown_Td']:g}",
                nrp=inp["demonstrated_NRP_bar"], pulser=inp["pulser_kV"], pulsx=xb[1] / 1.15,
                legx=math.log10(inp["demonstrated_NRP_bar"] / xb[0]) / math.log10(xb[1] / xb[0]),
                pulserlab=f"{inp['pulser_kV']:g}", xc0=xc[0], xc1=xc[1], yc0=yc[0], yc1=yc[1],
                burn=f"{nov['burn_s']:.0f}")


# ================================================================== fig12 and fig13 economics
_ECON = {}


def econ_models():
    """Rebuild the three CostModel objects exactly as run_economics.run() does (same Sampler, same order)."""
    if _ECON:
        return _ECON["RE"], _ECON["models"]
    import run_economics as RE
    from ffsc.economics import CostModel, Sampler
    S = Sampler(RE.N_MC)
    models = {}
    for sc in RE.SCEN:
        if sc == "hybrid":
            for g in RE.load("components.yaml")["groups"]:
                cc = np.median(models["conventional"][1]["groups"].get(g["id"], 0.0))
                ca = np.median(models["inhouse_am"][1]["groups"].get(g["id"], 0.0))
                RE.HYBRID_ROUTES[g["id"]] = g["routes"]["inhouse_am"] if ca < cc else g["routes"]["conventional"]
        cm = CostModel(RE.BOM0, RE.D0, sc, S, routes=RE.HYBRID_ROUTES if sc == "hybrid" else None)
        uc = cm.unit_cost()
        cm.learning(uc, [1, 10, 100, 1000])
        cm.nre(uc)
        models[sc] = (cm, uc)
    E = load_json("results/economics.json")
    for sc, (cm, uc) in models.items():                 # parity check against the stored results
        ref = E["scenarios"][sc]
        a = float(np.median(uc["total"]))
        b = float(np.median(cm.learning(uc, [1000])[1000]["unit"]))
        ra, rb = ref["unit_cost_T1"]["P50"], ref["learning"]["1000"]["unit"]["P50"]
        if abs(a / ra - 1) > 1e-6 or abs(b / rb - 1) > 1e-6:
            print(f"  WARNING: recomputed {sc} cost differs from results/economics.json "
                  f"(T1 {a:.4g} vs {ra:.4g}, unit@1000 {b:.4g} vs {rb:.4g})")
    _ECON.update(RE=RE, models=models)
    return RE, models


@figure("fig12_cost")
def fig12():
    RE, models = econ_models()
    out = load_json("results/economics.json")
    seg_names = list(RE.SUPER.items()) + [("Assembly, acceptance test", None)]
    cols = ["cCu", "cIn", "cOx", "cAmber", "cP", "cG", "cGrey", "cSand", "cK"]
    rects = {k: [] for k in range(len(seg_names))}
    seg_tab = {"scenario": []}
    for name, _ in seg_names:
        seg_tab[name] = []
    err = {"y": [], "p50": [], "ep": [], "em": []}
    for i, sc in enumerate(RE.SCEN):
        _, uc = models[sc]
        left = 0.0
        seg_tab["scenario"].append(sc)
        for k, (name, ids) in enumerate(seg_names):
            v = np.median(uc["assembly_test"]) if ids is None else sum(np.median(uc["groups"].get(g, 0.0)) for g in ids)
            rects[k].append((left, left + v / 1e6, i - 0.4, i + 0.4))
            seg_tab[name].append(v / 1e6)
            left += v / 1e6
        t = out["scenarios"][sc]["unit_cost_T1"]
        err["y"].append(i)
        err["p50"].append(t["P50"] / 1e6)
        err["ep"].append((t["P90"] - t["P50"]) / 1e6)
        err["em"].append((t["P50"] - t["P10"]) / 1e6)
    write_csv("fig12a_segments_P50", seg_tab)
    reads = [tread(write_csv("fig12a_T1_P10_P50_P90", err), "err")]
    bars = []
    for k, (name, _) in enumerate(seg_names):
        m = "seg" + "abcdefghijk"[k]
        reads.append(tread(write_csv(f"fig12a_bar_{k}", rect_polys(rects[k])), m))
        bars.append(rf"  \addplot[fill={cols[k]}, draw=white, line width=0.3pt, area] table[x=x, y=y] {{\{m}}};"
                    + "\n" + rf"  \addlegendentry{{{name}}}")
    xa1 = mlim([0.0] + [p + e for p, e in zip(err["p50"], err["ep"])])[1]
    # (b) learning curve bands
    n = np.array([1, 2, 5, 10, 20, 50, 100, 200, 500, 1000])
    lc = {"n": n}
    plots_b = []
    for (sc, lab), col in zip(RE.SCEN.items(), ("cIn", "cCu", "cG")):
        cm, uc = models[sc]
        lr = cm.learning(uc, list(n))
        u = np.array([lr[k]["unit"] for k in n])
        p10, p50, p90 = (np.percentile(u, q, axis=1) / 1e6 for q in (10, 50, 90))
        lc[f"{sc}_P10"], lc[f"{sc}_P50"], lc[f"{sc}_P90"] = p10, p50, p90
        reads.append(tread(write_csv(f"fig12b_band_{sc}", band_poly(n, p10, p90)), "band" + sc.replace("_", "")))
        plots_b.append(rf"  \addplot[draw=none, fill={col}, fill opacity=0.2, forget plot] table[x=x, y=y] "
                       rf"{{\band{sc.replace('_', '')}}};")
    reads.append(tread(write_csv("fig12b_learning_P10_P50_P90", lc), "lc"))
    for (sc, lab), col in zip(RE.SCEN.items(), ("cIn", "cCu", "cG")):
        plots_b.append(rf"  \addplot[{col}] table[x=n, y={sc}_P50] {{\lc}};" + "\n" + rf"  \addlegendentry{{{tex(lab)}}}")
    xb = mlim(n, log=True)
    bench = []
    for lab, v in out["benchmarks_usd"].items():
        if v < 3e7:
            y = v / 1e6
            bench.append(rf"  \draw[cK, refline] (axis cs:{num(xb[0])},{num(y)}) -- (axis cs:{num(xb[1])},{num(y)});")
            a, xpos, dy, knock = BENCH_POS.get(lab, ("south east", 950, 0.5, False))
            box = ", fill=white, fill opacity=0.75, text opacity=1" if knock else ""
            bench.append(rf"  \node[ann, anchor={a}, yshift={dy}pt{box}] at (axis cs:{xpos},{num(y)}) {{{tex(lab)}}};")
    td = out["top_down"]
    t1A, t1S = td["transcost_t1_A"]["P50"] / 1e6, td["svlcm_t1"]["P50"] / 1e6
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{axis}[name=A, width=<<WA>>cm, height=<<H>>cm, xmin=0, xmax=<<xa1>>, ymin=-0.6, ymax=2.6,
    ytick={0,1,2}, yticklabels={{Conventional,\\buy to print},{In-house AM},{Hybrid}},
    yticklabel style={align=right}, xlabel={first-unit cost T1 (USD million)},
    title={(a) first engine, P50 by subsystem (bar: P10--P90 of total)},
    legend style={at={(-0.31,-0.25)}, anchor=north west, legend columns=3, fill=none}, transpose legend]
<<bars>>
  \addplot[draw=none, mark=none, forget plot, error bars/.cd, x dir=both, x explicit,
      error bar style={cK, line width=0.6pt}, error mark options={rotate=90, mark size=2.2pt, cK, line width=0.6pt}]
      table[x=p50, y=y, x error plus=ep, x error minus=em] {\err};
\end{axis}
\begin{axis}[at={($(A.south east)+(<<sep>>cm,0)$)}, anchor=south west, width=<<WB>>cm, height=<<H>>cm,
    xmode=log, ymode=log, xmin=<<xb0>>, xmax=<<xb1>>, ymin=0.15, ymax=90,
    xlabel={unit number}, ylabel={unit cost (USD million)}, title={(b) learning curve vs public figures},
    legend style={at={(1,-0.25)}, anchor=north east, fill=none}]
<<plotsb>>
<<bench>>
  \addplot[only marks, mark=triangle*, mark size=2.2pt, mark options={rotate=180}, cR, forget plot]
      coordinates {(1,<<t1A>>)};
  \node[ann, text=cR, anchor=west] at (axis cs:1.3,<<t1Ay>>) {TRANSCOST T1};
  \addplot[only marks, mark=triangle*, mark size=2.2pt, cR, forget plot] coordinates {(1,<<t1S>>)};
  \node[ann, text=cR, anchor=west] at (axis cs:1.3,<<t1Sy>>) {SVLCM T1};
\end{axis}
\end{tikzpicture}"""
    body = (body.replace("<<bars>>", "\n".join(bars)).replace("<<plotsb>>", "\n".join(plots_b))
            .replace("<<bench>>", "\n".join(bench)))
    return fill(body, reads="\n".join(reads), WA=6.55, WB=6.05, sep=1.55, H=4.6, xa1=xa1, xb0=xb[0], xb1=xb[1],
                t1A=t1A, t1S=t1S, t1Ay=t1A * 1.17, t1Sy=t1S * 1.12)


# benchmark text placement in fig12(b): label -> (anchor, x unit number, yshift pt, white backing box).
# The learning-curve bands cover the 2 M$ line from unit 10 on, so the Raptor 1 label sits at the left
# end on a light white box where it overlaps the lower edge of the hybrid band.
BENCH_POS = {'Raptor 1 (2019, "more than")': ("north west", 0.78, -0.5, True),
             "Raptor 2 (estimate)": ("north east", 600, -0.5, False),
             "Raptor goal (~$1k per tf)": ("south east", 950, 0.5, False),
             "RD-180 (ULA price 2014)": ("north east", 950, -0.5, False)}

# option label offsets in fig13(b): id -> (anchor, xshift pt, yshift pt)
OPT_POS = {"Y2": ("east", -4, 0), "N2": ("south west", 3, -1), "I4": ("south west", 3, 1)}
TRL_COL = {2: "cTRLii", 4: "cTRLiv", 5: "cTRLv", 6: "cTRLvi", 7: "cTRLvii", 8: "cTRLviii"}
CAT_MARK = {"component": "*", "integration": "square*", "cycle": "diamond*", "novel": "triangle*"}


@figure("fig13_nre_options")
def fig13():
    out = load_json("results/economics.json")
    opt = load_json("results/options.json")
    scen = list(out["scenarios"])
    comps = ["design", "dev_hardware", "hot_fire_tests", "test_stand", "tooling_or_am_capex"]
    labs = ["design hours", "development engines", "hot-fire tests", "test stand", "tooling / AM capital"]
    cols = ["cOx", "cIn", "cR", "cK", "cCu"]
    reads, bars = [], []
    tab = {"scenario": scen}
    for k, (comp, lab, col) in enumerate(zip(comps, labs, cols)):
        rects = []
        tab[comp] = []
        for i, sc in enumerate(scen):
            left = sum(out["scenarios"][sc]["nre"][c]["P50"] / 1e9 for c in comps[:k])
            v = out["scenarios"][sc]["nre"][comp]["P50"] / 1e9
            rects.append((left, left + v, i - 0.4, i + 0.4))
            tab[comp].append(v)
        m = "nre" + "abcde"[k]
        reads.append(tread(write_csv(f"fig13a_bar_{comp}", rect_polys(rects)), m))
        bars.append(rf"  \addplot[fill={col}, draw=white, line width=0.3pt, area] table[x=x, y=y] {{\{m}}};"
                    + "\n" + rf"  \addlegendentry{{{lab}}}")
    write_csv("fig13a_nre_P50_by_component", tab)
    td = out["top_down"]
    t = td["transcost_dev"]
    sv = td["svlcm_nre"]["P50"] / 1e9
    reads.append(tread(write_csv("fig13a_topdown_bars", rect_polys([(0, sv, 2.6, 3.4), (0, t["P50"] / 1e9, 3.6, 4.4)])),
                       "topdown"))
    reads.append(tread(write_csv("fig13a_transcost_err", {"y": [4], "p50": [t["P50"] / 1e9],
                                                          "ep": [(t["P90"] - t["P50"]) / 1e9],
                                                          "em": [(t["P50"] - t["P10"]) / 1e9]}), "tcerr"))
    xa1 = mlim([0.0, t["P90"] / 1e9, sv])[1]
    # (b) options
    tw0 = opt["baseline"]["thrust_to_weight"]
    pts = []
    for row in opt["options"]:
        r = row["result"]
        if "thrust_to_weight" not in r or row["id"] not in out["options"]:
            continue
        pts.append((row["id"], row["category"], row["trl"], out["options"][row["id"]]["nre_usd"]["P50"] / 1e6,
                    r["thrust_to_weight"] - tw0))
    write_csv("fig13b_options", {"id": [p[0] for p in pts], "category": [p[1] for p in pts], "trl": [p[2] for p in pts],
                                 "nre_MUSD": [p[3] for p in pts], "d_tw": [p[4] for p in pts]})
    plots_b = []
    classes = ",".join(f"{k}={{fill={c},draw={c}}}" for k, c in TRL_COL.items())
    for cat, mk_ in CAT_MARK.items():
        sub = [p for p in pts if p[1] == cat]
        if not sub:
            continue
        m = "opt" + cat
        reads.append(tread(write_csv(f"fig13b_{cat}", {"nre_MUSD": [p[3] for p in sub], "d_tw": [p[4] for p in sub],
                                                       "trl": [str(p[2]) if p[2] in TRL_COL else "x" for p in sub]}), m))
        plots_b.append(rf"  \addplot[scatter, only marks, mark={mk_}, mark size={2.6 if cat in ('cycle', 'novel') else 2.1}pt, "
                       rf"scatter src=explicit symbolic, scatter/classes={{{classes},x={{fill=cTRLx,draw=cTRLx}}}}, forget plot] "
                       rf"table[x=nre_MUSD, y=d_tw, meta=trl] {{\{m}}};")
    nodes = []
    for pid, cat, trl, x, y in pts:
        a, dx, dy = OPT_POS.get(pid, ("south west", 3, 1))
        nodes.append(rf"  \node[ann, anchor={a}, xshift={dx}pt, yshift={dy}pt] at (axis cs:{num(x)},{num(y)}) {{{pid}}};")
    keys = []
    for cat, mk_ in CAT_MARK.items():
        keys.append(rf"  \addlegendimage{{only marks, mark={mk_}, cKey, mark size={2.4 if cat in ('cycle', 'novel') else 1.9}pt}}"
                    + "\n" + rf"  \addlegendentry{{{cat}}}")
    xb = mlim([p[3] for p in pts], log=True)
    yb = mlim([p[4] for p in pts] + [0.0])
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{axis}[name=A, width=<<WA>>cm, height=<<H>>cm, xmin=0, xmax=<<xa1>>, ymin=-0.6, ymax=4.6,
    ytick={0,...,4}, yticklabels={{Conventional\\(bottom-up)},{In-house AM\\(bottom-up)},{Hybrid\\(bottom-up)},
    {NASA SVLCM},{TRANSCOST 8.2}}, yticklabel style={align=right},
    xlabel={development cost (USD billion, P50)}, title={(a) development cost},
    legend style={at={(0.98,0.03)}, anchor=south east}]
<<bars>>
  \addplot[fill=cBench, draw=none, forget plot] table[x=x, y=y] {\topdown};
  \addplot[draw=none, mark=none, forget plot, error bars/.cd, x dir=both, x explicit,
      error bar style={cK, line width=0.6pt}, error mark options={rotate=90, mark size=2.2pt, cK, line width=0.6pt}]
      table[x=p50, y=y, x error plus=ep, x error minus=em] {\tcerr};
\end{axis}
\begin{axis}[at={($(A.south east)+(<<sep>>cm,0)$)}, anchor=south west, width=<<WB>>cm, height=<<H>>cm,
    xmode=log, xmin=<<xb0>>, xmax=<<xb1>>, ymin=<<yb0>>, ymax=<<yb1>>,
    xlabel={development cost of the option (USD million, P50)}, ylabel={change in thrust-to-weight},
    title={(b) options: benefit vs development cost (colour: TRL)},
    legend style={at={(0.98,0.5)}, anchor=east}]
  \draw[cK, line width=0.45pt] (axis cs:<<xb0>>,0) -- (axis cs:<<xb1>>,0);
<<plotsb>>
<<keys>>
<<nodes>>
\end{axis}
\end{tikzpicture}"""
    body = (body.replace("<<bars>>", "\n".join(bars)).replace("<<plotsb>>", "\n".join(plots_b))
            .replace("<<keys>>", "\n".join(keys)).replace("<<nodes>>", "\n".join(nodes)))
    return fill(body, reads="\n".join(reads), WA=6.2, WB=6.35, sep=1.35, H=4.9, xa1=xa1, xb0=xb[0], xb1=xb[1],
                yb0=yb[0], yb1=yb[1])


# ================================================================== fig14 power and energy density
PD_NAMES = {"fission_microreactor": r"fission reactor\\(SP-100 $\bullet$, Kilopower $\circ$)",
            "li_ion_high_power": "Li-ion pack", "next_gen_cells": "next-gen cells",
            "shaft_alternator": "shaft alternator + inverter"}
PD_COLS = {"fission_microreactor": "cR", "li_ion_high_power": "cOx", "next_gen_cells": "cG", "shaft_alternator": "cFu"}
PD_NOT_LIMITING = {"shaft_alternator": r"energy not limiting\\(turbines)"}


def concept_label(name):
    s = tex(name)
    for a in (" to reach", " to double"):
        s = s.replace(a, r"\\" + a.strip())
    return s.replace(", inlet", r",\\inlet")


@figure("fig14_power_density")
def fig14():
    out = load_json("results/pac.json")
    if "power_density" not in out:
        return None
    pdn = out["power_density"]
    nov = yaml.safe_load(open(ROOT / "config" / "novel.yaml"))
    keys = list(PD_NAMES)
    nsrc = len(keys)
    conc = pdn["concepts"]
    src = {"row": list(range(nsrc)), "key": [k.replace("_", "") for k in keys],
           "kW_per_kg": [pdn["sources"][k]["kW_per_kg"] for k in keys],
           "Wh_per_kg": [pdn["sources"][k]["Wh_per_kg"] if pdn["sources"][k]["Wh_per_kg"] else float("nan") for k in keys]}
    cc = {"row": [nsrc + 1 + i for i in range(len(conc))],
          "req_kW_per_kg": [c["req_kW_per_kg"] if c["req_kW_per_kg"] else float("nan") for c in conc],
          "req_Wh_per_kg": [c["req_Wh_per_kg"] if c["req_Wh_per_kg"] else float("nan") for c in conc]}
    reads = [tread(write_csv("fig14_sources", src), "src"), tread(write_csv("fig14_concepts", cc), "conc"),
             tread(write_csv("fig14_references", {"row": [0, nsrc], "kilopower_kW_per_kg": [pdn["kilopower_kW_per_kg"], float("nan")],
                                                  "turbomachinery_kW_per_kg": [float("nan"), pdn["engine_turbomachinery_kW_per_kg"]],
                                                  "propellant_Wh_per_kg": [float("nan"), pdn["propellant_chemical_Wh_per_kg"]]}),
                   "refs")]
    nrows = nsrc + 1 + len(conc)
    classes = ",".join(f"{k.replace('_', '')}={{{PD_COLS[k]}, fill={PD_COLS[k]}}}" for k in keys)
    lab_a = [PD_NAMES[k] for k in keys] + ["engine turbopumps (this design)"] + [concept_label(c["name"]) for c in conc]
    lab_b = [PD_NAMES[k] for k in keys] + [r"CH$_4$/O$_2$ propellant, chemical"] + [concept_label(c["name"]) for c in conc]
    txt_a, txt_b = [], []
    for i, c in enumerate(conc):
        if not c["req_kW_per_kg"]:
            txt_a.append(rf"  \node[ann, text=cP, anchor=west] at (axis cs:0.005,{nsrc + 1 + i}) {{no mass budget left}};")
        if not c["req_Wh_per_kg"]:
            txt_b.append(rf"  \node[ann, text=cP, anchor=west] at (axis cs:1.3,{nsrc + 1 + i}) {{no mass budget left}};")
    for i, k in enumerate(keys):
        if not pdn["sources"][k]["Wh_per_kg"]:
            t = PD_NOT_LIMITING.get(k, r"energy not limiting\\(fission fuel)")
            txt_b.append(rf"  \node[ann, text={PD_COLS[k]}, anchor=west, align=left] at (axis cs:1.3,{i}) {{{t}}};")
    body = r"""<<reads>>
\begin{tikzpicture}
\begin{groupplot}[group style={group size=2 by 1, horizontal sep=4.3cm},
    width=<<W>>cm, height=<<H>>cm, xmode=log, ymin=-0.6, ymax=<<y1>>, ytick={0,...,<<n1>>},
    yticklabel style={align=right}, ytick style={draw=none}]
\nextgroupplot[xmin=0.003, xmax=3e4, xtick={1e-2,1,1e2,1e4}, yticklabels={<<laba>>}, xlabel={specific power (kW/kg)},
    title={(a) power: sources ($\bullet$) and what each concept needs ($\blacktriangledown$)}]
  \draw[cK, line width=0.45pt] (axis cs:0.003,<<hl>>) -- (axis cs:3e4,<<hl>>);
  \addplot[scatter, only marks, mark=*, mark size=2.2pt, scatter src=explicit symbolic,
      scatter/classes={<<classes>>}] table[x=kW_per_kg, y=row, meta=key] {\src};
  \addplot[only marks, mark=o, mark size=2.2pt, cR, line width=0.7pt] table[x=kilopower_kW_per_kg, y=row] {\refs};
  \addplot[only marks, mark=square*, mark size=2.1pt, cK] table[x=turbomachinery_kW_per_kg, y=row] {\refs};
  \addplot[only marks, mark=triangle*, mark size=2.6pt, mark options={rotate=180}, cP] table[x=req_kW_per_kg, y=row] {\conc};
<<txta>>
\nextgroupplot[xmin=1, xmax=1e6, xtick={1,1e2,1e4,1e6}, yticklabels={<<labb>>},
    xlabel={specific energy over a <<burn>> s burn (Wh/kg)}, title={(b) energy}]
  \draw[cK, line width=0.45pt] (axis cs:1,<<hl>>) -- (axis cs:1e6,<<hl>>);
  \addplot[scatter, only marks, mark=*, mark size=2.2pt, scatter src=explicit symbolic,
      scatter/classes={<<classes>>}] table[x=Wh_per_kg, y=row, meta=key] {\src};
  \addplot[only marks, mark=square*, mark size=2.1pt, cK] table[x=propellant_Wh_per_kg, y=row] {\refs};
  \addplot[only marks, mark=triangle*, mark size=2.6pt, mark options={rotate=180}, cP] table[x=req_Wh_per_kg, y=row] {\conc};
<<txtb>>
\end{groupplot}
\end{tikzpicture}"""
    body = body.replace("<<txta>>", "\n".join(txt_a)).replace("<<txtb>>", "\n".join(txt_b))
    return fill(body, reads="\n".join(reads), W=3.95, H=7.0, y1=nrows - 0.4, n1=nrows - 1, hl=nsrc + 0.5,
                laba=",".join("{" + l + "}" for l in lab_a), labb=",".join("{" + l + "}" for l in lab_b),
                classes=classes, burn=f"{nov['burn_s']:.0f}")


# ================================================================== build
def compile_one(name):
    env = dict(os.environ)
    env["PATH"] = str(MIKTEX) + os.pathsep + env.get("PATH", "")
    cmd = [str(MIKTEX / "pdflatex.exe"), "-interaction=nonstopmode", "-halt-on-error", "--disable-installer",
           f"{name}.tex"]
    for _ in range(2):
        r = subprocess.run(cmd, cwd=OUT, env=env, capture_output=True, text=True, errors="replace")
        log = (OUT / f"{name}.log").read_text(errors="replace") if (OUT / f"{name}.log").exists() else r.stdout
        if r.returncode != 0:
            err = [ln for ln in log.splitlines() if ln.startswith("!") or "Error" in ln][:8]
            raise RuntimeError(f"{name}: pdflatex failed\n" + "\n".join(err) + "\n" + log[-1500:])
        if "Rerun" not in log and "undefined references" not in log:
            break
    warns = sorted({ln.strip() for ln in log.splitlines() if "Missing character" in ln or "Overfull" in ln})
    for w in warns[:5]:
        print(f"  {name}: {w}")
    for ext in (".aux", ".log", ".out", ".synctex.gz", ".fls", ".fdb_latexmk"):
        (OUT / f"{name}{ext}").unlink(missing_ok=True)
    png = OUT / f"{name}.png"
    subprocess.run([str(GS), "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=png16m", f"-r{DPI}",
                    "-dTextAlphaBits=4", "-dGraphicsAlphaBits=4", f"-sOutputFile={png}", str(OUT / f"{name}.pdf")],
                   check=True, capture_output=True)
    info = subprocess.run([str(MIKTEX / "miktex-pdfinfo.exe"), str(OUT / f"{name}.pdf")], capture_output=True,
                          text=True, errors="replace").stdout
    m = re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", info)
    return (float(m.group(1)) * 2.54 / 72, float(m.group(2)) * 2.54 / 72) if m else (float("nan"), float("nan"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="figure name prefixes, e.g. fig03 fig11")
    ap.add_argument("--no-compile", action="store_true", help="write data and .tex only")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    (OUT / "style.tex").write_text(STYLE, encoding="utf-8")
    names = [n for n in FIGS if not args.only or any(n.startswith(p) for p in args.only)]
    for name in names:
        body = FIGS[name]()
        if body is None:
            print(f"{name}: skipped (input missing)")
            continue
        (OUT / f"{name}.tex").write_text(DOC.replace("<<body>>", body), encoding="utf-8")
        if args.no_compile:
            print(f"{name}: .tex written")
            continue
        w, h = compile_one(name)
        print(f"{name}: {w:5.2f} x {h:5.2f} cm  -> figures/pgf/{name}.pdf, .png")


if __name__ == "__main__":
    main()
