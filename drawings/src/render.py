"""Build helpers: DXF -> AutoCAD (DWG + PDF) -> PNG preview, and set PDF merging."""

import subprocess
from pathlib import Path

from pypdf import PdfWriter

import acad

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "drawings"
GS = Path(r"C:\Users\siddh\AppData\Local\Programs\Ghostscript\gs10.05.1\bin\gswin64c.exe")


def publish(sheet, name, paper="A3", png=True):
    """Save <name>.dxf, plot <name>.pdf and save <name>.dwg with AutoCAD; optional PNG preview."""
    (OUT / "dxf").mkdir(parents=True, exist_ok=True)
    (OUT / "dwg").mkdir(parents=True, exist_ok=True)
    (OUT / "pdf").mkdir(parents=True, exist_ok=True)
    dxf = OUT / "dxf" / f"{name}.dxf"
    sheet.save(dxf)
    pdf, dwg = OUT / "pdf" / f"{name}.pdf", OUT / "dwg" / f"{name}.dwg"
    for f in (pdf, dwg):
        if f.exists():
            f.unlink()
    ok, log = acad.run(dxf, dwg=dwg, pdf=pdf, paper=paper)
    if not ok:
        raise RuntimeError(f"AutoCAD failed for {name}:\n{log[-2000:]}")
    if png:
        (OUT / "preview").mkdir(exist_ok=True)
        subprocess.run([str(GS), "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m", "-r110",
                        f"-sOutputFile={OUT / 'preview' / (name + '.png')}", str(pdf)], check=True)
    return pdf


def merge(pdfs, target):
    w = PdfWriter()
    for p in pdfs:
        w.append(str(p))
    with open(target, "wb") as f:
        w.write(f)
