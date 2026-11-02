"""Where is a plume snapshot steady? Compares three saves of one case cell by cell.

usage (AetherCFD environment, reconstructed saves on Windows paths):
    uv run --project D:/Research-Software/AetherCFD python cfd/plume_steadiness.py SNAP_A SNAP_B SNAP_C
    (same mesh, increasing iteration)
Prints, per 1 m x-band, inside the hot plume (T > 600 K at C) and outside it:
the 95th percentile of |dp|/p and |dT|/T between B->C and A->B, and the largest Mach change;
then the centreline Mach maxima (shock-cell positions) of each save.
"""
import sys
from pathlib import Path

import numpy as np
import vtk
from vtk.util import numpy_support as nps

from aethercfd.results.foam_reader import FoamResults, iter_leaves


def load(snap):
    fr = FoamResults(Path(snap))
    fr.refresh()
    ug = next(ds for n, ds in iter_leaves(fr.read(None, fields=["p", "T", "Ma"])) if n.endswith("internalMesh"))
    cc = vtk.vtkCellCenters()
    cc.SetInputData(ug)
    cc.Update()
    X = nps.vtk_to_numpy(cc.GetOutput().GetPoints().GetData())
    return X, {k: nps.vtk_to_numpy(ug.GetCellData().GetArray(k)).astype(float) for k in ("p", "T", "Ma")}


snaps = sys.argv[1:4]
X, A = load(snaps[0])
_, B = load(snaps[1])
_, C = load(snaps[2])
x, r = X[:, 0], np.hypot(X[:, 1], X[:, 2])
hot = C["T"] > 600.0
print(f"cells {len(x)}, x {x.min():.2f}..{x.max():.2f} m, hot-plume cells {hot.sum()}")
print(" x band  | region | n     | p95 |dp|/p  B-C   A-B | p95 |dT|/T  B-C   A-B | max |dMa| B-C  A-B")
for lo in np.arange(0.0, np.ceil(x.max()), 1.0):
    band = (x >= lo) & (x < lo + 1)
    for name, m in (("plume", band & hot), ("outside", band & ~hot)):
        if m.sum() < 5:
            continue
        dp1 = np.abs(C["p"][m] - B["p"][m]) / C["p"][m]
        dp0 = np.abs(B["p"][m] - A["p"][m]) / B["p"][m]
        dT1 = np.abs(C["T"][m] - B["T"][m]) / C["T"][m]
        dT0 = np.abs(B["T"][m] - A["T"][m]) / B["T"][m]
        dM1 = np.abs(C["Ma"][m] - B["Ma"][m]).max()
        dM0 = np.abs(B["Ma"][m] - A["Ma"][m]).max()
        print(f" {lo:4.0f}-{lo+1:<3.0f}| {name:7s}| {m.sum():5d} | {100*np.percentile(dp1,95):7.2f}% {100*np.percentile(dp0,95):6.2f}%"
              f" | {100*np.percentile(dT1,95):7.2f}% {100*np.percentile(dT0,95):6.2f}% | {dM1:6.3f} {dM0:6.3f}")

core = hot & (A["Ma"] > 3) & (B["Ma"] > 3) & (C["Ma"] > 3)
shear = hot & ~core
print("\nhot plume split: supersonic core (Ma > 3 in all saves) vs the rest (shear layer, subsonic pockets)")
print(" x band  | core n | p95 |dp|/p B-C  A-B | shear n | p95 |dp|/p B-C  A-B")
for lo in np.arange(0.0, np.ceil(x.max()), 1.0):
    band = (x >= lo) & (x < lo + 1)
    s = []
    for m in (band & core, band & shear):
        if m.sum() < 5:
            s.append(f"{m.sum():6d} |       -       -")
            continue
        d1 = np.percentile(np.abs(C["p"][m] - B["p"][m]) / C["p"][m], 95)
        d0 = np.percentile(np.abs(B["p"][m] - A["p"][m]) / B["p"][m], 95)
        s.append(f"{m.sum():6d} | {100*d1:7.2f}% {100*d0:6.2f}%")
    print(f" {lo:4.0f}-{lo+1:<3.0f}| " + " | ".join(s))

# centreline: cells with r < 0.03, averaged per 0.25 m bin
ax = r < 0.03
print("\ncentreline Mach (0.25 m bin means)   x : A  B  C")
for lo in np.arange(0.0, x.max(), 0.25):
    m = ax & (x >= lo) & (x < lo + 0.25)
    if m.sum():
        a, b, c = (F["Ma"][m].mean() for F in (A, B, C))
        flag = "  <-- moves" if max(abs(a - c), abs(b - c)) > 0.1 else ""
        print(f"  {lo + 0.125:6.2f} : {a:5.2f} {b:5.2f} {c:5.2f}{flag}")
