"""Plume post-processing through AetherCFD's results pipeline (GPU isosurface, OptiX path tracing).

fields  : one image per field on the full x-r plane (mid-plane of the wedge and its mirror image): Mach number,
          temperature, log10 pressure and a schlieren of ln(rho), rasterised so the colours are the data.
split   : Mach number above the axis, schlieren below.
cutaway : 270-degree revolved nozzle walls, Mach number on the two cut faces (hot gas only, T > T_cut) and a
          translucent T isosurface contoured on the GPU (CuPy), path-traced with OptiX.

Smoothing is linear interpolation only: cell values are averaged to the mesh points (VTK cell-to-point) and
coloured per pixel, so no cell edges show and no value is added that the solver did not compute; a shock spreads
over about one cell. The schlieren is AetherCFD's stage: S = exp(-k |grad ln rho| / its 99th percentile).

usage (AetherCFD environment, a reconstructed case on a Windows path; VTK cannot open \\\\wsl.localhost):
    uv run --project D:/Research-Software/AetherCFD python cfd/render_plume.py CASE TAG OUTDIR MODE [W H SPP]
    MODE = fields | split | cutaway | all
"""
import math
import sys
from pathlib import Path

import numpy as np
import vtk
from vtk.util import numpy_support as nps

from aethercfd.results import beauty as B
from aethercfd.results import pipeline as P
from aethercfd.results.foam_reader import FoamResults, iter_leaves

case, tag, outdir, mode = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4]
W, H, SPP = (int(a) for a in (sys.argv[5:8] if len(sys.argv) > 7 else (1920, 1080, 16)))
X_MIN, X_MAX, T_CUT, T_ISO, K_SCH = 0.15, 10.5, 700.0, 1000.0, 4.0
BG = [(0.06, 0.065, 0.075)]

fr = FoamResults(case)
fr.refresh()
walls = ["patch/wall_chamber", "patch/wall_bell", "patch/lip", "patch/wall_outer"]
mb = fr.read(None, fields=["p", "T", "U", "rho", "Ma"], patches=["internalMesh"] + walls)
leaves = dict(iter_leaves(mb))
ug = next(ds for n, ds in leaves.items() if n.endswith("internalMesh"))
wall_polys = [P.to_poly(ds) for n, ds in leaves.items() if any(n.endswith(w.split("/")[1]) for w in walls)]
pts = nps.vtk_to_numpy(ug.GetPoints().GetData())
wedge = 2.0 * math.degrees(np.max(np.arctan2(np.abs(pts[:, 2]), np.maximum(pts[:, 1], 1e-9))))
print(f"cells {ug.GetNumberOfCells()}, wedge {wedge:.3f} deg")

ugp = P.cell_to_point(ug)  # interpolated point values for smooth colouring; the cell values stay on it
lp = nps.numpy_to_vtk(np.log10(np.maximum(nps.vtk_to_numpy(ugp.GetPointData().GetArray("p")), 1.0)), deep=True)
lp.SetName("log10p")
ugp.GetPointData().AddArray(lp)


def cut_z0(ds):
    """Mid-plane (z = 0) section of a wedge dataset; point and cell data kept."""
    pl = vtk.vtkPlane()
    pl.SetOrigin(0, 0, 0)
    pl.SetNormal(0, 0, 1)
    c = vtk.vtkCutter()
    c.SetCutFunction(pl)
    c.SetInputData(ds)
    c.Update()
    return c.GetOutput()


def clip_x(poly, xmax=X_MAX):
    pl = vtk.vtkPlane()
    pl.SetOrigin(xmax, 0, 0)
    pl.SetNormal(-1, 0, 0)
    c = vtk.vtkClipPolyData()
    c.SetClipFunction(pl)
    c.SetInputData(poly)
    c.Update()
    return c.GetOutput()


def rotate(poly, deg):
    t = vtk.vtkTransform()
    t.RotateWXYZ(deg, 1, 0, 0)
    return P._transform(poly, t)


def append(polys):
    a = vtk.vtkAppendPolyData()
    for p in polys:
        a.AddInputData(p)
    a.Update()
    return a.GetOutput()


