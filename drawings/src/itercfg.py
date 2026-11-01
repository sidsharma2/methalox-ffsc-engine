"""Design iteration selection for the drawing pipeline (inputs, outputs, title-block data).

One switch selects the iteration, either the environment variable or a command-line flag:

    set FFSC_ITER=I2-C                     (or)    ... --iter I2-C

No switch (or FFSC_ITER=I1) is iteration 1 exactly as frozen at tag iter-1:
    inputs   results/, cad/output/
    outputs  drawings/ (MFE280-DWG-SET.pdf, MFE280-PID-SET.pdf), figures/
Any other ID:
    inputs   results/iterations/<ID>/, cad/iterations/<ID>/
    outputs  drawings/<ID>/ (MFE280-<ID>-DWG-SET.pdf, MFE280-<ID>-PID-SET.pdf), figures/<ID>/

Other switches (flag / environment variable):
    --addendum   FFSC_ADDENDUM=1   I1 only: single-sheet MFG addendum in drawings/I1-addendum/
    --out DIR    FFSC_DWG_OUT      drawing output root (scratch builds)
    --fig DIR    FFSC_FIG_DIR      render folder read by the VIS / MFG sheets
    --build DIR  FFSC_DWG_BUILD    folder of the extract_views JSON files (default <out>/build)
    --dxf-only   FFSC_DXF_ONLY=1   write DXF only, no AutoCAD run (fast checks)

The flags are removed from sys.argv when this module is imported, and copied to the
environment so that child processes (freecadcmd, render scripts) see the same selection.
Only the standard library is used: extract_views.py imports this module inside freecadcmd.
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("MFE_ROOT", Path(__file__).resolve().parents[2]))

_FLAGS = {"--iter": "FFSC_ITER", "--out": "FFSC_DWG_OUT", "--fig": "FFSC_FIG_DIR", "--build": "FFSC_DWG_BUILD"}
_SWITCHES = {"--addendum": "FFSC_ADDENDUM", "--dxf-only": "FFSC_DXF_ONLY"}


def _parse_argv():
    argv, out, i = sys.argv, [], 0
    while i < len(argv):
        a = argv[i]
        key, _, val = a.partition("=")
        if i > 0 and key in _FLAGS:
            if not val:
                i += 1
                val = argv[i] if i < len(argv) else ""
            os.environ[_FLAGS[key]] = val
        elif i > 0 and a in _SWITCHES:
            os.environ[_SWITCHES[a]] = "1"
        else:
            out.append(a)
        i += 1
    sys.argv[:] = out


_parse_argv()

ID = (os.environ.get("FFSC_ITER") or "").strip() or None
if ID == "I1":
    ID = None
IS_I1 = ID is None
ADDENDUM = os.environ.get("FFSC_ADDENDUM", "") not in ("", "0")
DXF_ONLY = os.environ.get("FFSC_DXF_ONLY", "") not in ("", "0")
if ADDENDUM and not IS_I1:
    raise SystemExit("--addendum is the iteration-1 MFG addendum; the other iterations carry MFG-009 in their set")

TAG = "I1" if IS_I1 else ID
RESULTS = ROOT / "results" if IS_I1 else ROOT / "results" / "iterations" / ID
CAD = ROOT / "cad" / "output" if IS_I1 else ROOT / "cad" / "iterations" / ID
MESH = CAD / "mesh"
_default_out = ROOT / "drawings" / ("I1-addendum" if ADDENDUM else "") if IS_I1 else ROOT / "drawings" / ID
OUT = Path(os.environ.get("FFSC_DWG_OUT") or _default_out)
BUILD = Path(os.environ.get("FFSC_DWG_BUILD") or OUT / "build")
_default_fig = (ROOT / "figures" / "I1-addendum" if ADDENDUM else ROOT / "figures") if IS_I1 else ROOT / "figures" / ID
FIG = Path(os.environ.get("FFSC_FIG_DIR") or _default_fig)
IMG = OUT / "img"
SET_DWG = OUT / ("MFE280-DWG-SET.pdf" if IS_I1 else f"MFE280-{ID}-DWG-SET.pdf")
SET_PID = OUT / ("MFE280-PID-SET.pdf" if IS_I1 else f"MFE280-{ID}-PID-SET.pdf")

DESIGN = json.load(open(RESULTS / "design.json", encoding="utf-8"))
_cfg_file = RESULTS / "config.json"
CONFIG = json.load(open(_cfg_file, encoding="utf-8")) if _cfg_file.exists() else DESIGN["config"]
ITERATION = CONFIG.get("iteration") or {"id": "I1", "rev": "A", "title": "Iteration 1"}
REV = "A" if IS_I1 else ITERATION.get("rev", "A")
m = re.match(r"I(\d+)", TAG)
IT_NO = int(m.group(1)) if m else 1
TECH_REF = f"FREECAD v1.1, IT. {IT_NO}"
PID_TECH_REF = f"PID DB v1, IT. {IT_NO}"
LABEL = "ITERATION 1" if IS_I1 else f"ITERATION {IT_NO} ({ID})"

# CAD switches (config "cad"): all off for iteration 1
CADSW = CONFIG.get("cad") or {}
WELDED = list(CADSW.get("welded_joints", []))
WELD_REASON = "I1/I3: WELDED, NOT SERVICEABLE"
LASER = CADSW.get("ignition") == "laser"
SINGLE_INJ = bool(CADSW.get("single_piece_injector"))
INTEGRAL_MAN = bool(CADSW.get("integral_manifolds"))
BEARINGS = CADSW.get("bearings") or {}
HYDRO_FUEL = BEARINGS.get("fuel") == "hydrostatic"
HYBRID_OX = str(BEARINGS.get("ox", "")).lower().startswith("hybrid")

# text that names input files on the sheets (iteration 1 wording kept as issued)
RES_TXT = "RESULTS/" if IS_I1 else f"RESULTS/ITERATIONS/{ID}/"
CAD_TXT = "CAD/OUTPUT/" if IS_I1 else f"CAD/ITERATIONS/{ID}/"


def welded(joint_name):
    return joint_name in WELDED
