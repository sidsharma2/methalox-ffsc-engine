r"""Generate the first OpenFOAM case for the MFE-280 sea-level thrust chamber.

The case is a 2-D axisymmetric wedge (one cell thick) of the hot-gas path, from a
plane a little downstream of the injector face through the throat and the Rao bell
to the exit, plus the external sea-level region around the nozzle lip and the
plume. Solver: rhoCentralFoam (OpenFOAM v2306, ESI) with Kurganov fluxes,
k-omega SST and one calorically perfect gas.

Inputs : results/design.json, results/contour.csv
         (results/cooling_profile.csv only with --wall-thermal profile)
Output : cfd/cases/<name>/ with case_info.json (all chosen numbers)

From the project root (Windows):
    .venv\Scripts\python.exe cfd\make_case.py             # write the case
    .venv\Scripts\python.exe cfd\make_case.py --mesh      # write + mesh in WSL + initial fields
    .venv\Scripts\python.exe cfd\make_case.py --init-only # initial fields after a manual Allmesh
"""

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import brentq, least_squares

CFD = Path(__file__).resolve().parent
ROOT = CFD.parent
RES = ROOT / "results"                  # design results; --results points at an iteration build
sys.path.insert(0, str(ROOT))

OF_BASHRC = "/usr/lib/openfoam/openfoam2306/etc/bashrc"
RU = 8314.462618
G0 = 9.80665
P_AMB, T_AMB = 101325.0, 288.0
EUCKEN = (1.32, 1.77)            # OpenFOAM sutherland transport: kappa = mu*Cv*(1.32 + 1.77 R/Cv)


# ----------------------------------------------------------------------------- gas model

def area_mach(ar, g, supersonic):
    """Mach number for area ratio A/A* of a perfect gas with ratio of specific heats g."""
    ar = max(ar, 1.0)
    if ar - 1.0 < 1e-12:
        return 1.0
    f = lambda M: (1 / M) * ((2 / (g + 1)) * (1 + 0.5 * (g - 1) * M * M)) ** ((g + 1) / (2 * (g - 1))) - ar
    return brentq(f, 1 + 1e-12, 60.0) if supersonic else brentq(f, 1e-9, 1 - 1e-12)


def isentropic(g, R, p0, T0, M):
    T = T0 / (1 + 0.5 * (g - 1) * M * M)
    p = p0 * (T / T0) ** (g / (g - 1))
    u = M * math.sqrt(g * R * T)
    return {"M": M, "p": p, "T": T, "u": u, "rho": p / (R * T)}


def ideal_1d(g, R, p0, T0, eps, At, pa=P_AMB):
    """Ideal 1-D nozzle (uniform, axial exit flow) for a calorically perfect gas."""
    ex = isentropic(g, R, p0, T0, area_mach(eps, g, True))
    cstar = math.sqrt(R * T0 / g) * ((g + 1) / 2) ** ((g + 1) / (2 * (g - 1)))
    mdot = p0 * At / cstar
    Ae = eps * At
    f_vac = mdot * ex["u"] + ex["p"] * Ae
    f_amb = f_vac - pa * Ae
    return {"gamma": g, "R": R, "cp": g * R / (g - 1), "pe": ex["p"], "Me": ex["M"], "Te": ex["T"],
            "ue": ex["u"], "rho_e": ex["rho"], "cstar": cstar, "mdot": mdot,
            "pt": p0 * (2 / (g + 1)) ** (g / (g - 1)), "Tt": T0 * 2 / (g + 1),
            "F_vac": f_vac, "F_amb": f_amb, "isp_vac": f_vac / (mdot * G0), "isp_amb": f_amb / (mdot * G0)}


def gas_model(design, kind, pc_frac):
    """Single-gas properties from Cantera (via ffsc.thermo) at the chamber state.

    kind = 'equivalent': MW of the chamber mixture; gamma chosen so that the ideal
           perfect-gas expansion to the design area ratio gives the same exit pressure
           as the shifting-equilibrium solution; cp = gamma R / (gamma - 1).
    kind = 'frozen'    : frozen cp, gamma and MW of the chamber mixture.
    """
    from ffsc import thermo
    perf, cfg = design["performance"], design["config"]
    pc = perf["pc"] * pc_frac
    of, eps, At = perf["mr_core"], perf["eps"], perf["At_m2"]
    prop = cfg["propellants"]
    kw = dict(T_ox=prop["lox"]["T_K"], T_fu=prop["lch4"]["T_K"], p_feed=prop["lox"]["p_inlet_bar"] * 1e5)
    shift = thermo.rocket(pc, of, eps, P_AMB, shifting=True, **kw)
    froz = thermo.rocket(pc, of, eps, P_AMB, shifting=False, **kw)

    h0 = (thermo.liquid_enthalpy("Methane", kw["T_fu"], kw["p_feed"])
          + of * thermo.liquid_enthalpy("Oxygen", kw["T_ox"], kw["p_feed"])) / (1 + of)
    gas = thermo.equilibrium_hp(h0, pc, thermo.mixture_Y(of))
    Tc, X0 = gas.T, gas.X.copy()
    mw, cp_f, cv_f = gas.mean_molecular_weight, gas.cp_mass, gas.cv_mass
    mu_c, k_c = gas.viscosity, gas.thermal_conductivity
    comp = {n: round(float(x), 4) for n, x in zip(gas.species_names, X0) if x > 1e-3}
    h_c = gas.enthalpy_mass
    gas.TPX = froz.exit.T, froz.pe, X0
    cp_mean = (h_c - gas.enthalpy_mass) / (Tc - froz.exit.T)

    # Sutherland fit to the frozen chamber-mixture viscosity, 250-4000 K
    T_fit = np.geomspace(250.0, 4000.0, 40)
    mu_fit = []
    for T in T_fit:
        gas.TPX = T, 1e5, X0
        mu_fit.append(gas.viscosity)
    mu_fit = np.array(mu_fit)
    model = lambda q, T: np.exp(q[0]) * np.sqrt(T) / (1 + np.exp(q[1]) / T)
    sol = least_squares(lambda q: np.log(model(q, T_fit) / mu_fit), x0=[np.log(1.5e-6), np.log(150.0)])
    As, Ts = float(np.exp(sol.x[0])), float(np.exp(sol.x[1]))
    mu_err = float(np.max(np.abs(model(sol.x, T_fit) / mu_fit - 1)))

    R = RU / mw
    pe_ratio = lambda g: (1 + 0.5 * (g - 1) * area_mach(eps, g, True) ** 2) ** (-g / (g - 1))
    g_equiv = brentq(lambda g: pe_ratio(g) - shift.pe / pc, 1.03, 1.40)
    cands = {
        "frozen_chamber": cp_f / cv_f,
        "frozen_mean_cp": cp_mean / (cp_mean - R),
        "gamma_eff_throat": shift.gamma_eff,
        "equivalent": g_equiv,
    }
    ref = {"pe": shift.pe, "Me": shift.exit.M, "Te": shift.exit.T, "ue": shift.exit.u, "cstar": shift.cstar,
           "isp_vac": shift.isp_vac, "isp_amb": shift.isp_sl, "pt": shift.throat.p, "Tt": shift.throat.T}
    ref_frozen = {"pe": froz.pe, "Me": froz.exit.M, "Te": froz.exit.T, "ue": froz.exit.u, "cstar": froz.cstar,
                  "isp_vac": froz.isp_vac, "isp_amb": froz.isp_sl}
    table = {}
    for name, g in cands.items():
        r = ideal_1d(g, R, pc, Tc, eps, At)
        r["err_pct_vs_shifting"] = {k: 100 * (r[k] / ref[k] - 1) for k in ("pe", "Te", "ue", "cstar", "isp_vac", "isp_amb", "pt")}
        table[name] = r

    g = cands["equivalent" if kind == "equivalent" else "frozen_chamber"]
    chosen = {"kind": kind, "gamma": g, "R": R, "MW": mw, "cp": g * R / (g - 1), "As": As, "Ts": Ts,
              "Pr_model": g / (EUCKEN[0] + EUCKEN[1] * (g - 1)), "mu_fit_max_rel_err": mu_err}
    return {"pc": pc, "Tc": Tc, "of_core": of, "eps": eps, "At": At, "gas": chosen,
            "chamber_frozen": {"cp": cp_f, "gamma": cp_f / cv_f, "MW": mw, "mu": mu_c, "k": k_c,
                               "Pr": cp_f * mu_c / k_c, "X": comp, "cp_mean_frozen_expansion": cp_mean},
            "shifting_eq": ref, "frozen_eq": ref_frozen, "candidates": table,
            "ideal_chosen": table["equivalent" if kind == "equivalent" else "frozen_chamber"]}


