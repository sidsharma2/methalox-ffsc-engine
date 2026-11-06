"""Check the wedge sector factor of a nozzle-only case without using the monitors.

    python cfd/check_wedge.py CASE [WEDGE_DEG]

CASE is a Windows copy of the case with an ASCII polyMesh. Prints the measured area of the inlet and outlet patches
against pi R^2 for the arc factor 360 / theta and for the flat-face factor 2 pi / sin(theta) of post_compare.py.
"""

import math
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from post_compare import sector_factor

case = Path(sys.argv[1])
wedge = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
mesh = case / "constant" / "polyMesh"
text = (mesh / "points").read_text(errors="ignore")
pts = np.array(re.findall(r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", text[text.index("FoamFile"):]), float)
faces = [list(map(int, m.split())) for m in re.findall(r"\d+\(([\d\s]+)\)", (mesh / "faces").read_text(errors="ignore"))]
boundary = (mesh / "boundary").read_text()


def area(f):
    p = pts[f]
    c = p.mean(0)
    return 0.5 * sum(np.linalg.norm(np.cross(p[i] - c, p[(i + 1) % len(p)] - c)) for i in range(len(p)))


for name in ("inlet", "outlet"):
    m = re.search(name + r"\s*\{[^}]*?nFaces\s+(\d+);\s*startFace\s+(\d+);", boundary)
    n, start = int(m.group(1)), int(m.group(2))
    ids = range(start, start + n)
    A = sum(area(faces[i]) for i in ids)
    p = pts[np.unique(np.concatenate([faces[i] for i in ids]))]
    R = np.hypot(p[:, 1], p[:, 2]).max()
    full = math.pi * R ** 2
    print(f"{name}: {n} faces, R {R:.6f} m, 360/theta gives {360 / wedge * A / full:.6f} of pi R^2, 2 pi / sin(theta) gives {sector_factor(wedge) * A / full:.6f}")
