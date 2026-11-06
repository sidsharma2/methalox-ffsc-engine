"""Pseudo-time continuation of a trained 2-D model: does a shock form from the smooth field, with no CFD data?

The steady loss rates the smooth near-isentropic field far better than a sharp one, so more steps of it cannot find the
shock. Song, Cao and Zhang (arXiv:2607.08130) replace the steady residual with one implicit Euler step, repeated from the
previous output.

The step has to change for this model. Mass and total enthalpy are exact here, so momentum is the only equation left, and
rho u depends on the stream function alone. A time term on the momentum would never see the speed output. The step acts on
the velocity instead:

    g rho_n (V - V_n) / dtau + R(V) / vol = 0, with rho_n and dtau frozen at the start of the step

In 1-D this is g rho dU/dtau + dI/dx = 0, with I the impulse: a scalar conservation law with wave speed (U/g)(1 - 1/M^2),
so compression steepens and a steady jump keeps [I] = 0. Linearised about a uniform stream, the 2-D modes are neutral
(sigma purely imaginary) and the steady ones are Mach waves, k^2 (M^2 - 1) = l^2. It is a fictitious time, because the
stream function keeps the mass balance steady at every step, so a transient here is not a physical transient.

Central fluxes have no dissipation, so a shock rings and the second law breaks. --ell adds a von Neumann-Richtmyer pressure
in compression, q = g rho (ell^2 d^2 + cl ell a d^2 / (d + 0.2)) with d = -div V, to the momentum balances. With mass and total
enthalpy exact, a 1-D shock then has the Rankine-Hugoniot jump for any ell and a 90-10 % width of 1.91 ell along its normal at
cl = 0. Expansions have q = 0, so the throat and the bell upstream of the compression are untouched. Entropy peaks at the sonic
point inside a resolved shock, so the second-law hinge is relaxed where q is active.

usage: python -m pinn.pseudo --tag seed4_cfl5 --cfl 5
Writes results/pinn/pseudo/<tag>.jsonl (a row per diagnostic) and <tag>_*.pt.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from . import axisym as a
from .ensemble import RES, axis_shock, columns, reference
from .quasi1d import Nozzle

OUT = RES / "pseudo"
ROWS = 135            # cells across the nozzle in the finer Euler mesh
CD_REF = 0.99480
BANDS = ((9.8, 10.5), (10.5, 12.0), (12.0, 14.5))      # axis ln p0, where the CFD shows the shock's entropy
ONSET = 0.2           # compression rate, in a0/Rt, below which the linear term of q fades out
Q_ACTIVE = 1e-3       # q/p at which the second-law hinge is halved
SECTIONS = (11.0, 12.0, 13.0, 14.0, 14.8)              # stations of the mass-weighted ln p0 check


def cell(q):
    return a.avg_i(a.avg_j(q))


def to_nodes(c):
    """Cell values to the grid nodes, with the edge cells repeated outward."""
    p = F.pad(c[None, None], (1, 1, 1, 1), mode="replicate")[0, 0]
    return (p[:-1, :-1] + p[1:, :-1] + p[:-1, 1:] + p[1:, 1:]) / 4


class PseudoTime:
    """One implicit step per call of snapshot(). The frozen values are constants of the loss, so its gradient is exact."""

    def __init__(self, model, cfl, k=0.0, weight=1.0, keep=("sec", "s", "p0", "bc"), ell=0.0, cl=0.0):
        self.m, self.cfl, self.k, self.w, self.keep, self.ell, self.cl = model, cfl, k, weight, tuple(keep), ell, cl
        self.dx = (model.x_t[1:] - model.x_t[:-1])[:, None]
        self.sec = a.avg_i((model.r_t[:, 1:] ** 2 - model.r_t[:, :-1] ** 2) / 2)
        self.snapshot()

    def divergence(self, f):
        """Volume flux out of each cell over its volume, to mark compression for the Liu et al. weight."""
        m = self.m
        r, u, v = m.r_t, f["u"], f["v"]
        dx = self.dx
        cx = a.avg_j(u) * (r[:, 1:] ** 2 - r[:, :-1] ** 2) / 2
        cr = -a.avg_i(u) * (r[1:] ** 2 - r[:-1] ** 2) / 2 + a.avg_i(v) * a.avg_i(r) * dx
        return (cx[1:] - cx[:-1] + cr[:, 1:] - cr[:, :-1]) / (self.sec * dx)

    def stress(self, f):
        """The von Neumann-Richtmyer pressure on the grid nodes, or None when it is off. A function of the live fields."""
        if self.ell == 0:
            return None
        d = torch.relu(-self.divergence(f))
        rate = self.ell ** 2 * d ** 2 + self.cl * self.ell * torch.sqrt(cell(f["T"])) * d ** 2 / (d + ONSET)
        return to_nodes(self.m.g * cell(f["rho"]) * rate)

    def snapshot(self):
        m = self.m
        f = {k: q.detach() for k, q in m.grid_fields().items()}
        self.un, self.vn = cell(f["u"]), cell(f["v"])
        wave = torch.sqrt(self.un ** 2 + self.vn ** 2) + torch.sqrt(cell(f["T"]))
        dtau = self.cfl * self.dx / wave
        # the velocity change that one unit of relative residual R/scale gives in one step
        self.c = dtau * m.scale / (m.g * cell(f["rho"]) * self.sec * self.dx)
        d = self.divergence(f)
        self.lam = 1 / (self.k * (d.abs() - d) + 1)
        q = self.stress(f)
        self.s_weight = None if q is None else 1 / (1 + (cell(q) / (Q_ACTIVE * cell(f["p"]))) ** 2)

    def residual_terms(self, f, q=None):
        m = self.m
        p = f["p"] if q is None else f["p"] + q
        rx, rr, _ = a.fv_residuals(m.x_t, m.r_t, f["psi"], f["u"], f["v"], p, m.g)
        ex = rx / m.scale + (cell(f["u"]) - self.un) / self.c
        er = rr / m.scale + (cell(f["v"]) - self.vn) / self.c
        return self.w * (self.lam * (ex ** 2 + er ** 2)).mean()

    def terms(self):
        f = self.m.grid_fields()
        q = self.stress(f)
        t = {"pt": self.residual_terms(f, q)}
        steady = self.m.terms(f, q=q, s_weight=self.s_weight)
        t.update({k: steady[k] for k in self.keep})
        return t


def section_lnp0(m, nz, xi, n=2000):
    """Mass-weighted ln p0 across the section at xi."""
    g = nz.gamma
    R = float(nz.r(nz.phys(xi))) / nz.Rt
    e = (np.arange(n) + 0.5) / n
    q = m.predict(np.full_like(e, nz.phys(xi)), e * R * nz.Rt)
    w = q["rho"] * q["u"] * e
    return float(np.sum(w * (np.log(q["p"]) - g / (g - 1) * np.log(q["T"]))) / np.sum(w))


def diagnostics(m, ref, nz):
    """Everything is measured on the finer Euler cells, with the same axis row and bands as the earlier scores."""
    g = nz.gamma
    q = m.predict(ref["x"], ref["r"])
    row = columns(ref, ROWS)[:, 0]
    xi = (ref["x"][row] - nz.x_t) / nz.Rt
    lnp0 = np.log(q["p"]) - g / (g - 1) * np.log(q["T"])
    sh = axis_shock({"x": ref["x"], "r": ref["r"], "Ma": q["Ma"]}, nz, ROWS)
    k = (xi > 8) & (xi < 13)
    out = {"peak": sh["peak"], "trough": sh["trough"], "xi_peak": sh["xi_peak"], "xi_trough": sh["xi_trough"], "width": sh["width"],
           "axis_dMdx": float(np.gradient(q["Ma"][row], xi)[k].min()), "share_above": float((lnp0 > 0.001).mean())}
    for lo, hi in BANDS:
        b = (xi >= lo) & (xi < hi)
        out[f"lnp0_{lo}_{hi}"] = float(lnp0[row][b].mean())
    out.update({f"steady_{k_}": v.item() for k_, v in m.terms().items()})
    for x0 in SECTIONS:
        out[f"sec_lnp0_{x0}"] = section_lnp0(m, nz, x0)
    near = (xi > 8.8) & (xi < 9.75)
    out["axis_dip"] = float(np.min(q["Ma"][row][near] - ref["Ma"][row][near]))
    out.update({k_: v for k_, v in a.compare(m, ref).items() if k_ in ("l2_Ma", "l2v_Ma", "max_err_Ma")})
    out.update(m.integrals())
    return out


def run(args):
    torch.set_num_threads(args.threads)
    a.DEVICE = torch.device(args.device)
    nz = Nozzle()
    ref = reference("euler_r15", nz)
    m = a.Axisym(nz, 0, nx=args.nx, nr=args.nr, width=64, depth=5)
    m.load_state_dict(torch.load(args.start, weights_only=True, map_location=a.DEVICE))
    pt = PseudoTime(m, args.cfl, k=args.k, weight=args.weight, keep=[k for k in args.keep.split(",") if k], ell=args.ell, cl=args.cl)
    params = list(m.parameters())
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / f"{args.tag}.jsonl"
    log.write_text("", encoding="utf-8")
    t0 = time.time()

    def write(row):
        row = {"seconds": round(time.time() - t0, 1), **row}
        with log.open("a", encoding="utf-8") as h:
            h.write(json.dumps(row) + "\n")
        print(json.dumps({k: (float(f"{v:.5g}") if isinstance(v, float) else v) for k, v in row.items()}), flush=True)

    write({"outer": 0, "config": vars(args) | {"start": str(args.start)}, **diagnostics(m, ref, nz)})
    for n in range(1, args.outer + 1):
        pt.snapshot()
        opt = torch.optim.LBFGS(params, lr=1.0, max_iter=args.inner, max_eval=int(1.25 * args.inner), history_size=50,
                                tolerance_grad=1e-14, tolerance_change=1e-16, line_search_fn="strong_wolfe")
        seen = []

        def closure():
            opt.zero_grad()
            terms = pt.terms()
            loss = sum(terms.values())
            if not torch.isfinite(loss):
                raise FloatingPointError(f"non-finite loss at outer {n}")
            loss.backward()
            seen.append(loss.item())
            return loss

        opt.step(closure)
        final = {k: v.item() for k, v in pt.terms().items()}
        row = {"outer": n, "evals": len(seen), "first": seen[0], "last": sum(final.values()), **{f"t_{k}": v for k, v in final.items()}}
        if n % args.every == 0 or n == args.outer:
            row.update(diagnostics(m, ref, nz))
            write(row)
            torch.save(m.state_dict(), OUT / f"{args.tag}_last.pt")
            if row["l2_Ma"] > args.stop_l2 or abs(row["Cd"] / CD_REF - 1) > args.stop_cd:
                write({"outer": n, "stopped": f"left the bounds: Mach L2 {row['l2_Ma']:.4f}, Cd {row['Cd']:.5f}"})
                break
        else:
            write(row)
        if n % args.keep_every == 0:
            torch.save(m.state_dict(), OUT / f"{args.tag}_outer{n}.pt")
    print("done", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--start", type=Path, default=RES / "weights" / "axisym_seed4.pt")
    ap.add_argument("--cfl", type=float, default=5.0)
    ap.add_argument("--k", type=float, default=0.0, help="Liu et al. shock down-weighting, 0 for none")
    ap.add_argument("--ell", type=float, default=0.0, help="length of the shock viscosity in Rt, 0 for none")
    ap.add_argument("--cl", type=float, default=0.0, help="linear part of the shock viscosity")
    ap.add_argument("--weight", type=float, default=1.0)
    ap.add_argument("--keep", default="sec,s,p0,bc", help="steady terms kept beside the time step")
    ap.add_argument("--outer", type=int, default=300)
    ap.add_argument("--inner", type=int, default=300)
    ap.add_argument("--every", type=int, default=5, help="outer steps between full diagnostics")
    ap.add_argument("--keep-every", type=int, default=50)
    ap.add_argument("--nx", type=int, default=360)
    ap.add_argument("--nr", type=int, default=48)
    ap.add_argument("--stop-l2", type=float, default=0.03, help="stop if Mach L2 passes the Step 3 gate")
    ap.add_argument("--stop-cd", type=float, default=0.005)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--device", default="cuda")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
