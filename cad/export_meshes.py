"""Tessellate the assembly into one STL per part (global coordinates) plus an index,
for offscreen rendering (scripts/render_cad.py) and quick viewing.

Run:  "C:\\Program Files\\FreeCAD 1.1\\bin\\freecadcmd.exe" cad\\export_meshes.py
"""

import json
import os

import FreeCAD as App
import Mesh
import MeshPart

ROOT = os.environ.get("FFSC_ROOT", r"D:\Research\projects\methalox-ffsc-engine")
SRC = os.path.join(os.environ.get("FFSC_CAD_OUT", os.path.join(ROOT, "cad", "output")), "MFE280.FCStd")
OUT = os.path.join(os.path.dirname(SRC), "mesh")
os.makedirs(OUT, exist_ok=True)

doc = App.openDocument(SRC)
index = []
for o in doc.Objects:
    if o.TypeId != "Part::Feature" or not hasattr(o, "Material"):
        continue
    s = o.Shape.copy()
    s.Placement = o.getGlobalPlacement()
    fine = not any(k in o.Name for k in ("bolts", "nuts", "blades", "vanes", "posts"))
    m = MeshPart.meshFromShape(Shape=s, LinearDeflection=0.6 if fine else 1.5, AngularDeflection=0.35)
    path = os.path.join(OUT, f"{o.Name}.stl")
    m.write(path)
    group = o.getParentGeoFeatureGroup().Name if o.getParentGeoFeatureGroup() else ""
    index.append({"name": o.Name, "group": group, "material": o.Material, "file": os.path.basename(path)})
json.dump(index, open(os.path.join(OUT, "index.json"), "w"), indent=1)
print(f"[mesh] {len(index)} parts -> {OUT}")
