"""Line-of-sight images of the axisymmetric plume: knife-edge schlieren, shadowgraph and thermal emission.

A camera looks across the plume, rays along z, normal to the x-r plane, in the frame of render_plume.py. Each field
is averaged from the cells to the mesh points (VTK cell-to-point), the density gradient is the VTK gradient of that
point field, and the result is sampled on a regular (x, r) grid by linear interpolation. A ray at height y then
crosses the annular rings of the grid; OPD, deflection, radiance and optical depth are sums over rings with the
exact chord integrals of a ring of constant value, so the projection adds nothing the solver did not compute.
The shadowgraph Laplacian is the divergence of the two deflection images (central differences at pixel scale);
taking second derivatives on the mesh instead leaves a false line wherever the radial cell size changes.

Optics (Settles, Schlieren and Shadowgraph Techniques, 2001; Merzkirch, Flow Visualization, 1987):
    n - 1 = K rho, with one Gladstone-Dale constant K = 2.3e-4 m^3/kg (air, visible light)
    OPD(x, y)  = int (n - n_amb) dz                optical path difference
    eps        = grad OPD                          ray deflection (rad)
    knife-edge schlieren  I/I0 = 1 - (f/a) eps_k, clipped to [0, 2] (half of the source image cut)
    shadowgraph           I/I0 = 1 - L lap(OPD),  clipped to [0, 2] (small-deflection limit)
f/a and L are the instrument sensitivities. They are set so that the 99th percentile of the signal uses half of
the range, as an experimenter sets the knife edge, and the equivalent values are printed and written to JSON.

Thermal emission (grey gas, Planck-mean absorption coefficient):
    Z = (h0 - h0_amb)/(h0_jet - h0_amb), h0 = cp T + |U|^2/2. The CFD has one gas with constant cp and adiabatic
        walls, so h0 mixes as a passive scalar when the turbulent Prandtl and Schmidt numbers are equal.
    X_H2O, X_CO2: the exit composition from cfd/plume_composition.py, diluted with dry air by mass fraction Z.
        Frozen: no afterburning of the CO and H2 with the entrained air.
    kappa_P = (p / 1 atm) sum X_i a_i(T), with the RADCAL Planck-mean fits used by the TNF workshop (the numbers in
        OpenFOAM v2306 tutorials/combustion/reactingFoam/RAS/SandiaD_LTS/constant/radiationProperties), valid
        300-2500 K; T is clipped to that range for kappa only. CO, OH and soot are left out.
    optically thin   L = int kappa_P sigma T^4/pi dz   (W m^-2 sr^-1). Self-absorption only removes radiance, so
        this is an upper bound on any path.
    tau = int kappa_P dz along each ray is written as its own image: where tau > 1 the thin image overstates.
    No grey self-absorbing image: with the local Planck mean, a cool mixing layer (CO2 kappa_P is largest near
    600-1000 K, from the 15 um band) absorbs the 2000 K core radiation far more than a band model would, and the
    plume goes dark where it should not. That needs a band or WSGG model, which this script does not have.

usage (AetherCFD environment, reconstructed case on a Windows path):
    uv run --project D:/Research-Software/AetherCFD python cfd/render_los.py CASE NAME TAG OUTDIR [W H]
    NAME = the case name in cfd/cases/ and results/plume_exit_composition.json
"""
import json
import math
import sys
import time
from pathlib import Path

import matplotlib
import numpy as np
import vtk
from vtk.util import numpy_support as nps

from aethercfd.results import pipeline as P
from aethercfd.results.foam_reader import FoamResults, iter_leaves

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

try:
    import cupy as xp
    xp.zeros(1).sum()
except Exception:  # no CUDA: the grey-absorbing pass runs on the CPU
    xp = np

ROOT = Path(__file__).resolve().parents[1]
case, name, tag, outdir = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
W, H = (int(a) for a in (sys.argv[5:7] if len(sys.argv) > 6 else (1920, 1080)))
X_MIN, X_MAX = 0.15, 10.5
K_GD = 2.3e-4
P_ATM = 101325.0
SIGMA = 5.670374419e-8
AIR_MW = 28.965
T_FIT = (300.0, 2500.0)
# a_i(T) = sum_k c_k (1000/T)^k, 1/(m atm)
A_P = {"H2O": (-0.23093, -1.12390, 9.4153, -2.99885, 0.51382, -1.868e-5),
       "CO2": (18.741, -121.31, 273.5, -194.05, 56.31, -5.8169)}
