"""Offscreen renders of the CAD assembly (PyVista/VTK) from cad/output/mesh/*.stl.
Writes figures/cad_iso.png, cad_front.png, cad_section.png, cad_tpa_section.png."""

import json
import sys
from pathlib import Path

import pyvista as pv

ROOT = Path(__file__).resolve().parents[1]
MESH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cad" / "output" / "mesh"
TAG = sys.argv[2] if len(sys.argv) > 2 else ""
FIG = ROOT / "figures"
COLOR = {"GRCop-42": "#c46a37", "Inconel 718": "#a4a6ad", "SX500": "#6a7fa0", "MAR-M-247": "#7a6a5a",
         "Ti-6Al-4V": "#c3c7d0", "A286": "#3a3a40", "304L": "#d2d2d8", "PTFE/Inconel seal": "#e6cc40"}
idx = json.load(open(MESH / "index.json"))


def colour(item):
    n = item["name"]
    if ("duct" in n or "line" in n) and not n.endswith(("flanges", "bolts", "washers", "seal")):
        if any(k in n for k in ("LOX", "Ox_")):
            return "#6f9fd0"
        if any(k in n for k in ("CH4", "Fuel", "FPB", "Nozzle_return")):
            return "#c49a5c"
    return COLOR.get(item["material"], "#999999")


meshes = [(it, pv.read(MESH / it["file"])) for it in idx]


def shoot(name, view, clip=None, keep=None, zoom=1.0):
    pl = pv.Plotter(off_screen=True, window_size=(2400, 1800))
    pl.set_background("white")
    for it, m in meshes:
        if keep and not keep(it):
            continue
        mm = m
        if clip is not None:
            try:
                mm = m.clip(normal=clip[0], origin=clip[1], invert=True)
            except Exception:
                continue
            if mm.n_points == 0:
                continue
        pl.add_mesh(mm, color=colour(it), smooth_shading=False, specular=0.25, specular_power=20)
    pl.enable_anti_aliasing("ssaa")
    pl.view_vector(view, viewup=(0, 0, 1))
    pl.camera.zoom(zoom)
    pl.screenshot(str(FIG / f"{name}{TAG}.png"))
    pl.close()


shoot("cad_iso", (1.0, -1.25, 0.55), zoom=1.15)
shoot("cad_iso_rear", (-1.0, 1.25, 0.45), zoom=1.15)
shoot("cad_front", (0, -1, 0), zoom=1.2)
# half section through the x-z plane: chamber axis and both turbopump axes lie in it
shoot("cad_section", (0.25, -1.0, 0.15), clip=("-y", (0, 0, 0)), zoom=0.95)
shoot("cad_tpa_section", (0.25, -1.0, 0.15), clip=("-y", (0, 0, 0)),
      keep=lambda it: it["group"] in ("LOX_Turbopump",), zoom=1.1)
print("renders written")
