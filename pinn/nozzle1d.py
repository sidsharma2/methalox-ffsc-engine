"""Analytic quasi-1-D nozzle flow of a perfect gas: area-Mach relation, normal shock, back-pressure solve.

Pressures are in units of the inlet stagnation pressure and temperatures of the stagnation temperature.
"""

import numpy as np
from scipy.optimize import brentq


def area_ratio(M, g):
    """A/A* at Mach number M."""
    return (1 / M) * ((2 / (g + 1)) * (1 + (g - 1) / 2 * M ** 2)) ** ((g + 1) / (2 * (g - 1)))


def mach_from_area(ar, g, supersonic=True):
    """Mach number at area ratio ar (scalar or array) on the chosen branch."""
    ar = np.atleast_1d(np.asarray(ar, float))
    out = np.ones_like(ar)
    for i, a in enumerate(ar):
        if a - 1 < 1e-10:
            continue
        f = lambda M: area_ratio(M, g) - a
        out[i] = brentq(f, 1 + 1e-10, 60.0, xtol=1e-12) if supersonic else brentq(f, 1e-8, 1 - 1e-10, xtol=1e-13)
    return out


def isentropic(M, g):
    """(p/p0, rho/rho0, T/T0) at Mach number M."""
    t = 1 / (1 + (g - 1) / 2 * M ** 2)
    return t ** (g / (g - 1)), t ** (1 / (g - 1)), t


def normal_shock(M1, g):
    """(M2, p2/p1, rho2/rho1, p02/p01) across a normal shock."""
    m2 = M1 ** 2
    M2 = np.sqrt(((g - 1) * m2 + 2) / (2 * g * m2 - (g - 1)))
    pr = (2 * g * m2 - (g - 1)) / (g + 1)
    rr = (g + 1) * m2 / ((g - 1) * m2 + 2)
    p0r = rr ** (g / (g - 1)) * pr ** (-1 / (g - 1))
    return M2, pr, rr, p0r


def _exit_pressure(x_s, A, x_e, At, g):
    M1 = mach_from_area(A(x_s) / At, g)[0]
    _, _, _, p0r = normal_shock(M1, g)
    Me = mach_from_area(A(x_e) * p0r / At, g, supersonic=False)[0]  # A2* = At / p0r
    return p0r * isentropic(Me, g)[0]


def shock_location(pb, A, x_t, x_e, At, g):
    """Normal-shock station for back pressure pb, or None if the back pressure puts no shock in the diverging part."""
    lo, hi = x_t + 1e-6, x_e - 1e-9
    f = lambda x: _exit_pressure(x, A, x_e, At, g) - pb
    if f(lo) * f(hi) > 0:
        return None
    return brentq(f, lo, hi, xtol=1e-10)


def solve(x, pb, A, x_t, At, g):
    """Steady solution on stations x, with the flow choked at x_t. pb sets the shock; pb=None means shock-free
    supersonic flow. Returns dict of p, rho, T, M (velocities: v = M sqrt(T), in units of a0)."""
    x = np.asarray(x, float)
    ar = A(x) / At
    sub = x <= x_t
    M = np.empty_like(x)
    M[sub] = mach_from_area(ar[sub], g, supersonic=False)
    x_s = None if pb is None else shock_location(pb, A, x_t, x[-1], At, g)
    p0 = np.ones_like(x)
    down = ~sub if x_s is None else (~sub) & (x < x_s)
    M[down] = mach_from_area(ar[down], g)
    if x_s is not None:
        after = x >= x_s
        M1 = mach_from_area(A(x_s) / At, g)[0]
        p0r = normal_shock(M1, g)[3]
        M[after] = mach_from_area(ar[after] * p0r, g, supersonic=False)
        p0[after] = p0r
    p, _, T = isentropic(M, g)
    p = p * p0
    return {"x": x, "p": p, "rho": p / T, "T": T, "M": M, "v": M * np.sqrt(T), "x_shock": x_s}
