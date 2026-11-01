"""Helpers for the MFE-280 mechanical drawings: view placement, section hatching,
clipping for detail views, ISO fastener designations and data loading.

Geometry comes from <out>/build/<view>.json (written by extract_views.py in FreeCAD);
numbers come from design.json, cooling_profile.csv, bom.csv and layout.json of the selected
iteration (itercfg: results/ and cad/output/ for iteration 1, results/iterations/<ID>/ and
cad/iterations/<ID>/ otherwise).
"""

import csv
import json
import math
from pathlib import Path

import itercfg

ROOT = Path(__file__).resolve().parents[2]
BUILD = itercfg.BUILD

DESIGN = itercfg.DESIGN
LAYOUT = json.load(open(itercfg.CAD / "layout.json", encoding="utf-8"))
BOM = list(csv.DictReader(open(itercfg.CAD / "bom.csv", encoding="utf-8")))
PROFILE = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(open(itercfg.RESULTS / "cooling_profile.csv"))]
JOINTS = {j["name"]: j for j in DESIGN["joints"]}
IJOINTS = {j["name"]: j for j in DESIGN["internal_joints"]}
BOM_PARTS = {r["part"] for r in BOM}


def load_view(name):
    return json.load(open(BUILD / f"{name}.json", encoding="utf-8"))


def bom_row(part):
    for r in BOM:
        if r["part"] == part:
            return r
    raise KeyError(part)


def in_bom(part):
    return part in BOM_PARTS


def asm_mass(assembly):
    return sum(float(r["mass_kg"]) for r in BOM if r["assembly"] == assembly)


def mm(m):
    return 1000.0 * m


def fmt(v, nd=1):
    s = f"{v:.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


# ------------------------------------------------------------------ ISO fasteners
# coarse pitch (ISO 261), nut height m max (ISO 4032), washer h (ISO 7089)
PITCH = {6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 14: 2.0, 16: 2.0, 20: 2.5, 24: 3.0, 27: 3.0, 30: 3.5}
NUT_M = {6: 5.2, 8: 6.8, 10: 8.4, 12: 10.8, 14: 12.8, 16: 14.8, 20: 18.0, 24: 21.5, 27: 23.8, 30: 25.6}
WASHER_H = {6: 1.6, 8: 1.6, 10: 2.0, 12: 2.5, 14: 2.5, 16: 3.0, 20: 3.0, 24: 4.0, 27: 4.0, 30: 4.0}
L_SERIES = [20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 180, 200,
            220, 240, 260, 280, 300]
K_TORQUE = 0.15        # nut factor, MoS2-lubricated A286 / Inconel 718 threads


def through_bolt(d, t_flange):
    """ISO 4014 hex bolt through two flanges of thickness t (mm) with two ISO 7089 washers
    and an ISO 4032 nut; L = grip + 2 h + m + 2 P rounded up to the length series."""
    d = int(round(d))
    L_min = 2 * t_flange + 2 * WASHER_H[d] + NUT_M[d] + 2 * PITCH[d]
    L = next(x for x in L_SERIES if x >= L_min - 1e-9)
    return {"bolt": f"ISO 4014 M{d}X{L}", "nut": f"ISO 4032 M{d}", "washer": f"ISO 7089 {d}", "L": L,
            "L_min": L_min, "grip": 2 * t_flange}


def torque_Nm(preload_N, d_m, K=K_TORQUE):
    return K * preload_N * d_m


def grade_label(g):
    return {"Inconel 718": "IN718", "A286": "A286"}.get(g, g.upper())


def mat_label(m):
    return {"Inconel 718": "INCONEL 718", "GRCop-42": "GRCOP-42", "Ti-6Al-4V": "TI-6AL-4V",
            "PTFE/Inconel seal": "IN718 + PTFE", "MAR-M-247": "MAR-M-247"}.get(m, m.upper())


# ------------------------------------------------------------------ 2-D clipping
def _clip_seg_convex(p, q, poly):
    """Cyrus-Beck clip of segment p-q against a convex polygon (CCW). Returns (t0, t1) or None."""
    t0, t1 = 0.0, 1.0
    dx, dy = q[0] - p[0], q[1] - p[1]
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        nx, ny = ey, -ex                   # outward normal for CCW
        num = nx * (p[0] - a[0]) + ny * (p[1] - a[1])
        den = nx * dx + ny * dy
        if abs(den) < 1e-14:
            if num > 0:
                return None
            continue
        t = -num / den
        if den < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return t0, t1


