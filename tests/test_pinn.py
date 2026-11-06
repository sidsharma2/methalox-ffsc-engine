"""PINN residuals and analytic references. Needs torch; run from the PINN environment:
    <env>/python -m pytest tests/test_pinn.py
"""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from pinn import axisym, paper_cd  # noqa: E402
from pinn.core import ddx  # noqa: E402
from pinn.nozzle1d import area_ratio, isentropic, normal_shock, solve  # noqa: E402
from pinn.paper_integrals import ParabolicNozzle  # noqa: E402
from pinn.quasi1d import Nozzle, Quasi1D, impulse_balance, tensor  # noqa: E402

G = 1.126


def mach(xi):
    """A smooth Mach number that passes through 1 at xi = 0; area_ratio(mach(xi)) then defines an exact nozzle."""
    return 1 + 0.4 * xi + 0.02 * xi ** 2


def exact(xi, g=G):
    M = mach(xi)
    T = 1 / (1 + (g - 1) / 2 * M ** 2)
    p = T ** (g / (g - 1))
    rho = T ** (1 / (g - 1))
    return rho, M * torch.sqrt(T), T, p


def area_t(xi, g=G):
    M = mach(xi)
    return (1 / M) * ((2 / (g + 1)) * (1 + (g - 1) / 2 * M ** 2)) ** ((g + 1) / (2 * (g - 1)))


class ExactNozzle:
    gamma, xi0, xie = G, -1.5, 5.0

    def points(self, n):
        return np.linspace(self.xi0, self.xie, n)

    def A(self, xi):
        return area_ratio(mach(np.asarray(xi, float)), G)

    def dA(self, xi):
        x = tensor(xi).requires_grad_(True)
        return ddx(area_t(x), x).detach().numpy().ravel()


@pytest.mark.parametrize("form", ["paper", "logvars", "integrals"])
def test_quasi1d_residuals_vanish_on_exact_solution(form):
    nz = ExactNozzle()
    inlet = {k: v.item() for k, v in zip(("rho", "v", "T", "p"), exact(tensor([nz.xi0])), strict=True)}
    m = Quasi1D(nz, form, 0, p_exit=exact(tensor([nz.xie]))[3].item(), inlet=inlet, n=300)
    m.state = lambda xi, A: exact(xi)
    t = m.terms()
    for k in ("F1", "F2", "F3", "F4", "s"):
        if k in t:
            assert t[k].item() < 1e-22, k
    assert t["bc"].item() < 1e-22


def test_integrals_form_holds_mass_and_enthalpy_for_any_network():
    """Untrained network: mdot and total enthalpy are exact by construction, whatever v(x) is."""
    nz = ExactNozzle()
    m = Quasi1D(nz, "integrals", 3, n=50)
    xi = np.linspace(nz.xi0, nz.xie, 200)
    q = m.predict(xi)
    assert np.ptp(q["rho"] * q["v"] * nz.A(xi)) < 1e-12
    assert np.ptp(q["T"] + (G - 1) / 2 * q["v"] ** 2) < 1e-12
    # the impulse identity the residual relies on: (g rho v^2 + p) A = mdot (g v + T/v), with A cancelled
    mdot = q["rho"] * q["v"] * nz.A(xi)
    impulse = (G * q["rho"] * q["v"] ** 2 + q["p"]) * nz.A(xi)
    assert np.abs(impulse / (mdot * (G * q["v"] + q["T"] / q["v"])) - 1).max() < 1e-12


def test_choked_mdot_is_the_sonic_throat_value():
    m = Quasi1D(ExactNozzle(), "integrals", 0, n=50)
    p, rho, T = isentropic(1.0, G)
    assert m.mdot.item() == pytest.approx(rho * np.sqrt(T), rel=1e-13)


def test_integrals_ansatz_is_sonic_at_the_throat_for_any_network():
    nz = ExactNozzle()
    for seed in range(3):
        m = Quasi1D(nz, "integrals", seed, n=50)
        q = m.predict(np.array([0.0]))
        assert q["M"][0] == pytest.approx(1.0, abs=1e-12)


def test_integrals_residual_sees_the_area_change():
    """A trained-looking state with the wrong area slope must not pass: guards the cancelled-area form."""
    nz = ExactNozzle()
    m = Quasi1D(nz, "integrals", 0, n=300)
    m.state = lambda xi, A: exact(xi)
    m.dA_c = m.dA_c * 1.1
    assert m.terms()["F2"].item() > 1e-6