def mu_suth(gas, T):
    return gas["As"] * math.sqrt(T) / (1 + gas["Ts"] / T)


def first_cell(gas, st, s_arc, yplus, Tw=None):
    """First-cell height h for a target cell-centre y+ (OpenFOAM y = h/2, wall properties).

    Turbulent flat plate (cf = 0.0592 Re_x^-0.2) with Eckert reference temperature,
    x = wall arc length from the CFD inlet plane. Expect +/-30 %.
    """
    g, R = gas["gamma"], gas["R"]
    rec = gas["Pr_model"] ** (1 / 3)
    p, T, u, M = st["p"], st["T"], st["u"], st["M"]
    Taw = T * (1 + rec * 0.5 * (g - 1) * M * M)
    Tw = Taw if Tw is None else Tw
    Tref = 0.5 * (Tw + T) + 0.22 * (Taw - T)
    rho_r = p / (R * Tref)
    Re_x = rho_r * u * s_arc / mu_suth(gas, Tref)
    cf = 0.0592 * Re_x ** -0.2
    tau = 0.5 * cf * rho_r * u * u
    rho_w = p / (R * Tw)
    nu_w = mu_suth(gas, Tw) / rho_w
    u_tau = math.sqrt(tau / rho_w)
    return {"h": 2 * yplus * nu_w / u_tau, "Taw": Taw, "Tw": Tw, "Re_x": Re_x, "cf": cf, "tau_w": tau,
            "u_tau": u_tau, "nu_w": nu_w}


# ----------------------------------------------------------------------------- grading helpers

def geom_q(L, N, d1):
    """Common ratio of N geometric cells of total length L whose first cell is d1."""
    if abs(d1 * N - L) <= 1e-12 * L:
        return 1.0
    S = lambda q: N if abs(q - 1) < 1e-14 else (q ** N - 1) / (q - 1)
    f = lambda lq: d1 * S(math.exp(lq)) - L
    lo, hi = (1e-12, 2.0) if d1 * N < L else (-3.0, -1e-12)
    return math.exp(brentq(f, lo, hi, xtol=1e-14))


def n_cells(L, d1, d2):
    n = L / d1 if abs(d2 - d1) < 1e-12 else L * math.log(d2 / d1) / (d2 - d1)
    return max(2, int(round(n)))


def wall_layer(L, N, h, q=1.18):
    """Axis -> wall distribution: uniform core, then a geometric layer that shrinks to h at the wall."""
    d = L / N
    if d <= h * q:
        return 1.0, {"n_layer": 0, "d_core": d, "h": d, "q": 1.0}
    for _ in range(100):
        n_l = max(2, math.ceil(math.log(d / h) / math.log(q)))
        if n_l >= N - 2:
            raise ValueError(f"wall layer needs {n_l} of {N} cells: raise --res or --yplus")
        qq = (d / h) ** (1 / n_l)
        L_l = h * (qq ** n_l - 1) / (qq - 1)
        d_new = (L - L_l) / (N - n_l)
        if abs(d_new - d) < 1e-12 * L:
            break
        d = d_new
    segs = [((L - L_l) / L, (N - n_l) / N, 1.0), (L_l / L, n_l / N, qq ** -(n_l - 1))]
    return segs, {"n_layer": n_l, "d_core": d, "h": h, "q": qq}


def one_sided(L, N, d, at_end=False):
    """Geometric expansion ratio (last/first) for first cell d (or last cell d if at_end)."""
    q = geom_q(L, N, d)
    return 1 / q ** (N - 1) if at_end else q ** (N - 1)


def two_sided(L, N, h):
    n2 = N // 2
    er = geom_q(L / 2, n2, h) ** (n2 - 1)
    return [(0.5, 0.5, er), (0.5, 0.5, 1 / er)]


def fmt_grading(gr):
    if isinstance(gr, (int, float)):
        return f"{gr:.10g}"
    return "(" + " ".join(f"({a:.10g} {b:.10g} {c:.10g})" for a, b, c in gr) + ")"


# ----------------------------------------------------------------------------- mesh

FACES = {"x1min": (0, 4, 7, 3), "x1max": (1, 2, 6, 5), "x2min": (0, 1, 5, 4),
         "x2max": (3, 7, 6, 2), "x3min": (0, 3, 2, 1), "x3max": (4, 5, 6, 7)}