def clip_polyline(pts, poly):
    """Pieces of a polyline inside a convex CCW polygon."""
    out, cur = [], []
    for p, q in zip(pts[:-1], pts[1:]):
        r = _clip_seg_convex(p, q, poly)
        if r is None:
            if len(cur) > 1:
                out.append(cur)
            cur = []
            continue
        a = (p[0] + r[0] * (q[0] - p[0]), p[1] + r[0] * (q[1] - p[1]))
        b = (p[0] + r[1] * (q[0] - p[0]), p[1] + r[1] * (q[1] - p[1]))
        if cur and math.hypot(cur[-1][0] - a[0], cur[-1][1] - a[1]) < 1e-9:
            cur.append(b)
        else:
            if len(cur) > 1:
                out.append(cur)
            cur = [a, b]
        if r[1] < 1.0 - 1e-12:
            out.append(cur)
            cur = []
    if len(cur) > 1:
        out.append(cur)
    return out


def clip_polygon(subject, poly):
    """Sutherland-Hodgman clip of a closed polygon by a convex CCW polygon."""
    out = list(subject)
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        inp, out = out, []
        if not inp:
            break

        def inside(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

        def inter(p, q):
            x1, y1, x2, y2 = p[0], p[1], q[0], q[1]
            x3, y3, x4, y4 = a[0], a[1], b[0], b[1]
            den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            if abs(den) < 1e-14:
                return q
            t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
            return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        s = inp[-1]
        for e in inp:
            if inside(e):
                if not inside(s):
                    out.append(inter(s, e))
                out.append(e)
            elif inside(s):
                out.append(inter(s, e))
            s = e
    return out


def circle_poly(c, r, n=96):
    return [(c[0] + r * math.cos(2 * math.pi * i / n), c[1] + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def rect_poly(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def point_in_poly(p, poly):
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def poly_area(pts):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


# ------------------------------------------------------------------ view placement
HATCH_STYLES = [(45.0, 1.0), (135.0, 1.0), (45.0, 0.6), (135.0, 0.6), (0.0, 1.0), (90.0, 1.0)]


class View:
    """Places one extracted view on a sheet: sheet = at + R(rot) (p - ref) / den.
    clip: convex polygon in model coordinates (detail views)."""

    def __init__(self, sheet, data, den, at, ref=(0.0, 0.0), rot=0.0, clip=None):
        self.s, self.d, self.den, self.at, self.ref = sheet, data, float(den), at, ref
        self.c, self.sn = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        self.clip = clip
        if clip and poly_area(clip) < 0:
            self.clip = list(reversed(clip))

    def P(self, x, y=None):
        if y is None:
            x, y = x
        dx, dy = (x - self.ref[0]) / self.den, (y - self.ref[1]) / self.den
        return (self.at[0] + self.c * dx - self.sn * dy, self.at[1] + self.sn * dx + self.c * dy)

    def L(self, model_len):
        return model_len / self.den

    def _lines(self, plines, layer):
        for pl in plines:
            pieces = clip_polyline(pl, self.clip) if self.clip else [pl]
            for pc in pieces:
                if len(pc) >= 2:
                    self.s.poly([self.P(p) for p in pc], layer)

    def visible(self, layer="VISIBLE", skip=None):
        pls = self.d["visible"]
        if skip:
            pls = [p for p in pls if not skip(p)]
        self._lines(pls, layer)

    def polyline(self, pts, layer="VISIBLE", closed=False):
        if closed:
            pts = list(pts) + [pts[0]]
        self._lines([pts], layer)

    def _loop(self, pts):
        if self.clip:
            pts = clip_polygon(pts, self.clip)
        return [self.P(p) for p in pts] if len(pts) >= 3 else None

    def sections(self, base=2.0, solid_below=0.8, only=None, exclude=(), style_override=None, solid_parts=(),
                 masks=()):
        """Hatch every cut face (ISO 128-50). Thin sections (mean thickness on paper below
        solid_below mm) are filled solid. masks: paper rectangles (x0, y0, x1, y1) kept free of
        hatching where dimension text sits on a cut face."""
        styles = self.d.get("hatch", {})
        for n, p in self.d["parts"].items():
            if p["cat"] == "weld" and p["faces"]:          # weld beads cut by the plane: filled black
                solid_parts = tuple(solid_parts) + (n,)
            elif p["cat"] not in ("hatch", "cutonly") or not p["faces"]:
                continue
            if only and n not in only:
                continue
            if n in exclude:
                continue
            st = (style_override or {}).get(n, styles.get(n, 0))
            ang, f = HATCH_STYLES[st % len(HATCH_STYLES)]
            for face in p["faces"]:
                outer = self._loop(face["outer"])
                if not outer:
                    continue
                holes = [h for h in (self._loop(hh) for hh in face["holes"]) if h]
                for m in masks:
                    if point_in_poly(((m[0] + m[2]) / 2, (m[1] + m[3]) / 2), outer):
                        holes.append(rect_poly(*m))
                t_paper = 2.0 * face["area"] / max(face["perim"], 1e-9) / self.den
                solid = n in solid_parts or t_paper < solid_below
                hatch_loops(self.s, [outer] + holes, angle=ang, spacing=base * f, solid=solid)

    def cut_outlines(self, names, layer="VISIBLE"):
        for n in names:
            for face in self.d["parts"][n]["faces"]:
                self.polyline(face["outer"], layer, closed=True)
                for h in face["holes"]:
                    self.polyline(h, layer, closed=True)

    def bearings(self):
        """ISO 8826-1 general simplified representation: outline + free-standing upright cross."""
        for n, p in self.d["parts"].items():
            if p["cat"] != "bearing":
                continue
            for face in p["faces"]:
                xs = [q[0] for q in face["outer"]]
                ys = [q[1] for q in face["outer"]]
                x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                hx, hy = 0.32 * (x1 - x0), 0.32 * (y1 - y0)
                self.polyline([(cx - hx, cy), (cx + hx, cy)], "VISIBLE")
                self.polyline([(cx, cy - hy), (cx, cy + hy)], "VISIBLE")

    def anchor(self, name, frac=None):
        p = self.d["parts"][name]
        if frac is not None and p["faces"]:
            f = max(p["faces"], key=lambda f: f["area"])
            pts = f["outer"]
            k = int(frac * (len(pts) - 1))
            return self.P(pts[k])
        if "anchor" in p:
            return self.P(p["anchor"])
        if p["faces"]:
            f = max(p["faces"], key=lambda f: f["area"])
            xs = [q[0] for q in f["outer"]]
            ys = [q[1] for q in f["outer"]]
            return self.P((sum(xs) / len(xs), sum(ys) / len(ys)))
        bb = p["bbox"]
        return self.P(((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2))

    def faces_of(self, name):
        return self.d["parts"][name]["faces"]


def balloon_row(sheet, items, y, x0, x1, r=4.25):
    """Balloons evenly spaced on a horizontal line, ordered by target x so that leaders
    do not cross. items: list of (label, target)."""
    items = sorted(items, key=lambda t: t[1][0])
    n = len(items)
    for i, (lab, tgt) in enumerate(items):
        x = x0 + (x1 - x0) * (i / (n - 1) if n > 1 else 0.5)
        sheet.balloon((x, y), lab, tgt, r=r)


def balloon_col(sheet, items, x, y0, y1, r=4.25):
    items = sorted(items, key=lambda t: t[1][1])
    n = len(items)
    for i, (lab, tgt) in enumerate(items):
        y = y0 + (y1 - y0) * (i / (n - 1) if n > 1 else 0.5)
        sheet.balloon((x, y), lab, tgt, r=r)


def break_line(sheet, p, q, amp=1.6, layer="THIN"):
    """ISO 128-20 thin continuous line with zigzag (break boundary)."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    L = math.hypot(dx, dy)
    ux, uy = dx / L, dy / L
    m = (p[0] + dx / 2, p[1] + dy / 2)
    a = (m[0] - ux * 2.0, m[1] - uy * 2.0)
    b = (m[0] - ux * 0.7 - uy * amp, m[1] - uy * 0.7 + ux * amp)
    c = (m[0] + ux * 0.7 + uy * amp, m[1] + uy * 0.7 - ux * amp)
    d = (m[0] + ux * 2.0, m[1] + uy * 2.0)
    sheet.poly([p, a, b, c, d, q], layer)


# ------------------------------------------------------------------ profile and view look-ups
def profile_at(x_m):
    """Linear interpolation of cooling_profile.csv at axial station x (m)."""
    P = PROFILE
    if x_m <= P[0]["x"]:
        return P[0]
    for a, b in zip(P[:-1], P[1:]):
        if a["x"] <= x_m <= b["x"]:
            t = (x_m - a["x"]) / (b["x"] - a["x"]) if b["x"] > a["x"] else 0.0
            return {k: a[k] + t * (b[k] - a[k]) for k in a}
    return P[-1]


def wall_mid(x_mm):
    """Radius (mm) inside the solid chamber/nozzle wall at axial station x (mm)."""
    r = profile_at(x_mm / 1000.0)
    return mm(r["r"] + 0.5 * (r["t_hot"] + r["H"]))


def face_extreme(view, name, side, direction):
    """Outline point of a part's cut face on one side of the axis (side = +1/-1 in view y),
    extreme in direction (dx, dy); returns sheet coordinates (balloon / leader target).
    Parts without a cut face fall back to the corner of their projected bounding box."""
    best, bv = None, -1e18
    for f in view.faces_of(name):
        for q in f["outer"]:
            if side and q[1] * side <= 0:
                continue
            val = q[0] * direction[0] + q[1] * direction[1]
            if val > bv:
                best, bv = q, val
    if best is None:
        bb = view.d["parts"][name]["bbox"]
        corners = [(bb[0], bb[1]), (bb[2], bb[1]), (bb[2], bb[3]), (bb[0], bb[3])]
        if side:
            corners = [c for c in corners if c[1] * side > 0] or corners
        best = max(corners, key=lambda q: q[0] * direction[0] + q[1] * direction[1])
    return view.P(best)


def faces_bbox(view, name):
    pts = [q for f in view.faces_of(name) for q in f["outer"]]
    if not pts:
        return tuple(view.d["parts"][name]["bbox"])
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    return min(xs), min(ys), max(xs), max(ys)


def has_part(view, name):
    return name in view.d["parts"]


def weld_symbol(sheet, target, at, side=1, tail="141", all_round=True, length=16.0, h=2.2):
    """ISO 2553 (system A) weld symbol: arrow line from the reference-line start `at` to the joint
    `target`, continuous reference line of `length` towards side (+1 right, -1 left), dashed
    identification line under it, single-V butt symbol on the arrow side, all-round circle at the
    arrow / reference-line junction and the process number (ISO 4063) in the tail."""
    x, y = at
    sheet.line(target, at, "THIN")
    sheet.arrowhead(target, at, 2.5, 0.85)
    x1 = x + side * length
    sheet.line((x, y), (x1, y), "THIN")
    sheet.line((x, y - 1.0), (x1 - side * 2.0, y - 1.0), "HIDDEN")
    xv = x + side * 0.45 * length
    sheet.poly([(xv - 1.6, y + 2.6), (xv, y), (xv + 1.6, y + 2.6)], "THIN")
    if all_round:
        sheet.circle((x, y), 1.4, "THIN")
    if tail:
        sheet.line((x1, y), (x1 + side * 2.2, y + 2.2), "THIN")
        sheet.line((x1, y), (x1 + side * 2.2, y - 2.2), "THIN")
        sheet.text(tail, (x1 + side * 3.2, y), h, "MIDDLE_LEFT" if side > 0 else "MIDDLE_RIGHT", width=0.9)


def weld_marks(view, pick=None):
    """Weld beads recorded by extract_views (cat 'weld') with a cut face or a kept half in the view:
    list of (name, model-space target point on the bead). pick: {name: (dx, dy)} chooses the outline
    point extreme in that direction; default the point farthest from the view axis."""
    out = []
    for n, p in view.d["parts"].items():
        if p.get("cat") != "weld":
            continue
        pts = [q for f in p["faces"] for q in f["outer"]]
        if pts:
            d = (pick or {}).get(n)
            q = max(pts, key=(lambda q: q[0] * d[0] + q[1] * d[1]) if d else (lambda q: abs(q[1])))
            out.append((n, (q[0], q[1])))
        elif p.get("bbox"):
            bb = p["bbox"]
            out.append((n, ((bb[0] + bb[2]) / 2, bb[3])))
    return out


def bolt_set_points(z_top, grip, d, y):
    """Points (view coordinates, X = -z) on a through-bolt set built by cadlib.bolt_set:
    washer + head above z_top, washer + nut below z_top - grip. Outer points lie on the side
    of the bolt away from the axis (sign of y)."""
    tw, k, m = 0.16 * d, 0.65 * d, 0.84 * d
    sg = 1.0 if y >= 0 else -1.0
    xf = -z_top
    return {"head": (xf - tw - k, y), "washer_top": (xf - tw / 2, y + sg * d), "nut": (xf + grip + tw + m, y),
            "washer_nut": (xf + grip + tw / 2, y + sg * d), "shank": (xf + grip / 2, y + sg * d / 2),
            "nut_side": (xf + grip + tw + m / 2, y + sg * 0.6 * d)}


def balloon_stack(sheet, first, labels, target, r=4.25, step=(1, 0)):
    """ISO 6433 grouped item references: adjacent balloons with one leader from the first."""
    sheet.balloon(first, labels[0], target, r=r)
    for i, lab in enumerate(labels[1:], start=1):
        c = (first[0] + step[0] * 2 * r * i, first[1] + step[1] * 2 * r * i)
        sheet.circle(c, r, "BALLOON")
        sheet.text(str(lab), c, 3.5, "MIDDLE_CENTER", layer="BALLOON")


def dim_lin(sheet, p1, p2, base, angle=0.0, scale=1.0, text="<>", shift=0.0):
    """Linear dimension like Sheet.dim_linear, with the text moved along the dimension line by
    shift (paper mm) so that it clears centre lines."""
    ov = {"dimlfac": scale}
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)
    # foot points of p1, p2 on the dimension line through base
    def foot(p):
        t = (p[0] - base[0]) * ux + (p[1] - base[1]) * uy
        return (base[0] + t * ux, base[1] + t * uy)
    f1, f2 = foot(p1), foot(p2)
    mx, my = (f1[0] + f2[0]) / 2 + ux * shift, (f1[1] + f2[1]) / 2 + uy * shift
    nx, ny = -uy, ux                                  # text sits above the line (dimtad = 1)
    loc = (mx + nx * (0.8 + 1.25), my + ny * (0.8 + 1.25))
    d = sheet.msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle="ISO25", text=text, location=loc,
                                 override=ov, dxfattribs={"layer": "DIM"})
    d.render()
    return d


def hatch_loops(sheet, loops, angle=45.0, spacing=2.5, solid=False, layer="HATCH"):
    """Section hatch with islands: first loop external, the others islands (normal style, so
    nested holes and text masks stay clear in AutoCAD)."""
    from ezdxf.lldxf.const import BOUNDARY_PATH_EXTERNAL, BOUNDARY_PATH_OUTERMOST
    h = sheet.msp.add_hatch(dxfattribs={"layer": layer, "hatch_style": 0})
    if solid:
        h.set_solid_fill(color=7)
    else:
        h.set_pattern_fill("ANSI31", scale=spacing / 3.175, angle=angle - 45.0, color=7)
    for i, lp in enumerate(loops):
        if len(lp) >= 3:
            flags = BOUNDARY_PATH_EXTERNAL if i == 0 else BOUNDARY_PATH_OUTERMOST
            h.paths.add_polyline_path(lp, is_closed=True, flags=flags)
    return h


def place_row(targets_x, allowed, pitch=10.0):
    """Balloon x positions on one row: order follows the (sorted) target x, spacing >= pitch,
    positions restricted to the allowed intervals [(a, b), ...]."""
    allowed = sorted(allowed)

    def snap_right(x):
        for a, b in allowed:
            if x <= b:
                return max(x, a)
        return allowed[-1][1]

    def snap_left(x):
        for a, b in reversed(allowed):
            if x >= a:
                return min(x, b)
        return allowed[0][0]
    pos, cur = [], -1e9
    for tx in targets_x:
        p = snap_right(max(tx, cur + pitch))
        pos.append(p)
        cur = p
    for i in reversed(range(len(pos))):
        lim = allowed[-1][1] if i == len(pos) - 1 else pos[i + 1] - pitch
        if pos[i] > lim:
            pos[i] = snap_left(lim)
    return pos


def balloon_rows(sheet, top, bottom, y_top, y_bot, allowed_top, allowed_bot, pitch=10.0):
    """top/bottom: lists of (label, target). Balloons on two rows, leaders without crossings."""
    for items, y, allowed in ((top, y_top, allowed_top), (bottom, y_bot, allowed_bot)):
        items = sorted(items, key=lambda t: t[1][0])
        xs = place_row([t[1][0] for t in items], allowed, pitch)
        for (lab, tgt), x in zip(items, xs):
            sheet.balloon((x, y), lab, tgt)


def wrapped_notes(sheet, x, y_top, notes, chars=70, h=1.9, gap=1.3):
    """Numbered notes wrapped at a character count, continuation lines indented."""
    import textwrap
    y = y_top
    for i, n in enumerate(notes):
        lines = textwrap.wrap(n, chars - 4)
        for j, ln in enumerate(lines):
            sheet.text((f"{i + 1}. " if j == 0 else "    ") + ln, (x, y), h, "TOP_LEFT", width=0.9)
            y -= h + gap
    return y


def dim_text_mask(x_line, y_mid, text, h=2.5):
    """Paper rectangle under the text of a vertical dimension (text left of the line)."""
    L = 0.72 * h * len(text) + 1.0
    return (x_line - 0.8 - h - 0.6, y_mid - L / 2, x_line - 0.3, y_mid + L / 2)
