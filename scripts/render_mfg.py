"""Renders for the build-strategy sheet MFE280-MFG-009: every part coloured by its manufacturing
route in the hybrid strategy (drawings/src/mfg_routes.py, from the cost model).

    .venv/Scripts/python.exe scripts/render_mfg.py [--iter ID] [--addendum]

Reads the iteration's mesh folder (cad/output/mesh for iteration 1, cad/iterations/<ID>/mesh) and
writes mfg_iso.png (exterior, front-right), mfg_quarter.png (quarter cutaway, quadrant x > 0, y < 0
removed, cut faces hatched in the route colour) and mfg_legend.json to the iteration's figures
folder (figures/<ID>/, or figures/I1-addendum/ with --addendum). Iteration-1 figures are not touched.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pyvista as pv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drawings" / "src"))
import itercfg as IT  # noqa: E402
import mfg_routes  # noqa: E402

if IT.IS_I1 and not IT.ADDENDUM and "FFSC_FIG_DIR" not in __import__("os").environ:
    raise SystemExit("iteration 1: use --addendum (figures/I1-addendum) so that figures/ stays as issued")
FIG = IT.FIG
FIG.mkdir(parents=True, exist_ok=True)
MESH = IT.MESH
EV = mfg_routes.evaluate()
idx = json.load(open(MESH / "index.json"))


def colour(it):
    p = EV["parts"].get(it["name"])
    return mfg_routes.CLASSES[p["cls"]][1] if p else "#cccccc"


def rgb(hex_):
    return np.array([int(hex_[i:i + 2], 16) for i in (1, 3, 5)], float) / 255.0


_TEX = {}


def hatch_texture(hex_, n=32, w=1.6):
    if hex_ not in _TEX:
        img = np.empty((n, n, 3))
        img[:] = 0.55 * rgb(hex_) + 0.45
        i, j = np.mgrid[0:n, 0:n]
        d = np.abs(((i - j + n // 2) % n) - n // 2)
        img[d < w] = 0.15
        t = pv.Texture((img * 255).astype(np.uint8))
        t.repeat = True
        _TEX[hex_] = t
    return _TEX[hex_]


meshes = []
for it in idx:
    m = pv.read(MESH / it["file"]).triangulate().clean()
    if m.n_open_edges:
        f = m.fill_holes(1.0e4).triangulate().clean()
        if f.n_open_edges == 0:
            m = f
    meshes.append((it, m, m.n_open_edges == 0))


def keep(m, closed, n, o):
    if closed:
        try:
            r = m.clip_closed_surface(normal=n, origin=o)
            if r.n_cells:
                return r
        except Exception:
            pass
    return m.clip(normal=n, origin=o, invert=False)


def quarter(m, closed):
    a = keep(m, closed, (0, 1, 0), (0, 0, 0))
    b = keep(m, closed, (0, -1, 0), (0, 0, 0))
    b = keep(b, closed, (-1, 0, 0), (0, 0, 0)) if b.n_cells else b
    parts = [p for p in (a, b) if p.n_cells]
    return parts[0].merge(parts[1:]) if len(parts) > 1 else (parts[0] if parts else None)


def split_caps(m, planes, spacing):
    if m.n_cells == 0:
        return m, []
    m = m.extract_surface().compute_normals(cell_normals=True, point_normals=False, auto_orient_normals=False)
    c = m.cell_centers().points
    nn = m.cell_data["Normals"]
    used = np.zeros(m.n_cells, bool)
    caps = []
    for n, o in planes:
        n = np.asarray(n, float) / np.linalg.norm(n)
        sel = (np.abs((c - np.asarray(o, float)) @ n) < 0.05) & (np.abs(nn @ n) > 0.999) & ~used
        if not sel.any():
            continue
        used |= sel
        cap = m.extract_cells(sel).extract_surface()
        a = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u = np.cross(n, a)
        u /= np.linalg.norm(u)
        v = np.cross(n, u)
        cap.active_texture_coordinates = np.c_[cap.points @ u, cap.points @ v] / spacing
        caps.append(cap)
    body = m.extract_cells(~used).extract_surface() if used.any() else m
    return body, caps


def shoot(name, view, cut=None, planes=(), spacing=18.0, zoom=1.0, size=(2400, 2400)):
    pl = pv.Plotter(off_screen=True, window_size=size, lighting="three lights")
    pl.set_background("white")
    for it, m, closed in meshes:
        mm = cut(m, closed) if cut else m
        if mm is None or mm.n_cells == 0:
            continue
        body, caps = split_caps(mm, planes, spacing) if planes else (mm, [])
        col = colour(it)
        if body.n_cells:
            pl.add_mesh(body, color=col, smooth_shading=False, specular=0.25, specular_power=20)
            fe = body.extract_feature_edges(feature_angle=50, boundary_edges=False, manifold_edges=False,
                                            non_manifold_edges=False)
            if fe.n_cells:
                pl.add_mesh(fe, color="#303030", line_width=0.8)
        for cap in caps:
            pl.add_mesh(cap, texture=hatch_texture(col), ambient=0.45, diffuse=0.55, specular=0.0)
            ce = cap.extract_feature_edges(boundary_edges=True, feature_edges=False, manifold_edges=False,
                                           non_manifold_edges=False)
            if ce.n_cells:
                pl.add_mesh(ce, color="#000000", line_width=1.6)
    pl.enable_anti_aliasing("ssaa")
    pl.view_vector(view, viewup=(0, 0, 1))
    pl.reset_camera()
    pl.camera.zoom(zoom)
    out = FIG / f"{name}.png"
    pl.screenshot(str(out))
    pl.close()
    print("wrote", out)


shoot("mfg_iso", (1.0, -1.25, 0.55), zoom=1.25)
shoot("mfg_quarter", (1.0, -1.15, 0.55), cut=quarter, planes=[((0, 1, 0), (0, 0, 0)), ((1, 0, 0), (0, 0, 0))], zoom=1.25)
used = sorted({p["cls"] for p in EV["parts"].values()}, key=list(mfg_routes.CLASSES).index)
json.dump({"classes": used, "colours": {k: mfg_routes.CLASSES[k][1] for k in used}},
          open(FIG / "mfg_legend.json", "w"), indent=2)
print("legend", used)
