"""P&ID graphical symbols drawn with the Sheet primitives (units mm on the sheet).

Equipment, valve and actuator forms follow ISO 10628-2; instrument functions follow
ANSI/ISA-5.1: circle = discrete field instrument, hexagon = computer function (engine
control unit), diamond = interlock logic. Line widths: 0.7 process, 0.35 secondary,
0.25 dashed electrical signal, chain line for shafts and mechanical links.
"""

import math


def flow_arrow(s, p, q, frac=0.5, size=3.0, layer="SYMBOL"):
    x = p[0] + (q[0] - p[0]) * frac
    y = p[1] + (q[1] - p[1]) * frac
    L = math.hypot(q[0] - p[0], q[1] - p[1]) or 1.0
    ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
    tip = (x + ux * size / 2, y + uy * size / 2)
    s.arrowhead(tip, (x - ux * size / 2, y - uy * size / 2), size, size * 0.6, layer)


def pipe(s, pts, minor=False, arrows=(), label=None, seg=0, offset=1.6, side=1, h=2.2, at=0.5):
    """Process line through pts; arrows on the listed segments; label along segment `seg`."""
    s.poly(pts, "PROCESS_MINOR" if minor else "PROCESS")
    for i in arrows:
        flow_arrow(s, pts[i], pts[i + 1], 0.5 if i != seg or not label else 0.82)
    if label:
        (x0, y0), (x1, y1) = pts[seg], pts[seg + 1]
        xm, ym = x0 + (x1 - x0) * at, y0 + (y1 - y0) * at
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
        if ang > 90 or ang <= -90:
            ang += 180
        nx, ny = -math.sin(math.radians(ang)), math.cos(math.radians(ang))
        s.text(label, (xm + nx * offset * side, ym + ny * offset * side), h, "BOTTOM_CENTER" if side > 0 else "TOP_CENTER",
               rot=ang, width=0.85)


def tee(s, p):
    s.dot(p, 0.9, "SYMBOL")


def pump(s, c, r=7.0, out="right", tag=None, desc=None, tag_pos="below"):
    s.circle(c, r, "SYMBOL")
    dirs = {"right": (1, 0), "left": (-1, 0), "down": (0, -1), "up": (0, 1)}
    ux, uy = dirs[out]
    apex = (c[0] + ux * r, c[1] + uy * r)
    b = 0.6 * r
    p1 = (c[0] - ux * b - uy * 0.78 * r, c[1] - uy * b + ux * 0.78 * r)
    p2 = (c[0] - ux * b + uy * 0.78 * r, c[1] - uy * b - ux * 0.78 * r)
    s.poly([apex, p1, p2], "SYMBOL_THIN", closed=True)
    _label(s, c, r, tag, desc, tag_pos)


def turbine(s, c, w=16.0, h=11.0, tag=None, desc=None, tag_pos="right"):
    """Turbine: trapezoid widening in the flow direction (gas enters at the bottom)."""
    x, y = c
    s.poly([(x - 0.3 * w, y - h / 2), (x + 0.3 * w, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)], "SYMBOL", closed=True)
    _label(s, c, w / 2, tag, desc, tag_pos)


def vessel(s, c, w, h, tag=None, desc=None, tag_pos="inside"):
    x, y = c
    r = min(w, h) * 0.25
    pts = []
    for cx, cy, a0 in ((x + w / 2 - r, y + h / 2 - r, 0), (x - w / 2 + r, y + h / 2 - r, 90), (x - w / 2 + r, y - h / 2 + r, 180),
                       (x + w / 2 - r, y - h / 2 + r, 270)):
        for k in range(7):
            a = math.radians(a0 + 15 * k)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    s.poly(pts, "SYMBOL", closed=True)
    if tag_pos == "inside" and tag:
        s.text(tag, (x, y + 1.0), 3.0, "BOTTOM_CENTER")
        if desc:
            s.text(desc, (x, y - 1.0), 2.0, "TOP_CENTER")
    else:
        _label(s, c, w / 2, tag, desc, tag_pos)


def hx(s, c, w=14.0, h=8.0, tag=None, desc=None, tag_pos="above"):
    x, y = c
    s.rect(x - w / 2, y - h / 2, w, h, "SYMBOL")
    s.poly([(x - w / 2 + 1, y - h / 2 + 1), (x - w / 4, y + h / 2 - 1), (x, y - h / 2 + 1), (x + w / 4, y + h / 2 - 1),
            (x + w / 2 - 1, y - h / 2 + 1)], "SYMBOL_THIN")
    _label(s, c, h / 2, tag, desc, tag_pos)


