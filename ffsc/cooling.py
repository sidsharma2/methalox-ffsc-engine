"""1-D regenerative cooling of the thrust chamber with supercritical methane.

Gas side: Bartz (1957) with the sigma property correction and recovery temperature,
evaluated with the near-wall (boundary-layer) mixture ratio when the injector outer
row is biased fuel-rich. Wall: 1-D conduction through the hot wall, ribs as fins.
Coolant side: Gnielinski with a Haaland rough-wall friction factor and the Norris
roughness enhancement, properties from CoolProp (HEOS methane).

Circuit: split flow from an inlet manifold at the liner joint. Circuit A runs upstream
through the copper chamber to the injector-end manifold; circuit B runs downstream
through the Inconel nozzle to the exit manifold and returns by duct. The coldest
coolant therefore meets the throat.

Channel height is sized station by station (pass 1) to the largest value that keeps the
hot wall at its zone target, smoothed conservatively, then re-evaluated with the fixed
profile (pass 2). The sized profile drives the PicoGK chamber geometry.
"""

from dataclasses import dataclass, asdict

import CoolProp.CoolProp as CP
import numpy as np
from scipy.optimize import brentq

from .materials import MATERIALS, yield_MPa
from .nozzle import mach_from_area

_AS = CP.AbstractState("HEOS", "Methane")


def ch4_props(T, p):
    _AS.update(CP.PT_INPUTS, p, T)
    return _AS.rhomass(), _AS.cpmass(), _AS.viscosity(), _AS.conductivity(), _AS.hmass()


def ch4_T_from_h(h, p):
    _AS.update(CP.HmassP_INPUTS, h, p)
    return _AS.T()


def friction_haaland(Re, rel_rough):
    return (-1.8 * np.log10((rel_rough / 3.7) ** 1.11 + 6.9 / Re)) ** -2


def nusselt(Re, Pr, f, f_smooth, Pr_wall):
    nu = (f_smooth / 8) * (Re - 1000) * Pr / (1 + 12.7 * np.sqrt(f_smooth / 8) * (Pr ** (2 / 3) - 1))
    rough = min(f / f_smooth, 4.0) ** 0.68                 # Norris (1971)
    return nu * rough * (Pr / Pr_wall) ** 0.11


@dataclass
class Zone:
    name: str
    material: str
    x_end: float
    t_hot: float
    w_max: float
    rib_min: float
    rib_max: float
    Twg_target: float
    h_min: float
    h_max: float


def channel_layout(r_floor, zone, n_base):
    """Channel count (base * 2^k), width and rib width at a station."""
    n = n_base
    while 2 * np.pi * r_floor / n - zone.w_max > zone.rib_max:
        n *= 2
    pitch = 2 * np.pi * r_floor / n
    w = min(zone.w_max, pitch - zone.rib_min)
    return n, w, pitch - w


def _base_count(r_floor, zone):
    n = int(2 * np.pi * r_floor / (zone.w_max + zone.rib_min))
    return n - n % 8


def resample(contour, n=400):
    s = np.concatenate([[0], np.cumsum(np.hypot(np.diff(contour.x), np.diff(contour.r)))])
    si = np.linspace(0, s[-1], n)
    return np.interp(si, s, contour.x), np.interp(si, s, contour.r), si


