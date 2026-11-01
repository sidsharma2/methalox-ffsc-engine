"""Design and CAD-build one engine variant for mass screening.

    .venv/Scripts/python.exe scripts/build_variant.py NAME key=value [key=value ...]

Starts from the iteration-1 improved configuration, applies dotted-key overrides
(e.g. requirements.pc_bar=400 cycle.T_opb_K=900), writes results/variants/NAME/ and builds the
FreeCAD assembly into cad/variants/NAME/ (no STEP export). Prints and returns the mass roll-up.
"""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ffsc import ROOT  # noqa: E402
from ffsc.design import design  # noqa: E402
from run_improved import apply  # noqa: E402

FREECADCMD = r"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe"


def build(name, mods, cad=True):
    cfg = copy.deepcopy(json.load(open(ROOT / "results" / "improved" / "config_improved.json")))
    apply(cfg, mods)
    res_dir = ROOT / "results" / "variants" / name
    res_dir.mkdir(parents=True, exist_ok=True)
    design(cfg, verbose=False, write=True, out_dir=res_dir)
    json.dump({"mods": mods, "config": cfg}, open(res_dir / "variant.json", "w"), indent=2)
    if not cad:
        return None
    cad_dir = ROOT / "cad" / "variants" / name
    cad_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, FFSC_RESULTS=str(res_dir), FFSC_CAD_OUT=str(cad_dir), FFSC_NO_STEP="1")
    log = subprocess.run([FREECADCMD, str(ROOT / "cad" / "build_engine.py")], env=env, capture_output=True,
                         text=True, timeout=1800)
    (cad_dir / "build.log").write_text(log.stdout + log.stderr, encoding="utf-8")
    ms = json.load(open(cad_dir / "mass_summary.json"))
    cl = json.load(open(cad_dir / "clash_report.json"))
    lay = json.load(open(cad_dir / "layout.json"))
    out = {"name": name, "mass_kg": ms["total_modelled_kg"], "by_assembly_kg": ms["by_assembly_kg"],
           "clashes": cl["n_clashes"], "envelope_mm": [lay["envelope_width_x_mm"], lay["envelope_width_y_mm"],
                                                        lay["height_mm"]]}
    json.dump(out, open(res_dir / "cad_summary.json", "w"), indent=2)
    print(json.dumps(out))
    return out


if __name__ == "__main__":
    name = sys.argv[1]
    mods = {}
    for kv in sys.argv[2:]:
        k, v = kv.split("=", 1)
        mods[k] = float(v)
    build(name, mods)
