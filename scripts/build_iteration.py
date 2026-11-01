"""Build one iteration from config/iterations.yaml (builds:): design, full CAD with STEP, meshes.

    .venv/Scripts/python.exe scripts/build_iteration.py I2-C [--design-only]

Starts from the iteration-1 improved configuration, applies the build's cycle overrides and CAD
switches, and writes results/iterations/<ID>/ and cad/iterations/<ID>/ (FCStd, STEP, BOM, clash
report, mass summary, layout, mesh/). Iteration 1 stays in results/ and cad/output/.
"""

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ffsc import ROOT  # noqa: E402
from ffsc.design import design  # noqa: E402
from run_improved import apply  # noqa: E402

FREECADCMD = r"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe"


def config_for(bid):
    B = yaml.safe_load(open(ROOT / "config" / "iterations.yaml"))["builds"][bid]
    cfg = copy.deepcopy(json.load(open(ROOT / "results" / "improved" / "config_improved.json")))
    apply(cfg, B["mods"])
    cfg["cad"] = B.get("cad", {})
    cfg["iteration"] = {"id": bid, "rev": B["rev"], "title": B["title"], "options": B["options"]}
    return cfg


def freecad(script, env, log):
    r = subprocess.run([FREECADCMD, str(ROOT / "cad" / script)], env=env, capture_output=True, text=True, timeout=3600)
    log.write_text(r.stdout + r.stderr, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"{script} failed, see {log}")


def build(bid, design_only=False):
    cfg = config_for(bid)
    res_dir = ROOT / "results" / "iterations" / bid
    res_dir.mkdir(parents=True, exist_ok=True)
    design(cfg, verbose=False, write=True, out_dir=res_dir)
    json.dump(cfg, open(res_dir / "config.json", "w"), indent=2)
    print(f"[{bid}] design written to {res_dir}")
    if design_only:
        return
    cad_dir = ROOT / "cad" / "iterations" / bid
    cad_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, FFSC_RESULTS=str(res_dir), FFSC_CAD_OUT=str(cad_dir))
    env.pop("FFSC_NO_STEP", None)
    freecad("build_engine.py", env, cad_dir / "build.log")
    freecad("export_meshes.py", env, cad_dir / "mesh.log")
    ms = json.load(open(cad_dir / "mass_summary.json"))
    cl = json.load(open(cad_dir / "clash_report.json"))
    lay = json.load(open(cad_dir / "layout.json"))
    out = {"id": bid, "mass_kg": ms["total_modelled_kg"], "by_assembly_kg": ms["by_assembly_kg"],
           "clashes": cl["n_clashes"], "clash_list": cl["clashes"][:20],
           "envelope_mm": [lay["envelope_width_x_mm"], lay["envelope_width_y_mm"], lay["height_mm"]]}
    json.dump(out, open(res_dir / "cad_summary.json", "w"), indent=2)
    print(json.dumps({k: v for k, v in out.items() if k != "clash_list"}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--design-only", action="store_true")
    a = ap.parse_args()
    build(a.build, a.design_only)
