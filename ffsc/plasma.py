"""Plasma-assisted combustion (PAC) screening for the preburners and the main chamber.

0-D model (Cantera, GRI-Mech 3.0 kinetics, ideal gas):

- Each combustor is a perfectly stirred reactor (PSR) at its design pressure and global O/F.
  Liquid injection cannot be expressed as a gas inlet temperature (the required enthalpy lies
  below the ideal-gas enthalpy at 0 K for the LOX-rich case), so the inlet is gas at T_gas and
  a heat sink proportional to the mass flow removes the vaporisation and sensible-heat deficit.
  On the fully burning branch the reactor then reaches the design exit temperature.
- The plasma deposits a specific energy e_p (J per kg of treated mixture) in the inlet stream.
  A fraction alpha_O goes into O-atom production at eps_O eV per atom (O2 + e -> 2 O); the rest
  heats the gas. Total enthalpy rises by e_p, so energy is conserved.
- tau_ext: shortest residence time at which the PSR still burns (continuation from the burning
  branch, then bisection). The combustor is kinetically safe when tau_design >> tau_ext.
- Breakdown: a non-equilibrium discharge needs a reduced field E/N of order (E/N)_b, so the
  voltage across a gap d is V = (E/N)_b * N * d with N = p / (k_B T).

Limitations: GRI-Mech 3.0 is not validated at 350-700 bar or for O/F 54 / 0.27; real-gas
effects (Z ~ 1.2) are ignored; the PSR is the well-mixed limit (no mixing time, no streaks).
"""

import math

import cantera as ct
import numpy as np

KB = 1.380649e-23
EV = 1.602176634e-19
NA = 6.02214076e23
MECH = "gri30.yaml"


def comp(mr):
    """CH4/O2 mole numbers for O/F by mass."""
    return {"O2": mr / 31.998, "CH4": 1.0 / 16.043}


def _sol():
    return ct.Solution(MECH)


def heat_sink(mr, p, T_design, T_gas=300.0):
    """J/kg removed from a gas-phase inlet at T_gas so that full burning gives T_design."""
    g = _sol()
    g.TPX = T_design, p, comp(mr)
    g.equilibrate("TP")
    h_eq = g.enthalpy_mass
    g.TPX = T_gas, p, comp(mr)
    return g.enthalpy_mass - h_eq


def seeded_inlet(mr, p, e_p=0.0, alpha_O=0.3, eps_O_eV=5.0, T_gas=300.0):
    """Inlet Solution with the plasma energy e_p (J/kg) split into O atoms and heat."""
    g = _sol()
    g.TPX = T_gas, p, comp(mr)
    h0 = g.enthalpy_mass
    if e_p <= 0:
        return g
    Y = dict(zip(g.species_names, g.Y))
    n_O = alpha_O * e_p / (eps_O_eV * EV * NA)          # mol O per kg mixture
    n_O = min(n_O, 2.0 * Y["O2"] / 0.031998 * 0.5)      # never dissociate more than half the O2
    Y["O2"] -= 0.5 * n_O * 0.031998
    Y["O"] = Y.get("O", 0.0) + n_O * 0.015999
    g.HPY = h0 + e_p, p, Y
    return g


def _limiting(mr):
    return "CH4" if mr > 3.99 else "O2"                  # stoichiometric O/F of CH4/O2 = 3.99


