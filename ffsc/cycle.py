"""Full-flow staged-combustion power balance (0-D, design point).

Ox side : LOX pump -> MOV -> ox-rich preburner (OPB, small fuel cross-feed) -> ox turbine
          -> hot-gas duct -> main injector (ox-rich gas, centre posts).
Fuel side: CH4 pump -> MFV -> regen jacket -> fuel-rich preburner (FPB, small ox cross-feed)
          -> fuel turbine -> hot-gas duct -> main injector (fuel-rich gas, annuli).

Preburner products are frozen complete combustion of the minor propellant (the major one
stays unreacted), which is the usual preliminary-design assumption for short-residence
preburners. Gases are ideal (Cantera); real-gas factors at 600-900 bar are reported for O2
and CH4 as a check, not applied.
"""

import CoolProp.CoolProp as CP
import numpy as np
from scipy.optimize import brentq

from .thermo import gas, liquid_enthalpy
from .turbopump import design_pump, design_turbine, shaft_diameter, as_dict

W_O2, W_CH4, W_CO2, W_H2O = 31.9988, 16.0425, 44.0095, 18.0153


def products(kind, m_major, m_minor):
    """Frozen complete-combustion mass fractions. kind 'ox': O2 major, CH4 minor."""
    if kind == "ox":
        n = m_minor / W_CH4
        Y = {"O2": m_major - 2 * n * W_O2, "CO2": n * W_CO2, "H2O": 2 * n * W_H2O}
    else:
        n = m_minor / W_O2 / 2
        Y = {"CH4": m_major - n * W_CH4, "CO2": n * W_CO2, "H2O": 2 * n * W_H2O}
    tot = sum(Y.values())
    if min(Y.values()) < 0:
        raise ValueError("minor propellant exceeds stoichiometric share")
    return {k: v / tot for k, v in Y.items()}


def T_from_h(Y, h, p, T_lo=200.0, T_hi=4000.0):
    """Frozen-composition temperature; returns T_lo when the mixture is colder than the
    NASA-polynomial range (gas-phase products cannot exist there anyway)."""
    g = gas()

    def f(T):
        g.TPY = T, p, Y
        return g.enthalpy_mass - h

    if f(T_lo) > 0:
        return T_lo
    return brentq(f, T_lo, T_hi, xtol=1e-3)


def preburner_T(kind, m_major, h_major, m_minor, h_minor, p):
    Y = products(kind, m_major, m_minor)
    h = (m_major * h_major + m_minor * h_minor) / (m_major + m_minor)
    return T_from_h(Y, h, p), Y, h


def gas_state(Y, T, p):
    g = gas()
    g.TPY = T, p, Y
    s, h = g.entropy_mass, g.enthalpy_mass
    R = 8314.46 / g.mean_molecular_weight

    def h_is(p_out):
        g.TPY = T, p, Y
        g.SP = s, p_out
        return g.enthalpy_mass

    g.TPY = T, p, Y
    return {"T": T, "p": p, "h": h, "s": s, "cp": g.cp_mass, "gamma": g.cp_mass / g.cv_mass,
            "R": R, "mw": g.mean_molecular_weight, "Y": Y, "h_is": h_is}


def first_root(f, lo=1.02, hi=2.6, step=0.04):
    """Lowest root of f on [lo, hi]. The shaft balance has a maximum, so the
    lower-pressure root is the design point."""
    a, fa = lo, f(lo)
    while a < hi:
        b = min(a + step, hi)
        fb = f(b)
        if fa * fb <= 0:
            return brentq(f, a, b, xtol=1e-5)
        a, fa = b, fb
    raise RuntimeError(f"turbine cannot drive the pump on [{lo}, {hi}]; best balance {fa / 1e6:.2f} MW")


def solve_minor(kind, m_major, h_major, h_minor, p, T_target):
    f = lambda m: preburner_T(kind, m_major, h_major, m, h_minor, p)[0] - T_target
    stoich = m_major / (2 * W_O2 / W_CH4) if kind == "ox" else m_major * 2 * W_O2 / W_CH4
    return brentq(f, 1e-6 * m_major, 0.5 * stoich, xtol=1e-6)


