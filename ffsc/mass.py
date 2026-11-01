"""Analytic thrust-chamber mass from the cooling profile (liner + ribs + closeout).
Used by the trade studies; the CAD BOM (cad/output/bom.csv) is the full-engine roll-up."""

import numpy as np

from .materials import MATERIALS


def tca_mass(cool, cfg, closeout_t):
    """Liner/rib mass in the zone material and closeout mass in Inconel 718 (kg)."""
    x, r, H, N, rib, zone = (np.asarray(cool[k]) for k in ("x", "r", "H", "N", "rib", "zone"))
    t_hot = np.array([cfg["cooling"]["zones"][int(z)]["t_hot_mm"] * 1e-3 for z in zone])
    ds = np.hypot(np.diff(x), np.diff(r))
    mid = lambda a: 0.5 * (a[1:] + a[:-1])
    rho_z = np.array([MATERIALS[cfg["cooling"]["zones"][int(z)]["material"]]["rho"] for z in zone])
    a_liner = 2 * np.pi * (r + t_hot / 2) * t_hot + N * rib * H
    r_c = r + t_hot + H
    a_close = 2 * np.pi * (r_c + closeout_t / 2) * closeout_t
    m_liner = float(np.sum(mid(a_liner * rho_z) * ds))
    m_close = float(np.sum(mid(a_close) * ds) * MATERIALS["Inconel 718"]["rho"])
    return {"liner_ribs_kg": m_liner, "closeout_kg": m_close, "total_kg": m_liner + m_close}
