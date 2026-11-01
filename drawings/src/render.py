"""Build helpers: DXF -> AutoCAD (DWG + PDF) -> PNG preview, and set PDF merging.

The output root follows the iteration selection (itercfg.OUT): drawings/ for iteration 1,
drawings/<ID>/ for later iterations."""

import subprocess
from pathlib import Path

from pypdf import PdfWriter

import acad
import itercfg

ROOT = Path(__file__).resolve().parents[2]
OUT = itercfg.OUT
GS = Path(r"C:\Users\siddh\AppData\Local\Programs\Ghostscript\gs10.05.1\bin\gswin64c.exe")


def publish(sheet, name, paper="A3", png=True):
    """Save <name>.dxf, plot <name>.pdf and save <name>.dwg with AutoCAD; optional PNG preview."""
    (OUT / "dxf").mkdir(parents=True, exist_ok=True)
    dxf = OUT / "dxf" / f"{name}.dxf"
    images = getattr(sheet, "images", [])
    if itercfg.DXF_ONLY:                    # fast check: the published DXF only, same save sequence
        if images:
            tmp = OUT / "dxf" / f"{name}.acad.dxf"
            sheet.save(tmp)
            tmp.unlink(missing_ok=True)
            sheet.embed_images(dxf.parent)
        sheet.save(dxf)
        return None
    (OUT / "dwg").mkdir(parents=True, exist_ok=True)
    (OUT / "pdf").mkdir(parents=True, exist_ok=True)
    if images:
        # accoreconsole cannot resolve IMAGE entities read from a DXF (no raster object enabler at load),
        # so AutoCAD gets a vector-only copy and attaches the PNGs itself; the published DXF keeps
        # ezdxf IMAGE entities. Both live in drawings/dxf, so ..\img\ is valid from dxf/ and dwg/.
        src = OUT / "dxf" / f"{name}.acad.dxf"
        sheet.save(src)
        sheet.embed_images(dxf.parent)
        sheet.save(dxf)
    else:
        src = dxf
        sheet.save(dxf)
    pdf, dwg = OUT / "pdf" / f"{name}.pdf", OUT / "dwg" / f"{name}.dwg"
    for f in (pdf, dwg):
        if f.exists():
            f.unlink()
    ok, log = acad.run(src, dwg=dwg, pdf=pdf, paper=paper, images=images)
    if src != dxf:
        src.unlink(missing_ok=True)
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