class Jacket:
    """Station geometry, gas-side boundary conditions and the coolant march."""

    def __init__(self, contour, rk_core, rk_wall, cfg, eta_cstar, n_stations=400):
        self.x, self.r, self.s = resample(contour, n_stations)
        self.cfg = cfg
        Rt, xt = contour.Rt, contour.x_throat
        self.Rt = Rt
        gam = rk_core.gamma_eff
        self.gam = gam
        wall = rk_wall.chamber
        self.T0 = eta_cstar ** 2 * wall.T
        Dt = 2 * Rt
        rc_throat = 0.5 * (cfg.get("R_up_over_Rt", 1.5) + cfg.get("R_dn_over_Rt", 0.382)) * Rt
        self.bartz0 = (cfg.get("bartz_factor", 1.0) * 0.026 / Dt ** 0.2
                       * (wall.mu ** 0.2 * wall.cp / wall.Pr ** 0.6)
                       * (rk_core.pc / (eta_cstar * rk_core.cstar)) ** 0.8 * (Dt / rc_throat) ** 0.1)
        rec = wall.Pr ** (1 / 3)
        self.M = np.array([mach_from_area((ri / Rt) ** 2, gam, xi > xt) for ri, xi in zip(self.r, self.x)])
        self.fac = 1 + 0.5 * (gam - 1) * self.M ** 2
        self.Taw = self.T0 * (1 + rec * 0.5 * (gam - 1) * self.M ** 2) / self.fac
        self.p_gas = rk_core.pc / self.fac ** (gam / (gam - 1))

        self.zones = [Zone(z["name"], z["material"], z["x_end"], z["t_hot_mm"] * 1e-3, z["w_max_mm"] * 1e-3,
                           z["rib_min_mm"] * 1e-3, z["rib_max_mm"] * 1e-3, z["Twg_target_K"],
                           z["h_min_mm"] * 1e-3, z["h_max_mm"] * 1e-3) for z in cfg["zones"]]
        self.zid = np.array([next(i for i, z in enumerate(self.zones) if xi <= z.x_end + 1e-9) for xi in self.x])
        self.i_joint = int(np.argmax(self.zid == 1))
        self.n_base = [_base_count(Rt + self.zones[0].t_hot, self.zones[0]),
                       _base_count(self.r[self.i_joint] + self.zones[1].t_hot, self.zones[1])]
        n = len(self.x)
        self.N = np.zeros(n, int); self.W = np.zeros(n); self.RIB = np.zeros(n)
        for i in range(n):
            z = self.zones[self.zid[i]]
            self.N[i], self.W[i], self.RIB[i] = channel_layout(self.r[i] + z.t_hot, z, self.n_base[self.zid[i]])
        self.rough = cfg["roughness_um"] * 1e-6

    def station(self, i, H, Tb, p, mdot):
        z = self.zones[self.zid[i]]
        kw = MATERIALS[z.material]["k"]
        W, RIB, N = self.W[i], self.RIB[i], self.N[i]
        rho, cp, mu, kc, _ = ch4_props(Tb, p)
        A = N * W * H
        v = mdot / (rho * A)
        Dh = 2 * W * H / (W + H)
        Re = rho * v * Dh / mu
        Pr = cp * mu / kc
        f = friction_haaland(Re, self.rough / Dh)
        fs = friction_haaland(Re, 0.0)
        ag = (self.Rt / self.r[i]) ** 1.8                      # (At/A)^0.9
        fac, Taw, T0 = self.fac[i], self.Taw[i], self.T0

        def resid(Twg):
            sig = 1 / ((0.5 * Twg / T0 * fac + 0.5) ** 0.68 * fac ** 0.12)
            hg = self.bartz0 * ag * sig
            q = hg * (Taw - Twg)
            Twc = Twg - q * z.t_hot / kw
            _, cpw, muw, kcw, _ = ch4_props(max(Twc, Tb + 0.1), p)
            hc = kc / Dh * nusselt(Re, Pr, f, fs, cpw * muw / kcw)
            mfin = np.sqrt(2 * hc / (kw * RIB))
            eta_f = np.tanh(mfin * H) / (mfin * H)
            hc_eff = hc * (W + 2 * eta_f * H) / (W + RIB)
            return q - hc_eff * (Twc - Tb), hg, q, Twc, hc

        Twg = brentq(lambda t: resid(t)[0], Tb + 1.0, Taw - 1.0, xtol=0.05)
        _, hg, q, Twc, hc = resid(Twg)
        return dict(Twg=Twg, hg=hg, q=q, Twc=Twc, hc=hc, v=v, Re=Re, f=f, Dh=Dh, rho=rho, A=A)

    def _size(self, i, Tb, p, mdot):
        z = self.zones[self.zid[i]]
        st = self.station(i, z.h_min, Tb, p, mdot)
        if st["Twg"] > z.Twg_target:
            return z.h_min
        if self.station(i, z.h_max, Tb, p, mdot)["Twg"] <= z.Twg_target:
            return z.h_max
        lo, hi = z.h_min, z.h_max
        for _ in range(16):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if self.station(i, mid, Tb, p, mdot)["Twg"] <= z.Twg_target else (lo, mid)
        return lo

    def march(self, idx, mdot, T_in, p_in, H=None):
        """March the coolant over station indices idx (in flow order)."""
        out = {k: {} for k in ["h_g", "h_c", "q", "Twg", "Twc", "Tb", "p", "v", "Re", "H", "sigma_liner", "liner_allow"]}
        Tb, p = T_in, p_in
        hb = ch4_props(Tb, p)[4]
        rho_prev = None
        for n_step, i in enumerate(idx):
            Hi = H[i] if H is not None else self._size(i, Tb, p, mdot)
            st = self.station(i, Hi, Tb, p, mdot)
            ds = abs(self.s[idx[n_step + 1]] - self.s[i]) if n_step + 1 < len(idx) else 0.0
            hb += st["q"] * 2 * np.pi * self.r[i] * ds / mdot
            p -= st["f"] * ds / st["Dh"] * 0.5 * st["rho"] * st["v"] ** 2
            if rho_prev:
                p -= max((mdot / st["A"]) ** 2 * (1 / st["rho"] - 1 / rho_prev), 0.0)
            rho_prev = st["rho"]
            if n_step + 1 < len(idx) and self.N[idx[n_step + 1]] != self.N[i]:
                p -= 0.3 * 0.5 * st["rho"] * st["v"] ** 2            # bifurcation loss
            Tb = ch4_T_from_h(hb, p)
            z = self.zones[self.zid[i]]
            out["sigma_liner"][i] = 0.5 * (p - self.p_gas[i]) * (self.W[i] / z.t_hot) ** 2 / 1e6
            out["liner_allow"][i] = yield_MPa(z.material, st["Twg"]) / 1.25
            for ko, ks in [("h_g", "hg"), ("h_c", "hc"), ("q", "q"), ("Twg", "Twg"), ("Twc", "Twc"), ("v", "v"), ("Re", "Re")]:
                out[ko][i] = st[ks]
            out["Tb"][i], out["p"][i], out["H"][i] = Tb, p, Hi
        return out, Tb, p


