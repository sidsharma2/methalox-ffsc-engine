"""Export a reconstructed nozzle case to a compact reference file for the PINN comparison.

Needs AetherCFD's environment (VTK cannot read \\\\wsl.localhost paths, so copy the case to a Windows folder first):
    uv run --project D:/Research-Software/AetherCFD python pinn/export_reference.py CASE_DIR OUT.npz
Writes cell-centre x, r, volume, rho, p, T, Ma, Ux, Ur of the latest time and, per wall/outlet patch, the face
centres and p. The wedge is folded onto the (x, r) plane.
"""

import json
import sys
from pathlib import Path

import numpy as np
import vtk
from vtk.util import numpy_support as nps

from aethercfd.results.foam_reader import FoamResults, iter_leaves


def cell_table(ug):
    cc = vtk.vtkCellCenters()
    cc.SetInputData(ug)
    cc.Update()
    X = nps.vtk_to_numpy(cc.GetOutput().GetPoints().GetData())
    r = np.hypot(X[:, 1], X[:, 2])
    get = lambda n: nps.vtk_to_numpy(ug.GetCellData().GetArray(n))
    U = get("U")
    with np.errstate(invalid="ignore", divide="ignore"):
        Ur = np.where(r > 0, (U[:, 1] * X[:, 1] + U[:, 2] * X[:, 2]) / r, 0.0)
    sizes = vtk.vtkCellSizeFilter()
    sizes.SetInputData(ug)
    sizes.ComputeVolumeOn()
    sizes.Update()
    vol = nps.vtk_to_numpy(sizes.GetOutput().GetCellData().GetArray("Volume"))
    return {"x": X[:, 0], "r": r, "vol": vol, "rho": get("rho"), "p": get("p"), "T": get("T"), "Ma": get("Ma"),
            "Ux": U[:, 0], "Ur": Ur}


def patch_table(pd):
    cc = vtk.vtkCellCenters()
    cc.SetInputData(pd)
    cc.Update()
    X = nps.vtk_to_numpy(cc.GetOutput().GetPoints().GetData())
    return {"x": X[:, 0], "r": np.hypot(X[:, 1], X[:, 2]), "p": nps.vtk_to_numpy(pd.GetCellData().GetArray("p"))}


def main(case, out):
    case = Path(case)
    fr = FoamResults(case)
    fr.refresh()
    fields = ["rho", "p", "T", "Ma", "U"]
    leaves = dict(iter_leaves(fr.read(None, fields=fields)))
    print("leaves:", list(leaves))
    name = next(n for n in leaves if n.endswith("internalMesh"))
    d = cell_table(leaves[name])
    for n, ds in leaves.items():
        if n == name or ds.GetNumberOfCells() == 0 or ds.GetCellData().GetArray("p") is None:
            continue
        short = n.split("/")[-1]
        if short.lower().startswith(("wedge", "front", "back")):
            continue
        for k, v in patch_table(ds).items():
            d[f"{short}__{k}"] = v
    info = json.loads((case / "case_info.json").read_text(encoding="utf-8"))
    d["meta"] = np.array(json.dumps({"case": info.get("case"), "source": str(case), "gas": info.get("gas")}))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, **d)
    print(out, "cells", len(d["x"]), "x", d["x"].min(), d["x"].max(), "r max", d["r"].max(), "Ma max", d["Ma"].max())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