def solve_cycle(cfg, mdot_o, mdot_f, jacket):
    """jacket: dict with dp_Pa and dh_J_kg (regen heat per kg of FPB fuel), from the cooling model."""
    req, cy, tp, pr = cfg["requirements"], cfg["cycle"], cfg["turbopumps"], cfg["propellants"]
    pc = req["pc_bar"] * 1e5
    p_te = pc * (1 + cy["dp_main_inj_frac"] + cy["dp_hot_gas_duct_frac"])
    T_lox, p_lox = pr["lox"]["T_K"], pr["lox"]["p_inlet_bar"] * 1e5
    T_ch4, p_ch4 = pr["lch4"]["T_K"], pr["lch4"]["p_inlet_bar"] * 1e5
    k_inj, k_line = 1 + cy["dp_pb_inj_frac"], 1 + cy["dp_line_frac"]
    h_lox0 = liquid_enthalpy("Oxygen", T_lox, p_lox)
    h_ch4_0 = liquid_enthalpy("Methane", T_ch4, p_ch4)

    # first guesses
    m_f_opb, m_o_fpb = 0.03 * mdot_f, 0.08 * mdot_f
    PR_o, PR_f = 1.6, 1.7
    for _ in range(30):
        p_opb, p_fpb = p_te * PR_o, p_te * PR_f
        p_od = p_opb * k_inj * k_line
        p_fd = (p_fpb * k_inj + jacket["dp_Pa"]) * k_line
        ox_pump = design_pump("Oxygen", mdot_o, T_lox, p_lox, p_od, tp["ox"])
        fu_pump = design_pump("Methane", mdot_f, T_ch4, p_ch4, p_fd, tp["fuel"])
        h_lox_d = h_lox0 + ox_pump.dh_J_kg
        h_ch4_d = h_ch4_0 + fu_pump.dh_J_kg
        h_ch4_jk = h_ch4_d + jacket["dh_J_kg"]          # regen heat returned to the FPB fuel
        # ox cross-feed to the FPB needs a kick stage if the FPB sits above the LOX discharge
        p_kick = max(p_fpb * k_inj * k_line - p_od, 0.0)
        m_f_opb_new = solve_minor("ox", mdot_o - m_o_fpb, h_lox_d, h_ch4_d, p_opb, cy["T_opb_K"])
        m_o_fpb_new = solve_minor("fuel", mdot_f - m_f_opb, h_ch4_jk, h_lox_d, p_fpb, cy["T_fpb_K"])
        m_opb = mdot_o - m_o_fpb_new + m_f_opb_new
        m_fpb = mdot_f - m_f_opb_new + m_o_fpb_new
        Y_opb = products("ox", mdot_o - m_o_fpb_new, m_f_opb_new)
        Y_fpb = products("fuel", mdot_f - m_f_opb_new, m_o_fpb_new)
        gs_o = gas_state(Y_opb, cy["T_opb_K"], p_opb)
        gs_f = gas_state(Y_fpb, cy["T_fpb_K"], p_fpb)

        def balance(side, PR):
            if side == "ox":
                pd = p_te * PR * k_inj * k_line
                pump = design_pump("Oxygen", mdot_o, T_lox, p_lox, pd, tp["ox"])
                kick = m_o_fpb_new * max(p_te * PR_f * k_inj * k_line - pd, 0) / (pump.rho * 0.60)
                gs = gas_state(Y_opb, cy["T_opb_K"], p_te * PR)
                turb = design_turbine(gs, m_opb, PR, pump.N_rpm, tp["ox"], cy)
                return turb.power_W - pump.power_W - kick
            pd = (p_te * PR * k_inj + jacket["dp_Pa"]) * k_line
            pump = design_pump("Methane", mdot_f, T_ch4, p_ch4, pd, tp["fuel"])
            gs = gas_state(Y_fpb, cy["T_fpb_K"], p_te * PR)
            turb = design_turbine(gs, m_fpb, PR, pump.N_rpm, tp["fuel"], cy)
            return turb.power_W - pump.power_W

        PR_o_new = first_root(lambda x: balance("ox", x))
        PR_f_new = first_root(lambda x: balance("fuel", x))
        done = (abs(PR_o_new - PR_o) < 1e-4 and abs(PR_f_new - PR_f) < 1e-4
                and abs(m_f_opb_new - m_f_opb) < 1e-4 and abs(m_o_fpb_new - m_o_fpb) < 1e-4)
        PR_o, PR_f, m_f_opb, m_o_fpb = PR_o_new, PR_f_new, m_f_opb_new, m_o_fpb_new
        if done:
            break

    p_opb, p_fpb = p_te * PR_o, p_te * PR_f
    p_od = p_opb * k_inj * k_line
    p_fd = (p_fpb * k_inj + jacket["dp_Pa"]) * k_line
    ox_pump = design_pump("Oxygen", mdot_o, T_lox, p_lox, p_od, tp["ox"])
    fu_pump = design_pump("Methane", mdot_f, T_ch4, p_ch4, p_fd, tp["fuel"])
    m_opb = mdot_o - m_o_fpb + m_f_opb
    m_fpb = mdot_f - m_f_opb + m_o_fpb
    gs_o = gas_state(products("ox", mdot_o - m_o_fpb, m_f_opb), cy["T_opb_K"], p_opb)
    gs_f = gas_state(products("fuel", mdot_f - m_f_opb, m_o_fpb), cy["T_fpb_K"], p_fpb)
    ox_t = design_turbine(gs_o, m_opb, PR_o, ox_pump.N_rpm, tp["ox"], cy)
    fu_t = design_turbine(gs_f, m_fpb, PR_f, fu_pump.N_rpm, tp["fuel"], cy)
    p_kick = max(p_fpb * k_inj * k_line - p_od, 0.0)
    kick_W = m_o_fpb * p_kick / (ox_pump.rho * 0.60)
    d_ox, tq_ox = shaft_diameter(ox_t.power_W, ox_pump.N_rpm, tp["ox"]["shaft_stress_MPa"])
    d_fu, tq_fu = shaft_diameter(fu_t.power_W, fu_pump.N_rpm, tp["fuel"]["shaft_stress_MPa"])
    Z_o2 = CP.PropsSI("Z", "T", cy["T_opb_K"], "P", p_opb, "Oxygen")
    Z_ch4 = CP.PropsSI("Z", "T", cy["T_fpb_K"], "P", p_fpb, "Methane")

    def gs_out(gs):
        return {k: (float(v) if isinstance(v, (float, np.floating)) else v) for k, v in gs.items() if k != "h_is"}

    return {
        "p_turbine_exit_Pa": p_te, "p_opb_Pa": p_opb, "p_fpb_Pa": p_fpb,
        "p_ox_discharge_Pa": p_od, "p_fuel_discharge_Pa": p_fd, "p_kick_rise_Pa": p_kick,
        "kick_stage_power_W": kick_W,
        "PR_ox_turbine": PR_o, "PR_fuel_turbine": PR_f,
        "mdot_ox_Pa": mdot_o, "mdot_fuel": mdot_f,
        "mdot_opb": m_opb, "mdot_fpb": m_fpb, "mdot_fuel_to_opb": m_f_opb, "mdot_ox_to_fpb": m_o_fpb,
        "mr_opb": (mdot_o - m_o_fpb) / m_f_opb, "mr_fpb": m_o_fpb / (mdot_f - m_f_opb),
        "opb_gas": gs_out(gs_o), "fpb_gas": gs_out(gs_f),
        "ox_pump": as_dict(ox_pump), "fuel_pump": as_dict(fu_pump),
        "ox_turbine": as_dict(ox_t), "fuel_turbine": as_dict(fu_t),
        "ox_shaft": {"D_m": d_ox, "torque_Nm": tq_ox}, "fuel_shaft": {"D_m": d_fu, "torque_Nm": tq_fu},
        "real_gas_Z_O2_at_OPB": Z_o2, "real_gas_Z_CH4_at_FPB": Z_ch4,
        "jacket_in_T_K": fu_pump.T_out_K, "jacket_in_p_Pa": p_fd / k_line,
    }