def build_mesh(args, design, gm, xc, rc):
    G = design["geometry"]
    gas = gm["gas"]
    g, R, p0, T0 = gas["gamma"], gas["R"], gm["pc"], gm["Tc"]
    Rt, Re = G["Rt_m"], float(rc[-1])
    x_t, x_e, L_cyl = G["x_throat_m"], float(xc[-1]), G["L_cyl_m"]
    res, t = args.res, args.lip_mm * 1e-3
    a = math.radians(0.5 * args.wedge_deg)
    x_in = args.x_inlet if args.x_inlet is not None else 0.25 * L_cyl
    if not 0.0 <= x_in < L_cyl - 0.01:
        raise ValueError("--x-inlet must lie in the chamber cylinder")
    rw = lambda x: float(np.interp(x, xc, rc))
    s_c = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xc), np.diff(rc)))])
    sw = lambda x: float(np.interp(x, xc, s_c))
    bell = xc >= x_t
    x_eps = lambda e: float(np.interp(e, (rc[bell] / Rt) ** 2, xc[bell]))

    N_r = int(round(90 * res))
    N_lip = max(6, 2 * int(round(6 * res)))
    Twg = None
    if args.wall_thermal == "profile":
        cp_ = np.genfromtxt(RES / "cooling_profile.csv", delimiter=",", names=True)
        Twg = lambda x: float(np.interp(x, cp_["x"], cp_["Twg"]))

    names = ["inlet", "cyl_end", "throat", "eps4", "eps15", "exit"]
    xs = [x_in, L_cyl, x_t, x_eps(4.0), x_eps(15.0), x_e]
    dxs = np.array([4e-3, 3e-3, 1.0e-3, 4e-3, 10e-3, 4e-3]) / res
    stations = []
    for nm, x, dx in zip(names, xs, dxs):
        M = area_mach((rw(x) / Rt) ** 2, g, supersonic=x > x_t + 1e-9)
        st = isentropic(g, R, p0, T0, M)
        s_arc = (sw(L_cyl) - sw(x_in)) if nm == "inlet" else (sw(x) - sw(x_in))
        fc = first_cell(gas, st, s_arc, args.yplus, Twg(x) if Twg else None)
        h = fc["h"] if nm != "exit" else min(fc["h"], 0.5 * t / N_lip)
        grad, info = wall_layer(rw(x), N_r, h)
        stations.append({"name": nm, "x": x, "r_wall": rw(x), "eps": (rw(x) / Rt) ** 2, "M": M, "p": st["p"],
                         "T": st["T"], "u": st["u"], "s_arc": s_arc, "dx": float(dx), "h": h,
                         "yplus_est": 0.5 * h * fc["u_tau"] / fc["nu_w"], "Taw": fc["Taw"], "Tw": fc["Tw"],
                         "Re_x": fc["Re_x"], "cf": fc["cf"], "tau_w": fc["tau_w"], "u_tau": fc["u_tau"],
                         "n_layer": info["n_layer"], "d_core": info["d_core"], "grading": grad})

    # external region
    De = 2 * Re
    x_far = x_e + args.down_de * De
    R_far = args.rad_re * Re
    x_up = x_e - args.up_re * Re
    r_up = rw(x_up) + t
    h_lip = stations[-1]["h"]
    d_lip = t / N_lip
    dx0, dx_far, dx_up, dr_far = dxs[-1], 0.15 / res, 0.04 / res, 0.06 / res
    n_down = n_cells(x_far - x_e, dx0, dx_far)
    n_up = n_cells(x_e - x_up, dx_up, dx0)
    N_out = n_cells(R_far - Re - t, h_lip, dr_far)
    g_down = dx_far / dx0
    g_up = dx0 / dx_up
    g_out_e = one_sided(R_far - Re - t, N_out, h_lip)
    g_out_far = one_sided(R_far - Re - t, N_out, d_lip)
    g_out_up = one_sided(R_far - r_up, N_out, h_lip)
    g_d1_far = one_sided(Re, N_r, d_lip, at_end=True)
    g_lip_e = two_sided(t, N_lip, h_lip)

    # vertices
    pts, vid = [], {}

    def add(name, x, r):
        if r == 0.0:
            vid[name] = len(pts)
            pts.append(((x, 0.0, 0.0), name))
        else:
            vid[name + "f"] = len(pts)
            pts.append(((x, r * math.cos(a), -r * math.sin(a)), name + " front"))
            vid[name + "b"] = len(pts)
            pts.append(((x, r * math.cos(a), r * math.sin(a)), name + " back"))

    for i, s in enumerate(stations):
        add(f"ax{i}", s["x"], 0.0)
        add(f"w{i}", s["x"], s["r_wall"])
    add("axfar", x_far, 0.0)
    add("d1", x_far, Re)
    add("d2", x_far, Re + t)
    add("lip", x_e, Re + t)
    add("o", x_up, r_up)
    add("f0", x_up, R_far)
    add("f2", x_e, R_far)
    add("f3", x_far, R_far)
    F = lambda n: vid.get(n + "f", vid.get(n))
    B = lambda n: vid.get(n + "b", vid.get(n))

    blocks = []

    def block(name, la, lb, hb, ha, n1, n2, gx, gra, grb):
        v = [F(la), F(lb), F(hb), F(ha), B(la), B(lb), B(hb), B(ha)]
        blocks.append({"name": name, "v": v, "n": (n1, n2), "gx": gx, "gra": gra, "grb": grb})
        return len(blocks) - 1

    seg_blocks = []
    for i in range(len(stations) - 1):
        s0, s1 = stations[i], stations[i + 1]
        n1 = n_cells(s1["x"] - s0["x"], s0["dx"], s1["dx"])
        seg_blocks.append(block(f"{s0['name']}-{s1['name']}", f"ax{i}", f"ax{i + 1}", f"w{i + 1}", f"w{i}",
                                n1, N_r, s1["dx"] / s0["dx"], s0["grading"], s1["grading"]))
    k = len(stations) - 1
    bD1 = block("plume core", f"ax{k}", "axfar", "d1", f"w{k}", n_down, N_r, g_down, stations[-1]["grading"], g_d1_far)
    bD2 = block("lip wake", f"w{k}", "d1", "d2", "lip", n_down, N_lip, g_down, g_lip_e, 1.0)
    bD3 = block("outer plume", "lip", "d2", "f3", "f2", n_down, N_out, g_down, g_out_e, g_out_far)
    bU3 = block("outside nozzle", "o", "lip", "f2", "f0", n_up, N_out, g_up, g_out_up, g_out_e)

    def faces(bi, key):
        v = blocks[bi]["v"]
        return tuple(v[j] for j in FACES[key])

    i_throat = next(i for i, s in enumerate(stations) if s["name"] == "throat")
    patches = [
        ("inlet", "patch", [faces(seg_blocks[0], "x1min")]),
        ("wall_chamber", "wall", [faces(b, "x2max") for b in seg_blocks[:i_throat]]),
        ("wall_bell", "wall", [faces(b, "x2max") for b in seg_blocks[i_throat:]]),
        ("lip", "wall", [faces(bD2, "x1min")]),
        ("wall_outer", "wall", [faces(bU3, "x2min")]),
        ("ambient_inlet", "patch", [faces(bU3, "x1min")]),
        ("ambient_side", "patch", [faces(bU3, "x2max"), faces(bD3, "x2max")]),
        ("outlet", "patch", [faces(b, "x1max") for b in (bD1, bD2, bD3)]),
        ("axis", "empty", [faces(b, "x2min") for b in seg_blocks + [bD1]]),
        ("front", "wedge", [faces(b, "x3min") for b in range(len(blocks))]),
        ("back", "wedge", [faces(b, "x3max") for b in range(len(blocks))]),
    ]

    # curved edges: inner wall between stations, outer nozzle surface
    edges = []
    for i in range(len(stations) - 1):
        xa, xb = stations[i]["x"], stations[i + 1]["x"]
        m = (xc > xa + 1e-9) & (xc < xb - 1e-9)
        edges.append((f"w{i}", f"w{i + 1}", xc[m], rc[m]))
    m = (xc > x_up + 1e-9) & (xc < x_e - 1e-9)
    edges.append(("o", "lip", xc[m], rc[m] + t))

    L = ["scale 1;", "", "mergeType points;   // wedge with collapsed axis vertices", "", "vertices", "("]
    for i, ((x, y, z), nm) in enumerate(pts):
        L.append(f"    ({x:.17g} {y:.17g} {z:.17g})  // {i} {nm}")
    L += [");", "", "blocks", "("]
    for b in blocks:
        gx = fmt_grading(b["gx"])
        ga, gb = fmt_grading(b["gra"]), fmt_grading(b["grb"])
        L.append(f"    // {b['name']}")
        L.append(f"    hex ({' '.join(map(str, b['v']))}) ({b['n'][0]} {b['n'][1]} 1)")
        L.append(f"    edgeGrading ({gx} {gx} {gx} {gx}  {ga} {gb} {gb} {ga}  1 1 1 1)")
    L += [");", "", "edges", "("]
    for na, nb, ex, er in edges:
        for side, sgn in (("f", -1.0), ("b", 1.0)):
            L.append(f"    polyLine {vid[na + side]} {vid[nb + side]}")
            L.append("    (")
            for x, r in zip(ex, er):
                L.append(f"        ({x:.17g} {r * math.cos(a):.17g} {sgn * r * math.sin(a):.17g})")
            L.append("    )")
    L += [");", "", "boundary", "("]
    for name, typ, fl in patches:
        L += [f"    {name}", "    {", f"        type {typ};", "        faces", "        ("]
        L += [f"            ({' '.join(map(str, f))})" for f in fl]
        L += ["        );", "    }"]
    L += [");"]

    n_total = sum(b["n"][0] * b["n"][1] for b in blocks)
    mesh = {"N_r": N_r, "N_lip": N_lip, "N_out": N_out, "n_down": n_down, "n_up": n_up,
            "n_axial_internal": [blocks[b]["n"][0] for b in seg_blocks],
            "cells": n_total, "cells_by_block": {b["name"]: b["n"][0] * b["n"][1] for b in blocks},
            "x_inlet": x_in, "x_throat": x_t, "x_exit": x_e, "x_far": x_far, "x_up": x_up, "R_far": R_far,
            "Re": Re, "Rt": Rt, "lip_t": t, "r_outer_up": r_up, "h_lip": h_lip, "d_lip_far": d_lip,
            "dx_exit": float(dx0), "dx_far": dx_far, "dx_up": dx_up, "dr_far": dr_far,
            "wedge_deg": args.wedge_deg, "stations": stations}
    return "\n".join(L) + "\n", mesh