def plane_camera(r_half=None):
    xc = 0.5 * (X_MIN + X_MAX)
    half_h = r_half or 0.5 * (X_MAX - X_MIN) * H / W
    return {"position": [xc, 0.0, 40.0], "focal_point": [xc, 0.0, 0.0], "view_up": [0, 1, 0], "view_angle": 30.0,
            "parallel": True, "parallel_scale": half_h}


def render(blocks, name, cam, raytrace=False):
    scene = B.Scene(blocks, cam, size=(W, H), background=BG, raytrace=raytrace, spp=SPP)
    r = B.render(scene, outdir / f"plume_{tag}_{name}.png", pvbatch=B.find_pvbatch())
    print(name, r["ok"], r["backend"], r["output"])
    if not r["ok"]:
        print(r["log"])


mid = clip_x(cut_z0(ugp), X_MAX + 0.5)
full = append([mid, P.mirror(mid, "y", 0.0)])
sch = P.run_stage({"type": "schlieren", "source": "rho", "scale": "log", "percentile": 99, "k": K_SCH,
                   "axis": "z", "pos": 0.5}, [ug], None, smooth=True)
print("schlieren:", sch.label, sch.notes)
sch_half = clip_x(sch.poly, X_MAX + 0.5)

if mode in ("fields", "all"):
    for arr, rng, cmap, title in (("Ma", (0.0, 5.0), "turbo", "Mach number"),
                                  ("T", (250.0, 3600.0), "inferno", "Temperature [K]"),
                                  ("log10p", (3.0, 7.4), "viridis", "log10 pressure [Pa]")):
        render([B.Block(full, arr, "point", rng, cmap, smooth=True, bar=True, title=title)], arr, plane_camera())
    sch_full = append([sch_half, P.mirror(sch_half, "y", 0.0)])
    render([B.Block(sch_full, "schlieren", "point", (0.0, 1.0), "gray", smooth=True)], "schlieren", plane_camera())

if mode in ("split", "all"):
    render([B.Block(mid, "Ma", "point", (0.0, 5.0), "turbo", smooth=True, bar=True, title="Mach number"),
            B.Block(P.mirror(sch_half, "y", 0.0), "schlieren", "point", (0.0, 1.0), "gray", smooth=True)],
           "split", plane_camera())

if mode in ("cutaway", "all"):
    n_copies = int(round(270.0 / wedge))
    shell = append(wall_polys)
    shell = append([shell] + P.revolve(shell, "x", wedge, n_copies))
    # hot gas only: clip the mid-plane along the interpolated T = T_CUT contour (a threshold keeps whole cells
    # and leaves a stair-stepped edge)
    face = clip_x(cut_z0(ugp))
    face.GetPointData().SetActiveScalars("T")
    hot = vtk.vtkClipPolyData()
    hot.SetInputData(face)
    hot.SetValue(T_CUT)
    hot.Update()
    face = hot.GetOutput()
    faces = append([rotate(face, -0.5 * wedge), rotate(face, (n_copies - 0.5) * wedge)])
    iso = P.stage_gpu_iso({"type": "isosurface", "field": "T", "value": T_ISO}, [ug], "T", "magnitude",
                          mesh_dirs=[case / "constant" / "polyMesh"])
    print("iso:", iso.label, iso.notes)
    plume = clip_x(iso.poly)
    plume = append([plume] + P.revolve(plume, "x", wedge, n_copies))
    th_c = math.radians((n_copies - 1) * wedge / 2.0 + 180.0)  # middle of the open quarter
    d = np.array([0.0, math.cos(th_c), math.sin(th_c)])
    up = np.array([0.0, -math.sin(th_c), math.cos(th_c)])
    f = np.array([4.4, 0.0, 0.0])
    v = -0.55 * np.array([1.0, 0.0, 0.0]) + d + 0.55 * up
    pos = f + 12.5 * v / np.linalg.norm(v)
    cam = {"position": pos.tolist(), "focal_point": f.tolist(), "view_up": up.tolist(), "view_angle": 30.0,
           "parallel": False, "parallel_scale": 1.0}
    render([B.Block(shell, None, "cell", None, "gray", smooth=True, color=(0.42, 0.44, 0.47)),
            B.Block(faces, "Ma", "point", (0.0, 5.0), "turbo", smooth=True, bar=True, title="Mach number"),
            B.Block(plume, None, "point", None, "gray", opacity=0.18, smooth=True, color=(1.0, 0.55, 0.18))],
           "cutaway", cam, raytrace=True)
