"""The exact-integrals form of pinn/quasi1d.py on the paper's own case, for a direct comparison with paper_cd.py:
same nozzle, gamma, back pressure, network size, collocation count and training budget.

usage: python -m pinn.paper_integrals --out results/pinn/step1_integrals.json [--seeds 0 1 2]
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from . import quasi1d as q
from .core import fit
from .nozzle1d import solve
from .paper_cd import G, PB, XE, XT, area, darea


class ParabolicNozzle:
    """The paper's area law with the throat at xi = 0."""

    gamma, xi0, xie = G, -XT, XE - XT

    def A(self, xi):
        return area(np.asarray(xi, float) + XT)

    def dA(self, xi):
        return darea(np.asarray(xi, float) + XT)

    def points(self, n):
        return np.linspace(self.xi0, self.xie, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--adam", type=int, default=20000)
    ap.add_argument("--lbfgs", type=int, default=5000)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--visc", type=float, default=0.03, help="von Neumann-Richtmyer length, sets the shock width")
    ap.add_argument("--weak", action="store_true", help="train the integral balance, on a larger network")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    nz = ParabolicNozzle()
    xi = np.linspace(nz.xi0, nz.xie, 4501)
    ref = solve(xi, PB, nz.A, 0.0, 1.0, G)
    rows = []
    for seed in a.seeds:
        if a.weak:
            m = q.Quasi1D(nz, "integrals", seed, pb=PB, weak=True, width=50, depth=4, n=4000)
        else:
            m = q.Quasi1D(nz, "integrals", seed, pb=PB, width=30, depth=3, n=2000, visc=a.visc)
        t0 = time.time()
        hist = fit([p for p in m.parameters() if p.requires_grad], m.terms, adam=a.adam, lbfgs=a.lbfgs)
        d = q.compare(m, xi, ref, G, xi_search=0.05)
        p = m.predict(xi)
        A = nz.A(xi)
        for k, v in (("rho", p["rho"]), ("T", p["T"]), ("p", p["p"])):
            d[f"l2_{k}"] = float(np.linalg.norm(v - ref[k]) / np.linalg.norm(ref[k]))
        d["x_shock"] = d.get("xi_shock", float("nan")) + XT
        r = {"form": "integrals", "seed": seed, "seconds": time.time() - t0, "final": hist[-1], **d}
        rows.append(r)
        print(json.dumps({k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items() if k != "final"}), flush=True)
        Path(a.out).write_text(json.dumps({"x_shock_analytic": ref["x_shock"] + XT, "runs": rows}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
