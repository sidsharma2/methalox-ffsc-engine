"""Step 3: steady axisymmetric Euler in the MFE-280 nozzle, against rhoCentralFoam with slip walls on the same contour.

Variables as in quasi1d.py: rho/rho0, p/p0, T/T0, velocity/a0, lengths in throat radii, x from the throat.

The network takes (x, e) with e = (r/R(x))^2 and gives a stream function correction and a speed correction.
  psi = m e F, F = 1 + (1 - e) N1     mass holds exactly, the wall and the axis are streamlines for any network
  U = 1-D speed, moved by N2          the 1-D flow is the starting point, so the supersonic branch needs no search
  T = 1 - (g-1)/2 U^2                 uniform total enthalpy, which also holds across a shock in steady flow
  rho = |rho U| / U, p = rho T

m is free through Cd, because a 2-D sonic line passes less than the 1-D mass flow. Only momentum is left to train, in
control-volume form on a structured grid of cells. Three things carried over from the 1-D study:
  - no derivative of the network across a shock, so a jump is legal
  - each balance is summed from the inlet to the station, so a small local bias cannot build up down the bell
  - the error is divided by the local pressure force. A relative impulse error e means a stagnation pressure error
    (1 + g M^2) e, about 17 e at this exit, so a loss on the impulse barely sees the bell

usage: python -m pinn.axisym --ref results/pinn/reference_I2C_euler.npz --out results/pinn/step3_axisym.json
"""

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .core import Mlp, fit, seed_all
from .nozzle1d import solve
from .quasi1d import Nozzle

ROOT = Path(__file__).resolve().parents[1]
DEVICE = torch.device("cpu")
P0, T0 = 40e6, 3803.62  # chamber state of the I2-C nozzle cases
WEDGE_DEG = 5.0      # sector angle of the CFD cases
XI_ISEN = 2.0  # upstream of this station no shock has formed and the flow is isentropic: the CFD has ln p0 of -0.001 at most
EPS = 0.02  # width of the rounded axis in the network's radial input


def ten(a):
    return torch.as_tensor(np.asarray(a, float), dtype=torch.float64, device=DEVICE)


def avg_j(a):
    """Node values to the middle of each segment of an x = const line."""
    return (a[:, 1:] + a[:, :-1]) / 2


def avg_i(a):
    """Node values to the middle of each segment of an eta = const line."""
    return (a[1:] + a[:-1]) / 2


def fv_residuals(x, r, psi, u, v, p, g):
    """Momentum out of each cell per radian, in units of p0 Rt^2, on nodes (nx+1, nr+1) with stations x (nx+1).

    Mass through a face is a difference of psi, so every cell conserves mass exactly. A uniform pressure gives exactly
    zero, the hoop term included. Returns the axial and radial residuals and the pressure force on each cell's section.
    """
    dx = (x[1:] - x[:-1])[:, None]
    mx = psi[:, 1:] - psi[:, :-1]  # through x = const faces, towards +x
    mr = psi[:-1] - psi[1:]  # through eta = const faces, towards +eta
    sx = (r[:, 1:] ** 2 - r[:, :-1] ** 2) / 2
    rb = avg_i(r)
    srx = -(r[1:] ** 2 - r[:-1] ** 2) / 2
    cx = g * mx * avg_j(u) + avg_j(p) * sx
    cr = g * mr * avg_i(u) + avg_i(p) * srx
    dxf = g * mx * avg_j(v)
    drf = g * mr * avg_i(v) + avg_i(p) * rb * dx
    pc = avg_i(avg_j(p))
    rx = cx[1:] - cx[:-1] + cr[:, 1:] - cr[:, :-1]
    rr = dxf[1:] - dxf[:-1] + drf[:, 1:] - drf[:, :-1] - pc * dx * (rb[:, 1:] - rb[:, :-1])
    return rx, rr, pc * avg_i(sx)


