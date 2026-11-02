"""Perspective GPU volume render of the optically thin plume emission (CuPy ray marching).

Reads the (x, r) grid that cfd/render_los.py writes (los_<tag>_grid.npz: kappa_P and B = sigma T^4/pi on a
regular grid, the nozzle outline r_out(x)) and marches camera rays through the revolved field. Each sample takes
j = kappa_P B by bilinear interpolation at its own (x, r); the pixel value is the ray sum of j ds, the optically
thin radiance of render_los.py seen from an oblique camera instead of side-on. The same limits apply: an upper
bound, no self-absorption, no afterburning. The nozzle is an opaque body of revolution r <= r_out(x), shaded with
one light so its shape reads; rays stop at it.

usage (AetherCFD environment):
    uv run --project D:/Research-Software/AetherCFD python cfd/render_volume.py GRID.npz TAG OUTDIR [W H]
"""
import math
import sys
from pathlib import Path

import cupy as cp
import matplotlib
import numpy as np
from cupyx.scipy.ndimage import map_coordinates

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

grid, tag, outdir = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
W, H = (int(a) for a in (sys.argv[4:6] if len(sys.argv) > 5 else (1920, 1080)))
N_STEP = 1400
R_MARCH = 3.6                      # m; the frame of render_los.py reaches r = 2.9 m
BG = (0.06, 0.065, 0.075)

d = np.load(grid)
dx, x0 = float(d["dx"]), float(d["x0"])
j = (d["kappa"].astype(np.float64) * d["B"].astype(np.float64))      # W m^-3 sr^-1, rows r, columns x
r_out = d["r_out"]
nr, nx = j.shape
# the gas inside the nozzle is hidden by the wall; zero it so that samples just outside the wall do not
# interpolate chamber values (kappa_P is several hundred 1/m at chamber pressure)
j[(np.arange(nr)[:, None] + 0.5) * dx <= r_out[None, :] + 2.0 * dx] = 0.0
x1 = x0 + nx * dx
jg = cp.asarray(j, dtype=cp.float32)
ro = cp.asarray(np.where(r_out > 0, r_out, -1.0), dtype=cp.float32)
dro = cp.asarray(np.gradient(np.where(r_out > 0, r_out, 0.0), dx), dtype=cp.float32)

# camera: from the side, 35 degrees below the plume and 15 degrees upstream, looking at the near plume. Kept close
# to side-on so that no ray reaches the end of the computed frame (x = 10.5 m), which would show as a false edge.
target = np.array([3.9, 0.0, 0.0])
view = np.array([-0.26, -0.55, 0.79])
eye = target + 8.6 * view / np.linalg.norm(view)
fov = 34.0
fwd = target - eye
fwd /= np.linalg.norm(fwd)
up0 = np.array([0.0, 1.0, 0.0])
right = np.cross(fwd, up0)
right /= np.linalg.norm(right)
up = np.cross(right, fwd)
th = math.tan(math.radians(fov) / 2.0)
sx = (cp.arange(W, dtype=cp.float32) + 0.5) / W * 2.0 - 1.0
sy = 1.0 - (cp.arange(H, dtype=cp.float32) + 0.5) / H * 2.0
SX, SY = cp.meshgrid(sx * th * W / H, sy * th)
D = cp.asarray(fwd, dtype=cp.float32)[None, None] + SX[..., None] * cp.asarray(right, dtype=cp.float32) \
    + SY[..., None] * cp.asarray(up, dtype=cp.float32)
D /= cp.linalg.norm(D, axis=-1, keepdims=True)
E = cp.asarray(eye, dtype=cp.float32)

