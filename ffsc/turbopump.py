"""Turbopump preliminary design: inducer-limited shaft speed, centrifugal pump stages,
single-stage axial reaction turbine, and shaft sizing.

US customary specific speeds (rpm, gpm, ft) are used where the rocket-pump literature
uses them (NASA SP-8107, SP-8052); everything else is SI.
"""

from dataclasses import dataclass, asdict

import CoolProp.CoolProp as CP
import numpy as np

GPM = 15850.32          # gpm per m3/s
FT = 3.28084


def specific_speed_us(N, Q, H):
    return N * np.sqrt(Q * GPM) / (H * FT) ** 0.75


def pump_efficiency(nq, Q):
    """Guelich (2010) eq. 3.28 for radial pumps, minus 0.04 for high-speed rocket service."""
    qr = 1.0 / Q
    m = 0.08 * qr ** 0.15 * (45.0 / nq) ** 0.06
    eta = 1 - 0.095 * qr ** m - 0.3 * (0.35 - np.log10(nq / 23.0)) ** 2 * qr ** 0.05
    return float(np.clip(eta - 0.04, 0.55, 0.80))


@dataclass
class PumpDesign:
    fluid: str
    mdot: float
    rho: float
    Q: float
    p_in: float
    p_out: float
    head_m: float
    npsh_a_m: float
    N_rpm: float
    stages: int
    Ns_us: float
    Nss_us: float
    nq: float
    eta: float
    power_W: float
    T_out_K: float
    dh_J_kg: float
    D2_m: float          # impeller tip diameter
    b2_m: float          # impeller exit width
    D_eye_m: float
    D_hub_m: float
    u2_m_s: float
    inducer_D_m: float
    inducer_hub_m: float
    inducer_pitch_m: float
    volute_throat_m: float
    discharge_D_m: float


def design_pump(fluid, mdot, T_in, p_in, p_out, cfg, N_rpm=None):
    rho = CP.PropsSI("D", "T", T_in, "P", p_in, fluid)
    p_vap = CP.PropsSI("P", "T", T_in, "Q", 0, fluid)
    Q = mdot / rho
    H = (p_out - p_in) / (rho * 9.80665)
    npsh = (p_in - p_vap) / (rho * 9.80665)
    nss = cfg["suction_specific_speed_us"]
    if N_rpm is None:
        N_rpm = nss * (npsh * FT) ** 0.75 / np.sqrt(Q * GPM)
    stages = cfg["stages"]
    Hs = H / stages
    Ns = specific_speed_us(N_rpm, Q, Hs)
    nq = N_rpm * np.sqrt(Q) / Hs ** 0.75
    eta = pump_efficiency(nq, Q)
    dh = (p_out - p_in) / (rho * eta)               # adiabatic pump: all shaft work stays in the flow
    power = mdot * dh
    try:
        h_out = CP.PropsSI("H", "T", T_in, "P", p_in, fluid) + dh
        T_out = CP.PropsSI("T", "H", h_out, "P", p_out, fluid)
    except ValueError:                              # O2 EOS ends at 80 MPa: heating by losses only
        cp = CP.PropsSI("C", "T", T_in, "P", p_in, fluid)
        T_out = T_in + (1 - eta) * dh / cp
    omega = N_rpm * 2 * np.pi / 60
    u2 = np.sqrt(9.80665 * Hs / cfg["head_coefficient"])
    D2 = 2 * u2 / omega
    # eye sized for an inlet flow coefficient of 0.10 over the inducer-limited speed (SP-8107)
    D_hub = 0.30 * D2
    cm1 = 0.10 * u2
    D_eye = np.sqrt(4 * Q / (np.pi * cm1) + D_hub ** 2)
    D_eye = min(D_eye, 0.75 * D2)
    cm2 = 0.08 * u2
    b2 = Q / (np.pi * D2 * cm2 * 0.9)
    ind_D = 1.02 * D_eye
    ind_hub = 0.35 * ind_D
    ind_pitch = np.pi * ind_D * np.tan(np.radians(9.0))     # 9 deg tip blade angle
    c_vol = 0.45 * np.sqrt(2 * 9.80665 * Hs)                # volute throat velocity
    vol_throat = np.sqrt(4 * Q / (np.pi * c_vol))
    v_dis = 35.0
    D_dis = np.sqrt(4 * Q / (np.pi * v_dis))
    return PumpDesign(fluid, mdot, rho, Q, p_in, p_out, H, npsh, N_rpm, stages, Ns,
                      specific_speed_us(N_rpm, Q, npsh), nq, eta, power, T_out, dh,
                      D2, b2, D_eye, D_hub, u2, ind_D, ind_hub, ind_pitch, vol_throat, D_dis)


