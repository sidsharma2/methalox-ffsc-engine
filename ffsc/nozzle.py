"""Thrust-chamber contour: cylinder, convergent cone, circular throat arcs and a Rao
thrust-optimised parabola (TOP) bell. Also flow-separation checks for sea-level use.

Rao angles are a digitised approximation of the 80 % bell charts in Huzel & Huang
(1992, Fig. 4-16); expect about +/-1 deg error. A method-of-characteristics contour
is the planned upgrade (docs/04).
"""

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

_EPS = np.array([4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100])
_TN80 = np.array([21.0, 22.5, 23.5, 25.0, 26.0, 27.3, 28.3, 29.0, 29.6, 30.5, 31.3, 32.0, 33.0, 33.8])
_TE80 = np.array([14.0, 13.0, 12.3, 11.5, 11.0, 10.0, 9.4, 9.0, 8.6, 8.0, 7.6, 7.3, 7.0, 6.8])


def rao_angles(eps, bell_fraction=0.8):
    """Initial (theta_n) and exit (theta_e) wall angles in degrees for an 80 % bell."""
    if abs(bell_fraction - 0.8) > 1e-6:
        raise ValueError("only the 80 % bell table is digitised")
    le = np.log(eps)
    return float(np.interp(le, np.log(_EPS), _TN80)), float(np.interp(le, np.log(_EPS), _TE80))


@dataclass
class Contour:
    x: np.ndarray          # m, axial from injector face (positive downstream)
    r: np.ndarray          # m, inner radius
    Rt: float
    Rc: float
    Re: float
    L_cyl: float
    L_conv: float
    L_noz: float
    x_throat: float
    theta_n: float
    theta_e: float
    V_chamber: float       # injector face to throat

    @property
    def area_ratio(self):
        return (self.r / self.Rt) ** 2


def _arc(xc, yc, R, a0, a1, n):
    a = np.linspace(a0, a1, n)
    return xc + R * np.cos(a), yc + R * np.sin(a)


def _convergent(Rt, Rc, cfg):
    """Convergent section from the cylinder end (x=0) to the throat, in local x."""
    th = np.radians(cfg["convergent_half_angle_deg"])
    R1 = cfg["R_up_over_Rt"] * Rt
    Rf = cfg["R_fillet_over_Rc"] * Rc
    # fillet: centre below the wall at (0, Rc - Rf), from 90 deg down to 90-th
    x1, y1 = _arc(0.0, Rc - Rf, Rf, np.pi / 2, np.pi / 2 - th, 40)
    # throat upstream arc: centre (xt, Rt + R1), from 270-th to 270 deg
    yA = Rt + R1 - R1 * np.cos(th)          # radius where the cone meets the throat arc
    yB = y1[-1]
    dx_cone = (yB - yA) / np.tan(th)
    xA = x1[-1] + dx_cone
    xt = xA + R1 * np.sin(th)
    x2, y2 = _arc(xt, Rt + R1, R1, 1.5 * np.pi - th, 1.5 * np.pi, 40)
    x = np.concatenate([x1, x2])
    y = np.concatenate([y1, y2])
    return x, y, xt


def _bell(Rt, eps, theta_n, theta_e, cfg, bell_fraction):
    """Downstream throat arc then quadratic Bezier to the exit (Rao TOP)."""
    Rn = cfg["R_dn_over_Rt"] * Rt
    tn, te = np.radians(theta_n), np.radians(theta_e)
    xa, ya = _arc(0.0, Rt + Rn, Rn, -np.pi / 2, tn - np.pi / 2, 30)
    Nx, Ny = xa[-1], ya[-1]
    Re = np.sqrt(eps) * Rt
    # length of a 15 deg cone with the same expansion, times the bell fraction
    Ln = bell_fraction * ((np.sqrt(eps) - 1) * Rt + Rn * (1 / np.cos(np.radians(15)) - 1)) / np.tan(np.radians(15))
    Ex, Ey = Ln, Re
    m1, m2 = np.tan(tn), np.tan(te)
    c1, c2 = Ny - m1 * Nx, Ey - m2 * Ex
    Qx = (c2 - c1) / (m1 - m2)
    Qy = (m1 * c2 - m2 * c1) / (m1 - m2)
    t = np.linspace(0, 1, 120)[1:]
    bx = (1 - t) ** 2 * Nx + 2 * (1 - t) * t * Qx + t ** 2 * Ex
    by = (1 - t) ** 2 * Ny + 2 * (1 - t) * t * Qy + t ** 2 * Ey
    return np.concatenate([xa, bx]), np.concatenate([ya, by]), Ln


def _volume(x, r):
    return float(np.trapezoid(np.pi * r ** 2, x))


def build_contour(At, eps, chamber_cfg, bell_fraction=0.8, Lstar=None):
    """Full inner contour. Cylinder length is solved so that V_chamber = L* At."""
    Rt = np.sqrt(At / np.pi)
    Rc = np.sqrt(chamber_cfg["contraction_ratio"]) * Rt
    Lstar = Lstar or chamber_cfg["Lstar_m"]
    xc, yc, xt = _convergent(Rt, Rc, chamber_cfg)
    V_conv = _volume(xc, yc)
    L_cyl = (Lstar * At - V_conv) / (np.pi * Rc ** 2)
    if L_cyl < 0.02:
        raise ValueError(f"L* too small for this convergent (L_cyl={L_cyl:.3f} m)")
    tn, te = rao_angles(eps, bell_fraction)
    xb, yb, Ln = _bell(Rt, eps, tn, te, chamber_cfg, bell_fraction)
    x_throat = L_cyl + xt
    xs = np.concatenate([np.linspace(0, L_cyl, 25)[:-1], L_cyl + xc, x_throat + xb[1:]])
    rs = np.concatenate([np.full(24, Rc), yc, yb[1:]])
    keep = np.concatenate([[True], np.diff(xs) > 1e-9])
    return Contour(xs[keep], rs[keep], Rt, Rc, np.sqrt(eps) * Rt, L_cyl, xt, Ln,
                   x_throat, tn, te, Lstar * At)


def divergence_factor(theta_e):
    """Momentum loss factor of the exit flow angle (bell: about (1+cos te)/2)."""
    return 0.5 * (1 + np.cos(np.radians(theta_e)))


def mach_from_area(ar, gamma, supersonic=True):
    f = lambda M: (1 / M) * ((2 / (gamma + 1)) * (1 + (gamma - 1) / 2 * M ** 2)) ** ((gamma + 1) / (2 * (gamma - 1))) - ar
    if abs(ar - 1) < 1e-9:
        return 1.0
    return brentq(f, 1.0 + 1e-9, 50.0) if supersonic else brentq(f, 1e-6, 1.0 - 1e-9)


def separation_check(pe, pa, Me):
    """Summerfield (pe/pa < 0.4 -> risk) and Schmucker (1973) separation pressure ratios."""
    schmucker = (1.88 * Me - 1) ** -0.64
    return {"pe_over_pa": pe / pa, "summerfield_limit": 0.4, "schmucker_limit": schmucker,
            "separated_schmucker": pe / pa < schmucker,
            "margin_schmucker": pe / pa / schmucker}