def _label(s, c, r, tag, desc, pos):
    if not tag:
        return
    if pos == "below":
        s.text(tag, (c[0], c[1] - r - 4.0), 3.0, "TOP_CENTER")
        if desc:
            s.text(desc, (c[0], c[1] - r - 8.0), 2.0, "TOP_CENTER")
    elif pos == "above":
        s.text(tag, (c[0], c[1] + r + 2.0), 3.0, "BOTTOM_CENTER")
        if desc:
            s.text(desc, (c[0], c[1] + r + 6.2), 2.0, "BOTTOM_CENTER")
    elif pos == "left":
        s.text(tag, (c[0] - r - 2.5, c[1] + 0.5), 3.0, "BOTTOM_RIGHT")
        if desc:
            s.text(desc, (c[0] - r - 2.5, c[1] - 0.5), 2.0, "TOP_RIGHT")
    else:
        s.text(tag, (c[0] + r + 2.5, c[1] + 0.5), 3.0, "BOTTOM_LEFT")
        if desc:
            s.text(desc, (c[0] + r + 2.5, c[1] - 0.5), 2.0, "TOP_LEFT")


def valve(s, c, orient="v", body="ball", act=None, act_side=1, tag=None, tag_side=-1, fail=None, size=3.2):
    """Two-way valve (ISO 10628-2). body: gate | ball | globe | check | angle.
    act: None | 'M' (electric motor/EM) | 'S' (solenoid) | 'D' (diaphragm, self-acting).
    act_side: +1 actuator to the right (vertical valve) / above (horizontal), -1 opposite.
    Returns the actuator connection point (for signal lines) or None."""
    x, y = c
    a = size
    if orient == "v":
        t1, t2 = [(x - a, y + a), (x + a, y + a), (x, y)], [(x - a, y - a), (x + a, y - a), (x, y)]
    else:
        t1, t2 = [(x - a, y - a), (x - a, y + a), (x, y)], [(x + a, y - a), (x + a, y + a), (x, y)]
    s.poly(t1, "SYMBOL", closed=True)
    if body == "check":
        s.hatch([t2], solid=True, layer="SYMBOL")
    s.poly(t2, "SYMBOL", closed=True)
    if body == "ball":
        s.circle(c, 1.2, "SYMBOL_THIN")
    elif body == "globe":
        s.dot(c, 0.9, "SYMBOL")
    conn = None
    if act:
        if orient == "v":
            stem_end = (x + act_side * 6.0, y)
            ac = (x + act_side * 8.6, y)
        else:
            stem_end = (x, y + act_side * 6.0)
            ac = (x, y + act_side * 8.6)
        s.line(c, stem_end, "SYMBOL_THIN")
        if act == "M":
            s.circle(ac, 2.6, "SYMBOL")
            s.text("M", ac, 2.5, "MIDDLE_CENTER")
        elif act == "S":
            s.rect(ac[0] - 2.4, ac[1] - 2.4, 4.8, 4.8, "SYMBOL")
            s.text("S", ac, 2.5, "MIDDLE_CENTER")
        elif act == "D":
            if orient == "v":
                s.arc((x + act_side * 6.0, y), 3.0, -90 if act_side > 0 else 90, 90 if act_side > 0 else 270, "SYMBOL")
                s.line((x + act_side * 6.0, y - 3.0), (x + act_side * 6.0, y + 3.0), "SYMBOL")
            else:
                s.arc((x, y + act_side * 6.0), 3.0, 0 if act_side > 0 else 180, 180 if act_side > 0 else 360, "SYMBOL")
                s.line((x - 3.0, y + act_side * 6.0), (x + 3.0, y + act_side * 6.0), "SYMBOL")
        conn = ac
    if tag:                     # tag on the first line, alias and fail position on the second
        name, _, alias = tag.partition(" ")
        second = "  ".join(t for t in (alias, fail) if t)
        if orient == "v":
            xt = x + tag_side * (a + 2.0 + (11 if act and tag_side == act_side else 0))
            s.text(name, (xt, y + 0.4), 2.4, "BOTTOM_LEFT" if tag_side > 0 else "BOTTOM_RIGHT")
            if second:
                s.text(second, (xt, y - 0.4), 2.0, "TOP_LEFT" if tag_side > 0 else "TOP_RIGHT")
        else:
            yt = y + tag_side * (a + 2.0 + (11 if act and tag_side == act_side else 0))
            if tag_side > 0:
                s.text(name, (x, yt + (3.0 if second else 0)), 2.4, "BOTTOM_CENTER")
                if second:
                    s.text(second, (x, yt), 2.0, "BOTTOM_CENTER")
            else:
                s.text(name, (x, yt), 2.4, "TOP_CENTER")
                if second:
                    s.text(second, (x, yt - 3.0), 2.0, "TOP_CENTER")
    return conn


