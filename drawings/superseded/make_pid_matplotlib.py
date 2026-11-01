"""Piping and instrumentation diagram (P&ID) of the MFE-280 engine.

Sheet: ISO 5457 A2 landscape with filing margin, ISO 7200 title block.
Graphical symbols after ISO 10628-2 (pumps, turbines, valves, vessels, heat exchangers,
orifices); instrument bubbles and tags after ANSI/ISA-5.1 (PT pressure transmitter,
TT temperature, ST speed, VT vibration, ZT position). Lettering heights per ISO 3098
(2.5 / 3.5 / 5 mm). Line sizes are taken from results/design.json.
Writes drawings/MFE280-PID-001.{pdf,svg,png}.
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "drawings"
OUT.mkdir(exist_ok=True)
D = json.load(open(ROOT / "results" / "design.json"))
CY, DU = D["cycle"], D["ducts"]
dn = lambda k: f"DN{round(DU[k] * 1000)}"

PT = 72 / 25.4                       # points per mm
LW_P, LW_S, LW_T = 0.5 * PT, 0.25 * PT, 0.18 * PT
H25, H35, H5 = 2.5 * PT, 3.5 * PT, 5.0 * PT
COL = {"lox": "#1f5fa8", "ch4": "#8a5a19", "ox_gas": "#c0392b", "fu_gas": "#d35400", "he": "#2e7d32",
       "gox": "#5d8fc9", "k": "#111111"}

fig = plt.figure(figsize=(594 / 25.4, 420 / 25.4))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 594)
ax.set_ylim(0, 420)
ax.set_aspect("equal")
ax.axis("off")


def text(x, y, s, h=H25, **kw):
    kw.setdefault("ha", "center")
    kw.setdefault("va", "center")
    ax.text(x, y, s, fontsize=h, family="DejaVu Sans", **kw)


def line(pts, fluid="k", lw=LW_P, ls="-", arrows=(), label=None, lpos=0, loff=(2, 2), lrot=0):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=COL[fluid], lw=lw, ls=ls, solid_capstyle="butt", zorder=2)
    for i in arrows:                                  # arrow at the middle of segment i
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
        ax.annotate("", xy=(xm + (x1 - x0) * 0.04, ym + (y1 - y0) * 0.04), xytext=(xm - (x1 - x0) * 0.04, ym - (y1 - y0) * 0.04),
                    arrowprops=dict(arrowstyle="-|>", color=COL[fluid], lw=lw, mutation_scale=9), zorder=3)
    if label:
        (x0, y0), (x1, y1) = pts[lpos], pts[lpos + 1]
        text((x0 + x1) / 2 + loff[0], (y0 + y1) / 2 + loff[1], label, H25 * 0.85, color=COL[fluid], rotation=lrot,
             ha="left" if lrot == 0 else "center")


def pump(x, y, r=8, tag="", direction="right", note=""):
    ax.add_patch(Circle((x, y), r, fill=False, lw=LW_P, color=COL["k"], zorder=4))
    ax.add_patch(Circle((x, y), r, color="white", zorder=3))
    if direction == "right":
        tri = [(x - r * 0.6, y + r * 0.75), (x - r * 0.6, y - r * 0.75), (x + r, y)]
    else:
        tri = [(x + r * 0.6, y + r * 0.75), (x + r * 0.6, y - r * 0.75), (x - r, y)]
    ax.add_patch(Polygon(tri, closed=True, fill=False, lw=LW_S, color=COL["k"], zorder=5))
    text(x, y - r - 3.5, tag, H25, weight="bold")
    if note:
        text(x, y - r - 7, note, H25 * 0.8)


def turbine(x, y, w=18, h=12, tag=""):
    poly = [(x - w * 0.3, y - h / 2), (x + w * 0.3, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)]
    ax.add_patch(Polygon(poly, closed=True, facecolor="white", edgecolor=COL["k"], lw=LW_P, zorder=4))
    text(x, y, "T", H25, weight="bold", zorder=5)
    text(x + w / 2 + 2, y - h / 2 - 1, tag, H25, weight="bold", ha="left")


def vessel(x, y, w, h, tag, inner=""):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0,rounding_size=4",
                                facecolor="white", edgecolor=COL["k"], lw=LW_P, zorder=4))
    text(x, y + 2, tag, H25, weight="bold", zorder=5)
    if inner:
        text(x, y - 3, inner, H25 * 0.8, zorder=5)


def valve(x, y, orient="v", tag="", kind="ball", act=True, side="right"):
    s = 3.2
    if orient == "v":
        t1 = [(x - s, y + s), (x + s, y + s), (x, y)]
        t2 = [(x - s, y - s), (x + s, y - s), (x, y)]
    else:
        t1 = [(x - s, y - s), (x - s, y + s), (x, y)]
        t2 = [(x + s, y - s), (x + s, y + s), (x, y)]
    fill2 = kind == "check"
    ax.add_patch(Polygon(t1, closed=True, facecolor="white", edgecolor=COL["k"], lw=LW_S, zorder=5))
    ax.add_patch(Polygon(t2, closed=True, facecolor=COL["k"] if fill2 else "white", edgecolor=COL["k"], lw=LW_S, zorder=5))
    if kind == "ball":
        ax.add_patch(Circle((x, y), 1.3, facecolor="white", edgecolor=COL["k"], lw=LW_T, zorder=6))
    if act:
        dx, dy = (6, 0) if orient == "v" else (0, 6)
        if side == "left":
            dx = -dx
        ax.plot([x, x + dx], [y, y + dy], color=COL["k"], lw=LW_T, zorder=5)
        ax.add_patch(Circle((x + dx * 1.45, y + dy * 1.45), 2.6, facecolor="white", edgecolor=COL["k"], lw=LW_S, zorder=5))
        text(x + dx * 1.45, y + dy * 1.45, "M", H25 * 0.75, zorder=6)
    if tag:
        if orient == "v":
            text(x + (-12 if side == "left" else 0) - 5, y, tag, H25 * 0.85, ha="right" if side != "left" else "right", weight="bold")
        else:
            text(x, y - 6.5, tag, H25 * 0.85, weight="bold")


def orifice(x, y, orient="v", tag=""):
    if orient == "v":
        ax.plot([x - 3, x + 3], [y + 0.8, y + 0.8], color=COL["k"], lw=LW_P)
        ax.plot([x - 3, x + 3], [y - 0.8, y - 0.8], color=COL["k"], lw=LW_P)
    else:
        ax.plot([x + 0.8, x + 0.8], [y - 3, y + 3], color=COL["k"], lw=LW_P)
        ax.plot([x - 0.8, x - 0.8], [y - 3, y + 3], color=COL["k"], lw=LW_P)
    text(x + 5, y, tag, H25 * 0.85, ha="left", weight="bold")


def instrument(x, y, tag, px=None, py=None):
    """ISA-5.1 field-mounted instrument bubble with a dashed signal/impulse line."""
    if px is not None:
        ax.plot([px, x], [py, y], color=COL["k"], lw=LW_T, ls=(0, (2, 1.2)), zorder=3)
    ax.add_patch(Circle((x, y), 4.6, facecolor="white", edgecolor=COL["k"], lw=LW_S, zorder=6))
    a, b = tag.split("-")
    text(x, y + 1.3, a, H25 * 0.75, zorder=7)
    text(x, y - 1.6, b, H25 * 0.75, zorder=7)


def hx(x, y, w=12, h=8, tag=""):
    ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, facecolor="white", edgecolor=COL["k"], lw=LW_P, zorder=4))
    zz = [(x - w / 2 + 1, y), (x - w / 4, y + h / 3), (x, y - h / 3), (x + w / 4, y + h / 3), (x + w / 2 - 1, y)]
    ax.plot(*zip(*zz), color=COL["k"], lw=LW_S, zorder=5)
    text(x, y + h / 2 + 3, tag, H25 * 0.85, weight="bold")


def shaft(x0, y0, x1, y1):
    ax.plot([x0, x1], [y0, y1], color=COL["k"], lw=LW_S, ls=(0, (8, 2, 1.5, 2)), zorder=3)


def dot(x, y, c="k"):
    ax.add_patch(Circle((x, y), 0.9, color=COL[c], zorder=6))


# ======================================================================== sheet frame (ISO 5457)
ax.add_patch(Rectangle((0, 0), 594, 420, fill=False, lw=LW_T, color=COL["k"]))
ax.add_patch(Rectangle((20, 10), 564, 400, fill=False, lw=0.7 * PT, color=COL["k"]))
for i in range(1, 12):                                   # grid reference marks
    xg = 20 + i * 564 / 12
    ax.plot([xg, xg], [410, 415], color=COL["k"], lw=LW_T)
    ax.plot([xg, xg], [5, 10], color=COL["k"], lw=LW_T)
for i in range(12):
    text(20 + (i + 0.5) * 564 / 12, 413.5, str(i + 1), H25 * 0.8)
for j in range(8):
    text(14, 10 + (j + 0.5) * 400 / 8, "ABCDEFGH"[7 - j], H25 * 0.8)
for x0 in (290, 590):
    pass

# ======================================================================== engine boundary
ax.add_patch(Polygon([(32, 42), (400, 42), (400, 72), (430, 72), (430, 385), (32, 385)], closed=True, fill=False, lw=LW_S, ls=(0, (6, 3)), color=COL["k"]))
text(36, 380, "ENGINE / VEHICLE INTERFACE LIMIT", H25, ha="left", style="italic")
text(231, 401, "MFE-280  METHALOX FULL-FLOW STAGED-COMBUSTION ENGINE  -  DESIGN POINT 100 % THRUST, SEA LEVEL", H5, weight="bold")

# ======================================================================== main thrust chamber TC-101 + regen HX-101
cx = 240
ax.add_patch(Rectangle((cx - 30, 232), 60, 16, facecolor="white", edgecolor=COL["k"], lw=LW_P, zorder=4))
text(cx, 243.5, "MAIN INJECTOR", H25 * 0.85, zorder=5)
text(cx, 237.5, f"{D['injector']['n_elements']} gas-gas coax elements", H25 * 0.75, zorder=5)
body = [(cx - 22, 232), (cx + 22, 232), (cx + 22, 205), (cx + 9, 178), (cx + 32, 75), (cx - 32, 75), (cx - 9, 178), (cx - 22, 205)]
ax.add_patch(Polygon(body, closed=True, facecolor="white", edgecolor=COL["k"], lw=LW_P, zorder=3))
text(cx, 216, "TC-101", H35, weight="bold", zorder=5)
text(cx, 209, f"pc {D['performance']['pc'] / 1e5:.0f} bar", H25 * 0.85, zorder=5)
text(cx, 120, f"eps {D['config']['nozzle']['expansion_ratio']:.0f}", H25 * 0.85, zorder=5)
text(cx, 113, f"F_SL {D['performance']['thrust_sl_N'] / 1e6:.2f} MN", H25 * 0.85, zorder=5)
# regen jacket drawn as heat-exchange band on both sides (circuit A chamber, circuit B nozzle)
for sgn in (-1, 1):
    ax.plot([cx + sgn * 25, cx + sgn * 25, cx + sgn * 12, cx + sgn * 17], [228, 205, 178, 150], color=COL["ch4"], lw=LW_S, ls=(0, (3, 1.5)))
    ax.plot([cx + sgn * 21, cx + sgn * 36], [140, 79], color=COL["ch4"], lw=LW_S, ls=(0, (3, 1.5)))
text(cx + 45, 182, "HX-101A\nregen circuit A\n(GRCop-42 chamber)", H25 * 0.8, ha="left")
text(cx + 45, 100, "HX-101B\nregen circuit B\n(In718 nozzle)", H25 * 0.8, ha="left")
ax.plot([cx - 26, cx + 26], [142, 142], color=COL["k"], lw=LW_S)               # bolted joint, eps 12
text(cx - 40, 142, "joint eps 12", H25 * 0.75, ha="right")
# manifolds: inlet (joint), outlet (top), exit (bottom)
for yy, tg in [(142, "inlet manifold"), (226, "outlet manifold"), (77, "exit manifold")]:
    dot(cx + 22 if yy == 226 else (cx + 21 if yy == 142 else cx + 32), yy, "ch4")

# ======================================================================== LOX side (left)
xo = 100
line([(xo, 395), (xo, 349)], "lox", arrows=(0,), label=f"L-201 LOX inlet {dn('lox_inlet')}", loff=(3, 8))
ax.add_patch(Rectangle((xo - 4, 386), 8, 5, facecolor="white", edgecolor=COL["k"], lw=LW_S, ls=(0, (2, 1))))
text(xo + 6, 392, "PV-101 prevalve (vehicle)", H25 * 0.75, ha="left")
pump(xo, 340, tag="P-201", note="LOX main pump")
instrument(78, 368, "PT-201", xo, 368)
instrument(122, 372, "TT-201", xo, 372)
# discharge -> MOV -> OPB
line([(xo + 8, 340), (135, 340), (135, 150), (xo, 150), (xo, 157)], "lox", arrows=(0, 1), label=f"L-202 {dn('lox_discharge')}",
     lpos=1, loff=(2, 40))
valve(135, 315, "v", "V-201 MOV", side="right")
instrument(150, 330, "ZT-201", 141, 315)
instrument(146, 358, "PT-202", 129, 340)
# kick stage on the shaft
pump(118, 300, r=5, tag="P-202", direction="left")
shaft(xo, 300, 113, 300)
line([(124, 340), (124, 312), (118, 312), (118, 305)], "lox", lw=LW_S)
dot(124, 340, "lox")
line([(118, 295), (118, 52), (396, 52), (396, 150), (380, 150), (380, 157)], "lox", lw=LW_S, arrows=(1, 2),
     label=f"L-203 ox cross-feed {dn('ox_crossfeed')}", lpos=1, loff=(-100, -3.5))
valve(118, 90, "v", "V-202 FPOV", side="left")
text(121, 268, f"+{CY['p_kick_rise_Pa'] / 1e5:.0f} bar", H25 * 0.75, ha="left", rotation=0)
# OPB and turbine
vessel(xo, 175, 22, 36, "B-201", "OPB")
text(xo - 13, 192, f"{CY['p_opb_Pa'] / 1e5:.0f} bar\n{D['config']['cycle']['T_opb_K']:.0f} K", H25 * 0.8, ha="right")
instrument(72, 190, "PT-203", xo - 11, 188)
line([(xo, 193), (xo, 239)], "ox_gas", arrows=(0,))
turbine(xo, 245, tag="T-201")
instrument(72, 228, "TT-203", xo, 228)
shaft(xo, 251, xo, 332)
instrument(70, 290, "ST-204", xo, 290)
instrument(70, 312, "VT-205", xo, 312)
# igniter
ax.add_patch(Circle((xo - 18, 163), 4, facecolor="white", edgecolor=COL["k"], lw=LW_S, zorder=5))
text(xo - 18, 163, "IG", H25 * 0.75, zorder=6)
text(xo - 18, 156, "IG-201 torch", H25 * 0.75)
ax.plot([xo - 14, xo - 11], [163, 163], color=COL["k"], lw=LW_S)
# ox-rich hot gas to the injector, through the GOX pressurant HX
line([(xo + 9, 248), (cx - 30, 248)], "ox_gas", arrows=(0,), label=f"L-205 ox-rich gas {dn('ox_hot_gas')}", loff=(-38, -4.5))
hx(165, 248, tag="HX-201")
line([(135, 290), (158, 290), (158, 252)], "lox", lw=LW_S)
dot(135, 290, "lox")
valve(158, 272, "v", "V-204", act=True, side="right")
line([(172, 252), (172, 389)], "gox", lw=LW_S, arrows=(0,))
text(174, 376, "L-206 GOX to LOX tank pressurisation", H25 * 0.85, ha="left", color=COL["gox"])

# ======================================================================== CH4 side (right)
xf = 380
line([(xf, 395), (xf, 349)], "ch4", arrows=(0,), label=f"L-301 CH4 inlet {dn('ch4_inlet')}", loff=(3, 8))
ax.add_patch(Rectangle((xf - 4, 386), 8, 5, facecolor="white", edgecolor=COL["k"], lw=LW_S, ls=(0, (2, 1))))
text(xf + 6, 392, "PV-301 prevalve (vehicle)", H25 * 0.75, ha="left")
pump(xf, 340, tag="P-301", direction="left", note="CH4 pump, 2 stages")
instrument(402, 368, "PT-301", xf, 368)
instrument(358, 372, "TT-301", xf, 372)
line([(xf - 8, 340), (345, 340), (345, 142), (cx + 21, 142)], "ch4", arrows=(0, 1, 2), label=f"L-302 {dn('ch4_discharge')}", lpos=1, loff=(2, 50))
valve(345, 318, "v", "V-301 MFV", side="right")
instrument(366, 318, "ZT-301", 351, 318)
instrument(368, 358, "PT-302", 366, 340)
# fuel cross-feed tap -> OPFV -> OPB
dot(356, 340, "ch4")
line([(356, 340), (356, 56), (85, 56), (85, 145), (xo - 6, 145), (xo - 6, 157)], "ch4", lw=LW_S, arrows=(1, 2),
     label=f"L-303 fuel cross-feed {dn('fuel_crossfeed')}", lpos=1, loff=(-160, 3))
valve(356, 90, "v", "V-302 OPFV", side="right")
# jacket circuit A outlet -> FPB ; circuit B return -> orifice -> FPB
line([(cx + 22, 226), (330, 226), (330, 145), (xf - 4, 145), (xf - 4, 157)], "ch4", arrows=(0, 1),
     label=f"L-304 jacket A out {dn('fpb_feed')}", lpos=0, loff=(-12, -4.5))
instrument(318, 238, "PT-304", 318, 226)
instrument(304, 238, "TT-304", 304, 226)
line([(cx + 32, 77), (318, 77), (318, 145)], "ch4", lw=LW_S, arrows=(0, 1), label=f"L-305 jacket B return {dn('nozzle_return')}", loff=(-6, -4.5))
dot(318, 145, "ch4")
orifice(318, 110, "v", "RO-301")
# GCH4 tap for tank pressurisation
dot(330, 200, "ch4")
line([(330, 200), (310, 200), (310, 389)], "ch4", lw=LW_S, ls=(0, (5, 1.5)), arrows=(1,))
text(308, 376, "L-307 GCH4 to CH4 tank pressurisation", H25 * 0.85, ha="right", color=COL["ch4"])
valve(310, 262, "v", "V-304", side="left")
# FPB and turbine
vessel(xf, 175, 22, 36, "B-301", "FPB")
text(xf + 13, 192, f"{CY['p_fpb_Pa'] / 1e5:.0f} bar\n{D['config']['cycle']['T_fpb_K']:.0f} K", H25 * 0.8, ha="left")
instrument(408, 190, "PT-303", xf + 11, 188)
line([(xf, 193), (xf, 239)], "fu_gas", arrows=(0,))
turbine(xf, 245, tag="T-301")
instrument(408, 228, "TT-303", xf, 228)
shaft(xf, 251, xf, 332)
instrument(410, 290, "ST-305", xf, 290)
instrument(410, 312, "VT-306", xf, 312)
ax.add_patch(Circle((xf + 18, 163), 4, facecolor="white", edgecolor=COL["k"], lw=LW_S, zorder=5))
text(xf + 18, 163, "IG", H25 * 0.75, zorder=6)
text(xf + 18, 156, "IG-301 torch", H25 * 0.75)
ax.plot([xf + 11, xf + 14], [163, 163], color=COL["k"], lw=LW_S)
line([(xf - 9, 244), (cx + 30, 244)], "fu_gas", arrows=(0,), label=f"L-306 fuel-rich gas {dn('fuel_hot_gas')}", loff=(-30, 3))
instrument(cx - 38, 215, "PT-101", cx - 22, 215)

# ======================================================================== GHe purge
line([(32, 125), (52, 125), (52, 260), (cx - 30, 260), (cx - 30, 248)], "he", lw=LW_S, ls=(0, (4, 1.5)), arrows=(0, 2))
text(34, 110, "GHe purge (vehicle)", H25 * 0.8, ha="left", color=COL["he"])
valve(44, 125, "h", "SV-401", act=True)
valve(52, 200, "v", "CV-402", kind="check", act=False, side="left")
line([(52, 175), (xo - 11, 175)], "he", lw=LW_S, ls=(0, (4, 1.5)))
dot(52, 175, "he")
line([(cx - 30, 260), (420, 260), (420, 175), (xf + 11, 175)], "he", lw=LW_S, ls=(0, (4, 1.5)))
valve(420, 210, "v", "CV-403", kind="check", act=False, side="right")

# ======================================================================== legend and equipment list
lx, ly = 440, 395
text(lx, ly, "LEGEND (ISO 10628-2 symbols, ISA-5.1 tags)", H35, ha="left", weight="bold")
items = [("lox", "-", "LOX liquid"), ("ch4", "-", "CH4 liquid / supercritical"), ("ox_gas", "-", "ox-rich turbine gas"),
         ("fu_gas", "-", "fuel-rich turbine gas"), ("gox", "-", "GOX pressurant"), ("he", (0, (4, 1.5)), "GHe purge")]
for i, (c, ls, lab) in enumerate(items):
    yy = ly - 8 - 5.5 * i
    ax.plot([lx, lx + 14], [yy, yy], color=COL[c], lw=LW_P, ls=ls)
    text(lx + 17, yy, lab, H25, ha="left")
yy = ly - 46
pump(lx + 6, yy, r=4)
text(lx + 17, yy, "centrifugal pump", H25, ha="left")
turbine(lx + 6, yy - 10, w=10, h=7)
text(lx + 17, yy - 10, "turbine (axial)", H25, ha="left")
valve(lx + 6, yy - 24, "v", act=True)
text(lx + 17, yy - 24, "ball valve, EM actuator (M)", H25, ha="left")
valve(lx + 6, yy - 34, "v", kind="check", act=False)
text(lx + 17, yy - 34, "check valve", H25, ha="left")
orifice(lx + 6, yy - 42, "v")
text(lx + 17, yy - 42, "restriction orifice", H25, ha="left")
instrument(lx + 6, yy - 51, "PT-000")
text(lx + 17, yy - 51, "field instrument (ISA-5.1)", H25, ha="left")
shaft(lx, yy - 59, lx + 14, yy - 59)
text(lx + 17, yy - 59, "shaft / mechanical link", H25, ha="left")
ax.plot([lx, lx + 14], [yy - 65, yy - 65], color=COL["k"], lw=LW_T, ls=(0, (2, 1.2)))
text(lx + 17, yy - 65, "instrument connection", H25, ha="left")

ey = yy - 76
text(lx, ey, "EQUIPMENT LIST", H35, ha="left", weight="bold")
op, fp, ot, ft = CY["ox_pump"], CY["fuel_pump"], CY["ox_turbine"], CY["fuel_turbine"]
eq = [
    ("P-201", f"LOX pump, 1 stage + inducer, {op['mdot']:.0f} kg/s, {op['p_out'] / 1e5:.0f} bar, {op['N_rpm'] / 1e3:.1f} krpm, {op['power_W'] / 1e6:.1f} MW"),
    ("P-202", f"LOX kick stage, {CY['mdot_ox_to_fpb']:.0f} kg/s, +{CY['p_kick_rise_Pa'] / 1e5:.0f} bar"),
    ("T-201", f"ox turbine, 1 stage reaction, PR {ot['PR']:.2f}, eta {ot['eta']:.2f}"),
    ("B-201", f"ox-rich preburner, {CY['mdot_opb']:.0f} kg/s, O/F {CY['mr_opb']:.0f}"),
    ("P-301", f"CH4 pump, 2 stages + inducer, {fp['mdot']:.0f} kg/s, {fp['p_out'] / 1e5:.0f} bar, {fp['N_rpm'] / 1e3:.1f} krpm, {fp['power_W'] / 1e6:.1f} MW"),
    ("T-301", f"fuel turbine, 1 stage reaction, PR {ft['PR']:.2f}, eta {ft['eta']:.2f}"),
    ("B-301", f"fuel-rich preburner, {CY['mdot_fpb']:.0f} kg/s, O/F {CY['mr_fpb']:.2f}"),
    ("TC-101", f"main chamber, Dt {2 * D['geometry']['Rt_m'] * 1e3:.0f} mm, De {2 * D['geometry']['Re_m'] * 1e3:.0f} mm"),
    ("HX-101", f"regen jacket A+B, {D['cooling']['Q_total_W'] / 1e6:.1f} MW, dP {D['cooling']['dp_jacket_Pa'] / 1e5:.0f} bar"),
    ("HX-201", "GOX pressurant HX in ox-rich gas duct"),
    ("RO-301", "circuit B orifice (balances A/B outlet pressure)"),
    ("IG-x01", "spark-torch igniters (GOX/GCH4 taps)"),
]
for i, (t, d_) in enumerate(eq):
    text(lx, ey - 6 - 4.6 * i, t, H25 * 0.85, ha="left", weight="bold")
    text(lx + 13, ey - 6 - 4.6 * i, d_, H25 * 0.72, ha="left")

ny = ey - 6 - 4.6 * len(eq) - 6
text(lx, ny, "NOTES", H35, ha="left", weight="bold")
notes = ["1. Line sizes DN = inside diameter in mm from results/design.json.",
         "2. FFSC: no inter-propellant seal or purge on the turbopumps.",
         "3. Main chamber has no igniter; hot ox-rich and fuel-rich gases",
         "   ignite on contact at the injector.",
         "4. Valves fail-closed; actuators electromechanical (M).",
         "5. Vehicle-side items (PV-101/301, GHe supply) shown dashed."]
for i, n in enumerate(notes):
    text(lx, ny - 5 - 3.8 * i, n, H25 * 0.75, ha="left")

# ======================================================================== title block (ISO 7200)
X0, Y0, W, Hb = 404, 10, 180, 56
ax.add_patch(Rectangle((X0, Y0), W, Hb, facecolor="white", edgecolor=COL["k"], lw=0.7 * PT, zorder=7))
for y_ in (24, 38, 52):
    ax.plot([X0, X0 + W], [y_, y_], color=COL["k"], lw=LW_T, zorder=8)
for x_, y0_, y1_ in [(474, 10, 24), (504, 10, 24), (544, 10, 24), (464, 24, 38), (524, 24, 38), (514, 38, 52), (554, 38, 52)]:
    ax.plot([x_, x_], [y0_, y1_], color=COL["k"], lw=LW_T, zorder=8)
cells = [
    (406, 66, "Legal owner", "Sid Sharma (personal project)"),
    (406, 52, "Title", "MFE-280 engine P&ID"),
    (516, 52, "Document type", "P&ID"),
    (556, 52, "Status", "Preliminary"),
    (406, 38, "Created by", "S. Sharma"),
    (466, 38, "Approved by", "-"),
    (526, 38, "Date of issue", "2026-10-31"),
    (406, 24, "Identification number", "MFE280-PID-001"),
    (476, 24, "Rev.", "A"),
    (506, 24, "Scale", "NTS"),
    (546, 24, "Sheet", "1/1"),
]
for x0, y0, lab, val in cells:
    text(x0, y0 - 1.5, lab, H25 * 0.7, ha="left", va="top", zorder=9, color="#444444")
    text(x0, y0 - 7.5, val, H35 * 0.85, ha="left", va="top", zorder=9,
         weight="bold" if lab in ("Title", "Identification number") else "normal")
text(X0, Y0 + Hb + 2.5, "Symbols ISO 10628-2  |  tags ANSI/ISA-5.1  |  sheet ISO 5457 A2  |  title block ISO 7200", H25 * 0.7,
     ha="left", color="#444444")

for ext in ("pdf", "svg", "png"):
    fig.savefig(OUT / f"MFE280-PID-001.{ext}", dpi=200 if ext == "png" else None)
print("P&ID written to", OUT)
