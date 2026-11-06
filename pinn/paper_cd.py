"""Step 1: Liang et al. (2024) steady normal shock in a parabolic nozzle, with three residual forms.

Non-dimensional Euler equations as in the paper: rho/rho0, T/T0, p/p0, v/a0, A(x) = 1 + 2.2 (x - 1.5)^2 on
x in [0, 2.25], gamma 1.4, back pressure 0.81017, analytic shock at x = 1.875.

forms
  noncons     outputs rho, v, T, p; the paper's differential form (its eq. 4)
  conserved   outputs U1 = rho A, U2 = rho A v, U3, p; the paper's eq. 22, which it reports does not train
  primflux    outputs rho, v, T, p as noncons, with the residuals taken on the conservative fluxes (the idea
              in pinn4hcf: primitive outputs, conservative residuals)
Every form takes the paper's fix (momentum weight 20, hard pressure BCs); --vanilla removes both.

usage: python -m pinn.paper_cd --out results/pinn/step1_paper.json [--seeds 0 1 2] [--forms ...]
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from .core import Mlp, ddx, fit, seed_all
from .nozzle1d import normal_shock, solve

G, PB, XE, XT = 1.4, 0.81017, 2.25, 1.5


def area(x):
    return 1 + 2.2 * (x - XT) ** 2


def darea(x):
    return 4.4 * (x - XT)


class Case:
    def __init__(self, form, vanilla, seed, n=2000, width=30, depth=3):
        self.form, self.vanilla = form, vanilla
        seed_all(seed)
        self.net = Mlp(1, 4, width, depth).double()
        self.x = torch.linspace(0, XE, n, dtype=torch.float64).reshape(-1, 1).requires_grad_(True)
        self.x0 = torch.zeros((1, 1), dtype=torch.float64)
        self.xe = torch.full((1, 1), XE, dtype=torch.float64)
        self.w_mom = 1.0 if vanilla else 20.0

    def state(self, x):
        """(rho, v, T, p) from the network, whichever variables it outputs."""
        o = self.net(x)
        p = o[:, 3:4]
        if not self.vanilla:
            p = x * (x - XE) * p + (1 + (PB - 1) * x / XE)  # exact at both ends
        if self.form == "conserved":
            A = area(x)
            U1, U2, U3 = o[:, 0:1], o[:, 1:2], o[:, 2:3]
            v = U2 / U1
            return U1 / A, v, (G - 1) * (U3 / U1 - G / 2 * v ** 2), p
        return o[:, 0:1], o[:, 1:2], o[:, 2:3], p

    def residuals(self, x):
        A, dA = area(x), darea(x)
        o = self.net(x)
        rho, v, T, p = self.state(x)
        if self.form == "noncons":
            rho_x, v_x, T_x, p_x = ddx(rho, x), ddx(v, x), ddx(T, x), ddx(p, x)
            F1 = A * v * rho_x + A * rho * v_x + v * rho * dA
            F2 = A * (G * rho * v * v_x + p_x)
            F3 = A * v * rho * T_x + (G - 1) * p * (A * v_x + v * dA)  # the paper's energy form times (gamma - 1)
            F4 = p - rho * T
        elif self.form == "primflux":
            F1 = ddx(rho * v * A, x)
            F2 = ddx((G * rho * v ** 2 + p) * A, x) - p * dA
            F3 = (G - 1) * ddx(rho * v * A * (T / (G - 1) + G * v ** 2 / 2) + p * A * v, x)
            F4 = p - rho * T
        else:  # conserved, the paper's eq. 21-22
            U1, U2, U3 = o[:, 0:1], o[:, 1:2], o[:, 2:3]
            K2 = U2 ** 2 / U1 + (G - 1) / G * (U3 - G / 2 * U2 ** 2 / U1)
            K3 = G * U2 * U3 / U1 - G * (G - 1) / 2 * U2 ** 3 / U1 ** 2
            F1, F2, F3 = ddx(U2, x), ddx(K2, x) - p * dA / G, ddx(K3, x)
            F4 = p - U1 / A * (G - 1) * (U3 / U1 - G / 2 * U2 ** 2 / U1 ** 2)
        return F1, F2, F3, F4

    def terms(self):
        F1, F2, F3, F4 = self.residuals(self.x)
        rho0, _, T0, p0 = self.state(self.x0)
        t = {"F1": (F1 ** 2).mean(), "F2": self.w_mom * (F2 ** 2).mean(), "F3": (F3 ** 2).mean(), "F4": (F4 ** 2).mean(),
             "bc": ((rho0 - 1) ** 2).sum() + ((T0 - 1) ** 2).sum()}
        if self.vanilla:
            t["bc"] = t["bc"] + ((p0 - 1) ** 2).sum() + ((self.state(self.xe)[3] - PB) ** 2).sum()
        return t


def diagnostics(case, ref):
    """Errors against the analytic solution and the conservation checks across the PINN's shock."""
    x = torch.as_tensor(ref["x"], dtype=torch.float64).reshape(-1, 1)
    with torch.no_grad():
        rho, v, T, p = [q.numpy().ravel() for q in case.state(x)]
    xn, A = ref["x"], area(ref["x"])
    v = np.abs(v)
    T_safe = np.maximum(T, 1e-9)
    M = v / np.sqrt(T_safe)
    d = {"finite": bool(np.isfinite(rho + v + T + p).all())}
    if not d["finite"]:
        return d
    for k, q in (("rho", rho), ("M", M), ("T", T), ("p", p)):
        d[f"l2_{k}"] = float(np.linalg.norm(q - ref[k]) / np.linalg.norm(ref[k]))
    down = xn > XT
    k = np.argmax(np.abs(np.gradient(M, xn)) * down)
    d["x_shock"] = float(xn[k])
    d["M_max"] = float(M.max())
    mdot = rho * v * A
    H = T + (G - 1) / 2 * v ** 2
    # stations clear of the smeared shock on both sides
    a, b = np.searchsorted(xn, d["x_shock"] - 0.06), min(np.searchsorted(xn, d["x_shock"] + 0.06), len(xn) - 1)
    d["mdot_spread"] = float((mdot.max() - mdot.min()) / abs(np.mean(mdot)))
    d["mdot_jump"] = float(mdot[b] / mdot[a] - 1)
    d["H_jump"] = float(H[b] / H[a] - 1)
    d["H_spread"] = float((H.max() - H.min()) / np.mean(H))
    # normal-shock relations from the PINN's own upstream Mach number; p here holds at the two stations
    M1 = M[a]
    d["M1"], d["M2_pinn"] = float(M1), float(M[b])
    d["M2_rh"] = float(normal_shock(M1, G)[0]) if M1 > 1 else None
    return d


def run(form, vanilla, seed, ref, adam, lbfgs):
    case = Case(form, vanilla, seed)
    t0 = time.time()
    hist = fit(case.net.parameters(), case.terms, adam=adam, lbfgs=lbfgs)
    return {"form": form, "vanilla": vanilla, "seed": seed, "seconds": time.time() - t0, "final": hist[-1],
            **diagnostics(case, ref)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--forms", nargs="+", default=["noncons", "primflux", "conserved"])
    ap.add_argument("--adam", type=int, default=20000)
    ap.add_argument("--lbfgs", type=int, default=5000)
    ap.add_argument("--threads", type=int, default=2)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    xs = np.linspace(0, XE, 4501)
    ref = solve(xs, PB, area, XT, 1.0, G)
    print(f"analytic shock at x = {ref['x_shock']:.4f}", flush=True)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    cases = [("noncons", True)] + [(f, False) for f in a.forms]
    for form, vanilla in cases:
        for seed in a.seeds:
            r = run(form, vanilla, seed, ref, a.adam, a.lbfgs)
            rows.append(r)
            print(json.dumps({k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items() if k != "final"}), flush=True)
            out.write_text(json.dumps({"x_shock_analytic": ref["x_shock"], "runs": rows}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
