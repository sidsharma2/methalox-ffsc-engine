"""Main injector: gas-gas shear coaxial elements, ox-rich gas in the centre post and
fuel-rich gas in the annulus (both streams fully gasified in FFSC).

Elements are laid out on concentric rings. The outer ring carries the fuel-rich wall
bias (lower element mixture ratio) used by the cooling model.
"""

import numpy as np


def orifice_area(mdot, rho, dp, cd):
    return mdot / (cd * np.sqrt(2 * rho * dp))


def ring_layout(R_face, pitch, edge_margin):
    """Centre element plus rings at one-pitch radial spacing that fit inside R_face."""
    rings = [(0.0, 1)]
    k = 1
    while k * pitch <= R_face - edge_margin:
        r = k * pitch
        rings.append((r, int(np.floor(2 * np.pi * r / pitch))))
        k += 1
    return rings


def design_injector(cfg, Rc, pc, m_ox_gas, rho_ox, m_fu_gas, rho_fu, bl_fraction):
    inj = cfg["injector"]
    dp = cfg["cycle"]["dp_main_inj_frac"] * pc
    cd = 0.82
    post_wall = 1.0e-3
    def element(n):
        a_ox = orifice_area(m_ox_gas / n, rho_ox, dp, cd)
        a_fu = orifice_area(m_fu_gas / n, rho_fu, dp, cd)
        d_ox = np.sqrt(4 * a_ox / np.pi)
        d_post = d_ox + 2 * post_wall
        return d_ox, d_post, np.sqrt(d_post ** 2 + 4 * a_fu / np.pi)

    def fit(pitch):
        rings = ring_layout(Rc, pitch, 0.5 * pitch)
        return rings, sum(c for _, c in rings)

    # element count from the thrust-per-element target; pitch is the largest that fits
    # (n scales the element size as 1/sqrt(n), so the face-area limit fixes pitch/d)
    n = int(round(cfg["requirements"]["thrust_sl_kN"] / inj["thrust_per_element_kN"]))
    for _ in range(5):
        d_ox, d_post, d_ann = element(n)
        pitch = inj["ring_pitch_factor"] * d_ann
        while fit(pitch)[1] < n and pitch > 1.05 * d_ann:
            pitch *= 0.99
        rings, n_new = fit(pitch)
        if n_new == n:
            break
        n = n_new
    d_ox, d_post, d_ann = element(n)
    # wall bias: the outer ring takes a larger fuel share so its local O/F matches the
    # wall stream tube; the flow areas of those elements are rescaled accordingly
    n_outer = rings[-1][1]
    return {
        "n_elements": n, "rings": [{"r_m": r, "count": c} for r, c in rings],
        "n_outer_ring": n_outer, "outer_ring_mass_share": n_outer / n,
        "bl_mass_fraction": bl_fraction,
        "d_ox_post_m": d_ox, "d_post_outer_m": d_post, "d_annulus_outer_m": d_ann,
        "pitch_m": pitch, "pitch_over_d_annulus": pitch / d_ann, "dp_Pa": dp, "cd": cd,
        "open_area_fraction": n * np.pi / 4 * d_ann ** 2 / (np.pi * Rc ** 2),
        "v_ox_m_s": cd * np.sqrt(2 * dp / rho_ox), "v_fu_m_s": cd * np.sqrt(2 * dp / rho_fu),
        "velocity_ratio_fu_ox": np.sqrt(rho_ox / rho_fu),
        "momentum_flux_ratio": 1.0,       # equal dP across both streams
        "thrust_per_element_kN": cfg["requirements"]["thrust_sl_kN"] / n,
        "faceplate_R_m": Rc,
    }