@dataclass
class TurbineDesign:
    mdot: float
    T_in: float
    p_in: float
    p_out: float
    PR: float
    dh_is: float
    c0: float
    u_mean: float
    velocity_ratio: float
    eta: float
    power_W: float
    T_out: float
    Dm_m: float
    blade_h_m: float
    hub_D_m: float
    tip_D_m: float
    n_stator: int
    n_rotor: int
    chord_m: float
    rho_in: float


def turbine_efficiency(nu, eta_max, nu_opt=0.70):
    """Parabolic efficiency vs velocity ratio u/c0 for a 50 % reaction stage."""
    return float(max(eta_max * (1 - ((nu - nu_opt) / nu_opt) ** 2), 0.2))


def design_turbine(gas_state, mdot, PR, N_rpm, cfg, cycle_cfg):
    """gas_state: dict with Cantera-derived cp, gamma, R, T_in, p_in, s, h and a
    callable 'h_is(p_out)' returning isentropic outlet enthalpy (frozen)."""
    p_in, T_in = gas_state["p"], gas_state["T"]
    p_out = p_in / PR
    dh_is = gas_state["h"] - gas_state["h_is"](p_out)
    c0 = np.sqrt(2 * dh_is)
    omega = N_rpm * 2 * np.pi / 60
    u_tip_max = cfg["turbine_tip_speed_max_m_s"]
    rho_in = p_in / (gas_state["R"] * T_in)
    c_ax = 0.45 * c0 + 60.0
    area = mdot / (rho_in * 0.85 * c_ax)            # annulus at rotor exit (expanded gas)
    # tip-clearance loss for short blades: about 1.5 x clearance/height (Ainley-type estimate)
    clearance = cycle_cfg.get("tip_clearance_mm", 0.25) * 1e-3

    def stage(nu):
        u = nu * c0
        Dm = 2 * u / omega
        h = area / (np.pi * Dm)
        ok = h / Dm <= 0.25 and u + 0.5 * h * omega <= u_tip_max
        eta = turbine_efficiency(nu, cycle_cfg["eta_turbine_max"]) * (1 - 1.5 * clearance / h)
        return eta, u, Dm, h, ok

    # dense preburner gas gives short blades, so the best mean speed is often below u/c0 = 0.7
    cands = [stage(nu) for nu in np.linspace(0.30, 0.85, 56)]
    feasible = [c for c in cands if c[4]] or cands
    eta, u, Dm, h, _ = max(feasible, key=lambda c: c[0])
    nu = u / c0
    power = mdot * eta * dh_is
    T_out = T_in - eta * dh_is / gas_state["cp"]
    chord = max(0.6 * h, 0.012)
    n_rot = int(np.ceil(np.pi * Dm / (0.8 * chord)))
    n_st = n_rot - 7 if n_rot > 20 else n_rot - 3      # avoid common factors with the rotor
    return TurbineDesign(mdot, T_in, p_in, p_out, PR, dh_is, c0, u, nu, eta, power, T_out,
                         Dm, h, Dm - h, Dm + h, n_st, n_rot, chord, rho_in)


def shaft_diameter(power_W, N_rpm, tau_allow_MPa):
    torque = power_W / (N_rpm * 2 * np.pi / 60)
    return (16 * torque / (np.pi * tau_allow_MPa * 1e6)) ** (1 / 3), torque


def as_dict(obj):
    return {k: (float(v) if isinstance(v, (np.floating, float)) else v) for k, v in asdict(obj).items()}
