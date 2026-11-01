"""Bolted-joint sizing (VDI 2230-lite), pressure-vessel wall thickness, duct sizing.

Each bolted joint is sized from its separating force at proof pressure: the clamp load
left after the external load must exceed separation_safety x separating force, and the
bolt spacing must sit between 2.5 d (wrench access) and 6 d (seal load uniformity).
"""

import numpy as np

# ISO 898 coarse threads: (name, d_mm, tensile stress area mm2, head across flats mm)
ISO_BOLTS = [("M6", 6, 20.1, 10), ("M8", 8, 36.6, 13), ("M10", 10, 58.0, 16), ("M12", 12, 84.3, 18),
             ("M14", 14, 115.0, 21), ("M16", 16, 157.0, 24), ("M20", 20, 245.0, 30),
             ("M24", 24, 353.0, 36), ("M27", 27, 459.0, 41), ("M30", 30, 561.0, 46)]

BOLT_GRADES = {
    "A286": {"proof_MPa": 760.0, "note": "AMS 5737 / NAS1352-class, cryogenic and up to ~900 K"},
    "Inconel 718": {"proof_MPa": 1030.0, "note": "AMS 5662/5663 aged, high-load hot joints"},
}

PROOF_FACTOR = 1.2           # proof pressure / MEOP
JOINT_STIFFNESS_C = 0.25     # share of external load seen by the bolt


def size_joint(name, p_meop, D_seal, cfg, grade="A286", extra_axial_N=0.0, n_min=6, d_min_mm=6, wall_r=None):
    """wall_r: radius of a wall rising next to the flange (body, closeout, flaring nozzle).
    The bolt circle then keeps one washer radius (d) plus 2 mm of tool clearance to it."""
    st = cfg["structures"]
    F_ext = p_meop * PROOF_FACTOR * np.pi / 4 * D_seal ** 2 + extra_axial_N
    proof = BOLT_GRADES[grade]["proof_MPa"] * 1e6
    for bname, d_mm, As_mm2, af in ISO_BOLTS:
        if d_mm < d_min_mm:
            continue
        d, As = d_mm * 1e-3, As_mm2 * 1e-6
        Fp = st["preload_frac_proof"] * proof * As
        n = max(n_min, int(np.ceil(st["separation_safety"] * (1 - JOINT_STIFFNESS_C) * F_ext / Fp)))
        n += (-n) % 2
        bcd = D_seal + 2 * (0.9 * d + 4e-3)                    # seal land + bolt edge distance
        if wall_r is not None:
            bcd = max(bcd, 2 * (wall_r + d + 2e-3))
        spacing = np.pi * bcd / n
        if spacing < 2.5 * d:
            continue                                            # too crowded: next size up
        while spacing > 6 * d:
            n += 2
            spacing = np.pi * bcd / n
        bolt_stress = (Fp + JOINT_STIFFNESS_C * F_ext / n) / As
        flange_od = bcd + 2 * (af * 1e-3 * 0.5 + 2.5e-3) + d
        # flange thickness from ring bending about the seal diameter (Roark, conservative)
        arm = (bcd - D_seal) / 2
        M = F_ext * arm / (np.pi * bcd)                         # per unit circumference
        t = max(np.sqrt(6 * M / (st["closeout_allow_MPa"] * 1e6)), 1.0 * d)
        return {"name": name, "p_meop_Pa": p_meop, "D_seal_m": D_seal, "F_sep_proof_N": F_ext,
                "bolt": bname, "d_m": d, "n_bolts": n, "bcd_m": bcd, "spacing_over_d": spacing / d,
                "preload_N": Fp, "bolt_stress_MPa": bolt_stress / 1e6,
                "bolt_stress_ratio": bolt_stress / proof, "grade": grade,
                "flange_od_m": flange_od, "flange_t_m": t, "across_flats_m": af * 1e-3}
    raise ValueError(f"{name}: no ISO size fits; use a split joint or welded design")


def wall_thickness(p, r, allow_MPa, t_min=1.5e-3):
    return max(p * PROOF_FACTOR * r / (allow_MPa * 1e6), t_min)


def duct_diameter(mdot, rho, v):
    return np.sqrt(4 * mdot / (np.pi * rho * v))
