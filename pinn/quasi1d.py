"""Step 2: quasi-1-D PINN on the real MFE-280 contour, against the analytic area-Mach and normal-shock solution.

Same non-dimensional variables as the paper: rho/rho0, T/T0, p/p0, v/a0, area A/A*, length x/Rt from the throat.

forms
  paper      outputs rho, v, T, p; differential residuals, momentum weight 20, hard pressure at both ends
  logvars    outputs ln rho, ln v, ln p; every residual is relative, so the 300:1 pressure range is balanced
  integrals  outputs v(x) and one number, mdot. Mass (rho v A = mdot) and total enthalpy (T + (g-1)/2 v^2 = 1) hold
             exactly, across a shock too, and only the conservative momentum equation is left to train. weak=True
             trains its integral form, the impulse balance from the inlet to every station

The integrals form needs no exit value for a supersonic exit. The velocity ansatz is sonic at the throat for any
network, and mdot takes the choked closed form. Without these the equations also accept a subsonic branch (the
paper's Fig. 5), a fully supersonic one, and unchoked flows with a smeared jump at the throat.

usage: python -m pinn.quasi1d --out results/pinn/step2_quasi1d.json [--seeds 0 1 2]
"""

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
from scipy.interpolate import PchipInterpolator
from torch import nn

from .core import Mlp, ddx, fit, seed_all
from .nozzle1d import _exit_pressure, solve

ROOT = Path(__file__).resolve().parents[1]
CASES = {"I2C": {"contour": "results/iterations/I2-C/contour.csv", "gamma": 1.1259970666897456, "x_in": 0.033}}
DEVICE = torch.device("cpu")


