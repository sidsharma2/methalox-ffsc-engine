"""Render shaded views of the assembly to figures/cad_*.png (FreeCAD GUI, read-only).

Run:  "C:\\Program Files\\FreeCAD 1.1\\bin\\freecad.exe" cad\\render_views.py
Set FFSC_CAD_OUT to render another build (e.g. cad\\output_improved). Exits when done.
"""

import os

import FreeCAD as App
import FreeCADGui as Gui
import time

from PySide import QtCore, QtGui

ROOT = os.environ.get("FFSC_ROOT", r"D:\Research\projects\methalox-ffsc-engine")
SRC = os.path.join(os.environ.get("FFSC_CAD_OUT", os.path.join(ROOT, "cad", "output")), "MFE280.FCStd")
FIG = os.path.join(ROOT, "figures")
TAG = os.environ.get("FFSC_RENDER_TAG", "")

COLOR = {"GRCop-42": (0.78, 0.42, 0.22), "Inconel 718": (0.63, 0.63, 0.66), "SX500": (0.40, 0.48, 0.62),
         "MAR-M-247": (0.45, 0.40, 0.35), "Ti-6Al-4V": (0.75, 0.77, 0.82), "A286": (0.22, 0.22, 0.25),
         "304L": (0.82, 0.82, 0.86), "PTFE/Inconel seal": (0.90, 0.80, 0.25)}


def pump_events(n=20):
    for _ in range(n):
        QtGui.QApplication.processEvents()
        time.sleep(0.05)


def render():
    try:
        _render()
    except Exception as err:
        App.Console.PrintError(f"render failed: {err}
")
    finally:
        os._exit(0)


def _render():
    doc = App.openDocument(SRC)
    for o in doc.Objects:
        if o.ViewObject is not None:
            o.ViewObject.Visibility = True
        mat = getattr(o, "Material", None)
        if mat and o.ViewObject is not None:
            c = COLOR.get(mat, (0.6, 0.6, 0.6))
            n = o.Name
            if "LOX" in n or n.startswith("Ox_") or "MOV" in n or "FPOV" in n:
                c = (0.45, 0.62, 0.82) if "duct" in n or "line" in n else c
            if ("CH4" in n or "Fuel" in n or "FPB_feed" in n or "Nozzle_return" in n) and ("duct" in n or "line" in n):
                c = (0.72, 0.62, 0.45)
            o.ViewObject.ShapeColor = c
    view = Gui.activeDocument().activeView()
    Gui.getMainWindow().showMaximized()
    pump_events(50)

    shots = [("iso", view.viewIsometric), ("front", view.viewFront), ("top", view.viewTop), ("right", view.viewRight)]
    for name, fn in shots:
        fn()
        Gui.SendMsgToActiveView("ViewFit")
        pump_events()
        view.saveImage(os.path.join(FIG, f"cad_{name}{TAG}.png"), 2400, 1800, "White")

    # half-section through the x-z plane (chamber axis and both turbopump axes)
    try:
        view.viewIsometric()
        Gui.SendMsgToActiveView("ViewFit")
        view.toggleClippingPlane(1, False, True, App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(1, 0, 0), -90)))
        pump_events()
        view.saveImage(os.path.join(FIG, f"cad_section{TAG}.png"), 2400, 1800, "White")
        view.toggleClippingPlane(0)
    except Exception as err:          # clipping API differs between versions; the other views are enough
        App.Console.PrintWarning(f"section render skipped: {err}\n")

    App.closeDocument(doc.Name)


QtCore.QTimer.singleShot(4000, render)