def relief(s, c, tag=None, vent="VENT"):
    """Spring-loaded relief valve on a branch: angle body, inlet from below, outlet to the
    right, spring above (ISO 10628-2 form). c is the valve centre."""
    x, y = c
    a = 3.0
    s.poly([(x - a, y - a), (x + a, y - a), (x, y)], "SYMBOL", closed=True)          # inlet from below
    s.poly([(x + a, y - a), (x + a, y + a), (x, y)], "SYMBOL", closed=True)          # outlet to the right
    zz = [(x, y)] + [(x + (1.6 if k % 2 == 0 else -1.6), y + 1.2 + k * 1.2) for k in range(5)] + [(x, y + 7.2)]
    s.poly(zz, "SYMBOL_THIN")
    s.line((x + a, y), (x + a + 6, y), "PROCESS_MINOR")
    s.arrowhead((x + a + 8, y), (x + a + 6, y), 2.2, 1.3, "SYMBOL")
    s.text(vent, (x + a + 9.5, y), 1.9, "MIDDLE_LEFT")
    if tag:
        s.text(tag, (x - a - 1.5, y + 2), 2.4, "BOTTOM_RIGHT")


def orifice(s, c, orient="v", tag=None, tag_side=1):
    x, y = c
    if orient == "v":
        s.line((x - 3, y + 0.8), (x + 3, y + 0.8), "SYMBOL")
        s.line((x - 3, y - 0.8), (x + 3, y - 0.8), "SYMBOL")
        if tag:
            s.text(tag, (x + tag_side * 4.5, y), 2.4, "MIDDLE_LEFT" if tag_side > 0 else "MIDDLE_RIGHT")
    else:
        s.line((x - 0.8, y - 3), (x - 0.8, y + 3), "SYMBOL")
        s.line((x + 0.8, y - 3), (x + 0.8, y + 3), "SYMBOL")
        if tag:
            s.text(tag, (x, y + tag_side * 4.5), 2.4, "BOTTOM_CENTER" if tag_side > 0 else "TOP_CENTER")


def instrument(s, c, tag, kind="field", r=5.0, conn=None):
    """ISA-5.1 function symbol. kind: field (circle), computer (hexagon), logic (diamond).
    conn: point on the process/equipment; joined with a thin instrument line."""
    x, y = c
    if conn is not None:
        dx, dy = conn[0] - x, conn[1] - y
        L = math.hypot(dx, dy) or 1.0
        s.line((x + dx / L * r, y + dy / L * r), conn, "SYMBOL_THIN")
    if kind == "field":
        s.circle(c, r, "SYMBOL")
    elif kind == "computer":
        s.poly([(x + r * math.cos(math.radians(a)), y + r * math.sin(math.radians(a))) for a in range(0, 360, 60)], "SYMBOL",
               closed=True)
    elif kind == "logic":
        s.poly([(x + r * 1.25, y), (x, y + r * 1.25), (x - r * 1.25, y), (x, y - r * 1.25)], "SYMBOL", closed=True)
    letters, number = tag.split("-", 1)
    s.text(letters, (x, y + 1.0), 2.4, "BOTTOM_CENTER", width=0.85)
    s.text(number, (x, y - 0.6), 2.4, "TOP_CENTER", width=0.85)


def signal(s, pts):
    s.poly(pts, "SIGNAL")


def shaft(s, p, q):
    s.line(p, q, "PHANTOM")


def connector(s, p, text, direction="up", w=8.0, h=4.5, side=1):
    """Interface / off-sheet connector: pentagon flag at the line end, label beside it."""
    x, y = p
    if direction == "up":
        pts = [(x - h / 2, y), (x + h / 2, y), (x + h / 2, y + w - h / 2), (x, y + w), (x - h / 2, y + w - h / 2)]
        s.text(text, (x + side * (h / 2 + 1.2), y + w / 2), 2.0, "MIDDLE_LEFT" if side > 0 else "MIDDLE_RIGHT", width=0.85)
    elif direction == "down":
        pts = [(x - h / 2, y), (x + h / 2, y), (x + h / 2, y - w + h / 2), (x, y - w), (x - h / 2, y - w + h / 2)]
        s.text(text, (x + side * (h / 2 + 1.2), y - w / 2), 2.0, "MIDDLE_LEFT" if side > 0 else "MIDDLE_RIGHT", width=0.85)
    elif direction == "left":
        pts = [(x, y - h / 2), (x, y + h / 2), (x - w + h / 2, y + h / 2), (x - w, y), (x - w + h / 2, y - h / 2)]
        s.text(text, (x - w / 2, y + side * (h / 2 + 1.0)), 1.9, "BOTTOM_CENTER" if side > 0 else "TOP_CENTER", width=0.85)
    else:
        pts = [(x, y - h / 2), (x, y + h / 2), (x + w - h / 2, y + h / 2), (x + w, y), (x + w - h / 2, y - h / 2)]
        s.text(text, (x + w / 2, y + side * (h / 2 + 1.0)), 1.9, "BOTTOM_CENTER" if side > 0 else "TOP_CENTER", width=0.85)
    s.poly(pts, "SYMBOL", closed=True)