def smooth_conservative(H, window=9):
    """Running minimum then running mean: never taller than any sized value nearby."""
    n = len(H)
    hm = np.array([H[max(0, i - window):min(n, i + window + 1)].min() for i in range(n)])
    pad = np.pad(hm, window // 2, mode="edge")
    return np.minimum(np.convolve(pad, np.ones(window) / window, mode="valid")[:n], H)


def solve_split(contour, rk_core, rk_wall, cfg, mdot_total, T_in, p_in, eta_cstar):
    """Size and solve both circuits. Returns station arrays and a summary."""
    jk = Jacket(contour, rk_core, rk_wall, cfg, eta_cstar)
    n, ij = len(jk.x), jk.i_joint
    phi_b = cfg["nozzle_circuit_fraction"]
    idx_a = list(range(ij - 1, -1, -1))           # joint -> injector
    idx_b = list(range(ij, n))                    # joint -> exit
    H = np.zeros(n)
    for idx, m in [(idx_a, (1 - phi_b) * mdot_total), (idx_b, phi_b * mdot_total)]:
        o, _, _ = jk.march(idx, m, T_in, p_in)
        for i in idx:
            H[i] = o["H"][i]
    H_sized = H.copy()
    H = np.concatenate([smooth_conservative(H[:ij]), smooth_conservative(H[ij:])])
    oa, Ta, pa = jk.march(idx_a, (1 - phi_b) * mdot_total, T_in, p_in, H)
    ob, Tb_, pb = jk.march(idx_b, phi_b * mdot_total, T_in, p_in, H)
    arr = {k: np.array([{**oa[k], **ob[k]}[i] for i in range(n)]) for k in oa}
    # outlets mix at the FPB feed; the higher-pressure circuit is orificed down
    p_out = min(pa, pb)
    h_mix = (1 - phi_b) * ch4_props(Ta, pa)[4] + phi_b * ch4_props(Tb_, pb)[4]
    T_mix = ch4_T_from_h(h_mix, p_out)
    Q = float(np.trapezoid(arr["q"] * 2 * np.pi * jk.r, jk.s))
    return {"x": jk.x, "r": jk.r, "s": jk.s, "M": jk.M, "Taw": jk.Taw, "N": jk.N, "W": jk.W, "rib": jk.RIB,
            "zone": jk.zid, "H_sized": H_sized, **arr,
            "i_joint": ij, "x_joint": float(jk.x[ij]), "n_base": jk.n_base,
            "zones": [asdict(z) for z in jk.zones],
            "Q_total_W": Q, "T_out_A_K": Ta, "T_out_B_K": Tb_, "p_out_A_Pa": pa, "p_out_B_Pa": pb,
            "T_out_K": T_mix, "p_out_Pa": p_out, "dp_jacket_Pa": p_in - p_out,
            "Twg_max_K": float(arr["Twg"].max()), "q_max_W_m2": float(arr["q"].max()),
            "liner_stress_ratio_max": float((arr["sigma_liner"] / arr["liner_allow"]).max()),
            "Twg_margin_K": float(min(z.Twg_target - arr["Twg"][jk.zid == k].max() for k, z in enumerate(jk.zones)))}
