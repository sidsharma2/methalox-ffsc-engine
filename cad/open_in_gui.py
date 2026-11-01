"""Open the engine in the FreeCAD GUI with material colours and save them into the file.

Run:  "C:\\Program Files\\FreeCAD 1.1\\bin\\freecad.exe" cad\\open_in_gui.py
build_engine.py runs headless and cannot store colours, so run this after every rebuild.
Environment: FFSC_FCSTD = another file to open (e.g. a variant in cad/variants/), FFSC_LABEL = name
shown in the tree, FFSC_NO_SAVE = 1 to leave the file untouched (frozen iterations).
"""

import os

import FreeCAD as App
import FreeCADGui as Gui

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() \
    else os.path.join(os.environ.get("FFSC_ROOT", r"D:\Research\projects\methalox-ffsc-engine"), "cad")
PATH = os.environ.get("FFSC_FCSTD") or os.path.join(HERE, "output", "MFE280.FCStd")

COLOR = {"GRCop-42": (0.78, 0.42, 0.22), "Inconel 718": (0.63, 0.63, 0.66), "SX500": (0.40, 0.48, 0.62),
         "MAR-M-247": (0.45, 0.40, 0.35), "Ti-6Al-4V": (0.75, 0.77, 0.82), "A286": (0.22, 0.22, 0.25),
         "304L": (0.82, 0.82, 0.86), "PTFE/Inconel seal": (0.90, 0.80, 0.25)}

ORIGIN_TYPES = ("App::Origin", "App::Line", "App::Plane", "App::Point")

doc = App.openDocument(PATH)
for o in doc.Objects:
    if o.ViewObject is not None:            # a GUI save can store everything hidden; always show the parts
        o.ViewObject.Visibility = o.TypeId not in ORIGIN_TYPES
    mat = getattr(o, "Material", None)
    if mat and o.ViewObject is not None:
        o.ViewObject.ShapeColor = COLOR.get(mat, (0.6, 0.6, 0.6))
        if o.Name.startswith("Plumbing") or "duct" in o.Name or "line" in o.Name:
            o.ViewObject.ShapeColor = (0.70, 0.66, 0.55) if "CH4" in o.Name or "Fuel" in o.Name or "FPB" in o.Name \
                else (0.55, 0.68, 0.80) if "LOX" in o.Name or "Ox" in o.Name else o.ViewObject.ShapeColor
if os.environ.get("FFSC_LABEL"):
    doc.Label = os.environ["FFSC_LABEL"]
if not os.environ.get("FFSC_NO_SAVE"):
    doc.save()
Gui.activeDocument().activeView().viewIsometric()
Gui.SendMsgToActiveView("ViewFit")
