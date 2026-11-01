"""Design-point pipeline: performance -> contour -> coupled cooling/cycle -> injector,
preburners, ducts, bolted joints, throttle check. Writes results/design.json and CSVs."""

import csv
import json
import time
from pathlib import Path

import numpy as np

from . import G0, ROOT, load_config
from . import cooling
from .cycle import solve_cycle
from .injector import design_injector
from .mass import tca_mass
from .materials import yield_MPa
from .nozzle import build_contour, separation_check
from .structures import size_joint, wall_thickness, duct_diameter
from .thermo import rocket, isp_delivered


def stream_split(mr, phi, mr_wall):
    """Core mixture ratio that keeps the overall O/F when a mass share phi runs at mr_wall."""
    mf, mo = 1 / (1 + mr), mr / (1 + mr)
    mfw, mow = phi / (1 + mr_wall), phi * mr_wall / (1 + mr_wall)
    return (mo - mow) / (mf - mfw)


def performance(cfg, pc=None, eps=None, mr=None, phi=None, mr_wall=None, pa=None):
    req, eff, inj, pr = cfg["requirements"], cfg["efficiencies"], cfg["injector"], cfg["propellants"]
    pc = pc or req["pc_bar"] * 1e5
    eps = eps or cfg["nozzle"]["expansion_ratio"]
    mr = mr or req["mixture_ratio"]
    phi = inj["bl_mass_fraction"] if phi is None else phi
    mr_wall = mr_wall or inj["bl_mixture_ratio"]
    pa = req["p_ambient_Pa"] if pa is None else pa
    kw = dict(T_ox=pr["lox"]["T_K"], T_fu=pr["lch4"]["T_K"], p_feed=pr["lox"]["p_inlet_bar"] * 1e5)
    mr_core = stream_split(mr, phi, mr_wall) if phi > 0 else mr
    core = rocket(pc, mr_core, eps, pa, **kw)
    wall = rocket(pc, mr_wall, eps, pa, **kw) if phi > 0 else core
    uni = rocket(pc, mr, eps, pa, **kw)
    dc = isp_delivered(core, eff["eta_cstar"], eff["eta_cf"], pa)
    dw = isp_delivered(wall, eff["eta_cstar"], eff["eta_cf"], pa)
    du = isp_delivered(uni, eff["eta_cstar"], eff["eta_cf"], pa)
    mix = lambda k: (1 - phi) * dc[k] + phi * dw[k]
    out = {"pc": pc, "eps": eps, "mr": mr, "mr_core": mr_core, "mr_wall": mr_wall, "phi": phi,
           "isp_sl": mix("isp_amb"), "isp_vac": mix("isp_vac"), "cstar": mix("cstar"),
           "isp_sl_uniform": du["isp_amb"], "isp_vac_uniform": du["isp_vac"],
           "isp_sl_ideal": uni.isp_sl, "isp_vac_ideal": uni.isp_vac,
           "Tc_core": core.Tc, "Tc_wall": wall.Tc, "pe": core.pe, "Me": core.exit.M,
           "gamma_eff": core.gamma_eff}
    return out, core, wall