class Nozzle:
    """Contour as area ratio A/A* and its slope against x/Rt, with x measured from the throat in Rt."""

    def __init__(self, name="I2C"):
        c = CASES[name]
        d = np.loadtxt(ROOT / c["contour"], delimiter=",", skiprows=1)
        self.gamma = c["gamma"]
        self.r = PchipInterpolator(d[:, 0], d[:, 1])
        self.dr = self.r.derivative()
        fine = np.linspace(d[0, 0], d[-1, 0], 200001)
        k = np.argmin(self.r(fine))
        self.x_t, self.Rt = float(fine[k]), float(self.r(fine[k]))
        self.xi0 = (c["x_in"] - self.x_t) / self.Rt
        self.xie = (d[-1, 0] - self.x_t) / self.Rt

    def phys(self, xi):
        return self.x_t + self.Rt * np.asarray(xi, float)

    def A(self, xi):
        return (self.r(self.phys(xi)) / self.Rt) ** 2

    def dA(self, xi):
        x = self.phys(xi)
        return 2 * self.r(x) * self.dr(x) / self.Rt ** 2 * self.Rt  # d(A/A*)/d(x/Rt)

    def points(self, n):
        """Collocation stations: uniform, with a third of them added around the throat where the slope changes fast."""
        a = np.linspace(self.xi0, self.xie, n)
        b = np.linspace(-1.5, 1.5, n // 3)
        return np.sort(np.concatenate([a, b]))


def tensor(a):
    return torch.as_tensor(np.asarray(a, float), dtype=torch.float64, device=DEVICE).reshape(-1, 1)


def impulse_balance(v, T, A, g, scale=None, anchor=0):
    """Impulse balance from station `anchor` to every other one, w - w_a = int (T/v) d ln A, with w = g v + T/v and
    stations sorted. It takes no derivative of the network, so a jump is legal: a shock of width d costs about d here,
    where the strong form costs 1/d. It also reaches the exit directly, so a small local bias cannot build up.

    Anchor it at the sonic station for a choked flow. That state is exact, and w is stationary against v there, so
    an error made upstream could not be corrected on the way through.

    Divide by the pressure force pA, in these variables T/v, and not by the impulse. At high Mach the impulse hardly
    depends on entropy: a relative impulse error e means a stagnation pressure error (1 + g M^2) e, which is 17 e at the
    MFE-280 exit. Over pA the result reads directly as an error in ln p0, so the bell counts. For training pass a fixed
    scale. A detached local value changes the loss without showing in its gradient, which stops L-BFGS at once."""
    q = T / v
    w = g * v + q
    lnA = torch.log(A)
    I = torch.cat([torch.zeros_like(w[:1]), torch.cumsum((q[1:] + q[:-1]) / 2 * (lnA[1:] - lnA[:-1]), 0)])
    return (w - w[anchor] - (I - I[anchor])) / (q if scale is None else scale)


class Quasi1D(nn.Module):
    def __init__(self, nozzle, form, seed, pb=None, p_exit=None, inlet=None, width=50, depth=4, n=2000, gamma=None,
                 learn_gamma=False, data=None, choked=True, visc=0.0, l1_eps=0.0, weak=False, second_law=True):
        super().__init__()
        seed_all(seed)
        self.nz, self.form, self.pb, self.p_exit, self.inlet = nozzle, form, pb, p_exit, inlet
        self.choked, self.visc, self.l1_eps, self.weak, self.second_law = choked, visc, l1_eps, weak, second_law
        n_out = {"paper": 4, "logvars": 3, "integrals": 1}[form]
        self.net = Mlp(1, n_out, width, depth).double().to(DEVICE)
        self.lnm = nn.Parameter(torch.tensor(math.log(0.5), dtype=torch.float64, device=DEVICE), requires_grad=not choked)
        g0 = gamma or nozzle.gamma
        self.lng = nn.Parameter(torch.tensor(math.log(g0 - 1), dtype=torch.float64, device=DEVICE), requires_grad=learn_gamma)
        self.data = data  # (xi, ln p) for the inverse problem
        xi = nozzle.points(n)
        self.xi = tensor(xi).requires_grad_(True)
        self.A_c, self.dA_c = tensor(nozzle.A(xi)), tensor(nozzle.dA(xi))
        if weak:  # pressure force of the shock-free 1-D flow, a fixed scale that needs nothing from the solution sought
            r1 = solve(xi, None, nozzle.A, 0.0, 1.0, g0)
            self.scale, self.k0 = tensor(r1["T"] / r1["v"]), int(np.argmin(np.abs(xi)))
        self.w_mom = 20.0 if form == "paper" else 1.0
        self.A0, self.Ae = tensor(nozzle.A([nozzle.xi0])), tensor(nozzle.A([nozzle.xie]))
        self.xi_0, self.xi_e = tensor([nozzle.xi0]), tensor([nozzle.xie])

    @property
    def g(self):
        return 1 + torch.exp(self.lng)

    @property
    def mdot(self):
        """rho v A in units of rho0 a0 A*. Choked: the closed form, which forces M = 1 at the throat, since no other
        Mach number passes that flux through A*. Left free, nothing pulls the network up to it."""
        g = self.g
        return (2 / (g + 1)) ** ((g + 1) / (2 * (g - 1))) if self.choked else torch.exp(self.lnm)

    def s(self, xi):
        return (xi - self.nz.xi0) / (self.nz.xie - self.nz.xi0)

    def state(self, xi, A):
        """(rho, v, T, p) on stations xi with area ratio A."""
        s = self.s(xi)
        o = self.net(2 * s - 1)
        g = self.g
        if self.form == "paper":
            p0, pe = self.inlet["p"], self.p_exit
            p = s * (1 - s) * o[:, 3:4] + p0 + (pe - p0) * s
            return o[:, 0:1], o[:, 1:2], o[:, 2:3], p
        if self.form == "logvars":
            lp0, lpe = math.log(self.inlet["p"]), math.log(self.p_exit)
            rho, v = torch.exp(o[:, 0:1]), torch.exp(o[:, 1:2])
            p = torch.exp(s * (1 - s) * o[:, 2:3] + lp0 + (lpe - lp0) * s)
            return rho, v, p / rho, p
        # sonic at the throat for any network, subsonic before it and supersonic after it to start with: the raw value is
        # the sonic one plus z (k + N), and z changes sign at xi = 0. asinh keeps the long bell from saturating the sigmoid
        vmax = torch.sqrt(2 / (g - 1))
        vs = torch.sqrt(2 / (g + 1)) / vmax
        v = vmax * torch.sigmoid(torch.log(vs / (1 - vs)) + torch.asinh(xi) * (0.7 + o))
        rho = self.mdot / (v * A)
        T = 1 - (g - 1) / 2 * v ** 2
        return rho, v, T, rho * T

    def terms(self):
        xi, A, dA, g = self.xi, self.A_c, self.dA_c, self.g
        rho, v, T, p = self.state(xi, A)
        t = {}
        if self.form == "paper":
            rho_x, v_x, T_x, p_x = ddx(rho, xi), ddx(v, xi), ddx(T, xi), ddx(p, xi)
            t["F1"] = ((A * v * rho_x + A * rho * v_x + v * rho * dA) ** 2).mean()
            t["F2"] = self.w_mom * ((A * (g * rho * v * v_x + p_x)) ** 2).mean()
            t["F3"] = ((A * v * rho * T_x + (g - 1) * p * (A * v_x + v * dA)) ** 2).mean()
            t["F4"] = ((p - rho * T) ** 2).mean()
        elif self.form == "logvars":
            lnr, lnv, lnp = torch.log(rho), torch.log(v), torch.log(p)
            d_r, d_v, d_p = ddx(lnr, xi), ddx(lnv, xi), ddx(lnp, xi)
            t["F1"] = ((d_r + d_v + dA / A) ** 2).mean()
            t["F2"] = ((g * v ** 2 / T * d_v + d_p) ** 2).mean()
            t["F3"] = ((d_p - d_r + (g - 1) * v ** 2 / T * d_v) ** 2).mean()
        elif self.weak:
            R = impulse_balance(v, T, A, g, self.scale, self.k0)
            t["F2"] = (R ** 2).mean()
            # the mean hardly sees one station, so the network could meet the exit value with a false jump at the very end
            t["Fe"] = 10 * R[-1:].pow(2).sum()
            if self.second_law:  # int (d ln p0/dx)^2 dx over the parts where stagnation pressure rises
                lnp0 = torch.log(T / v) - g / (g - 1) * torch.log(T) - torch.log(A)
                t["s"] = (torch.relu(lnp0[1:] - lnp0[:-1]) ** 2 / (xi[1:] - xi[:-1]).detach().clamp_min(1e-9)).sum()
        else:
            # impulse (g rho v^2 + p) A = mdot (g v + T/v): the area cancels, so the conservative form needs no dA/dx of it.
            # A strong-form L2 loss on bare Euler charges a shock of width d about 1/d, so it smears the entropy rise
            # along the nozzle. The von Neumann-Richtmyer pressure, active only in compression, gives the shock a
            # profile with zero residual, and the jump stays right because it enters the conservative flux.
            w = g * v + T / v
            if self.visc:
                w = w + g * self.visc ** 2 * torch.relu(-ddx(v, xi)) ** 2 / v
            R = (ddx(w, xi) - T / v * dA / A) / w
            t["F2"] = (torch.sqrt(R ** 2 + self.l1_eps ** 2) - self.l1_eps).mean() if self.l1_eps else (R ** 2).mean()
            # second law: local stagnation pressure may only fall. The jump relations alone also admit expansion shocks.
            # ln p0 = ln(mdot T / (v A)) - g/(g-1) ln T, with the area term written out for the same reason
            t["s"] = (torch.relu(ddx(torch.log(T / v) - g / (g - 1) * torch.log(T), xi) - dA / A) ** 2).mean()
        if self.form in ("paper", "logvars"):
            r0, _, T0, _ = self.state(self.xi_0, self.A0)
            t["bc"] = (r0 - self.inlet["rho"]).pow(2).sum() + (T0 - self.inlet["T"]).pow(2).sum()
        else:
            r0, v0, T0, p0 = self.state(self.xi_0, self.A0)
            t["bc"] = 10 * (torch.log(p0) - g / (g - 1) * torch.log(T0)).pow(2).sum()  # inlet stagnation pressure
            # the flow enters subsonic: a fully supersonic solution with a tiny mdot also meets every other term
            t["sub"] = torch.relu(v0 / torch.sqrt(T0) - 0.9).pow(2).sum()
            re, ve, Te, pe = self.state(self.xi_e, self.Ae)
            if self.pb is not None:
                t["exit"] = 10 * (torch.log(pe) - math.log(self.pb)).pow(2).sum()
            else:
                t["exit"] = torch.relu(1.5 - ve / torch.sqrt(Te)).pow(2).sum()
        if self.data is not None:
            xd, Ad, lpd = self.data
            t["data"] = 10 * ((torch.log(self.state(xd, Ad)[3]) - lpd) ** 2).mean()
        return t

    def predict(self, xi):
        """Numpy dict on stations xi."""
        with torch.no_grad():
            rho, v, T, p = [q.cpu().numpy().ravel() for q in self.state(tensor(xi), tensor(self.nz.A(xi)))]
        return {"rho": rho, "v": v, "T": T, "p": p, "M": v / np.sqrt(np.maximum(T, 1e-12))}


def isp_measure(q, A, g):
    """Vacuum Isp up to a constant, at the last station: thrust over mass flow in the non-dimensional variables."""
    return float((g * q["rho"][-1] * q["v"][-1] ** 2 + q["p"][-1]) / (q["rho"][-1] * q["v"][-1]))


def compare(model, xi, ref, g, xi_search=0.5):
    q = model.predict(xi)
    d = {"finite": bool(np.isfinite(q["p"] + q["M"] + q["rho"]).all() and (q["p"] > 0).all())}
    if not d["finite"]:
        return d
    # Euler is unchanged by v -> -v and the paper's form has nothing to fix the sign, so compare magnitudes and flag it
    d["reversed"] = bool(np.median(q["v"]) < 0)
    q["v"], q["M"] = np.abs(q["v"]), np.abs(q["M"])
    d["l2_lnp"] = float(np.linalg.norm(np.log(q["p"]) - np.log(ref["p"])) / np.linalg.norm(np.log(ref["p"])))
    d["l2_M"] = float(np.linalg.norm(q["M"] - ref["M"]) / np.linalg.norm(ref["M"]))
    d["max_err_M"] = float(np.abs(q["M"] - ref["M"]).max())
    d["M_exit"], d["M_exit_ref"] = float(q["M"][-1]), float(ref["M"][-1])
    d["p_exit"], d["p_exit_ref"] = float(q["p"][-1]), float(ref["p"][-1])
    d["isp_ratio"] = isp_measure(q, None, g) / isp_measure(ref, None, g)
    A = model.nz.A(xi)
    m = q["rho"] * q["v"] * A
    mref = (ref["rho"] * ref["v"] * A)[0]
    d["mdot_ratio"] = float(np.mean(m) / mref)
    d["mdot_spread"] = float(np.ptp(m) / np.mean(m))
    H = q["T"] + (g - 1) / 2 * q["v"] ** 2
    d["H_spread"] = float(np.ptp(H))
    if ref["x_shock"] is not None:
        k = np.argmax(np.abs(np.gradient(q["M"], xi)) * (xi > xi_search))
        d["xi_shock"], d["xi_shock_ref"] = float(xi[k]), float(ref["x_shock"])
    return d


def run(nz, form, seed, pb, ref, adam, lbfgs, xi, label, visc=0.0):
    inlet = {k: float(ref[k][0]) for k in ("rho", "T", "p")}
    if form == "weak":  # the integrals form, trained on its integral balance; the shock-free case has no use for the hinge
        m = Quasi1D(nz, "integrals", seed, pb=pb, weak=True, n=4000, second_law=pb is not None)
    else:
        m = Quasi1D(nz, form, seed, pb=pb, p_exit=float(ref["p"][-1]), inlet=inlet, visc=visc)
    t0 = time.time()
    hist = fit([p for p in m.parameters() if p.requires_grad], m.terms, adam=adam, lbfgs=lbfgs)
    return {"case": label, "form": form, "seed": seed, "seconds": time.time() - t0, "final": hist[-1],
            **compare(m, xi, ref, nz.gamma)}, m


def inverse(nz, seed, xd, lpd, adam, lbfgs, g_start=1.3):
    """Recover gamma from pressures at stations xd, integrals form; the exit hinge stays on."""
    data = (tensor(xd), tensor(nz.A(xd)), tensor(lpd))
    m = Quasi1D(nz, "integrals", seed, gamma=g_start, learn_gamma=True, data=data, weak=True, n=4000, second_law=False)
    hist = fit([p for p in m.parameters() if p.requires_grad], m.terms, adam=adam, lbfgs=lbfgs)
    return m.g.item(), hist[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--forms", nargs="+", default=["paper", "logvars", "integrals", "weak"])
    ap.add_argument("--adam", type=int, default=20000)
    ap.add_argument("--lbfgs", type=int, default=5000)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--xshock", type=float, default=5.0, help="shock station for the over-expanded case, x/Rt")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--visc", type=float, default=0.1, help="von Neumann-Richtmyer length for the shock case, x/Rt")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    global DEVICE
    DEVICE = torch.device(a.device)
    nz = Nozzle()
    g = nz.gamma
    xi = np.linspace(nz.xi0, nz.xie, 6001)
    smooth = solve(xi, None, nz.A, 0.0, 1.0, g)
    pb = _exit_pressure(a.xshock, nz.A, nz.xie, 1.0, g)
    shock = solve(xi, pb, nz.A, 0.0, 1.0, g)
    M1 = shock["M"][np.searchsorted(xi, shock["x_shock"]) - 1]
    print(f"gamma {g:.5f} Rt {nz.Rt:.4f} xi {nz.xi0:.3f}..{nz.xie:.3f} A0 {float(nz.A(nz.xi0)):.3f} Ae {float(nz.A(nz.xie)):.3f}", flush=True)
    print(f"smooth: Me {smooth['M'][-1]:.4f} pe/p0 {smooth['p'][-1]:.5f} (1:{1 / smooth['p'][-1]:.0f})  "
          f"shock case: x/Rt {shock['x_shock']:.3f} M1 {M1:.3f} pb/p0 {pb:.5f}", flush=True)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows, doc = [], {"gamma": g, "Me": float(smooth["M"][-1]), "pe": float(smooth["p"][-1]), "shock": {"xi": shock["x_shock"], "M1": float(M1), "pb": pb}}
    for label, ref, p_back in (("smooth", smooth, None), ("shock", shock, pb)):
        for form in a.forms:
            for seed in a.seeds:
                r, _ = run(nz, form, seed, p_back, ref, a.adam, a.lbfgs, xi, label, visc=a.visc if p_back else 0.0)
                rows.append(r)
                print(json.dumps({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items() if k != "final"}), flush=True)
                doc["runs"] = rows
                out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    # inverse problem: gamma from 50 pressures of the analytic solution, then from the CFD
    st = np.linspace(nz.xi0 + 0.05, nz.xie - 0.05, 50)
    rows_inv = []
    for seed in a.seeds:
        ga, f = inverse(nz, seed, st, np.log(np.interp(st, xi, smooth["p"])), a.adam, a.lbfgs)
        rows_inv.append({"data": "analytic", "seed": seed, "gamma": ga, "final": f})
        print("inverse analytic", seed, ga, flush=True)
        doc["inverse"] = rows_inv
        out.write_text(json.dumps(doc, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