BG = (0.06, 0.065, 0.075)
outdir.mkdir(parents=True, exist_ok=True)
t_start = time.time()

info = json.loads((ROOT / "cfd" / "cases" / name / "case_info.json").read_text())
comp = json.loads((ROOT / "results" / "plume_exit_composition.json").read_text())[name]
cp, R_gas = info["gas"]["cp"], info["gas"]["R"]
T0, rho_amb = info["bc"]["T0"], info["bc"]["rho_amb"]
T_amb = P_ATM / (R_gas * rho_amb)
R_far = info["mesh"]["R_far"]

dx = (X_MAX - X_MIN) / W
r_half = 0.5 * H * dx
ny, nr = H // 2, int(math.ceil(R_far / dx))
print(f"{name}: image {W} x {H}, pixel {1e3 * dx:.2f} mm, {nr} rings to R_far {R_far:.3f} m; "
      f"cp {cp:.1f}, T0 {T0:.1f} K, T_amb {T_amb:.1f} K; array module {xp.__name__}")

# --- fields, derivatives, sampling ---------------------------------------------------------------------------
fr = FoamResults(case)
fr.refresh()
walls = ["wall_chamber", "wall_bell", "lip", "wall_outer"]
leaves = dict(iter_leaves(fr.read(None, fields=["p", "T", "U", "rho"],
                                  patches=["internalMesh"] + [f"patch/{w}" for w in walls])))
ug = next(ds for n, ds in leaves.items() if n.endswith("internalMesh"))
ugp = P.cell_to_point(ug)
pd = ugp.GetPointData()
U = nps.vtk_to_numpy(pd.GetArray("U"))
h0 = cp * nps.vtk_to_numpy(pd.GetArray("T")) + 0.5 * np.einsum("ij,ij->i", U, U)
a = nps.numpy_to_vtk(h0, deep=True)
a.SetName("h0")
pd.AddArray(a)


def gradient(ds, arr, out):
    g = vtk.vtkGradientFilter()
    g.SetInputData(ds)
    g.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, arr)
    g.SetResultArrayName(out)
    g.Update()
    return g.GetOutput()


src = gradient(ugp, "rho", "grad_rho")
spd = src.GetPointData()
gr = nps.vtk_to_numpy(spd.GetArray("grad_rho"))
keep = {"rho_x": gr[:, 0], "rho_r": gr[:, 1]}
for k in [spd.GetArrayName(i) for i in range(spd.GetNumberOfArrays())]:
    if k not in ("rho", "T", "p", "h0"):
        spd.RemoveArray(k)
for k, v in keep.items():
    a = nps.numpy_to_vtk(np.ascontiguousarray(v), deep=True)
    a.SetName(k)
    spd.AddArray(a)
src.GetCellData().Initialize()

img = vtk.vtkImageData()
img.SetOrigin(X_MIN + 0.5 * dx, 0.5 * dx, 0.0)
img.SetSpacing(dx, dx, 1.0)
img.SetDimensions(W, nr, 1)
pf = vtk.vtkProbeFilter()
pf.SetInputData(img)
pf.SetSourceData(src)
pf.Update()
po = pf.GetOutput().GetPointData()
valid = nps.vtk_to_numpy(po.GetArray("vtkValidPointMask")).astype(bool).reshape(nr, W)
amb = {"rho": rho_amb, "T": T_amb, "p": P_ATM, "h0": cp * T_amb}
F = {}
for k in ("rho", "T", "p", "h0", "rho_x", "rho_r"):
    F[k] = np.where(valid, nps.vtk_to_numpy(po.GetArray(k)).reshape(nr, W), amb.get(k, 0.0))
del pf, po, src
print(f"sampled {valid.sum()} of {valid.size} grid points in the fluid ({time.time() - t_start:.0f} s)")