def test_impulse_balance_converges_at_second_order_on_the_exact_solution():
    nz = ExactNozzle()

    def worst(n):
        xi = np.linspace(nz.xi0, nz.xie, n)
        _, v, T, _ = exact(tensor(xi))
        return impulse_balance(v, T, tensor(nz.A(xi)), G).abs().max().item()

    assert worst(801) < 1e-5
    assert worst(201) / worst(801) == pytest.approx(16, rel=0.05)


def test_impulse_balance_takes_a_sharp_shock_and_charges_a_smeared_one_by_its_width():
    """The reason for the integral form: the strong form charges a shock of width d about 1/d, this one about d."""
    nz = ParabolicNozzle()
    x = np.linspace(nz.xi0, nz.xie, 4001)
    shocked = solve(x, paper_cd.PB, nz.A, 0.0, 1.0, nz.gamma)
    smooth = solve(x, None, nz.A, 0.0, 1.0, nz.gamma)
    xs = shocked["x_shock"]

    def cost(width):
        f = np.clip((x - xs) / width, 0, 1) if width else (x >= xs).astype(float)
        v = tensor(shocked["v"] * f + smooth["v"] * (1 - f))
        T = 1 - (nz.gamma - 1) / 2 * v ** 2
        return (impulse_balance(v, T, tensor(nz.A(x)), nz.gamma) ** 2).mean().item()

    assert cost(0) < 1e-9
    assert cost(0.01) > 100 * cost(0)
    assert 1.5 < cost(0.04) / cost(0.02) < 2.5


def directional_check(model):
    """Autograd against a central difference along a random direction. A term that changes the loss without showing in
    its gradient, such as a scale detached inside the loss, fails here. It would otherwise only show as L-BFGS stopping."""
    params = [p for p in model.parameters() if p.requires_grad]
    torch.manual_seed(1)
    d = [torch.randn_like(p) for p in params]
    grads = torch.autograd.grad(sum(model.terms().values()), params)
    exact = sum((g * x).sum() for g, x in zip(grads, d, strict=True)).item()

    def at(step):
        with torch.no_grad():
            for p, x in zip(params, d, strict=True):
                p.add_(step * x)
        value = sum(model.terms().values()).item()
        with torch.no_grad():
            for p, x in zip(params, d, strict=True):
                p.sub_(step * x)
        return value

    return exact, (at(1e-6) - at(-1e-6)) / 2e-6


def test_integral_balance_loss_has_its_true_gradient():
    exact, numeric = directional_check(Quasi1D(Nozzle(), "integrals", 0, weak=True, n=300, width=16, depth=2))
    assert exact == pytest.approx(numeric, rel=1e-5)


def test_axisym_loss_has_its_true_gradient():
    exact, numeric = directional_check(axisym.Axisym(Nozzle(), 0, nx=24, nr=6, width=16, depth=2))
    assert exact == pytest.approx(numeric, rel=1e-5)


def test_pseudo_time_step_starts_from_the_steady_residual():
    from pinn.pseudo import PseudoTime

    m = axisym.Axisym(Nozzle(), 0, nx=24, nr=6, width=16, depth=2)
    step = PseudoTime(m, 5.0, keep=[])
    f = m.grid_fields()
    rx, rr, _ = axisym.fv_residuals(m.x_t, m.r_t, f["psi"], f["u"], f["v"], f["p"], m.g)
    steady = ((rx / m.scale) ** 2 + (rr / m.scale) ** 2).mean().item()
    assert step.terms()["pt"].item() == pytest.approx(steady, rel=1e-12)


def test_pseudo_time_loss_has_its_true_gradient():
    from pinn.pseudo import PseudoTime

    m = axisym.Axisym(Nozzle(), 0, nx=24, nr=6, width=16, depth=2)
    step = PseudoTime(m, 5.0, k=0.1)
    params = list(m.parameters())
    with torch.no_grad():                    # move off the snapshot, so the time term is not zero
        for p in params:
            p.add_(1e-3 * torch.randn_like(p))
    torch.manual_seed(1)
    d = [torch.randn_like(p) for p in params]
    exact = sum((g * x).sum() for g, x in zip(torch.autograd.grad(sum(step.terms().values()), params), d, strict=True)).item()

    def at(h):
        with torch.no_grad():
            for p, x in zip(params, d, strict=True):
                p.add_(h * x)
        value = sum(step.terms().values()).item()
        with torch.no_grad():
            for p, x in zip(params, d, strict=True):
                p.sub_(h * x)
        return value

    assert exact == pytest.approx((at(1e-6) - at(-1e-6)) / 2e-6, rel=1e-5)