class PSR:
    """Perfectly stirred reactor with an inlet, a heat sink and a pressure-controlled outlet."""

    def __init__(self, mr, p, T_design, e_p=0.0, alpha_O=0.3, eps_O_eV=5.0, T_gas=300.0, V=1e-6, h_in=None):
        """h_in: real inlet enthalpy (J/kg) of the liquid/supercritical propellants, e.g. the cycle's
        preburner gas enthalpy. When given, the sink matches it and kinetics set the exit temperature;
        otherwise the sink is set so that equilibrium at T_design is reached."""
        self.mr, self.p, self.T_design = mr, p, T_design
        g = _sol()
        if h_in is None:
            self.dh = heat_sink(mr, p, T_design, T_gas)
            g.TPX = T_design, p, comp(mr)
            g.equilibrate("TP")                          # start on the burning branch
        else:
            g.TPX = T_gas, p, comp(mr)
            self.dh = g.enthalpy_mass - h_in
            g.TPX = T_design, p, comp(mr)                # products first: h_in lies below the reactant gas at 0 K
            g.equilibrate("TP")
            g.HP = h_in, p
            g.equilibrate("HP")
        self.inlet = seeded_inlet(mr, p, e_p, alpha_O, eps_O_eV, T_gas)
        self.lim = _limiting(mr)
        self.Y_lim_in = self.inlet.Y[self.inlet.species_index(self.lim)]
        self.burning_state = g.state
        self.r = ct.IdealGasReactor(g, energy="on", clone=False)
        self.r.volume = V
        self.tau = 1e-2
        up = ct.Reservoir(self.inlet, clone=True)
        down = _sol()
        down.TPX = T_design, p, comp(mr)                 # outlet reservoir at chamber pressure
        ex = ct.Reservoir(down, clone=False)
        env = ct.Reservoir(_sol(), clone=False)
        self.mfc = ct.MassFlowController(up, self.r, mdot=lambda t: self.r.mass / self.tau)
        ct.PressureController(self.r, ex, primary=self.mfc, K=1e-5)
        w = ct.Wall(self.r, env, A=1.0)
        w.heat_flux = lambda t: (self.r.mass / self.tau) * self.dh
        self.net = ct.ReactorNet([self.r])
        self.gas = g

    def set_state(self, state):
        self.gas.state = state
        self.r.syncState()

    def solve(self, tau):
        self.tau = tau
        self.net.initial_time = 0.0                      # restart the clock: an accumulated t makes t + h == t at tiny tau
        try:
            self.net.advance_to_steady_state()
        except Exception:                                # treated as not burning; the continuation retries closer
            return None
        Yl = self.gas.Y[self.gas.species_index(self.lim)]
        conv = 1.0 - Yl / self.Y_lim_in
        X = {k: float(self.gas[k].X[0]) for k in ("H2", "CO", "CO2", "H2O", "CH4", "O2")}
        return {"tau_s": tau, "T_K": float(self.gas.T), "conversion": float(conv), "burning": bool(conv > 0.5), "X": X}


def tau_extinction(mr, p, T_design, e_p=0.0, tau_max=0.1, tau_min=1e-8, rel=0.02, **kw):
    """Shortest burning residence time (s); None if it does not burn even at tau_max."""
    psr = PSR(mr, p, T_design, e_p=e_p, **kw)
    s = psr.solve(tau_max)
    if s is None or not s["burning"]:
        return None, s
    # Continuation down the burning branch: every step starts from the last converged burning
    # state, and the step shrinks when the reactor goes out. Large jumps near the turning point of
    # the S-curve can fall off the branch early, so no bisection between distant states.
    last_ok, last_state, step = tau_max, psr.gas.state, 0.5
    while last_ok > tau_min and step < 1.0 - rel / 2:
        psr.set_state(last_state)
        s = psr.solve(last_ok * step)
        if s is not None and s["burning"]:
            last_ok, last_state = last_ok * step, psr.gas.state
        else:
            step = math.sqrt(step)
    psr.set_state(last_state)
    return last_ok, psr.solve(last_ok)


def breakdown_voltage(p, T, gap_m, EN_Td=120.0):
    """Static breakdown voltage (V) of a gap at number density N = p / (k_B T)."""
    N = p / (KB * T)
    return EN_Td * 1e-21 * N * gap_m


def max_pressure_for_voltage(V, T, gap_m, EN_Td=120.0):
    """Highest pressure (Pa) at which a pulser of amplitude V still breaks down the gap."""
    return V / (EN_Td * 1e-21 * gap_m) * KB * T


def power_source_mass(P_W, t_s, source):
    """Mass (kg) of a power source sized by power and by energy; source has kW_per_kg, Wh_per_kg."""
    m_p = P_W / (source["kW_per_kg"] * 1e3)
    m_e = P_W * t_s / 3600.0 / source["Wh_per_kg"] if source.get("Wh_per_kg") else 0.0
    return max(m_p, m_e) * source.get("packaging_factor", 1.0)


def sweep(mr, p, T_design, e_list, **kw):
    out = []
    for e in e_list:
        t, s = tau_extinction(mr, p, T_design, e_p=e, **kw)
        out.append({"e_p_J_kg": e, "tau_ext_s": t, "state": s})
    return out


if __name__ == "__main__":
    for name, mr, p, T in (("FPB", 0.268, 697e5, 1100.0), ("OPB", 54.18, 665e5, 820.0)):
        for e in (0.0, 1e4, 1e5):
            t, s = tau_extinction(mr, p, T, e_p=e)
            print(name, e, t, s)
    print(np.round(breakdown_voltage(665e5, 820.0, 1e-3) / 1e3), "kV for 1 mm at OPB conditions")