# --- nozzle silhouette from the wall patches (mid-plane cut, sampled at half a pixel) ---------------------------
r_out = np.full(W, -1.0)
for n, ds in leaves.items():
    if n.split("/")[-1] not in walls:
        continue
    pl = vtk.vtkPlane()
    pl.SetOrigin(0, 0, 0)
    pl.SetNormal(0, 0, 1)
    c = vtk.vtkCutter()
    c.SetCutFunction(pl)
    c.SetInputData(P.to_poly(ds))
    c.Update()
    cut = c.GetOutput()
    pts = nps.vtk_to_numpy(cut.GetPoints().GetData()) if cut.GetNumberOfPoints() else np.zeros((0, 3))
    for i in range(cut.GetNumberOfCells()):
        ids = cut.GetCell(i).GetPointIds()
        p0, p1 = pts[ids.GetId(0)], pts[ids.GetId(ids.GetNumberOfIds() - 1)]
        s = np.linspace(0.0, 1.0, max(2, int(np.hypot(*(p1 - p0)[:2]) / (0.5 * dx)) + 2))
        xs, rs = p0[0] + s * (p1[0] - p0[0]), np.abs(p0[1] + s * (p1[1] - p0[1]))
        col = np.floor((xs - X_MIN) / dx).astype(int)
        m = (col >= 0) & (col < W)
        np.maximum.at(r_out, col[m], rs[m])

# --- ring projection matrices -----------------------------------------------------------------------------------
y = (np.arange(ny) + 0.5) * dx
re_ = np.arange(nr + 1) * dx
Y = y[:, None]
on = re_[None, 1:] > Y
za = np.where(on, np.sqrt(np.maximum(np.maximum(re_[None, :-1], Y) ** 2 - Y ** 2, 0.0)), 0.0)
zb = np.where(on, np.sqrt(np.maximum(re_[None, 1:] ** 2 - Y ** 2, 0.0)), 0.0)
Lc = 2.0 * (zb - za)                                                           # int dz
Dm = 2.0 * Y * (np.arcsinh(zb / Y) - np.arcsinh(za / Y))                      # int y/r dz

opd = K_GD * (Lc @ (F["rho"] - rho_amb))
eps_x = K_GD * (Lc @ F["rho_x"])
eps_y = K_GD * (Dm @ F["rho_r"])

# --- emission ---------------------------------------------------------------------------------------------------
Z = np.clip((F["h0"] - cp * T_amb) / (cp * (T0 - T_amb)), 0.0, 1.0)
n_p, n_a = Z / comp["MW"], (1.0 - Z) / AIR_MW
u = 1000.0 / np.clip(F["T"], *T_FIT)
kappa = np.zeros_like(Z)
for sp, c in A_P.items():
    X = n_p * comp["X"][sp] / (n_p + n_a)
    kappa += X * sum(ck * u ** k for k, ck in enumerate(c))
kappa *= F["p"] / P_ATM
kappa = np.maximum(kappa, 0.0)
Bsrc = SIGMA * F["T"] ** 4 / math.pi
L_thin = Lc @ (kappa * Bsrc)
tau = Lc @ kappa
print(f"projections done ({time.time() - t_start:.0f} s)")


# --- full frame: top half is y > 0, the bottom half mirrors it ---------------------------------------------------
def frame(half, odd=False):
    return np.vstack([half[::-1], -half if odd else half])


yy = np.concatenate([y[::-1], -y])
sil = np.abs(yy)[:, None] <= r_out[None, :]
fluid_px = ~sil


def p99(a):
    return float(np.percentile(np.abs(a[fluid_px]), 99))


def save(img, fname, cmap, vmin, vmax, bad, label, bar=None, contours=None):
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    cm = plt.get_cmap(cmap).copy()
    cm.set_bad(bad)
    im = ax.imshow(np.ma.masked_where(sil, img), cmap=cm, vmin=vmin, vmax=vmax, interpolation="nearest",
                   extent=(X_MIN, X_MAX, -r_half, r_half), aspect="auto")
    if contours is not None:
        cs = ax.contour(X_MIN + (np.arange(W) + 0.5) * dx, yy[::-1], np.ma.masked_where(sil, contours[0])[::-1],
                        levels=contours[1], colors="white", linewidths=1.2)
        ax.clabel(cs, fmt=lambda v: f"tau = {v:g}", fontsize=14)
    fs = 9 * W / 1920
    if bar:
        cax = fig.add_axes([0.33, 0.035, 0.34, 0.012])
        cb = fig.colorbar(im, cax=cax, orientation="horizontal")
        cb.set_label(bar, color="0.85", fontsize=fs)
        cb.ax.tick_params(colors="0.85", labelsize=0.9 * fs)
        cb.outline.set_edgecolor("0.85")
    fig.text(0.008, 0.985, label, color="0.85" if cmap != "gray" else "0.1", fontsize=fs, va="top", family="sans-serif")
    path = outdir / f"los_{tag}_{fname}.png"
    fig.savefig(path, dpi=100, facecolor=BG)
    plt.close(fig)
    print("wrote", path)