def test_shock_viscosity_acts_in_compression_only():
    from pinn.pseudo import PseudoTime

    m = axisym.Axisym(Nozzle(), 0, nx=24, nr=6, width=16, depth=2)
    step = PseudoTime(m, 5.0, ell=0.1, cl=0.3)
    x = m.x_t[:, None] * torch.ones_like(m.r_t)
    base = {"rho": torch.ones_like(x), "T": torch.ones_like(x), "v": torch.zeros_like(x)}
    assert step.stress({**base, "u": 1 + 0.05 * x}).abs().max().item() == 0
    assert step.stress({**base, "u": 3 - 0.05 * x}).min().item() > 0


def test_shock_viscosity_off_gives_the_plain_step():
    from pinn.pseudo import PseudoTime

    m = axisym.Axisym(Nozzle(), 0, nx=24, nr=6, width=16, depth=2)
    plain, off = PseudoTime(m, 5.0), PseudoTime(m, 5.0, ell=0.0, cl=0.3)
    assert sum(off.terms().values()).item() == sum(plain.terms().values()).item()


def test_pseudo_time_loss_with_shock_viscosity_has_its_true_gradient():
    from pinn.pseudo import PseudoTime

    m = axisym.Axisym(Nozzle(), 0, nx=24, nr=6, width=16, depth=2)
    step = PseudoTime(m, 5.0, ell=0.1, cl=0.3)
    params = list(m.parameters())
    with torch.no_grad():
        for p in params:
            p.add_(1e-2 * torch.randn_like(p))
    torch.manual_seed(1)
    d = [torch.randn_like(p) for p in params]
    exact = sum((g * x).sum() for g, x in zip(torch.autograd.grad(sum(step.terms().values()), params), d, strict=True)).item()

    def at(h):
        with torch.no_grad():
            for p, x in zip(params, d, strict=True):
                p.add_(h * x)
        value = sum(step.terms().values()).item()
        with torch.no_grad():
            for p, x in zip(params, d, strict=True):
                p.sub_(h * x)
        return value

    assert exact == pytest.approx((at(1e-6) - at(-1e-6)) / 2e-6, rel=1e-5)


def test_axisym_balance_gives_zero_for_a_uniform_pressure():
    x = axisym.ten(np.linspace(0, 3, 9))
    eta = np.linspace(0, 1, 6)
    r = axisym.ten(np.outer(1 + 0.3 * np.sin(np.linspace(0, 3, 9)), eta))
    zero = torch.zeros_like(r)
    rx, rr, _ = axisym.fv_residuals(x, r, zero, zero, zero, 0.7 + zero, G)
    assert rx.abs().max().item() < 1e-14
    assert rr.abs().max().item() < 1e-14