# ----------------------------------------------------------------------------- case files

def foam_file(cls, obj, body, location=None):
    loc = f'    location    "{location}";\n' if location else ""
    return ("/*--------------------------------*- C++ -*----------------------------------*\\\n"
            "  Generated by cfd/make_case.py for OpenFOAM v2306 (ESI)\n"
            "\\*---------------------------------------------------------------------------*/\n"
            "FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
            f"    class       {cls};\n{loc}    object      {obj};\n}}\n"
            "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n\n"
            + body.rstrip() + "\n\n// ************************************************************************* //\n")


def bc(patches):
    out = ["boundaryField", "{"]
    for name, entries in patches:
        out += [f"    {name}", "    {"]
        out += [f"        {k:<16}{v};" for k, v in entries]
        out += ["    }"]
    out += ["}"]
    return "\n".join(out)


def internal(value, kind, arr=None):
    if arr is None:
        return f"internalField   uniform {value};\n"
    n = len(arr)
    if kind == "scalar":
        body = "\n".join(f"{v:.9g}" for v in arr)
        return f"internalField   nonuniform List<scalar>\n{n}\n(\n{body}\n)\n;\n"
    body = "\n".join(f"({u:.7g} {v:.7g} {w:.7g})" for u, v, w in arr)
    return f"internalField   nonuniform List<vector>\n{n}\n(\n{body}\n)\n;\n"


def field_files(info, arrays=None):
    arrays = arrays or {}
    gas, bcd = info["gas"], info["bc"]
    G = f"{gas['gamma']:.6g}"
    walls_inner = "(wall_chamber|wall_bell)"
    walls_other = "(lip|wall_outer)"
    walls_all = "(wall_chamber|wall_bell|lip|wall_outer)"
    common = [("axis", [("type", "empty")]), ("\"(front|back)\"", [("type", "wedge")])]
    p0, T0, pa, Ta = bcd["p0"], bcd["T0"], P_AMB, T_AMB
    files = {}

    p = [("inlet", [("type", "totalPressure"), ("p0", f"uniform {p0:.9g}"), ("psi", "thermo:psi"),
                    ("gamma", G), ("value", f"uniform {p0:.9g}")]),
         (f'"{walls_all}"', [("type", "zeroGradient")]),
         # static-pressure far field: a total-pressure inflow sets p = p0 - rho U^2 / 2 and collapsed to
         # negative density at r = 5 Re when the plume's starting vortex drove fast entrainment (run 1, it 2,194)
         ('"ambient_.*"', [("type", "waveTransmissive"), ("psi", "thermo:psi"), ("gamma", G),
                           ("fieldInf", f"{pa:.9g}"), ("lInf", f"{bcd['lInf']:.4g}"), ("value", f"uniform {pa:.9g}")]),
         ("outlet", [("type", "waveTransmissive"), ("psi", "thermo:psi"), ("gamma", G),
                     ("fieldInf", f"{pa:.9g}"), ("lInf", f"{bcd['lInf']:.4g}"), ("value", f"uniform {pa:.9g}")])]
    files["p"] = ("volScalarField", "[1 -1 -2 0 0 0 0]", pa, "scalar", p)

    U = [("inlet", [("type", "pressureInletOutletVelocity"), ("value", "uniform (0 0 0)")]),
         (f'"{walls_all}"', [("type", "noSlip")]),
         ('"ambient_.*"', [("type", "pressureInletOutletVelocity"), ("value", "uniform (0 0 0)")]),
         ("outlet", [("type", "inletOutlet"), ("inletValue", "uniform (0 0 0)"), ("value", "uniform (0 0 0)")])]
    files["U"] = ("volVectorField", "[0 1 -1 0 0 0 0]", "(0 0 0)", "vector", U)

    if bcd["wall_thermal"] == "profile":
        tab = " ".join(f"({x:.6g} {T:.6g})" for x, T in bcd["Twg_table"])
        Tw = [("type", "fixedProfile"), ("profile", f"table ({tab})"), ("direction", "(1 0 0)"),
              ("origin", "0"), ("value", f"uniform {bcd['Twg_table'][0][1]:.6g}")]
    else:
        Tw = [("type", "zeroGradient")]
    T = [("inlet", [("type", "totalTemperature"), ("T0", f"uniform {T0:.9g}"), ("psi", "thermo:psi"),
                    ("gamma", G), ("value", f"uniform {T0:.9g}")]),
         (f'"{walls_inner}"', Tw),
         (f'"{walls_other}"', [("type", "zeroGradient")]),
         ('"ambient_.*"', [("type", "inletOutlet"), ("inletValue", f"uniform {Ta:.6g}"), ("value", f"uniform {Ta:.6g}")]),
         ("outlet", [("type", "inletOutlet"), ("inletValue", f"uniform {Ta:.6g}"), ("value", f"uniform {Ta:.6g}")])]
    files["T"] = ("volScalarField", "[0 0 0 1 0 0 0]", Ta, "scalar", T)

    k_in, w_in, k_a, w_a = bcd["k_in"], bcd["omega_in"], bcd["k_amb"], bcd["omega_amb"]
    k = [("inlet", [("type", "turbulentIntensityKineticEnergyInlet"), ("intensity", f"{bcd['intensity']:.3g}"),
                    ("value", f"uniform {k_in:.6g}")]),
         (f'"{walls_all}"', [("type", "kqRWallFunction"), ("value", f"uniform {k_a:.6g}")]),
         ('"(ambient_.*|outlet)"', [("type", "inletOutlet"), ("inletValue", f"uniform {k_a:.6g}"),
                                    ("value", f"uniform {k_a:.6g}")])]
    files["k"] = ("volScalarField", "[0 2 -2 0 0 0 0]", k_a, "scalar", k)

    w = [("inlet", [("type", "turbulentMixingLengthFrequencyInlet"), ("mixingLength", f"{bcd['mixing_length']:.4g}"),
                    ("value", f"uniform {w_in:.6g}")]),
         (f'"{walls_all}"', [("type", "omegaWallFunction"), ("value", f"uniform {w_in:.6g}")]),
         ('"(ambient_.*|outlet)"', [("type", "inletOutlet"), ("inletValue", f"uniform {w_a:.6g}"),
                                    ("value", f"uniform {w_a:.6g}")])]
    files["omega"] = ("volScalarField", "[0 0 -1 0 0 0 0]", w_a, "scalar", w)

    nut = [(f'"{walls_all}"', [("type", "nutUSpaldingWallFunction"), ("value", "uniform 0")]),
           ('"(inlet|ambient_.*|outlet)"', [("type", "calculated"), ("value", "uniform 0")])]
    files["nut"] = ("volScalarField", "[0 2 -1 0 0 0 0]", 0, "scalar", nut)

    alphat = [(f'"{walls_all}"', [("type", "compressible::alphatJayatillekeWallFunction"), ("Prt", "0.85"),
                                  ("value", "uniform 0")]),
              ('"(inlet|ambient_.*|outlet)"', [("type", "calculated"), ("value", "uniform 0")])]
    files["alphat"] = ("volScalarField", "[1 -1 -1 0 0 0 0]", 0, "scalar", alphat)

    out = {}
    for name, (cls, dims, val, kind, pats) in files.items():
        body = f"dimensions      {dims};\n\n" + internal(val, kind, arrays.get(name)) + "\n" + bc(pats + common)
        out[name] = foam_file(cls, name, body, location="0")
    return out


