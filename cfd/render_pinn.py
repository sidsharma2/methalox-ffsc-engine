"""CFD against PINN on the real mesh, through the same pipeline as cfd/render_plume.py.

The PINN is evaluated at the CFD cell centres (pinn/ensemble.py --fields), so both sides pass through the same cell-to-point
interpolation and no griddata is involved. Upper half CFD, lower half PINN, then the difference alone. Close-ups of the
throat and the internal shock of I2-C follow, and the Mach spread over the seeds when the fields carry Ma_std.

usage (AetherCFD environment, a reconstructed case on a Windows path):
    uv run --project D:/Research-Software/AetherCFD python cfd/render_pinn.py CASE FIELDS.npz TAG OUTDIR [W H]
"""
import sys
from pathlib import Path

import numpy as np
import vtk
from vtk.util import numpy_support as nps

from aethercfd.results import beauty as B
from aethercfd.results import pipeline as P
from aethercfd.results.foam_reader import FoamResults, iter_leaves

case, fields, tag, outdir = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
W, H = (int(a) for a in (sys.argv[5:7] if len(sys.argv) > 6 else (1920, 1000)))
BG = [(0.06, 0.065, 0.075)]
outdir.mkdir(parents=True, exist_ok=True)

fr = FoamResults(case)
fr.refresh()
leaves = dict(iter_leaves(fr.read(None, fields=["p", "T", "rho", "Ma"])))
ug = next(ds for n, ds in leaves.items() if n.endswith("internalMesh"))
d = np.load(fields, allow_pickle=False)

cc = vtk.vtkCellCenters()
cc.SetInputData(ug)
cc.Update()
x = nps.vtk_to_numpy(cc.GetOutput().GetPoints().GetData())[:, 0]
if len(x) != len(d["x"]) or np.abs(x - d["x"]).max() > 1e-6:
    sys.exit("the PINN fields are not in this case's cell order")


def add(name, values):
    a = nps.numpy_to_vtk(np.asarray(values, float), deep=True)
    a.SetName(name)
    ug.GetCellData().AddArray(a)


cell = lambda n: nps.vtk_to_numpy(ug.GetCellData().GetArray(n))
lp = np.log10(np.maximum(cell("p"), 1.0))
lq = np.log10(np.maximum(d["p"], 1.0))
add("log10p", lp)
add("MaPinn", d["Ma"])
add("TPinn", d["T"])
add("log10pPinn", lq)
add("MaErr", d["Ma"] - cell("Ma"))
add("TErr", d["T"] - cell("T"))
add("log10pErr", lq - lp)
if "Ma_std" in d:
    add("MaStd", d["Ma_std"])
ugp = P.cell_to_point(ug)

pl = vtk.vtkPlane()
pl.SetOrigin(0, 0, 0)
pl.SetNormal(0, 0, 1)
cut = vtk.vtkCutter()
cut.SetCutFunction(pl)
cut.SetInputData(ugp)
cut.Update()
mid = cut.GetOutput()
low = P.mirror(mid, "y", 0.0)
a = vtk.vtkAppendPolyData()
a.AddInputData(mid)
a.AddInputData(low)
a.Update()
full = a.GetOutput()



def camera(centre, scale):
    return {"position": [centre, 0.0, 40.0], "focal_point": [centre, 0.0, 0.0], "view_up": [0, 1, 0], "view_angle": 30.0,
            "parallel": True, "parallel_scale": scale}


xc = 0.5 * (float(x.min()) + float(x.max()))
half = 0.5 * (float(x.max()) - float(x.min()) + 0.1) * H / W
cam = camera(xc, max(half, 0.68))


def render(blocks, name, view=None):
    r = B.render(B.Scene(blocks, view or cam, size=(W, H), background=BG), outdir / f"pinn_{tag}_{name}.png", pvbatch=B.find_pvbatch())
    print(name, r["ok"], r["backend"], r["output"])
    if not r["ok"]:
        print(r["log"])


for cfd, pinn, err, rng, erng, cmap, title in (
        ("Ma", "MaPinn", "MaErr", (0.0, 4.2), (-0.4, 0.4), "turbo", "Mach number"),
        ("log10p", "log10pPinn", "log10pErr", (5.0, 7.7), (-0.2, 0.2), "viridis", "log10 pressure [Pa]"),
        ("T", "TPinn", "TErr", (1500.0, 3850.0), (-150.0, 150.0), "inferno", "Temperature [K]")):
    render([B.Block(mid, cfd, "point", rng, cmap, smooth=True, bar=True, title=f"{title}: CFD above, PINN below"),
            B.Block(low, pinn, "point", rng, cmap, smooth=True)], cfd)
    render([B.Block(full, err, "point", erng, "coolwarm", smooth=True, bar=True, title=f"{title}: PINN minus CFD")], err)

for name, view, rng, erng in (("throat", camera(0.40, 0.14), (0.3, 2.6), (-0.12, 0.12)), ("shock", camera(1.44, 0.22), (2.8, 4.2), (-0.5, 0.5))):
    render([B.Block(mid, "Ma", "point", rng, "turbo", smooth=True, bar=True, title=f"Mach number, {name}: CFD above, PINN below"),
            B.Block(low, "MaPinn", "point", rng, "turbo", smooth=True)], f"{name}_Ma", view)
    render([B.Block(full, "MaErr", "point", erng, "coolwarm", smooth=True, bar=True, title=f"Mach number, {name}: PINN minus CFD")], f"{name}_MaErr", view)
if "Ma_std" in d:
    render([B.Block(full, "MaStd", "point", (0.0, float(np.max(d["Ma_std"]))), "viridis", smooth=True, bar=True, title="Mach number: standard deviation over the PINN seeds")], "seed_spread")
