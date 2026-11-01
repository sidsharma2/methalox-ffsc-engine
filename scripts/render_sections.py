"""Section views of the CAD assembly (PyVista/VTK) from the iteration's mesh folder.

Each part is clipped as a closed surface, so its cut faces are capped. The caps get a
45-degree hatch in the part colour, like a section on a drawing. Writes sec_*.png and
sec_overview.png.

Run:  .venv/Scripts/python.exe scripts/render_sections.py [MESH] [--iter ID] [--fig DIR]

Iteration 1 (default): cad/output/mesh -> figures/ as before. --iter ID: cad/iterations/<ID>/mesh
-> figures/<ID>/, so the iteration-1 figures are never overwritten.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pyvista as pv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drawings" / "src"))
import itercfg as IT  # noqa: E402  (parses --iter / --fig)

MESH = Path(sys.argv[1]) if len(sys.argv) > 1 else IT.MESH
FIG = IT.FIG
FIG.mkdir(parents=True, exist_ok=True)
LAYOUT = json.load(open(MESH.parent / "layout.json"))
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


def rgb(hex_):
    return np.array([int(hex_[i:i + 2], 16) for i in (1, 3, 5)], float) / 255.0


_TEX = {}


def hatch_texture(hex_, n=32, w=1.6):
    """Seamless 45-degree hatch: light part colour with dark lines."""
    if hex_ not in _TEX:
        base = 0.55 * rgb(hex_) + 0.45                   # lighter than the part surfaces
        img = np.empty((n, n, 3))
        img[:] = base
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
    if m.n_open_edges:                                   # close small tessellation gaps so the cut can be capped
        f = m.fill_holes(1.0e4).triangulate().clean()
        if f.n_open_edges == 0:
            m = f
    meshes.append((it, m, m.n_open_edges == 0))


def keep(m, closed, n, o):
    """Part of m on the side (p - o) . n >= 0; capped when the surface is closed."""
    if closed:
        try:
            r = m.clip_closed_surface(normal=n, origin=o)
            if r.n_cells:
                return r
        except Exception:
            pass
    return m.clip(normal=n, origin=o, invert=False)


def split_caps(m, planes, spacing):
    """(body, [caps with hatch texture coordinates]) for the cells lying in a cutting plane."""
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


def shoot(name, view, up, cut, planes, spacing, select=None, zoom=1.0, parallel=False, size=(2400, 1800), edges=True):
    """cut(m, closed) -> clipped mesh; planes = the cutting planes; spacing = hatch pitch in mm."""
    pl = pv.Plotter(off_screen=True, window_size=size, lighting="three lights")
    pl.set_background("white")
    for it, m, closed in meshes:
        if select and not select(it):
            continue
        mm = cut(m, closed) if cut else m
        if mm is None or mm.n_cells == 0:
            continue
        body, caps = split_caps(mm, planes, spacing)
        if body.n_cells:
            pl.add_mesh(body, color=colour(it), smooth_shading=False, specular=0.3, specular_power=25)
            if edges:
                fe = body.extract_feature_edges(feature_angle=50, boundary_edges=False, manifold_edges=False,
                                                non_manifold_edges=False)
                if fe.n_cells:
                    pl.add_mesh(fe, color="#303030", line_width=0.8)
        for cap in caps:
            pl.add_mesh(cap, texture=hatch_texture(colour(it)), ambient=0.45, diffuse=0.55, specular=0.0)
            ce = cap.extract_feature_edges(boundary_edges=True, feature_edges=False, manifold_edges=False,
                                           non_manifold_edges=False)
            if ce.n_cells:
                pl.add_mesh(ce, color="#000000", line_width=1.6)
    if parallel:
        pl.enable_parallel_projection()
    pl.enable_anti_aliasing("ssaa")
    pl.view_vector(view, viewup=up)
    pl.reset_camera()
    pl.camera.zoom(zoom)
    out = FIG / f"{name}.png"
    pl.screenshot(str(out))
    pl.close()
    print("wrote", out.name)
    return out


Y0 = ((0, 1, 0), (0, 0, 0))
X0 = ((-1, 0, 0), (0, 0, 0))
outs, titles = [], []


def quarter(m, closed):
    """Quadrant x > 0, y < 0 removed."""
    a = keep(m, closed, (0, 1, 0), (0, 0, 0))
    b = keep(m, closed, (0, -1, 0), (0, 0, 0))
    b = keep(b, closed, (-1, 0, 0), (0, 0, 0)) if b.n_cells else b
    parts = [p for p in (a, b) if p.n_cells]
    return parts[0].merge(parts[1:]) if len(parts) > 1 else (parts[0] if parts else None)


outs.append(shoot("sec_quarter_cutaway", (1.0, -1.15, 0.55), (0, 0, 1), quarter,
                  [((0, 1, 0), (0, 0, 0)), ((1, 0, 0), (0, 0, 0))], 18.0, zoom=1.2))
titles.append("Quarter cutaway (quadrant +x / -y removed)")

# longitudinal section in the x-z plane: chamber axis and both turbopump axes lie in it
outs.append(shoot("sec_xz_full", (0.32, -1.0, 0.18), (0, 0, 1), lambda m, c: keep(m, c, *Y0), [Y0], 18.0, zoom=1.02))
titles.append("Section x-z: chamber and both turbopump axes")

# longitudinal section in the y-z plane through the chamber axis, CH4 side kept
outs.append(shoot("sec_yz_full", (1.0, 0.32, 0.18), (0, 0, 1), lambda m, c: keep(m, c, *X0), [X0], 18.0, zoom=1.02))
titles.append("Section y-z: chamber axis, seen from the LOX side")

# turbopump close-ups in the plane of their axes, straight on like the drawing sections
for tag, grp, lab in (("lox", "LOX_Turbopump", "LOX"), ("ch4", "CH4_Turbopump", "CH4")):
    outs.append(shoot(f"sec_{tag}_tpa", (0, -1, 0), (0, 0, 1), lambda m, c: keep(m, c, *Y0), [Y0], 7.0,
                      select=lambda it, g=grp: it["group"] == g, zoom=1.15, parallel=True, size=(1800, 2400)))
    titles.append(f"{lab} turbopump + preburner, section on the axis")

# horizontal cut through the CH4 pump volute, injector dome, gimbal and LOX bearing housing
zc = 480.0
outs.append(shoot("sec_z480_pumps", (0.0, -0.45, 1.0), (0, 1, 0),
                  lambda m, c: keep(m, c, (0, 0, -1), (0, 0, zc)), [((0, 0, 1), (0, 0, zc))], 14.0,
                  select=lambda it: it["group"] != "Thrust_Chamber", zoom=1.5))
titles.append("Horizontal cut z = +480 mm, from above")

# injector face seen from inside the chamber: cut 30 mm below the face, looking up
zi = -30.0
outs.append(shoot("sec_injector_face", (0, 0, -1), (0, 1, 0),
                  lambda m, c: keep(m, c, (0, 0, 1), (0, 0, zi)), [((0, 0, 1), (0, 0, zi))], 9.0,
                  select=lambda it: it["group"] in ("Thrust_Chamber", "Injector_Head"), zoom=1.6, size=(2000, 2000),
                  parallel=True, edges=False))
titles.append("Injector face from the chamber (cut z = -30 mm)")

# overview sheet
try:
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "serif", "font.serif": ["STIXGeneral"], "mathtext.fontset": "stix"})
    fig, axs = plt.subplots(2, 4, figsize=(16, 9.2))
    for ax in axs.flat:
        ax.axis("off")
    for ax, p, t in zip(axs.flat, outs, titles):
        im = mpimg.imread(p)
        rows = np.where(im[..., :3].min(axis=(1, 2)) < 0.99)[0]
        cols = np.where(im[..., :3].min(axis=(0, 2)) < 0.99)[0]
        if rows.size and cols.size:                       # crop the white margin
            im = im[max(rows[0] - 20, 0):rows[-1] + 20, max(cols[0] - 20, 0):cols[-1] + 20]
        ax.imshow(im)
        ax.set_title(t, fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG / "sec_overview.png", dpi=150)
    print("wrote sec_overview.png")
except Exception as e:                                   # the overview is a convenience only
    print("overview skipped:", e)