def test_axisym_balance_converges_at_second_order_on_a_source_flow():
    """Isentropic spherical source flow in a cone: an exact Euler solution with curved pressure lines, so the wall
    pressure force, the hoop term and the axis are all tested."""
    tab = np.linspace(1.0, 8.0, 400001)
    ar = area_ratio(tab, G)

    def worst(n):
        xs = np.linspace(1.5, 4.0, n + 1)
        X, E = np.meshgrid(xs, np.linspace(0, 1, n // 2 + 1), indexing="ij")
        r = E * X * np.tan(0.3)
        rs, th = np.hypot(X, r), np.arctan2(r, X)
        M = np.interp(rs ** 2, ar, tab)
        T = 1 / (1 + (G - 1) / 2 * M ** 2)
        U = M * np.sqrt(T)
        rho = T ** (1 / (G - 1))
        psi = rho * U * rs ** 2 * (1 - np.cos(th))
        rx, rr, sc = axisym.fv_residuals(*[axisym.ten(a) for a in (xs, r, psi, U * np.cos(th), U * np.sin(th), rho * T)], G)
        return max((rx / sc).abs().max().item(), (rr / sc).abs().max().item())

    assert worst(80) < 1e-4
    # a cell residual is the truncation error (h^2) times the cell length (h)
    assert 7 < worst(40) / worst(80) < 9


def test_axisym_model_conserves_mass_and_keeps_wall_and_axis_for_any_network():
    nz = Nozzle()
    m = axisym.Axisym(nz, 3, nx=16, nr=8, width=16, depth=2)
    for xi in (-2.0, 0.0, 6.0, 14.0):
        x = nz.phys(np.full(4001, xi))
        R = float(nz.r(x[0]))
        eta = np.linspace(0, 1, 4001)
        q = m.predict(x, eta * R)
        assert abs(q["v"][0]) < 1e-14  # axis
        assert q["v"][-1] / q["u"][-1] == pytest.approx(float(nz.dr(x[0])), abs=1e-10)  # wall tangency
        flux = np.trapezoid(q["rho"] * q["u"] * eta * (R / nz.Rt) ** 2, eta)
        assert flux == pytest.approx(m.m.item(), rel=1e-5)


@pytest.mark.parametrize("form", ["noncons", "primflux"])
def test_paper_forms_vanish_on_exact_solution(form, monkeypatch):
    monkeypatch.setattr(paper_cd, "G", G)
    monkeypatch.setattr(paper_cd, "area", area_t)

    def darea(x):
        y = x.detach().clone().requires_grad_(True)
        return torch.autograd.grad(area_t(y).sum(), y)[0]

    monkeypatch.setattr(paper_cd, "darea", darea)
    c = paper_cd.Case(form, False, 0, n=300)
    c.state = exact
    x = torch.linspace(-1.5, 5, 300, dtype=torch.float64).reshape(-1, 1).requires_grad_(True)
    for F in c.residuals(x):
        assert (F ** 2).mean().item() < 1e-22


def test_paper_hard_pressure_is_exact_for_an_untrained_network():
    c = paper_cd.Case("noncons", False, 1, n=20)
    assert abs(c.state(c.x0)[3].item() - 1) < 1e-14
    assert abs(c.state(c.xe)[3].item() - paper_cd.PB) < 1e-14


def test_shock_solution_matches_the_paper_and_textbook_relations():
    x = np.linspace(0, 2.25, 2001)
    r = solve(x, 0.81017, paper_cd.area, 1.5, 1.0, 1.4)
    assert r["x_shock"] == pytest.approx(1.875, abs=1e-3)
    assert r["p"][-1] == pytest.approx(0.81017, abs=1e-4)
    M2, pr, rr, p0r = normal_shock(2.0, 1.4)  # NACA 1135 table values at M1 = 2
    assert (M2, pr, rr, p0r) == pytest.approx((0.5774, 4.5, 2.6667, 0.7209), abs=1e-3)
    assert isentropic(1.0, 1.4)[0] == pytest.approx(0.5283, abs=1e-4)
    assert area_ratio(2.0, 1.4) == pytest.approx(1.6875, abs=1e-4)


def test_wedge_corrections():
    """A wedge face is a flat triangle, so the full-nozzle factor is 2 pi / sin(theta), and exported radii read short by cos(theta / 2)."""
    import importlib.util
    import math
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("post_compare", root / "cfd" / "post_compare.py")
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)
    a = math.radians(axisym.WEDGE_DEG / 2)
    R = 0.3
    tri = (R * math.cos(a)) * (R * math.sin(a))      # triangle (0, 0), (R cos a, +-R sin a)
    assert math.isclose(pc.sector_factor(axisym.WEDGE_DEG) * tri, math.pi * R ** 2, rel_tol=1e-12)
    assert abs(pc.sector_factor(5.0) - 72.0915) < 1e-4
    ref = root / "results" / "pinn" / "reference_I2C_euler.npz"
    if ref.exists():
        nz = Nozzle()
        d = axisym.load_ref(str(ref), nz)
        e = (d["r"] / nz.r(d["x"])) ** 2
        assert 0.999 < e.max() < 1.001       # wall cells on a slanted column can sit just past the design contour


def test_columns():
    """Cells of a structured mesh, in any order, come back as columns sorted by radius."""
    from pinn.ensemble import columns

    x, r = np.meshgrid(np.arange(6.0), np.arange(1.0, 5.0), indexing="ij")
    k = np.random.default_rng(0).permutation(x.size)
    ref = {"x": (x + 0.01 * r).ravel()[k], "r": r.ravel()[k]}
    g = columns(ref, 4)
    assert g.shape == (6, 4)
    assert np.all(np.diff(ref["r"][g], axis=1) > 0)
    assert np.all(np.round(ref["x"][g]) == np.arange(6.0)[:, None])
