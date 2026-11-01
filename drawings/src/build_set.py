"""Build the complete drawing set of one design iteration with one command.

    .venv\\Scripts\\python.exe drawings\\src\\build_set.py --iter I2-C      iteration 2, candidate C
    .venv\\Scripts\\python.exe drawings\\src\\build_set.py --addendum       iteration-1 MFG-009 addendum
    .venv\\Scripts\\python.exe drawings\\src\\build_set.py                  iteration 1 (frozen set)

Later iterations run every step into drawings/<ID>/ and figures/<ID>/:
  1. extract_views.py in freecadcmd (cad/iterations/<ID>/MFE280.FCStd -> drawings/<ID>/build/*.json)
  2. renders: scripts/render_sections.py, render_cad.py, render_mfg.py
  3. mechanical set: make_mech_drawings.py -> MFE280-<ID>-DWG-SET.pdf (11 sheets)
  4. P&ID set: make_pid_set.py -> MFE280-<ID>-PID-SET.pdf (5 sheets)
Iteration 1 rebuilds only steps 3 and 4 from the frozen inputs (drawings/build, figures/), which
reproduces the issued DXF content; --extract / --render force steps 1 / 2 (they rewrite issued files).
--addendum renders the I1 route colours into figures/I1-addendum/ and writes the single sheet
drawings/I1-addendum/pdf/MFE280-MFG-009.pdf (sheet 1/1); the I1 set is not touched.

Options: --skip-extract, --skip-render, --mech-only, --pid-only, plus the itercfg flags.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OWN = {"--skip-extract", "--skip-render", "--mech-only", "--pid-only", "--extract", "--render"}
opts = {a for a in sys.argv[1:] if a in OWN}
sys.argv = [a for a in sys.argv if a not in OWN]
sys.path.insert(0, str(HERE))
import itercfg as IT  # noqa: E402  (parses --iter / --addendum and exports them to the environment)

ROOT = IT.ROOT
PY = sys.executable
FREECADCMD = r"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe"


def run(args, label):
    t0 = time.time()
    print(f"[build_set] {label} ...", flush=True)
    env = dict(os.environ)
    env.pop("MFE_VIEWS", None)
    r = subprocess.run(args, cwd=ROOT, env=env)
    if r.returncode != 0:
        raise SystemExit(f"[build_set] {label} failed (exit {r.returncode})")
    print(f"[build_set] {label} done in {time.time() - t0:.0f} s", flush=True)


def main():
    if IT.ADDENDUM:
        if "--skip-render" not in opts:
            run([PY, str(ROOT / "scripts" / "render_mfg.py")], "route-coloured renders (I1 addendum)")
        run([PY, str(HERE / "make_mech_drawings.py")], "MFG-009 addendum sheet")
        print("[build_set] addendum:", IT.OUT / "pdf" / "MFE280-MFG-009.pdf")
        return
    later = not IT.IS_I1
    do_extract = (later and "--skip-extract" not in opts) or "--extract" in opts
    do_render = (later and "--skip-render" not in opts) or "--render" in opts
    if "--pid-only" not in opts:
        if do_extract:
            IT.BUILD.mkdir(parents=True, exist_ok=True)
            run([FREECADCMD, str(HERE / "extract_views.py")], f"view extraction ({IT.TAG})")
        if do_render:
            for sc in ("render_sections.py", "render_cad.py", "render_mfg.py"):
                if sc == "render_mfg.py" and IT.IS_I1:
                    continue                      # I1 route colours belong to the addendum
                run([PY, str(ROOT / "scripts" / sc)], f"{sc} ({IT.TAG})")
        run([PY, str(HERE / "make_mech_drawings.py")], f"mechanical set ({IT.TAG})")
    if "--mech-only" not in opts:
        run([PY, str(HERE / "make_pid_set.py")], f"P&ID set ({IT.TAG})")
    print("[build_set] sets:", IT.SET_DWG, IT.SET_PID)


if __name__ == "__main__":
    main()