EX, EY, OPD = frame(eps_x), frame(eps_y, odd=True), frame(opd)
LAP = np.gradient(EX, dx, axis=1) + np.gradient(EY, -dx, axis=0)   # rows run downwards, y decreases
S_x, S_y, S_l = 0.5 / p99(EX), 0.5 / p99(EY), 0.5 / p99(LAP)
lab = f"{name}, line of sight across the plume, K = {K_GD:g} m3/kg"
save(np.clip(1.0 - S_x * EX, 0.0, 2.0), "schlieren_x", "gray", 0.0, 2.0, "black",
     f"knife-edge schlieren, edge normal to x (axial gradients): full range +-{1e3 / S_x:.2f} mrad. {lab}")
save(np.clip(1.0 - S_y * EY, 0.0, 2.0), "schlieren_r", "gray", 0.0, 2.0, "black",
     f"knife-edge schlieren, edge normal to r (radial gradients): full range +-{1e3 / S_y:.2f} mrad. {lab}")
save(np.clip(1.0 - S_l * LAP, 0.0, 2.0), "shadowgraph", "gray", 0.0, 2.0, "black",
     f"shadowgraph, screen at L = {S_l:.2f} m (small-deflection limit). {lab}")

LT, TAU = frame(L_thin), frame(tau)
top = math.log10(np.max(LT[fluid_px]))
save(np.log10(np.maximum(LT, 1e-30)), "emission_thin", "inferno", top - 2.5, top, (0.25, 0.26, 0.28),
     f"{name}: H2O + CO2 thermal emission, optically thin (upper bound; see optical depth), Planck-mean kappa "
     f"(RADCAL fits), frozen exit composition diluted by h0 mixture fraction, no afterburning",
     bar="log10 radiance (W m-2 sr-1)")
save(TAU, "optical_depth", "viridis", 0.0, float(np.percentile(TAU[fluid_px], 99.9)), (0.25, 0.26, 0.28),
     f"{name}: Planck-mean optical depth along each ray; contours tau = 1 and 3", bar="optical depth tau",
     contours=(TAU, [1.0, 3.0]))

cols = {xx: int(round((xx - X_MIN) / dx - 0.5)) for xx in (2.0, 3.0, 4.0, 5.0, 7.0, 9.0) if X_MIN < xx < X_MAX}
summary = {"case": name, "tag": tag, "image": [W, H], "pixel_m": dx, "K_gladstone_dale": K_GD,
           "knife_x_f_over_a": S_x, "knife_x_full_range_rad": 1.0 / S_x,
           "knife_r_f_over_a": S_y, "knife_r_full_range_rad": 1.0 / S_y, "shadowgraph_L_m": S_l,
           "opd_range_m": [float(OPD[fluid_px].min()), float(OPD[fluid_px].max())],
           "tau_axis": {f"{k:g}": float(tau[0, c]) for k, c in cols.items()},
           "tau_max_in_frame": float(TAU[fluid_px].max()), "radiance_thin_max_in_frame": float(LT[fluid_px].max()),
           "T_amb": T_amb, "T0": T0, "cp": cp,
           "exit_composition": comp, "seconds": time.time() - t_start}
(outdir / f"los_{tag}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
np.savez_compressed(outdir / f"los_{tag}_grid.npz", kappa=kappa.astype(np.float32), B=Bsrc.astype(np.float32),
                    valid=valid, dx=dx, x0=X_MIN, r_out=r_out, opd=opd, eps_x=eps_x, eps_y=eps_y)
print(json.dumps({k: v for k, v in summary.items() if k != "exit_composition"}, indent=1))