def thermo_text(gas):
    return foam_file("dictionary", "thermophysicalProperties", f"""
// Single calorically perfect gas ({gas['kind']}): see cfd/README.md and case_info.json
thermoType
{{
    type            hePsiThermo;
    mixture         pureMixture;
    transport       sutherland;
    thermo          hConst;
    equationOfState perfectGas;
    specie          specie;
    energy          sensibleInternalEnergy;
}}

mixture
{{
    specie
    {{
        molWeight       {gas['MW']:.6g};      // chamber mixture (Cantera, CEA thermo)
    }}
    thermodynamics
    {{
        Cp              {gas['cp']:.6g};      // gamma = {gas['gamma']:.5f}
        Hf              0;
    }}
    transport
    {{
        As              {gas['As']:.6e};    // Sutherland fit to the chamber-mixture viscosity, 250-4000 K
        Ts              {gas['Ts']:.6g};
    }}
}}
""", location="constant")


def turbulence_text():
    return foam_file("dictionary", "turbulenceProperties", """
simulationType  RAS;

RAS
{
    RASModel        kOmegaSST;
    turbulence      on;
    printCoeffs     on;
}
""", location="constant")


def schemes_text(lts):
    return foam_file("dictionary", "fvSchemes", f"""
fluxScheme      Kurganov;

ddtSchemes
{{
    default         {'localEuler' if lts else 'Euler'};
}}

gradSchemes
{{
    default         Gauss linear;
}}

divSchemes
{{
    default         none;
    div(tauMC)      Gauss linear;
    div(phi,k)      Gauss limitedLinear 1;
    div(phi,omega)  Gauss limitedLinear 1;
}}

laplacianSchemes
{{
    default         Gauss linear limited corrected 0.5;
}}

interpolationSchemes
{{
    default         linear;
    reconstruct(rho) vanLeer;
    reconstruct(U)  vanLeerV;
    reconstruct(T)  vanLeer;
}}

snGradSchemes
{{
    default         limited corrected 0.5;
}}

wallDist
{{
    method          meshWave;
}}
""", location="system")


def solution_text():
    return foam_file("dictionary", "fvSolution", """
solvers
{
    "(rho|rhoU|rhoE)"
    {
        solver          diagonal;
    }

    "(U|e)"
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        nSweeps         2;
        tolerance       1e-10;
        relTol          0.01;
    }

    "(k|omega)"
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        nSweeps         2;
        tolerance       1e-10;
        relTol          0.01;
    }
}
""", location="system")


def control_text(info):
    m, run = info["mesh"], info["run"]
    lts = run["mode"] == "lts"
    x_t, x_e, De = m["x_throat"], m["x_exit"], 2 * m["Re"]
    yp = 0.002
    probes = [(x_t, yp), (x_e - 0.005, yp), (x_e - 0.005, 0.95 * m["Re"]), (x_e + 2 * De, yp), (x_e + 6 * De, yp)]
    probe_txt = "\n".join(f"            ({x:.6g} {y:.6g} 0)" for x, y in probes)
    if lts:
        timing = f"""
startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         {run['stages'][0][1]:g};   // Allrun sets the stage end times
deltaT          1;          // local time stepping: one time unit = one iteration
writeControl    timeStep;
writeInterval   {run['write_interval']:g};
purgeWrite      4;
writeFormat     ascii;
writePrecision  16;         // keeps wedge points planar to round-off
writeCompression off;
timeFormat      general;
timePrecision   8;
runTimeModifiable true;
adjustTimeStep  no;
maxCo           {run['stages'][0][0]:g};        // Allrun ramps 0.1 -> 0.15 -> 0.3 -> 0.5
maxDeltaT       1;          // upper bound of the local time step [s], not active
rDeltaTSmoothingCoeff 0.2;  // max ratio of neighbouring local time steps = 1.2
"""
        mon = 20
    else:
        timing = f"""
startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         {run['stages'][0][1]:g};
deltaT          1e-10;
writeControl    adjustable;
writeInterval   {run['write_interval']:g};
purgeWrite      4;
writeFormat     ascii;
writePrecision  16;
writeCompression off;
timeFormat      general;
timePrecision   8;
runTimeModifiable true;
adjustTimeStep  yes;
maxCo           {run['stages'][0][0]:g};
maxDeltaT       1e-6;
"""
        mon = 50
    whf = """
    wallHeatFlux
    {
        type            wallHeatFlux;
        libs            (fieldFunctionObjects);
        patches         (wall_chamber wall_bell);
        writeControl    writeTime;
    }
""" if info["bc"]["wall_thermal"] == "profile" else ""
    return foam_file("dictionary", "controlDict", f"""
application     rhoCentralFoam;
{timing}
// Wedge = {m['wedge_deg']:g} deg sector: multiply integrated flows/forces by 360/{m['wedge_deg']:g} = {360 / m['wedge_deg']:g}.
functions
{{
    // ---- exit plane (faceZone exitPlane, x = {x_e:.6g} m, oriented +x)
    exitMassFlow
    {{
        type            surfaceFieldValue;
        libs            (fieldFunctionObjects);
        regionType      faceZone;
        name            exitPlane;
        operation       sum;
        fields          (phi);
        writeFields     false;
        writeControl    timeStep;
        writeInterval   {mon};
        log             false;
    }}
    exitMomentumFlux        // sum rho (U.Sf) U
    {{
        $exitMassFlow;
        operation       weightedAreaIntegrate;
        weightFields    (rho U);
        fields          (U);
    }}
    exitPressureForce       // sum p |Sf|
    {{
        $exitMassFlow;
        operation       areaIntegrate;
        fields          (p);
    }}
    exitAreaAverage
    {{
        $exitMassFlow;
        operation       areaAverage;
        fields          (p T rho U);
        writeArea       true;       // wedge exit area, for the pa*A term
    }}
    exitMassAverage
    {{
        $exitMassFlow;
        operation       weightedAreaAverage;
        weightFields    (rho U);
        fields          (p T U);
    }}
    inletMassFlow
    {{
        $exitMassFlow;
        regionType      patch;
        name            inlet;
    }}

    // ---- derived fields (before the surfaces that sample them)
    yPlus
    {{
        type            yPlus;
        libs            (fieldFunctionObjects);
        writeControl    writeTime;
    }}
    MachNo
    {{
        type            MachNo;
        libs            (fieldFunctionObjects);
        executeControl  timeStep;
        writeControl    writeTime;
    }}

    // ---- walls
    innerWallForces
    {{
        type            forces;
        libs            (forces);
        patches         (wall_chamber wall_bell);
        rho             rho;
        pRef            {P_AMB:g};
        CofR            (0 0 0);
        writeControl    timeStep;
        writeInterval   {mon};
        log             false;
    }}
    wallSurfaces
    {{
        type            surfaces;
        libs            (sampling);
        writeControl    writeTime;
        surfaceFormat   raw;
        interpolationScheme cell;
        fields          (p T Ma yPlus);
        surfaces
        {{
            innerWall
            {{
                type            patch;
                patches         (wall_chamber wall_bell);
                interpolate     false;
            }}
            lipAndOuter
            {{
                type            patch;
                patches         (lip wall_outer);
                interpolate     false;
            }}
        }}
    }}
{whf}
    // ---- convergence monitors
    minMax
    {{
        type            fieldMinMax;
        libs            (fieldFunctionObjects);
        fields          (p T U);
        mode            magnitude;
        writeControl    timeStep;
        writeInterval   {mon};
        log             false;
    }}
    probes
    {{
        type            probes;
        libs            (sampling);
        fields          (p T U);
        writeControl    timeStep;
        writeInterval   {mon};
        probeLocations
        (
{probe_txt}
        );
    }}
}}
""", location="system")


