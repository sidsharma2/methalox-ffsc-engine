"""Score saved 2-D weights against a reference, without retraining.

usage: python -m pinn.score WEIGHTS.pt --ref results/pinn/reference_I2C_euler.npz [--width 64 --depth 5]
"""

import argparse
import json

import numpy as np
import torch

from . import axisym as a
from .quasi1d import Nozzle

# cfd/post_compare.py, with the flat-face sector factor
CFD = {"euler": {"Cd": 0.99478, "eta_cf_vac": 0.98781}, "euler_r15": {"Cd": 0.99480, "eta_cf_vac": 0.98787}, "nozzle": {"Cd": 0.99370, "eta_cf_vac": 0.98271}}


def bands(model, ref, nz):
    """Mach error along the nozzle, to show where the model departs from the CFD."""
    q = model.predict(ref["x"], ref["r"])
    xi = (ref["x"] - nz.x_t) / nz.Rt
    rows = []
    for lo, hi in [(-3, -1), (-1, 0), (0, 1), (1, 2), (2, 4), (4, 7), (7, 10), (10, 13), (13, 15)]:
        k = (xi >= lo) & (xi < hi)
        err = q["Ma"][k] - ref["Ma"][k]
        rows.append({"xi": [lo, hi], "bias": float(np.average(err, weights=ref["vol"][k])), "rms": float(np.sqrt(np.average(err ** 2, weights=ref["vol"][k]))), "max": float(np.abs(err).max())})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("weights")
    ap.add_argument("--ref", default="results/pinn/reference_I2C_euler.npz")
    ap.add_argument("--width", type=int, default=64)
    ap.add_argument("--depth", type=int, default=5)
    ap.add_argument("--fields", default=None, help="write the PINN fields, in SI units, at the reference cells")
    a_ = ap.parse_args()
    torch.set_num_threads(2)
    nz = Nozzle()
    ref = a.load_ref(a_.ref, nz)
    m = a.Axisym(nz, 0, nx=16, nr=8, width=a_.width, depth=a_.depth)
    m.load_state_dict(torch.load(a_.weights, weights_only=True, map_location=a.DEVICE))
    res = {**m.integrals(), **a.compare(m, ref)}
    print(json.dumps({k: round(v, 5) for k, v in res.items()}))
    tag = "euler_r15" if "euler_r15" in a_.ref else "euler" if "euler" in a_.ref else "nozzle"
    print("CFD:", CFD[tag], " dCd {:+.3f} %  dCf {:+.3f} %".format(100 * (res["Cd"] / CFD[tag]["Cd"] - 1), 100 * (res["eta_cf_vac"] / CFD[tag]["eta_cf_vac"] - 1)))
    for r in bands(m, ref, nz):
        print("xi {:6.1f} {:6.1f}  bias {:+.4f}  rms {:.4f}  max {:.4f}".format(*r["xi"], r["bias"], r["rms"], r["max"]))
    if a_.fields:
        q = m.predict(ref["x"], ref["r"])
        gas = ref["meta"]["gas"]
        np.savez_compressed(a_.fields, x=ref["x"], r=ref["r"], Ma=q["Ma"], p=q["p"] * a.P0, T=q["T"] * a.T0,
                            rho=q["rho"] * a.P0 / (gas["R"] * a.T0))


if __name__ == "__main__":
    main()