def design(cfg=None, n_iter=2, verbose=True, write=True, out_dir=None):
    t0 = time.time()
    cfg = cfg or load_config()
    req = cfg["requirements"]
    F = req["thrust_sl_kN"] * 1e3
    pc = req["pc_bar"] * 1e5
    pa = req["p_ambient_Pa"]
    perf, core, wall = performance(cfg)
    mdot = F / (perf["isp_sl"] * G0)
    mr = req["mixture_ratio"]
    mdot_o, mdot_f = mdot * mr / (1 + mr), mdot / (1 + mr)
    At = mdot * perf["cstar"] / pc
    contour = build_contour(At, perf["eps"], cfg["chamber"], cfg["nozzle"]["bell_fraction"])
    if verbose:
        print(f"[perf] Isp SL {perf['isp_sl']:.1f} s, vac {perf['isp_vac']:.1f} s, mdot {mdot:.1f} kg/s, "
              f"Dt {2 * contour.Rt * 1e3:.1f} mm, De {2 * contour.Re * 1e3:.0f} mm")

    cc = dict(cfg["cooling"])
    cc["zones"] = [dict(z) for z in cfg["cooling"]["zones"]]
    i_j = np.argmax((contour.x > contour.x_throat) & (contour.area_ratio >= cc["eps_joint"]))
    cc["zones"][0]["x_end"] = float(contour.x[i_j])
    cc["zones"][1]["x_end"] = float(contour.x[-1]) + 1.0
    cc["R_up_over_Rt"] = cfg["chamber"]["R_up_over_Rt"]
    cc["R_dn_over_Rt"] = cfg["chamber"]["R_dn_over_Rt"]

    jacket = {"dp_Pa": 80e5, "dh_J_kg": 600e3}
    for it in range(n_iter):
        cyc = solve_cycle(cfg, mdot_o, mdot_f, jacket)
        m_cool = cc["coolant_fraction"] * (mdot_f - cyc["mdot_fuel_to_opb"])
        cool = cooling.solve_split(contour, core, wall, cc, m_cool, cyc["jacket_in_T_K"],
                                   cyc["jacket_in_p_Pa"], cfg["efficiencies"]["eta_cstar"])
        jacket = {"dp_Pa": cool["dp_jacket_Pa"], "dh_J_kg": cool["Q_total_W"] / (mdot_f - cyc["mdot_fuel_to_opb"])}
        if verbose:
            print(f"[iter {it}] jacket dP {jacket['dp_Pa'] / 1e5:.1f} bar, Q {cool['Q_total_W'] / 1e6:.1f} MW, "
                  f"T_out {cool['T_out_K']:.0f} K, Twg max {cool['Twg_max_K']:.0f} K, "
                  f"p_fd {cyc['p_fuel_discharge_Pa'] / 1e5:.0f} bar ({time.time() - t0:.0f} s)")
    cyc = solve_cycle(cfg, mdot_o, mdot_f, jacket)

    # Closeout (Inconel 718). Coolant pressure inside closed channels is self-equilibrated:
    # it bends the closeout across one channel width and loads the ribs in tension.
    # Global hoop load comes only from the gas pressure on the liner.
    sig = cc["closeout_allow_MPa"] * 1e6
    gam = perf["gamma_eff"]
    p_gas = pc / (1 + 0.5 * (gam - 1) * cool["M"] ** 2) ** (gam / (gam - 1))
    r_co = cool["r"] + np.array([cc["zones"][z]["t_hot_mm"] * 1e-3 for z in cool["zone"]]) + cool["H"]
    t_plate = cool["W"] * np.sqrt(1.2 * cool["p"] / (2 * 1.6 * sig))      # Inconel at ~300 K: 1.6 x working
    t_hoop = 1.2 * p_gas * r_co / sig
    t_close = np.maximum.reduce([np.full_like(t_hoop, 1.0e-3), t_plate, t_hoop])
    rib_mat = [cc["zones"][z]["material"] for z in cool["zone"]]
    rib_stress = 1.2 * cool["p"] * cool["W"] / cool["rib"] / 1e6
    rib_allow = np.array([yield_MPa(m, 0.5 * (a + b)) / 1.25 for m, a, b in zip(rib_mat, cool["Twc"], cool["Tb"])])
    cool["t_closeout"] = t_close
    r_jacket = r_co + t_close                       # outer surface of the chamber/nozzle wall
    tca = tca_mass(cool, cfg, t_close)

    # injector and gas densities at the main-injector manifolds (ideal gas)
    p_man = pc * (1 + cfg["cycle"]["dp_main_inj_frac"])
    og, fg = cyc["opb_gas"], cyc["fpb_gas"]
    rho_ox = p_man / (og["R"] * cyc["ox_turbine"]["T_out"])
    rho_fu = p_man / (fg["R"] * cyc["fuel_turbine"]["T_out"])
    inj = design_injector(cfg, contour.Rc, pc, cyc["mdot_opb"], rho_ox, cyc["mdot_fpb"], rho_fu,
                          cfg["injector"]["bl_mass_fraction"])

    # preburners: residence-time sizing, L/D 1.6
    def preburner(m, gas_R, T, p, tau):
        V = m * tau / (p / (gas_R * T))
        D = (4 * V / (np.pi * 1.6)) ** (1 / 3)
        return {"volume_m3": V, "D_m": D, "L_m": 1.6 * D, "tau_s": tau, "p_Pa": p, "T_K": T,
                "wall_t_m": wall_thickness(p, D / 2, 520.0)}
    opb = preburner(cyc["mdot_opb"], og["R"], og["T"], cyc["p_opb_Pa"], 0.003)
    fpb = preburner(cyc["mdot_fpb"], fg["R"], fg["T"], cyc["p_fpb_Pa"], 0.004)

    # ducts
    rho_lox, rho_ch4 = cyc["ox_pump"]["rho"], cyc["fuel_pump"]["rho"]
    rho_jk_out = cooling.ch4_props(cool["T_out_K"], cool["p_out_Pa"])[0]
    ducts = {
        "lox_inlet": duct_diameter(mdot_o, rho_lox, 12.0),
        "ch4_inlet": duct_diameter(mdot_f, rho_ch4, 12.0),
        "lox_discharge": duct_diameter(mdot_o - cyc["mdot_ox_to_fpb"], rho_lox, 35.0),
        "ch4_discharge": duct_diameter(m_cool, rho_ch4, 35.0),
        "jacket_outlet": duct_diameter(m_cool * (1 - cc["nozzle_circuit_fraction"]), rho_jk_out, 40.0),
        "nozzle_return": duct_diameter(m_cool * cc["nozzle_circuit_fraction"], rho_jk_out, 40.0),
        "fpb_feed": duct_diameter(m_cool * (1 - cc["nozzle_circuit_fraction"]), rho_jk_out, 40.0),   # circuit A only; B has its own port
        "ox_crossfeed": duct_diameter(cyc["mdot_ox_to_fpb"], rho_lox, 30.0),
        "fuel_crossfeed": duct_diameter(cyc["mdot_fuel_to_opb"], rho_ch4, 30.0),
        "ox_hot_gas": duct_diameter(cyc["mdot_opb"], cyc["p_turbine_exit_Pa"] / (og["R"] * cyc["ox_turbine"]["T_out"]), 140.0),
        "fuel_hot_gas": duct_diameter(cyc["mdot_fpb"], cyc["p_turbine_exit_Pa"] / (fg["R"] * cyc["fuel_turbine"]["T_out"]), 140.0),
    }

    # bolted joints
    p_te = cyc["p_turbine_exit_Pa"]
    joints = [
        size_joint("lox_inlet", cfg["propellants"]["lox"]["p_inlet_bar"] * 1e5 * 2.0, ducts["lox_inlet"] + 0.02, cfg, d_min_mm=10),
        size_joint("ch4_inlet", cfg["propellants"]["lch4"]["p_inlet_bar"] * 1e5 * 2.0, ducts["ch4_inlet"] + 0.02, cfg, d_min_mm=10),
        size_joint("lox_discharge", cyc["p_ox_discharge_Pa"], ducts["lox_discharge"] + 0.015, cfg, "Inconel 718"),
        size_joint("ch4_discharge", cyc["p_fuel_discharge_Pa"], ducts["ch4_discharge"] + 0.015, cfg, "Inconel 718"),
        size_joint("fpb_feed", cool["p_out_Pa"], ducts["fpb_feed"] + 0.015, cfg, "Inconel 718"),
        size_joint("nozzle_return", cool["p_out_Pa"], ducts["nozzle_return"] + 0.012, cfg, "Inconel 718"),
        size_joint("ox_crossfeed", cyc["p_ox_discharge_Pa"] + cyc["p_kick_rise_Pa"], ducts["ox_crossfeed"] + 0.01, cfg, "Inconel 718", d_min_mm=8),
        size_joint("fuel_crossfeed", cyc["p_fuel_discharge_Pa"], ducts["fuel_crossfeed"] + 0.01, cfg, "Inconel 718", d_min_mm=8),
        size_joint("ox_hot_gas", p_te, ducts["ox_hot_gas"] + 0.02, cfg, "Inconel 718"),
        size_joint("fuel_hot_gas", p_te, ducts["fuel_hot_gas"] + 0.02, cfg, "Inconel 718"),
        size_joint("injector_chamber", p_man, 2 * contour.Rc + 0.03, cfg, "Inconel 718",
                   wall_r=max(contour.Rc + 0.032, r_jacket[0])),          # injector body wall / chamber closeout
        size_joint("nozzle_joint", float(np.interp(cool["x_joint"], cool["x"], p_gas)),
                   2 * (np.interp(cool["x_joint"], contour.x, contour.r) + 0.02), cfg, "A286", n_min=24, d_min_mm=12,
                   wall_r=float(np.interp(cool["x_joint"] + 0.06, cool["x"], r_jacket)),   # nozzle flares below the joint
                   extra_axial_N=4 * cc["side_load_frac"] * F * 0.5 * (contour.x[-1] - cool["x_joint"])
                   / (2 * np.interp(cool["x_joint"], contour.x, contour.r) + 0.1)),
        size_joint("coolant_jumper", cyc["p_fuel_discharge_Pa"], 0.045, cfg, "Inconel 718", d_min_mm=8),
        size_joint("igniter", max(cyc["p_opb_Pa"], cyc["p_fpb_Pa"]), 0.020, cfg, "Inconel 718", n_min=4),
    ]

    # internal casing joints: bolted if an ISO pattern fits, otherwise welded/integral
    def casing_joint(name, p, D):
        try:
            return {**size_joint(name, p, D, cfg, "Inconel 718", n_min=12, d_min_mm=10), "welded": False}
        except ValueError as err:
            return {"name": name, "welded": True, "p_meop_Pa": p, "D_seal_m": D, "reason": str(err)}
    op, fp = cyc["ox_pump"], cyc["fuel_pump"]
    ot, ft = cyc["ox_turbine"], cyc["fuel_turbine"]
    internal = [
        casing_joint("ox_pump_inlet_housing", cfg["propellants"]["lox"]["p_inlet_bar"] * 1e5 * 3, op["inducer_D_m"] + 0.04),
        casing_joint("ox_pump_volute_cover", cyc["p_ox_discharge_Pa"], op["D2_m"] + 0.02),
        casing_joint("fuel_pump_inlet_housing", cfg["propellants"]["lch4"]["p_inlet_bar"] * 1e5 * 3, fp["inducer_D_m"] + 0.04),
        casing_joint("fuel_pump_volute_cover", cyc["p_fuel_discharge_Pa"], fp["D2_m"] + 0.02),
        casing_joint("ox_turbine_housing", cyc["p_opb_Pa"], ot["tip_D_m"] + 0.03),
        casing_joint("fuel_turbine_housing", cyc["p_fpb_Pa"], ft["tip_D_m"] + 0.03),
        casing_joint("ox_bearing_housing", cyc["p_turbine_exit_Pa"] * 0.1, cyc["ox_shaft"]["D_m"] * 2.6),
        casing_joint("fuel_bearing_housing", cyc["p_turbine_exit_Pa"] * 0.1, cyc["fuel_shaft"]["D_m"] * 2.6),
    ]
    # A turbine-housing bolt circle under the exhaust collector cannot be reached with a
    # wrench: the collector tube (radius r_c) wraps the rotor at about tip + 0.55 r_c.
    for j in internal:
        side = j["name"].split("_")[0]
        if j["name"].endswith("turbine_housing") and not j["welded"]:
            r_c = ducts[f"{side}_hot_gas"] / 2 + 0.008
            collector_inner = cyc[f"{side}_turbine"]["tip_D_m"] / 2 + 0.55 * r_c - r_c
            if j["bcd_m"] / 2 + j["across_flats_m"] > collector_inner:
                j.update(welded=True, reason="bolt circle lies under the turbine exhaust collector (no tool access)")

    # throttle: Pc scales with thrust at fixed O/F (first-order), separation at sea level
    throttle = []
    for frac in [1.0, 0.8, 0.6, 0.4]:
        pf, cf_, _ = performance(cfg, pc=pc * frac)
        sep = separation_check(cf_.pe, pa, cf_.exit.M)
        throttle.append({"throttle": frac, "pc_bar": pc * frac / 1e5, "isp_sl": pf["isp_sl"],
                         "pe_bar": cf_.pe / 1e5, **sep})

    res = {
        "name": cfg["name"], "config": cfg,
        "performance": {**perf, "thrust_sl_N": F, "thrust_vac_N": F + pa * contour.Re ** 2 * np.pi,
                        "mdot": mdot, "mdot_ox": mdot_o, "mdot_fuel": mdot_f, "At_m2": At,
                        "bl_isp_penalty_s": perf["isp_sl_uniform"] - perf["isp_sl"]},
        "geometry": {"Rt_m": contour.Rt, "Rc_m": contour.Rc, "Re_m": contour.Re, "L_cyl_m": contour.L_cyl,
                     "L_conv_m": contour.L_conv, "L_nozzle_m": contour.L_noz, "x_throat_m": contour.x_throat,
                     "x_exit_m": float(contour.x[-1]), "theta_n_deg": contour.theta_n, "theta_e_deg": contour.theta_e,
                     "V_chamber_m3": contour.V_chamber, "x_joint_m": cool["x_joint"],
                     "eps_joint": cc["eps_joint"]},
        "cycle": cyc,
        "cooling": {k: (float(v) if isinstance(v, (float, np.floating)) else v) for k, v in cool.items()
                    if not isinstance(v, np.ndarray)} | {"closeout_t_max_m": float(t_close.max()),
                    "closeout_t_chamber_m": float(t_close[0]), "closeout_t_exit_m": float(t_close[-1]),
                    "rib_stress_ratio_max": float((rib_stress / rib_allow).max())},
        "injector": inj, "opb": opb, "fpb": fpb, "ducts": ducts, "joints": joints,
        "internal_joints": internal, "throttle": throttle, "tca_mass": tca,
        "runtime_s": time.time() - t0,
    }
    if write:
        out = Path(out_dir) if out_dir else ROOT / "results"
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "design.json", "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, default=_jsonable)
        with open(out / "contour.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["x_m", "r_m"])
            w.writerows(zip(contour.x, contour.r))
        cols = ["x", "r", "s", "M", "zone", "N", "W", "rib", "H", "H_sized", "q", "h_g", "h_c", "Taw", "Twg", "Twc",
                "Tb", "p", "v", "Re", "sigma_liner", "liner_allow"]
        t_hot = np.array([cc["zones"][z]["t_hot_mm"] * 1e-3 for z in cool["zone"]])
        with open(out / "cooling_profile.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols + ["t_hot", "t_closeout", "rib_stress_MPa", "rib_allow_MPa"])
            for i in range(len(cool["x"])):
                w.writerow([float(cool[c][i]) for c in cols] + [t_hot[i], t_close[i], rib_stress[i], rib_allow[i]])
    if verbose:
        print(f"[done] {time.time() - t0:.0f} s")
    return res, contour, cool


def _jsonable(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))