# entry and exit of the cylinder r <= R_MARCH, x0 <= x <= x1
a = D[..., 1] ** 2 + D[..., 2] ** 2
b = 2.0 * (E[1] * D[..., 1] + E[2] * D[..., 2])
c = E[1] ** 2 + E[2] ** 2 - R_MARCH ** 2
disc = b * b - 4.0 * a * c
hit = disc > 0
sq = cp.sqrt(cp.maximum(disc, 0.0))
t0 = cp.where(hit, (-b - sq) / (2.0 * a), 0.0)
t1 = cp.where(hit, (-b + sq) / (2.0 * a), 0.0)
tx0 = (x0 - E[0]) / D[..., 0]
tx1 = (x1 - E[0]) / D[..., 0]
t0 = cp.maximum(t0, cp.minimum(tx0, tx1))
t1 = cp.minimum(t1, cp.maximum(tx0, tx1))
hit &= t1 > t0
t0 = cp.maximum(t0, 0.0)
dt = cp.where(hit, (t1 - t0) / N_STEP, 0.0)

acc = cp.zeros((H, W), dtype=cp.float32)
alive = hit.copy()
shade = cp.zeros((H, W), dtype=cp.float32)
light = cp.asarray(np.array([-0.3, -0.6, 0.75]) / np.linalg.norm([-0.3, -0.6, 0.75]), dtype=cp.float32)
for k in range(N_STEP):
    t = t0 + (k + 0.5) * dt
    P = E + t[..., None] * D
    r = cp.hypot(P[..., 1], P[..., 2])
    ci = (P[..., 0] - x0) / dx - 0.5
    ri = r / dx - 0.5
    col = cp.clip(cp.floor(ci + 0.5).astype(cp.int32), 0, nx - 1)
    solid = alive & (r <= ro[col])
    if bool(solid.any()):        # first contact with the nozzle: shade it and stop those rays
        nrm = cp.stack([-dro[col], P[..., 1] / cp.maximum(r, 1e-6), P[..., 2] / cp.maximum(r, 1e-6)], axis=-1)
        nrm /= cp.linalg.norm(nrm, axis=-1, keepdims=True)
        lam = cp.clip(cp.sum(nrm * light, axis=-1), 0.0, 1.0)
        shade = cp.where(solid, 0.18 + 0.55 * lam, shade)
        alive &= ~solid
    v = map_coordinates(jg, cp.stack([ri.ravel(), ci.ravel()]), order=1, mode="constant", cval=0.0).reshape(H, W)
    acc += cp.where(alive, v * dt, 0.0)

L = cp.asnumpy(acc)
S = cp.asnumpy(shade)
top = math.log10(np.percentile(L[L > 0], 99.9))
lo = top - 2.5
img = np.clip((np.log10(np.maximum(L, 1e-30)) - lo) / (top - lo), 0.0, 1.0)
rgb = plt.get_cmap("inferno")(img)[..., :3]     # its low end is black, so it is also the background
nozzle = S > 0
rgb[nozzle] = S[nozzle][:, None] * np.array([0.62, 0.64, 0.68])
BG = tuple(plt.get_cmap("inferno")(0.0)[:3])

outdir.mkdir(parents=True, exist_ok=True)
fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=BG)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_axis_off()
ax.imshow(rgb, interpolation="nearest", aspect="auto")
fs = 9 * W / 1920
cax = fig.add_axes([0.33, 0.035, 0.34, 0.012])
sm = plt.cm.ScalarMappable(cmap="inferno", norm=plt.Normalize(lo, top))
cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
cb.set_label("log10 radiance (W m-2 sr-1), optically thin upper bound", color="0.85", fontsize=fs)
cb.ax.tick_params(colors="0.85", labelsize=0.9 * fs)
cb.outline.set_edgecolor("0.85")
fig.text(0.008, 0.985, f"{tag}: H2O + CO2 emission, GPU ray march through the revolved field ({N_STEP} samples "
         "per ray); same model and limits as the side-on image", color="0.85", fontsize=fs, va="top")
path = outdir / f"volume_{tag}_emission.png"
fig.savefig(path, dpi=100, facecolor=BG)
plt.close(fig)
print("wrote", path, f"radiance range shown 10^{lo:.2f}..10^{top:.2f} W m-2 sr-1")
