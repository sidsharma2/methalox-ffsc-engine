"""Offscreen renders of the CAD assembly (PyVista/VTK) from the iteration's mesh folder.

    .venv/Scripts/python.exe scripts/render_cad.py [MESH] [TAG] [--iter ID] [--fig DIR]

Iteration 1 (default): cad/output/mesh -> figures/cad_iso.png, cad_iso_rear.png, cad_front.png,
cad_section.png, cad_tpa_section.png (TAG is appended to the file names), as before.
--iter ID: cad/iterations/<ID>/mesh -> figures/<ID>/ (the iteration-1 figures are not touched), plus
the exterior views of sheets MFE280-VIS-010 / 011 with feature edges: ext_front_right, ext_rear_left,
ext_lox_tpa_fr, ext_lox_tpa_rl, ext_ch4_tpa_fl, ext_ch4_tpa_rr. They are also written when --fig
points away from figures/ (scratch builds)."""

import json
import sys
from pathlib import Path

import pyvista as pv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drawings" / "src"))
import itercfg as IT  # noqa: E402  (parses --iter / --fig)

MESH = Path(sys.argv[1]) if len(sys.argv) > 1 else IT.MESH
TAG = sys.argv[2] if len(sys.argv) > 2 else ""
FIG = IT.FIG
FIG.mkdir(parents=True, exist_ok=True)
EXTERIOR = FIG.resolve() != (ROOT / "figures").resolve()
COLOR = {"GRCop-42": "#c46a37", "Inconel 718": "#a4a6ad", "SX500": "#6a7fa0", "MAR-M-247": "#7a6a5a",
         "Ti-6Al-4V": "#c3c7d0", "A286": "#3a3a40", "304L": "#d2d2d8", "PTFE/Inconel seal": "#e6cc40",
         "M50/Si3N4 hybrid": "#4d5260"}
idx = json.load(open(MESH / "index.json"))


def colour(item):
    n = item["name"]
    if ("duct" in n or "line" in n) and not n.endswith(("flanges", "bolts", "washers", "seal", "weld")):
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


def shoot_ext(name, view, keep=None, zoom=1.0, size=(2400, 2400)):
    """Exterior view for the drawing sheets: flat-shaded parts with dark feature edges."""
    pl = pv.Plotter(off_screen=True, window_size=size, lighting="three lights")
    pl.set_background("white")
    for it, m in meshes:
        if keep and not keep(it):
            continue
        pl.add_mesh(m, color=colour(it), smooth_shading=False, specular=0.3, specular_power=25)
        fe = m.extract_feature_edges(feature_angle=50, boundary_edges=False, manifold_edges=False,
                                     non_manifold_edges=False)
        if fe.n_cells:
            pl.add_mesh(fe, color="#303030", line_width=0.8)
    pl.enable_anti_aliasing("ssaa")
    pl.view_vector(view, viewup=(0, 0, 1))
    pl.reset_camera()
    pl.camera.zoom(zoom)
    pl.screenshot(str(FIG / f"{name}.png"))
    pl.close()
    print("wrote", FIG / f"{name}.png")


shoot("cad_iso", (1.0, -1.25, 0.55), zoom=1.15)
shoot("cad_iso_rear", (-1.0, 1.25, 0.45), zoom=1.15)
shoot("cad_front", (0, -1, 0), zoom=1.2)
# half section through the x-z plane: chamber axis and both turbopump axes lie in it
shoot("cad_section", (0.25, -1.0, 0.15), clip=("-y", (0, 0, 0)), zoom=0.95)
shoot("cad_tpa_section", (0.25, -1.0, 0.15), clip=("-y", (0, 0, 0)),
      keep=lambda it: it["group"] in ("LOX_Turbopump",), zoom=1.1)
if EXTERIOR:
    shoot_ext("ext_front_right", (1.0, -1.25, 0.55), zoom=1.2)
    shoot_ext("ext_rear_left", (-1.0, 1.25, 0.45), zoom=1.2)
    lox, ch4 = (lambda it: it["group"] == "LOX_Turbopump"), (lambda it: it["group"] == "CH4_Turbopump")
    shoot_ext("ext_lox_tpa_fr", (1.0, -1.2, 0.45), keep=lox, zoom=1.15, size=(1800, 2400))
    shoot_ext("ext_lox_tpa_rl", (-1.0, 1.2, 0.45), keep=lox, zoom=1.15, size=(1800, 2400))
    shoot_ext("ext_ch4_tpa_fl", (-1.0, -1.2, 0.45), keep=ch4, zoom=1.15, size=(1800, 2400))
    shoot_ext("ext_ch4_tpa_rr", (1.0, 1.2, 0.45), keep=ch4, zoom=1.15, size=(1800, 2400))
print("renders written to", FIG)