def decompose_text(n):
    return foam_file("dictionary", "decomposeParDict", f"""
numberOfSubdomains {n};

method          scotch;
""", location="system")


def toposet_text(m):
    a = math.radians(0.5 * m["wedge_deg"])
    x_e, ymax = m["x_exit"], m["Re"] * math.cos(a)
    return foam_file("dictionary", "topoSetDict", f"""
// Exit plane x = x_exit, axis to the inner lip edge. Face centres of the lip face lie
// above Re*cos(wedge/2), exit-plane face centres below it.
actions
(
    {{
        name    exitPlaneFaces;
        type    faceSet;
        action  new;
        source  boxToFace;
        box     ({x_e - 1e-6:.9g} -1 -1) ({x_e + 1e-6:.9g} {ymax:.9g} 1);
    }}
    {{
        name    exitPlane;
        type    faceZoneSet;
        action  new;
        source  setAndNormalToFaceZone;
        faceSet exitPlaneFaces;
        normal  (1 0 0);
    }}
);
""", location="system")


SOURCE_OF = f"""if [ -z "$WM_PROJECT_DIR" ]; then
    . {OF_BASHRC} || exit 1
fi"""

ALLMESH = f"""#!/bin/bash
# Mesh only: blockMesh, checkMesh, exit-plane faceZone, cell centres for the
# initial field. Does not start the flow solver.
cd "$(dirname "$0")" || exit 1
{SOURCE_OF}

blockMesh > log.blockMesh 2>&1 || {{ echo "blockMesh failed, see log.blockMesh"; exit 1; }}
checkMesh > log.checkMesh 2>&1
echo "checkMesh exit status $? (log.checkMesh)"
topoSet > log.topoSet 2>&1 || {{ echo "topoSet failed, see log.topoSet"; exit 1; }}
rm -rf 0 && cp -r 0.orig 0
postProcess -func writeCellCentres -time 0 > log.writeCellCentres 2>&1 \\
    || {{ echo "writeCellCentres failed"; exit 1; }}
grep -E "^ *cells:|non-orthogonality Max|Max skewness|Max aspect|Failed|Mesh OK|\\*\\*\\*" log.checkMesh
"""


def allrun_text(info):
    run = info["run"]
    stages = "\n".join(f"stage {i + 1} {co:g} {end:g}" for i, (co, end) in enumerate(run["stages"]))
    return f"""#!/bin/bash
# Parallel rhoCentralFoam run with a three-stage Courant-number ramp.
#   ./Allrun [nProcs]        default {run['nprocs']} (one rank per physical core)
#   FORCE=1 ./Allrun         skip the check for other running OpenFOAM jobs
# Re-running continues from the latest processor time; finished stages are skipped.
cd "$(dirname "$0")" || exit 1
{SOURCE_OF}
NP=${{1:-{run['nprocs']}}}

if [ -z "$FORCE" ]; then
    busy=$(pgrep -a -f 'Foam' | grep -v -E 'pgrep|Allrun|Allmesh|bash -c|bash -lc')
    if [ -n "$busy" ]; then
        echo "Other OpenFOAM processes are running in this distro:"; echo "$busy"
        echo "Not starting. Use FORCE=1 ./Allrun to override."; exit 1
    fi
fi
grep -q nonuniform 0/p || {{ echo "0/p has no initial field: run make_case.py --init-only first"; exit 1; }}

MPIFLAGS=""
[ "$(id -u)" = 0 ] && MPIFLAGS="--allow-run-as-root"

if [ ! -d processor0 ]; then
    foamDictionary -entry numberOfSubdomains -set "$NP" system/decomposeParDict > /dev/null
    decomposePar > log.decomposePar 2>&1 || {{ echo "decomposePar failed"; exit 1; }}
fi

latest() {{ foamListTimes -processor -latestTime 2>/dev/null | tail -1; }}

stage() {{  # stage <n> <maxCo> <endTime>
    t=$(latest); t=${{t:-0}}
    if awk -v a="$t" -v b="$3" 'BEGIN{{exit !(a+0 >= b+0)}}'; then echo "stage $1 already done (t = $t)"; return; fi
    foamDictionary -entry maxCo -set "$2" system/controlDict > /dev/null
    foamDictionary -entry endTime -set "$3" system/controlDict > /dev/null
    echo "stage $1: maxCo $2 until $3 ($(date))"
    mpirun $MPIFLAGS -np "$NP" rhoCentralFoam -parallel > "log.rhoCentralFoam.$1" 2>&1 \\
        || {{ echo "rhoCentralFoam failed in stage $1, see log.rhoCentralFoam.$1"; exit 1; }}
}}

{stages}
reconstructPar -latestTime > log.reconstructPar 2>&1
echo "done ($(date))"
"""


ALLCLEAN = f"""#!/bin/bash
# Remove mesh, results and logs; keeps 0.orig, constant/*Properties and system/.
cd "$(dirname "$0")" || exit 1
{SOURCE_OF}
rm -rf processor* postProcessing log.* constant/polyMesh 0
foamListTimes -rm > /dev/null 2>&1
"""


