"""Equilibrium thermochemistry and ideal-rocket performance (CEA-style) with Cantera.

Reactant enthalpies follow the NASA CEA convention: liquid O2 at 90.17 K and
liquid CH4 at 111.643 K, corrected to the subcooled inlet temperature with CoolProp.
In a closed (staged) cycle all pump work returns to the flow through the turbines,
so the main-chamber total enthalpy equals the enthalpy of the propellants at the
pump inlets (adiabatic engine, regen heat returned to the flow).
"""

from dataclasses import dataclass, field

import cantera as ct
import CoolProp.CoolProp as CP
import numpy as np
from scipy.optimize import brentq, minimize_scalar

from . import G0

SPECIES = ["H2", "H", "O", "O2", "OH", "H2O", "HO2", "H2O2", "CH4", "CO", "CO2",
           "HCO", "CH3", "CH2", "CH", "C", "C2H4", "C2H6"]

# CEA thermo.inp assigned enthalpies of the liquids at their normal boiling points
H_LOX_NBP = -12.979e3 / 31.9988e-3     # J/kg, O2(L) at 90.17 K
H_LCH4_NBP = -89.233e3 / 16.0425e-3    # J/kg, CH4(L) at 111.643 K

_GAS = None


def gas():
    """Shared Cantera ideal-gas phase: NASA CEA thermo (200-6000 K, nasa_gas.yaml) with
    GRI-Mech 3.0 transport parameters, mixture-averaged transport."""
    global _GAS
    if _GAS is None:
        nasa = {s.name: s for s in ct.Species.list_from_file("nasa_gas.yaml")}
        gri = {s.name: s for s in ct.Species.list_from_file("gri30.yaml")}
        species = []
        for n in SPECIES:
            sp = nasa[n]
            sp.transport = gri[n].transport
            species.append(sp)
        _GAS = ct.Solution(thermo="ideal-gas", species=species, transport_model="mixture-averaged")
    return _GAS


def liquid_enthalpy(fluid, T, p):
    """CEA-basis enthalpy (J/kg) of subcooled liquid 'Oxygen' or 'Methane' at T, p."""
    base = H_LOX_NBP if fluid == "Oxygen" else H_LCH4_NBP
    dh = CP.PropsSI("H", "T", T, "P", p, fluid) - CP.PropsSI("H", "Q", 0, "P", 101325.0, fluid)
    return base + dh


def mixture_Y(of):
    return {"CH4": 1.0 / (1.0 + of), "O2": of / (1.0 + of)}


def equilibrium_hp(h, p, Y):
    """Adiabatic equilibrium at mass enthalpy h (J/kg) and pressure p. Returns the gas object."""
    g = gas()
    g.TPY = 3000.0, p, Y
    g.equilibrate("TP")                # move to a product composition first,
    g.HP = h, p                        # so the frozen T solve stays inside the NASA fits
    g.equilibrate("HP")
    return g


@dataclass
class State:
    p: float
    T: float
    h: float
    s: float
    rho: float
    u: float
    M: float
    gamma: float
    mw: float
    cp: float
    mu: float = 0.0
    k: float = 0.0

    @property
    def Pr(self):
        return self.cp * self.mu / self.k if self.k else float("nan")


@dataclass
class RocketResult:
    pc: float
    of: float
    Tc: float
    chamber: State
    throat: State
    exit: State
    cstar: float
    cf_vac: float
    isp_vac: float
    isp_sl: float
    eps: float
    pe: float
    shifting: bool
    gamma_eff: float = field(default=0.0)


def _snapshot(g, h0, shifting):
    if shifting:
        g.equilibrate("SP")
    u = np.sqrt(max(2.0 * (h0 - g.enthalpy_mass), 0.0))
    gamma = g.cp_mass / g.cv_mass
    a = np.sqrt(gamma * ct.gas_constant / g.mean_molecular_weight * g.T)
    try:
        mu, k = g.viscosity, g.thermal_conductivity
    except ct.CanteraError:
        mu, k = 0.0, 0.0
    return State(g.P, g.T, g.enthalpy_mass, g.entropy_mass, g.density, u, u / a,
                 gamma, g.mean_molecular_weight, g.cp_mass, mu, k)


def rocket(pc, of, eps, pa=101325.0, T_ox=90.17, T_fu=111.643, p_feed=5e5, shifting=True):
    """Ideal 1-D rocket performance at expansion ratio eps.

    The throat is found as the point of maximum mass flux along the isentrope,
    which holds for both shifting and frozen flow without an explicit sound speed.
    """
    h_o = liquid_enthalpy("Oxygen", T_ox, p_feed)
    h_f = liquid_enthalpy("Methane", T_fu, p_feed)
    h0 = (h_f + of * h_o) / (1.0 + of)
    g = equilibrium_hp(h0, pc, mixture_Y(of))
    s0, X0 = g.entropy_mass, g.X.copy()
    chamber = _snapshot(g, h0, False)

    def at(p):
        g.TPX = chamber.T, chamber.p, X0
        g.SP = s0, p
        return _snapshot(g, h0, shifting)

    res = minimize_scalar(lambda lp: -at(np.exp(lp)).rho * at(np.exp(lp)).u,
                          bounds=(np.log(0.4 * pc), np.log(0.7 * pc)), method="bounded",
                          options={"xatol": 1e-7})
    throat = at(np.exp(res.x))
    Gt = throat.rho * throat.u

    def area_err(lp):
        st = at(np.exp(lp))
        return Gt / (st.rho * st.u) - eps

    lpe = brentq(area_err, np.log(pc * 1e-6), np.log(throat.p * 0.999), xtol=1e-10)
    ex = at(np.exp(lpe))
    cstar = pc / Gt
    cf_vac = (Gt * ex.u + ex.p * eps) / pc
    isp_vac = cf_vac * cstar / G0
    isp_sl = isp_vac - pa * eps / (Gt * G0)
    # effective isentropic exponent reproducing pc/pt for the throat (used by 1-D cooling)
    pr = pc / throat.p
    gam = brentq(lambda gm: ((gm + 1) / 2) ** (gm / (gm - 1)) - pr, 1.05, 1.67)
    return RocketResult(pc, of, chamber.T, chamber, throat, ex, cstar, cf_vac, isp_vac,
                        isp_sl, eps, ex.p, shifting, gam)


def isp_delivered(r: RocketResult, eta_cstar, eta_cf, pa):
    """Delivered Isp from ideal results with c* and vacuum-Cf efficiencies."""
    cstar = eta_cstar * r.cstar
    cf_vac = eta_cf * r.cf_vac
    cf_amb = cf_vac - pa * r.eps / r.pc
    return {"cstar": cstar, "cf_vac": cf_vac, "cf_amb": cf_amb,
            "isp_vac": cf_vac * cstar / G0, "isp_amb": cf_amb * cstar / G0}


def frozen_mixture_state(Y, h, p):
    """Frozen-composition state at enthalpy h and pressure p (preburner products)."""
    g = gas()
    g.TPY = 800.0, p, Y
    g.HP = h, p
    return g
