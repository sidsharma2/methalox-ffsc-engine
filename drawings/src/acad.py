"""Drive AutoCAD 2025 headless (accoreconsole) to save DXF sheets as DWG and plot PDFs.

Each call starts one accoreconsole process on one input file with a generated script.
Plots use 'DWG To PDF.pc3', paper 'ISO full bleed A3 (420.00 x 297.00 MM)' at 1:1,
monochrome.ctb and object lineweights, so the PDF matches a manual plot.
"""

import subprocess
import tempfile
from pathlib import Path

ACCORE = Path(r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe")
PAPER = {"A3": ("ISO full bleed A3 (420.00 x 297.00 MM)", 420, 297),
         "A2": ("ISO full bleed A2 (594.00 x 420.00 MM)", 594, 420)}


def plot_script(pdf, paper="A3"):
    name, w, h = PAPER[paper]
    return ["-PLOT", "Y", "Model", "DWG To PDF.pc3", name, "M", "L", "N", "W", "0,0", f"{w},{h}",
            "1:1", "0,0", "Y", "monochrome.ctb", "Y", "A", str(pdf), "N", "Y"]


def run(src, dwg=None, pdf=None, paper="A3", timeout=240):
    """Open src (DXF/DWG), optionally plot to pdf and save as dwg (AutoCAD 2018 format)."""
    lines = ["FILEDIA", "0", "_.ZOOM", "_E"]
    if pdf:
        lines += plot_script(pdf, paper)
    if dwg:
        lines += ["_.SAVEAS", "2018", str(dwg)]
    lines += ["_.QUIT", "Y"]
    with tempfile.TemporaryDirectory() as td:
        scr = Path(td) / "job.scr"
        scr.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
        try:
            p = subprocess.run([str(ACCORE), "/i", str(src), "/s", str(scr), "/l", "en-US"],
                               capture_output=True, timeout=timeout, cwd=td)
            log = p.stdout.decode("utf-16-le", errors="ignore") if b"\x00" in p.stdout[:200] else p.stdout.decode(errors="ignore")
        except subprocess.TimeoutExpired as err:          # the console sometimes lingers after QUIT
            log = (err.stdout or b"").decode("utf-16-le", errors="ignore")
    ok = (not pdf or Path(pdf).exists()) and (not dwg or Path(dwg).exists())
    return ok, log