# ----------------------------------------------------------------------------- initial field

def read_cell_centres(case):
    txt = (case / "0" / "C").read_text()
    i = txt.index("internalField")
    m = re.compile(r"nonuniform\s+List<vector>\s+(\d+)\s*\(").search(txt, i)
    if not m:
        raise RuntimeError("0/C is not an ascii nonuniform vector field")
    n = int(m.group(1))
    body = txt[m.end():].lstrip("\n").split("\n", n)[:n]
    return np.array([ln.strip()[1:-1].split() for ln in body], dtype=float)


def initial_fields(case, info):
    """1-D isentropic flow inside the nozzle, an exit-state column for 4 De downstream,
    still ambient gas elsewhere."""
    C = read_cell_centres(case)
    gas, m, bcd = info["gas"], info["mesh"], info["bc"]
    g, R, p0, T0 = gas["gamma"], gas["R"], bcd["p0"], bcd["T0"]
    con = np.loadtxt(RES / "contour.csv", delimiter=",", skiprows=1)
    xc, rc = con[:, 0], con[:, 1]
    Rt, Re, x_t, x_e = m["Rt"], m["Re"], m["x_throat"], m["x_exit"]
    slope = np.gradient(rc, xc)

    xg = np.linspace(xc[0], x_e, 4000)
    ar = (np.interp(xg, xc, rc) / Rt) ** 2
    Mg = np.array([area_mach(a_, g, x > x_t) for a_, x in zip(ar, xg)])

    x, y, z = C[:, 0], C[:, 1], C[:, 2]
    r = np.hypot(y, z)
    ey, ez = np.where(r > 0, y / np.maximum(r, 1e-30), 1.0), np.where(r > 0, z / np.maximum(r, 1e-30), 0.0)
    rwall = np.interp(x, xc, rc)
    inside = (x <= x_e + 1e-9) & (r < rwall + 0.5 * m["lip_t"])
    column = (x > x_e) & (x < x_e + 4 * 2 * Re) & (r < Re)

    M = np.interp(x, xg, Mg)
    M = np.where(column, Mg[-1], M)
    T = T0 / (1 + 0.5 * (g - 1) * M ** 2)
    p = p0 * (T / T0) ** (g / (g - 1))
    u = M * np.sqrt(g * R * T)
    phi = np.where(column, np.arctan(slope[-1]) * np.minimum(r / Re, 1.0),
                   np.arctan(np.interp(x, xc, slope)) * np.minimum(r / rwall, 1.0))
    flow = inside | column
    p = np.where(flow, p, P_AMB)
    T = np.where(flow, T, T_AMB)
    u = np.where(flow, u, 0.0)
    U = np.column_stack([u * np.cos(phi), u * np.sin(phi) * ey, u * np.sin(phi) * ez])
    k = np.where(flow, bcd["k_in"], bcd["k_amb"])
    w = np.where(flow, bcd["omega_in"], bcd["omega_amb"])
    files = field_files(info, {"p": p, "T": T, "U": U, "k": k, "omega": w})
    for name, txt in files.items():
        write(case / "0" / name, txt)
    for f in ("C", "Cx", "Cy", "Cz"):
        (case / "0" / f).unlink(missing_ok=True)
    return {"cells": len(C), "cells_nozzle": int(inside.sum()), "cells_column": int(column.sum()),
            "p_range": [float(p.min()), float(p.max())], "T_range": [float(T.min()), float(T.max())],
            "U_max": float(u.max())}


# ----------------------------------------------------------------------------- WSL helpers

def wsl_path(p):
    p = Path(p).resolve()
    return "/mnt/" + p.drive[0].lower() + p.as_posix()[2:]


def running_foam_jobs():
    """Return OpenFOAM processes in every running WSL distro (read-only pgrep)."""
    out = subprocess.run(["wsl", "-l", "-q", "--running"], capture_output=True).stdout
    distros = [d.strip("\ufeff \r") for d in out.decode("utf-16-le", errors="ignore").split("\n")]
    hits = []
    for d in filter(None, distros):
        r = subprocess.run(["wsl", "-d", d, "-e", "sh", "-c", "pgrep -a -f Foam || true"],
                           capture_output=True, text=True)
        hits += [f"{d}: {ln}" for ln in r.stdout.splitlines() if ln.strip() and "pgrep" not in ln]
    return hits


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="\n", encoding="utf-8") as f:
        f.write(text)