def entropy_rise(psi, s):
    """Rise of s through each cell, mass weighted: outflow of s minus inflow, over the mass passing through."""
    mx = psi[:, 1:] - psi[:, :-1]
    mr = psi[:-1] - psi[1:]
    ex = mx * avg_j(s)
    er = mr * avg_i(s)
    return (ex[1:] - ex[:-1] + er[:, 1:] - er[:, :-1]) / avg_i(mx)


def stations(nz, nx):
    """Stations along the nozzle, about four times denser at the throat than in the bell."""
    fine = np.linspace(nz.xi0, nz.xie, 20001)
    dens = 1 + 3 * np.exp(-((fine / 1.5) ** 2))
    c = np.concatenate([[0], np.cumsum((dens[1:] + dens[:-1]) / 2 * np.diff(fine))])
    xi = np.interp(np.linspace(0, c[-1], nx + 1), c, fine)
    xi[0], xi[-1] = nz.xi0, nz.xie
    return xi


class Axisym(nn.Module):
    def __init__(self, nozzle, seed, nx=320, nr=40, width=64, depth=5):
        super().__init__()
        seed_all(seed)
        self.nz, self.g, self.nx, self.nr = nozzle, nozzle.gamma, nx, nr
        g = self.g
        self.net = Mlp(2, 2, width, depth).double().to(DEVICE)
        self.lncd = nn.Parameter(torch.zeros((), dtype=torch.float64, device=DEVICE))
        self.m1d = 0.5 * (2 / (g + 1)) ** ((g + 1) / (2 * (g - 1)))  # 1-D choked mass flow per radian
        self.vmax = math.sqrt(2 / (g - 1))
        self.fine = np.linspace(nozzle.xi0, nozzle.xie, 12001)
        self.ref1d = solve(self.fine, None, nozzle.A, 0.0, 1.0, g)
        self.s0, self.se = math.asinh(2 * nozzle.xi0), math.asinh(2 * nozzle.xie)
        self.xi = stations(nozzle, nx)
        self.eta = np.linspace(0, 1, nr + 1)
        x, eta = np.meshgrid(self.xi, self.eta, indexing="ij")
        self.X, self.E = ten(x.ravel()), ten(eta.ravel() ** 2)
        self.geo = self.geometry(x.ravel())
        self.x_t = ten(self.xi)
        self.r_t = ten(eta * self.nz.r(self.nz.phys(x)) / self.nz.Rt)
        # pressure force on each cell's section in the 1-D flow: a fixed scale, so the gradient is the true gradient of
        # the loss. A detached local value stops L-BFGS at once
        p1 = ten(avg_i(np.interp(self.xi, self.fine, self.ref1d["p"])))[:, None]
        self.scale = p1 * avg_i((self.r_t[:, 1:] ** 2 - self.r_t[:, :-1] ** 2) / 2)
        self.i0 = int(np.argmin(np.abs(self.xi)))  # balances run out from the throat, both ways, as in the 1-D form
        self.i_isen = int(np.searchsorted(self.xi, XI_ISEN))

    def geometry(self, xi):
        """Wall radius, its slope and the logit of the 1-D speed at stations xi: constants for the network."""
        x = self.nz.phys(xi)
        vs = np.interp(xi, self.fine, self.ref1d["v"]) / self.vmax
        return ten(self.nz.r(x) / self.nz.Rt), ten(self.nz.dr(x)), ten(np.log(vs / (1 - vs)))

    @property
    def m(self):
        return self.m1d * torch.exp(self.lncd)

    def state(self, xi, e, geo, graph=True):
        """Fields on flat stations xi, e. The wall has e = 1, the axis e = 0."""
        R, dR, logit = geo
        xi = xi.detach().requires_grad_(True)
        e = e.detach().requires_grad_(True)
        with torch.enable_grad():
            # e itself would squeeze r < 0.1 R into 1 % of the input range, and the axis shock lives there. This stays even
            # in r and smooth at the axis, and is close to r/R everywhere else
            h = (torch.sqrt(e + EPS ** 2) - EPS) / (math.sqrt(1 + EPS ** 2) - EPS)
            o = self.net(torch.stack([2 * (torch.asinh(2 * xi) - self.s0) / (self.se - self.s0) - 1, 2 * h - 1], 1))
            F = 1 + 0.2 * (1 - e) * o[:, 0]
            Fx, Fe = torch.autograd.grad(F.sum(), (xi, e), create_graph=graph)
        G = F + e * Fe
        m = self.m
        rhou = 2 * m * G / R ** 2
        rhov = m * torch.sqrt(e) / R * (2 * G * dR / R - Fx)
        U = self.vmax * torch.sigmoid(logit + 0.3 * o[:, 1])
        flux = torch.sqrt(rhou ** 2 + rhov ** 2)
        T = 1 - (self.g - 1) / 2 * U ** 2
        rho = flux / U
        return {"psi": m * e * F, "rho": rho, "u": U * rhou / flux, "v": U * rhov / flux, "T": T, "p": rho * T, "U": U}

    def grid_fields(self):
        """Fields on the nodes of the control-volume grid, shape (nx + 1, nr + 1)."""
        q = self.state(self.X, self.E, self.geo)
        return {k: q[k].reshape(self.nx + 1, self.nr + 1) for k in ("psi", "rho", "u", "v", "p", "T")}

    def terms(self, f=None, q=None, s_weight=None):
        """Loss terms. q is an extra pressure in the momentum balances only, s_weight scales the entropy hinge cell by cell."""
        g = self.g
        f = self.grid_fields() if f is None else f
        psi, u, v, p, T = [f[k] for k in ("psi", "u", "v", "p", "T")]
        rx, rr, _ = fv_residuals(self.x_t, self.r_t, psi, u, v, p if q is None else p + q, g)
        scale = self.scale
        lnp0 = torch.log(p) - g / (g - 1) * torch.log(T)

        def running(a):
            c = torch.cumsum(a, 0)
            return c - c[self.i0:self.i0 + 1]

        t = {"Mx": (running(rx) / scale).pow(2).mean(), "Mr": (running(rr) / scale).pow(2).mean()}
        # the whole section, the balance that sets the thrust, with the exit counted again as in the 1-D form
        sec = running(rx.sum(1, keepdim=True)) / scale.sum(1, keepdim=True)
        t["sec"] = sec.pow(2).mean() + 10 * sec[-1].pow(2).sum()
        # second law: stagnation pressure can only fall along the flow, and starts from 1 everywhere. Before the first shock
        # it cannot fall at all. Without that, a small loss near the throat is cheap, and Cd and the thrust scale with it
        dx = (self.x_t[1:] - self.x_t[:-1])[:, None]
        hinge = torch.relu(-entropy_rise(psi, -lnp0)) ** 2 / dx
        t["s"] = (hinge if s_weight is None else s_weight * hinge).sum(0).mean()
        t["p0"] = torch.relu(lnp0).pow(2).mean() + 10 * lnp0[:self.i_isen].pow(2).mean()
        t["bc"] = 10 * (lnp0[0].pow(2).mean() + (v[0] / u[0]).pow(2).mean())
        return t

    def predict(self, x, r, batch=40000):
        """Numpy fields at physical stations (x, r) in metres."""
        xi = (np.asarray(x, float) - self.nz.x_t) / self.nz.Rt
        xi = np.clip(xi, self.nz.xi0, self.nz.xie)
        out = {}
        for k in range(0, len(xi), batch):
            s = xi[k:k + batch]
            geo = self.geometry(s)
            e = torch.clamp((ten(np.asarray(r, float)[k:k + batch]) / self.nz.Rt / geo[0]) ** 2, 0, 1)
            q = self.state(ten(s), e, geo, graph=False)
            for n, v in q.items():
                out.setdefault(n, []).append(v.detach().cpu().numpy())
        out = {n: np.concatenate(v) for n, v in out.items()}
        out["Ma"] = out["U"] / np.sqrt(np.maximum(out["T"], 1e-12))
        return out

    def integrals(self):
        """Cd and the vacuum thrust ratio, both against the 1-D flow with the same chamber state and throat."""
        g = self.g
        eta = np.linspace(0, 1, 2001)
        xe = self.nz.phys(self.nz.xie)
        Re = float(self.nz.r(xe)) / self.nz.Rt
        q = self.predict(np.full_like(eta, xe), eta * Re * self.nz.Rt)
        rc = eta * Re
        F = 2 * np.trapezoid((g * q["rho"] * q["u"] ** 2 + q["p"]) * rc, rc)  # over p0 A*
        r1 = self.ref1d
        F1 = (g * r1["rho"][-1] * r1["v"][-1] ** 2 + r1["p"][-1]) * Re ** 2
        return {"Cd": math.exp(self.lncd.item()), "eta_cf_vac": F / F1, "Ma_axis_exit": float(q["Ma"][0]), "Ma_wall_exit": float(q["Ma"][-1])}


