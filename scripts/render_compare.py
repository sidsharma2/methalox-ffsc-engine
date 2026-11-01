"""Side-by-side render of two engine builds at the same scale (front view and quarter cutaway).

    .venv/Scripts/python.exe scripts/render_compare.py OLD_MESH_DIR NEW_MESH_DIR "Old label" "New label" NAME

Both views use parallel projection with one shared scale, so sizes compare directly.
Writes figures/NAME.png.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pyvista as pv

ROOT = Path(__file__).resolve().parents[1]
COLOR = {"GRCop-42": "#c46a37", "Inconel 718": "#a4a6ad", "SX500": "#6a7fa0", "MAR-M-247": "#7a6a5a",
         "Ti-6Al-4V": "#c3c7d0", "A286": "#3a3a40", "304L": "#d2d2d8", "PTFE/Inconel seal": "#e6cc40"}


def colour(item):                                        # same palette as render_sections.py
    n = item["name"]
    if ("duct" in n or "line" in n) and not n.endswith(("flanges", "bolts", "washers", "seal")):
        if any(k in n for k in ("LOX", "Ox_")):
            return "#6f9fd0"
        if any(k in n for k in ("CH4", "Fuel", "FPB", "Nozzle_return")):
            return "#c49a5c"
    return COLOR.get(item["material"], "#999999")


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


def load(d):
    idx = json.load(open(Path(d) / "index.json"))
    out = []
    for it in idx:
        m = pv.read(Path(d) / it["file"]).triangulate().clean()
        out.append((it, m, m.n_open_edges == 0))
    return out


def quarter(m, closed):
    a = keep(m, closed, (0, 1, 0), (0, 0, 0))
    b = keep(m, closed, (0, -1, 0), (0, 0, 0))
    b = keep(b, closed, (-1, 0, 0), (0, 0, 0)) if b.n_cells else b
    parts = [p for p in (a, b) if p.n_cells]
    return parts[0].merge(parts[1:]) if len(parts) > 1 else (parts[0] if parts else None)


def main(old_dir, new_dir, old_lab, new_lab, name):
    sets = [(load(old_dir), old_lab), (load(new_dir), new_lab)]
    pl = pv.Plotter(off_screen=True, shape=(1, 4), window_size=(3600, 1500), lighting="three lights", border=False)
    pl.set_background("white")
    bounds = []
    for col, (view, cut) in enumerate([("front", False), ("front", False), ("iso", True), ("iso", True)]):
        meshes, lab = sets[col % 2]
        pl.subplot(0, col)
        for it, m, closed in meshes:
            mm = quarter(m, closed) if cut else m
            if mm is None or mm.n_cells == 0:
                continue
            pl.add_mesh(mm, color=colour(it), smooth_shading=False, specular=0.3)
            bounds.append(mm.bounds)
        pl.add_text(lab + ("\nquarter cutaway" if cut else "\nfront view"), font_size=11, color="black", position="upper_left")
        pl.enable_parallel_projection()
        if view == "front":
            pl.view_vector((0, -1, 0), viewup=(0, 0, 1))
        else:
            pl.view_vector((1.0, -1.15, 0.55), viewup=(0, 0, 1))
    b = np.array(bounds)
    span = max(b[:, 1].max() - b[:, 0].min(), b[:, 5].max() - b[:, 4].min())
    for col in range(4):                                     # one shared scale for all four panels
        pl.subplot(0, col)
        pl.reset_camera()
        pl.camera.parallel_scale = 0.55 * span
    pl.enable_anti_aliasing("ssaa")
    out = ROOT / "figures" / f"{name}.png"
    pl.screenshot(str(out))
    pl.close()
    print("wrote", out)


if __name__ == "__main__":
    main(*sys.argv[1:6])