# ----------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--res", type=float, default=1.0, help="resolution factor: cell counts scale with it in both directions")
    ap.add_argument("--yplus", type=float, default=50.0, help="target cell-centre y+ used to size the wall cells")
    ap.add_argument("--wedge-deg", type=float, default=5.0)
    ap.add_argument("--lip-mm", type=float, default=20.0, help="nozzle lip thickness")
    ap.add_argument("--down-de", type=float, default=12.0, help="plume region length in exit diameters")
    ap.add_argument("--rad-re", type=float, default=5.0, help="outer radius in exit radii")
    ap.add_argument("--up-re", type=float, default=1.5, help="external region upstream of the exit plane, in exit radii")
    ap.add_argument("--x-inlet", type=float, default=None, help="inlet plane [m from injector face], default L_cyl/4")
    ap.add_argument("--gas", choices=["equivalent", "frozen"], default="equivalent")
    ap.add_argument("--wall-thermal", choices=["adiabatic", "profile"], default="adiabatic",
                    help="profile = Twg(x) from results/cooling_profile.csv")
    ap.add_argument("--pc-frac", type=float, default=1.0, help="chamber pressure fraction (0.4 = 40 %% throttle)")
    ap.add_argument("--time-mode", choices=["lts", "transient"], default="lts")
    ap.add_argument("--iters", type=int, default=40000, help="LTS iterations (end of stage 3)")
    ap.add_argument("--nprocs", type=int, default=8)
    ap.add_argument("--name", default=None)
    ap.add_argument("--results", default=None, help="results directory of an iteration build (default: results/)")
    ap.add_argument("--distro", default="Ubuntu-22.04", help="WSL distro with OpenFOAM v2306")
    ap.add_argument("--force", action="store_true", help="overwrite an existing case directory")
    ap.add_argument("--mesh", action="store_true", help="also run Allmesh in WSL and write the initial field")
    ap.add_argument("--init-only", action="store_true", help="only write the initial field (needs 0/C from Allmesh)")
    args = ap.parse_args()
    global RES
    if args.results:
        RES = Path(args.results).resolve()

    name = args.name or ("mfe280_sl_axi" + ("" if abs(args.pc_frac - 1) < 1e-9 else f"_pc{round(100 * args.pc_frac):03d}"))
    case = CFD / "cases" / name

    if args.init_only:
        info = json.loads((case / "case_info.json").read_text())
        rep = initial_fields(case, info)
        print("initial field:", json.dumps(rep))
        return

    design = json.loads((RES / "design.json").read_text())
    con = np.loadtxt(RES / "contour.csv", delimiter=",", skiprows=1)
    xc, rc = con[:, 0], con[:, 1]
    gm = gas_model(design, args.gas, args.pc_frac)
    if abs(args.pc_frac - 1) < 1e-9 and abs(gm["Tc"] - design["performance"]["Tc_core"]) > 1.0:
        print(f"warning: Tc {gm['Tc']:.1f} K differs from design.json {design['performance']['Tc_core']:.1f} K")
    gas = gm["gas"]
    block_mesh, mesh = build_mesh(args, design, gm, xc, rc)

    # turbulence inlet/ambient values
    st_in = mesh["stations"][0]
    intensity = 0.05
    k_in = 1.5 * (intensity * st_in["u"]) ** 2
    l_mix = 0.07 * design["injector"]["pitch_m"]
    w_in = math.sqrt(k_in) / (0.09 ** 0.25 * l_mix)
    rho_a = P_AMB / (gas["R"] * T_AMB)
    nu_a = mu_suth(gas, T_AMB) / rho_a
    k_a = 0.01
    w_a = k_a / (5.0 * nu_a)                      # nu_t/nu = 5 in the ambient gas
    bcd = {"p0": gm["pc"], "T0": gm["Tc"], "wall_thermal": args.wall_thermal, "intensity": intensity,
           "k_in": k_in, "omega_in": w_in, "mixing_length": l_mix, "k_amb": k_a, "omega_amb": w_a,
           "lInf": mesh["x_far"] - mesh["x_exit"], "rho_amb": rho_a}
    if args.wall_thermal == "profile":
        cp_ = np.genfromtxt(RES / "cooling_profile.csv", delimiter=",", names=True)
        idx = np.unique(np.linspace(0, len(cp_) - 1, 80).astype(int))
        bcd["Twg_table"] = [[float(cp_["x"][i]), float(cp_["Twg"][i])] for i in idx]

    # run control and cost estimates
    th = next(s for s in mesh["stations"] if s["name"] == "throat")
    c_w = math.sqrt(gas["gamma"] * gas["R"] * th["Taw"])
    dt_est = 0.4 / (c_w / th["h"] + (th["u"] + c_w) / th["dx"])
    if args.time_mode == "lts":
        # gentler ramp: the plume's starting vortex (x ~ 8 m) over-expands to ~250 K / 17 kPa and the
        # first run hit a floating-point exception when maxCo jumped from 0.1 to 0.25 at iteration 2,000
        stages = [(0.1, 2000), (0.15, 8000), (0.3, 16000), (0.5, max(args.iters, 20000))]
        write_interval = 2000
        n_steps = stages[-1][1]
    else:
        stages = [(0.1, 5e-5), (0.25, 2e-4), (0.4, 5e-3)]
        write_interval = 2.5e-4
        n_steps = stages[-1][1] / dt_est
    cost_cell = 5e-6                            # s per cell-iteration on one core (assumed, check log)
    wall_h = n_steps * mesh["cells"] * cost_cell / (0.75 * args.nprocs) / 3600
    run = {"mode": args.time_mode, "stages": stages, "write_interval": write_interval, "nprocs": args.nprocs,
           "dt_transient_est_s": dt_est, "steps": n_steps, "wall_clock_h_est": wall_h,
           "cost_assumption_s_per_cell_iter": cost_cell}

    P = design["performance"]
    info = {"case": name, "openfoam": "v2306 (ESI), /usr/lib/openfoam/openfoam2306, WSL " + args.distro,
            "args": vars(args), "gas": gas, "gas_study": {k: gm[k] for k in ("chamber_frozen", "shifting_eq",
                                                                           "frozen_eq", "candidates")},
            "bc": bcd, "mesh": mesh, "run": run,
            "reference_1d": {"ideal_chosen_gas": gm["ideal_chosen"], "shifting_eq": gm["shifting_eq"],
                             "design_json": {"pc": P["pc"], "Tc_core": P["Tc_core"], "pe": P["pe"], "Me": P["Me"],
                                             "mdot": P["mdot"], "cstar_delivered": P["cstar"],
                                             "isp_sl_delivered": P["isp_sl"], "isp_sl_ideal_uniform": P["isp_sl_ideal"],
                                             "At": P["At_m2"], "gamma_eff": P["gamma_eff"],
                                             "throttle": design["throttle"]}},
            "wedge_factor": 360.0 / args.wedge_deg}

    if case.exists() and not args.force:
        sys.exit(f"{case} exists: use --force to overwrite (or --init-only)")
    if case.exists():
        shutil.rmtree(case)
    write(case / "system" / "blockMeshDict", foam_file("dictionary", "blockMeshDict", block_mesh, "system"))
    write(case / "system" / "controlDict", control_text(info))
    write(case / "system" / "fvSchemes", schemes_text(args.time_mode == "lts"))
    write(case / "system" / "fvSolution", solution_text())
    write(case / "system" / "decomposeParDict", decompose_text(args.nprocs))
    write(case / "system" / "topoSetDict", toposet_text(mesh))
    write(case / "constant" / "thermophysicalProperties", thermo_text(gas))
    write(case / "constant" / "turbulenceProperties", turbulence_text())
    for fname, txt in field_files(info).items():
        write(case / "0.orig" / fname, txt)
    write(case / "Allmesh", ALLMESH)
    write(case / "Allrun", allrun_text(info))
    write(case / "Allclean", ALLCLEAN)
    write(case / "case_info.json", json.dumps(info, indent=2, default=float))

    ic = gm["ideal_chosen"]
    print(f"case        {case}")
    print(f"gas         {gas['kind']}: gamma {gas['gamma']:.4f}, cp {gas['cp']:.1f} J/kg/K, MW {gas['MW']:.3f}, "
          f"Sutherland As {gas['As']:.4e} Ts {gas['Ts']:.1f} K (max err {100 * gas['mu_fit_max_rel_err']:.1f} %)")
    print(f"inlet       p0 {gm['pc'] / 1e5:.1f} bar, T0 {gm['Tc']:.1f} K")
    print(f"1-D ideal   pe {ic['pe'] / 1e5:.3f} bar, Me {ic['Me']:.3f}, mdot {ic['mdot']:.1f} kg/s, "
          f"Isp_amb {ic['isp_amb']:.1f} s, Isp_vac {ic['isp_vac']:.1f} s")
    print(f"mesh        {mesh['cells']} cells, blocks {mesh['cells_by_block']}")
    for s in mesh["stations"]:
        print(f"  {s['name']:8s} x {s['x']:.4f} m  r {s['r_wall']:.4f} m  M {s['M']:.3f}  h {s['h'] * 1e6:7.1f} um  "
              f"y+ {s['yplus_est']:5.1f}  layer {s['n_layer']} cells, core {s['d_core'] * 1e3:.2f} mm, dx {s['dx'] * 1e3:.2f} mm")
    print(f"run         {args.time_mode}: {n_steps:.3g} steps, ~{wall_h:.1f} h on {args.nprocs} ranks (assumed cost); "
          f"transient dt ~ {dt_est:.2e} s")

    if args.mesh:
        busy = running_foam_jobs()
        if busy:
            print("OpenFOAM processes are running in WSL; meshing skipped:\n  " + "\n  ".join(busy))
            return
        cmd = f"bash '{wsl_path(case / 'Allmesh')}'"
        r = subprocess.run(["wsl", "-d", args.distro, "-e", "bash", "-lc", cmd], capture_output=True, text=True)
        print(r.stdout, r.stderr)
        if not (case / "0" / "C").exists():
            sys.exit("Allmesh did not write 0/C; see the logs in the case directory")
        print("initial field:", json.dumps(initial_fields(case, info)))


if __name__ == "__main__":
    main()