def load_ref(path, nz):
    """Reference cells, restricted to the nozzle, in the PINN's variables."""
    d = np.load(path, allow_pickle=False)
    meta = json.loads(str(d["meta"]))
    gas = meta["gas"]
    rho0 = P0 / (gas["R"] * T0)
    a0 = math.sqrt(gas["gamma"] * gas["R"] * T0)
    # make_case.py puts the wedge vertices at (r cos a, +-r sin a), so a cell centre sits at y = r cos a on the mid-plane.
    r = d["r"] / math.cos(math.radians(WEDGE_DEG / 2))
    return {"x": d["x"], "r": r, "vol": d["vol"], "rho": d["rho"] / rho0, "p": d["p"] / P0, "T": d["T"] / T0,
            "Ma": d["Ma"], "u": d["Ux"] / a0, "v": d["Ur"] / a0, "meta": meta}


def compare(model, ref):
    q = model.predict(ref["x"], ref["r"])
    w = ref["vol"]
    out = {}
    pairs = {"Ma": (q["Ma"], ref["Ma"]), "lnp": (np.log(q["p"]), np.log(ref["p"])), "T": (q["T"], ref["T"]), "rho": (q["rho"], ref["rho"])}
    for k, (a, b) in pairs.items():
        out[f"l2_{k}"] = float(np.linalg.norm(a - b) / np.linalg.norm(b))
        out[f"l2v_{k}"] = float(np.sqrt(np.sum(w * (a - b) ** 2) / np.sum(w * b ** 2)))
    out["max_err_Ma"] = float(np.abs(q["Ma"] - ref["Ma"]).max())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--adam", type=int, default=20000)
    ap.add_argument("--lbfgs", type=int, default=8000)
    ap.add_argument("--nx", type=int, default=320)
    ap.add_argument("--nr", type=int, default=40)
    ap.add_argument("--width", type=int, default=64)
    ap.add_argument("--depth", type=int, default=5)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--save", default=None, help="folder for the trained weights")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    global DEVICE
    DEVICE = torch.device(a.device)
    nz = Nozzle()
    ref = load_ref(a.ref, nz)
    rows = []
    for seed in a.seeds:
        m = Axisym(nz, seed, nx=a.nx, nr=a.nr, width=a.width, depth=a.depth)
        t0 = time.time()
        hist = fit(list(m.parameters()), m.terms, adam=a.adam, lbfgs=a.lbfgs, log_every=500)
        r = {"seed": seed, "seconds": time.time() - t0, "final": hist[-1], **m.integrals(), **compare(m, ref)}
        rows.append(r)
        print(json.dumps({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items() if k != "final"}), flush=True)
        print(json.dumps({k: float(f"{v:.3e}") for k, v in hist[-1].items() if isinstance(v, float)}), flush=True)
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        cfg = {"nx": a.nx, "nr": a.nr, "width": a.width, "depth": a.depth, "adam": a.adam, "lbfgs": a.lbfgs, "device": a.device, "ref": a.ref}
        out.write_text(json.dumps({"config": cfg, "runs": rows, "history": hist[::10]}, indent=1), encoding="utf-8")
        if a.save:
            Path(a.save).mkdir(parents=True, exist_ok=True)
            torch.save(m.state_dict(), Path(a.save) / f"axisym_seed{seed}.pt")


if __name__ == "__main__":
    main()
