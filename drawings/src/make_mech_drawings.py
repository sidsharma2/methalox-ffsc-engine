"""MFE-280 mechanical drawing set (A3, ISO, third-angle), sheets 1-6.

    .venv\\Scripts\\python.exe drawings\\src\\make_mech_drawings.py [ga tca inj tpo tpf jnt]

Needs drawings/build/*.json from extract_views.py (FreeCAD). Writes DXF, DWG, PDF and a PNG
preview per sheet through render.publish and merges the PDFs into drawings/MFE280-DWG-SET.pdf.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import channel_detail  # noqa: E402
import mech_lib as ml  # noqa: E402
from mech_lib import fmt, mm  # noqa: E402
from render import OUT, merge, publish  # noqa: E402
from sheet import Sheet, TitleInfo  # noqa: E402

D, G, INJ, CY = ml.DESIGN, ml.DESIGN["geometry"], ml.DESIGN["injector"], ml.DESIGN["cycle"]
PERF = ml.DESIGN["performance"]
J, JI = ml.JOINTS, ml.IJOINTS
DATE = "2026-10-31"
NSHEETS = 6
STATUS_NOTE = "ITERATION 1: LAYOUT-LEVEL CAD (FREECAD MFE280.FCSTD), NOT FOR MANUFACTURE."
LOM_COLS = [("ITEM", 9), ("QTY", 9), ("PART NO.", 57), ("DESCRIPTION", 67), ("MATERIAL", 26), ("SHEET", 12)]


def title(sheet_no, dwg, lines, doc_type="ASSEMBLY DRAWING", scale="AS NOTED"):
    return TitleInfo(dwg_no=dwg, title=lines, doc_type=doc_type, date=DATE, sheet=f"{sheet_no}/{NSHEETS}", scale=scale)


def lom_rows(items):
    return [[str(i + 1)] + it for i, it in enumerate(items)]


# ============================================================================ sheet 2: thrust chamber
def sheet_tca():
    s = Sheet("A3")
    s.frame(title(2, "MFE280-TCA-002", ["MFE-280 ENGINE", "THRUST CHAMBER ASSY", "SECTION A-A"]))
    d = ml.load_view("tca")
    den = 10.0
    v = ml.View(s, d, den, at=(80.0, 185.0))
    P = v.P
    xt, xj, xe = mm(G["x_throat_m"]), mm(G["x_joint_m"]), mm(G["x_exit_m"])
    Rt, Rc, Re = mm(G["Rt_m"]), mm(G["Rc_m"]), mm(G["Re_m"])
    jic, jn, jj = J["injector_chamber"], J["nozzle_joint"], J["coolant_jumper"]
    t_ic, t_n, t_j = mm(jic["flange_t_m"]), mm(jn["flange_t_m"]), mm(jj["flange_t_m"])
    od_ic, od_n, bcd = mm(jic["flange_od_m"]), mm(jn["flange_od_m"]), mm(jic["bcd_m"])
    b27, b12, b8 = (ml.through_bolt(mm(j["d_m"]), mm(j["flange_t_m"])) for j in (jic, jn, jj))

    # ---- section A-A: hatching first, then the exact HLR edges
    v.sections(base=1.6, solid_below=0.75)
    v.visible()
    s.centerline(P(-560, 0), P(xe + 40, 0), ext=0)
    s.view_title(24, 285, "SECTION A-A", "SCALE 1 : 10")

    # ---- dimensions: design.json values mapped through the view transform
    yt = 268.0
    s.dim_linear(P(0, od_ic / 2), P(xt, Rt + 30), base=(0, yt), angle=0, scale=den)
    s.dim_linear(P(0, od_ic / 2), P(xj, od_n / 2), base=(0, yt + 6.5), angle=0, scale=den)
    s.dim_linear(P(0, od_ic / 2), P(xe, Re), base=(0, yt + 13), angle=0, scale=den)
    ml.dim_lin(s, P(112, -Rc), P(112, Rc), base=P(112, 0), angle=90, scale=den, text="%%c<>", shift=-9)
    ml.dim_lin(s, P(xt, -Rt), P(xt, Rt), base=P(xt, 0), angle=90, scale=den, text="%%c<>", shift=6)
    ml.dim_lin(s, P(xe, -Re), P(xe, Re), base=P(xe + 90, 0), angle=90, scale=den, text="%%c<>", shift=-20)
    ml.dim_lin(s, P(xj - t_n, -od_n / 2), P(xj - t_n, od_n / 2), base=P(xj - 40, 0), angle=90, scale=den,
               text="%%c<>", shift=-12)

    # ---- balloons: targets on outlines; grouped fasteners share one leader (ISO 6433)
    fp27 = ml.bolt_set_points(t_ic, 2 * t_ic, mm(jic["d_m"]), bcd / 2)
    fp12 = ml.bolt_set_points(-xj + t_n, 2 * t_n, mm(jn["d_m"]), mm(jn["bcd_m"]) / 2)
    ml.balloon_stack(s, (86.0, 252.0), ["17", "18", "19"], P(fp27["head"]))
    s.balloon((124.0, 252.0), "3", ml.face_extreme(v, "Coolant_outlet_manifold", +1, (0.3, 1)))
    s.balloon((134.0, 252.0), "1", P(640, ml.wall_mid(640)))
    s.balloon((144.0, 252.0), "4", ml.face_extreme(v, "Coolant_distribution_manifold_chamber", +1, (-0.4, 1)))
    ml.balloon_stack(s, (151.0, 263.0), ["13", "14", "15"], P(fp12["head"]))
    s.balloon((196.0, 258.0), "5", ml.face_extreme(v, "Coolant_inlet_manifold_nozzle", +1, (0.2, 1)))
    s.balloon((222.0, 262.0), "2", P(1700, ml.wall_mid(1700)))
    s.balloon((258.0, 268.0), "6", ml.face_extreme(v, "Coolant_exit_manifold", +1, (-0.5, 1)))
    s.balloon((30.0, 240.0), "16", ml.face_extreme(v, "Ox_dome", +1, (-0.6, 1)))
    x0f, y0f, x1f, y1f = ml.faces_bbox(v, "Jumper_1_flanges")
    xjf, yjax = 0.5 * (x0f + x1f), 0.5 * (y0f + y1f)
    fp8 = ml.bolt_set_points(-xjf + t_j, 2 * t_j, mm(jj["d_m"]), yjax - mm(jj["bcd_m"]) / 2)
    s.balloon((200.0, 114.0), "7", ml.face_extreme(v, "Coolant_jumper_1", -1, (-0.2, -1)))
    s.balloon((210.0, 114.0), "8", ml.face_extreme(v, "Jumper_1_flanges", -1, (0.3, -1)))
    s.balloon((220.0, 114.0), "9", P(xjf, yjax + 14))
    ml.balloon_stack(s, (231.0, 114.0), ["10", "11", "12"], P(fp8["nut"]))

    # ---- detail B: injector / chamber bolted joint, 1:2
    cB, rB = (2.0, bcd / 2 - 4), 52.0
    s.detail_circle(P(cB), v.L(rB), "B")
    vb = ml.View(s, d, 2.0, at=(352.0, 240.0), ref=cB, clip=ml.circle_poly(cB, rB))
    vb.sections(base=2.0, solid_below=0.5)
    vb.visible()
    s.view_title(300, 285, "DETAIL B", "SCALE 1 : 2")
    s.dim_linear(vb.P(-t_ic, od_ic / 2), vb.P(0, od_ic / 2), base=vb.P(0, od_ic / 2 + 8), angle=0, scale=2.0)
    s.dim_linear(vb.P(0, od_ic / 2), vb.P(t_ic, od_ic / 2), base=vb.P(0, od_ic / 2 + 8), angle=0, scale=2.0)
    s.leader(vb.P(fp27["shank"][0] + 8, bcd / 2), (330.0, 206.0),
             [f"{jic['n_bolts']}X {b27['bolt']}, {b27['nut']}",
              f"2X {b27['washer']}, {ml.grade_label(jic['grade'])}, BCD %%c{fmt(bcd)}"], h=2.0)
    s.leader(vb.P(4, mm(jic["D_seal_m"]) / 2), (374.0, 219.0), [f"SEAL %%c{fmt(mm(jic['D_seal_m']))}", "C-SEAL, SHEET 6"], h=2.0)
    s.leader(vb.P(t_ic, od_ic / 2), (384.0, 258.0), [f"%%c{fmt(od_ic)}", "BOTH"], h=2.0)
    s.leader(vb.P(-t_ic * 0.6, bcd / 2 + 0.55 * mm(jic["d_m"])), (320.0, 262.0),
             [f"{jic['n_bolts']}X %%c{fmt(1.1 * mm(jic['d_m']))}"], h=2.0, align="right")

    # ---- detail C: channel section at the throat, 10:1 (analytic, cooling_profile.csv)
    i_t = min(range(len(ml.PROFILE)), key=lambda i: ml.PROFILE[i]["r"])
    row = ml.PROFILE[i_t]
    s.view_title(300, 199, "DETAIL C  THROAT CHANNELS",
                 f"SCALE 10 : 1   x = {fmt(mm(row['x']))}   N = {int(row['N'])}")
    g = channel_detail.draw(s, 303.0, 141.0, row, lo_pitch=-0.5, hi_pitch=1.5, keep=1.5, gap=5.0)
    Pc, X = g["P"], g["X"]
    ytop = Pc(g["r_o"], g["a_hi"])[1]
    yd = ytop + 4.0
    s.dim_linear(Pc(g["r"], g["a_hi"]), Pc(g["r_f"], g["a_hi"]), base=(0, yd), angle=0, scale=0.1)
    s.dim_linear(Pc(g["r_f"], g["a_hi"]), Pc(g["r_c"], g["a_hi"]), base=(0, yd), angle=0, scale=0.1, text=fmt(g["H"], 2))
    s.dim_linear(Pc(g["r_c"], g["a_hi"]), Pc(g["r_o"], g["a_hi"]), base=(0, yd), angle=0, scale=0.1, text=fmt(g["tc"], 2))
    wa = g["wall_angle"]
    xin = X(g["t"] + 0.9)
    s.dim_linear(Pc(g["r_f"], wa(0, -1, g["r_f"])), Pc(g["r_f"], wa(0, +1, g["r_f"])), base=(xin, 0), angle=90, scale=0.1,
                 text=fmt(g["W"], 2))
    s.dim_linear(Pc(g["r_f"], wa(0, +1, g["r_f"])), Pc(g["r_f"], wa(1, -1, g["r_f"])), base=(xin, 0), angle=90, scale=0.1,
                 text=fmt(mm(row["rib"]), 2))
    ybot = Pc(g["r"], g["a_lo"])[1]
    s.text(f"HOT WALL R{fmt(g['r'], 1)}", (303.0, ybot - 3.0), 2.0, "TOP_LEFT", width=0.9)
    s.text("LINER + RIBS GRCOP-42, CLOSEOUT IN718", (303.0, ybot - 6.5), 2.0, "TOP_LEFT", width=0.9)

    # ---- channel geometry table (5 stations)
    prof = ml.PROFILE
    st = [0, i_t, next(i for i, r in enumerate(prof) if r["N"] > 400 and r["zone"] == 0),
          next(i for i, r in enumerate(prof) if r["zone"] == 1), len(prof) - 1]
    names = ["INJECTOR FACE", "THROAT", "CU, N DOUBLED", "NOZZLE START", "NOZZLE EXIT"]
    rows = [[nm, fmt(mm(prof[i]["x"]), 1), fmt(mm(prof[i]["r"]), 1), str(int(prof[i]["N"])), fmt(mm(prof[i]["W"]), 2),
             fmt(mm(prof[i]["rib"]), 2), fmt(mm(prof[i]["H"]), 2), fmt(mm(prof[i]["t_hot"]), 2),
             fmt(mm(prof[i]["t_closeout"]), 2)] for nm, i in zip(names, st)]
    yb_t = s.table(299, 112.0, [("STATION", 24), ("x", 13), ("r", 12), ("N", 9), ("W", 9), ("RIB", 9), ("H", 11),
                                ("t HOT", 11), ("t CLOSE", 12)], rows, title="CHANNEL GEOMETRY (mm)", row_h=4.0, text_h=1.9)
    s.notes(299, yb_t - 1.5, ["x FROM THE INJECTOR FACE. LINER GRCOP-42 TO x 976.1, THEN IN718.",
                              "RIB WIDTH AT THE CHANNEL FLOOR. CHANNELS: PICOGK/README.MD."], h=1.9, gap=1.3, numbered=False)

    # ---- list of material
    gl = ml.grade_label
    items = [
        ["1", "CHAMBER_GRCOP42_REGEN", "REGEN CHAMBER: L-PBF LINER + RIBS, IN718 CLOSEOUT", "GRCOP-42", "2"],
        ["1", "NOZZLE_IN718_REGEN", "CHANNEL-WALL NOZZLE, EPS 12 - 34, JOINT FLANGE", "INCONEL 718", "2"],
        ["1", "COOLANT_OUTLET_MANIFOLD", "COLLECTS CIRCUIT A AT THE INJECTOR END", "INCONEL 718", "2"],
        ["1", "COOLANT_DISTRIBUTION_MANIFOLD_CHAMBER", "FEEDS CIRCUIT A UP THE CHAMBER", "INCONEL 718", "2"],
        ["1", "COOLANT_INLET_MANIFOLD_NOZZLE", "SPLIT-FLOW INLET AT THE JOINT (EPS 12)", "INCONEL 718", "2"],
        ["1", "COOLANT_EXIT_MANIFOLD", "COLLECTS CIRCUIT B AT THE NOZZLE EXIT", "INCONEL 718", "2"],
        ["4", "COOLANT_JUMPER_1 ... 4", "JUMPER ACROSS THE NOZZLE JOINT, %%c45 X 5", "INCONEL 718", "2"],
        ["8", "JUMPER_1 ... 4_FLANGES", f"JUMPER FLANGE %%c{fmt(mm(jj['flange_od_m']))} X {fmt(t_j)}", "INCONEL 718", "2"],
        ["4", "JUMPER_1 ... 4_SEAL", f"METALLIC C-SEAL %%c{fmt(mm(jj['D_seal_m']))}", "IN718 + PTFE", "6"],
        [str(4 * jj["n_bolts"]), b8["bolt"], "HEX BOLT, JUMPER FLANGES", gl(jj["grade"]), "6"],
        [str(4 * jj["n_bolts"]), b8["nut"], "HEX NUT", gl(jj["grade"]), "6"],
        [str(8 * jj["n_bolts"]), b8["washer"], "PLAIN WASHER", gl(jj["grade"]), "6"],
        [str(jn["n_bolts"]), b12["bolt"], f"HEX BOLT, NOZZLE JOINT, BCD %%c{fmt(mm(jn['bcd_m']))}", gl(jn["grade"]), "6"],
        [str(jn["n_bolts"]), b12["nut"], "HEX NUT", gl(jn["grade"]), "6"],
        [str(2 * jn["n_bolts"]), b12["washer"], "PLAIN WASHER", gl(jn["grade"]), "6"],
        ["1", "MFE280-INJ-003", "MAIN INJECTOR HEAD + OX DOME (SUB-ASSEMBLY)", "INCONEL 718", "3"],
        [str(jic["n_bolts"]), b27["bolt"], f"HEX BOLT, INJECTOR / CHAMBER, BCD %%c{fmt(bcd)}", gl(jic["grade"]), "6"],
        [str(jic["n_bolts"]), b27["nut"], "HEX NUT", gl(jic["grade"]), "6"],
        [str(2 * jic["n_bolts"]), b27["washer"], "PLAIN WASHER", gl(jic["grade"]), "6"],
    ]
    s.table(22, 100.0, LOM_COLS, lom_rows(items), title="LIST OF MATERIAL", row_h=4.2, text_h=2.0)

    # ---- notes and status
    notes = [
        "SECTION A-A: PLANE THROUGH THE ENGINE AND TURBOPUMP AXES (SHEET 1), SEEN FROM -Y.",
        "VISIBLE EDGES BEYOND THE CUT SHOWN (EXACT HLR); OX POSTS BEYOND THE CUT OMITTED.",
        "BOLTS AND JUMPER 7 (TRUE AT 45, 135, 247, 315 DEG) SHOWN ROTATED INTO THE PLANE.",
        "FASTENERS NOT HATCHED (ISO 128-44). L = GRIP + 2 WASHERS + NUT + 2 P, ROUNDED UP.",
        "WALLS SHOWN SOLID. CHANNELS: DETAIL C, COOLING_PROFILE.CSV, PICOGK (PICOGK/README.MD).",
        "DIMENSIONS FROM DESIGN.JSON. THE CAD WALL IS A B-SPLINE THROUGH EVERY POINT OF RESULTS/CONTOUR.CSV.",
    ]
    s.notes(24, 136.0, notes, h=2.0, gap=1.5)
    s.boxed_note(22, 107.5, 146, STATUS_NOTE, h=2.2)
    s.publish_name = "MFE280-TCA-002"
    return s


# ============================================================================ sheet 3: main injector
def sheet_inj():
    s = Sheet("A3")
    s.frame(title(3, "MFE280-INJ-003", ["MFE-280 ENGINE", "MAIN INJECTOR HEAD", "FACEPLATE + ELEMENT"]))
    jic = J["injector_chamber"]
    od, bcd, dh = mm(jic["flange_od_m"]), mm(jic["bcd_m"]), 1.1 * mm(jic["d_m"])
    d_b, d_p, d_a, pitch = (mm(INJ[k]) for k in ("d_ox_post_m", "d_post_outer_m", "d_annulus_outer_m", "pitch_m"))
    rings = INJ["rings"]
    centres = [(mm(r["r_m"]) * math.cos(2 * math.pi * k / r["count"]), mm(r["r_m"]) * math.sin(2 * math.pi * k / r["count"]))
               for r in rings for k in range(r["count"])]

    # ---- VIEW C: faceplate from the chamber side, 1:4 (HLR, viewer at -z; sheet up = -y)
    fv = ml.load_view("inj_face")
    R_fp = max(q[0] for f in ml.load_view("inj")["parts"]["Injector_faceplate"]["faces"] for q in f["outer"])
    vc = ml.View(s, fv, 4.0, at=(100.0, 194.0))

    def in_bore(pl):                     # edges seen through the post bores (dome interior): omitted
        xs, ys = [q[0] for q in pl], [q[1] for q in pl]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        return max(max(xs) - min(xs), max(ys) - min(ys)) < 0.9 * d_b and any(
            math.hypot(cx - x, cy + y) < d_b / 2 for x, y in centres)
    vc.visible(skip=in_bore)
    vc.polyline(ml.circle_poly((0, 0), R_fp, 180), "VISIBLE", closed=True)
    for r in rings[1:]:
        s.circle(vc.P(0, 0), vc.L(mm(r["r_m"])), "CENTER")
    s.circle(vc.P(0, 0), vc.L(bcd / 2), "CENTER")
    s.centerline(vc.P(-300, 0), vc.P(300, 0), ext=0)
    s.centerline(vc.P(0, -322), vc.P(0, 322), ext=0)
    s.cut_plane(vc.P(-301, 0), vc.P(292, 0), "B", (0.0, -1.0))
    s.view_title(24, 285, "VIEW C", "SCALE 1 : 4   FROM THE CHAMBER")
    for rr, ang, txt, tp in ((od / 2, 128.0, f"%%c{fmt(od)}", (36.0, 266.0)),
                             (R_fp, 147.0, f"%%c{fmt(2 * R_fp)}", (30.0, 252.0))):
        s.leader(vc.P(rr * math.cos(math.radians(ang)), rr * math.sin(math.radians(ang))), tp, [txt], h=2.0)
    r7 = mm(rings[-1]["r_m"])
    th = math.radians(180.0 / jic["n_bolts"] + 4 * 360.0 / jic["n_bolts"])      # a hole at the lower right (y up = -y)
    hc = (bcd / 2 * math.cos(th), -bcd / 2 * math.sin(th))
    s.leader(vc.P(hc[0] + dh / 2 * 0.7, hc[1] - dh / 2 * 0.7), (150.0, 120.0),
             [f"{jic['n_bolts']}X %%c{fmt(dh)} EQ SP", f"ON %%c{fmt(bcd)}"], h=2.0)
    k7 = round(rings[-1]["count"] * (1 - 50.0 / 360.0))
    a7 = 2 * math.pi * k7 / rings[-1]["count"]
    e7 = (r7 * math.cos(a7), -r7 * math.sin(a7))
    s.leader(vc.P(e7[0] + d_a / 2 * 0.7, e7[1] + d_a / 2 * 0.7), (145.0, 262.0),
             [f"{INJ['n_elements']} ELEMENTS, {len(rings)} RINGS", "SEE RING TABLE"], h=2.0)

    # ---- SECTION B-B through the injector head, 1:5
    d = ml.load_view("inj")
    v = ml.View(s, d, 5.0, at=(246.0, 165.0))
    P = v.P
    v.sections(base=1.5, solid_below=0.6)
    v.visible()
    s.centerline(P(0, -12), P(0, 525), ext=0)
    s.view_title(219, 285, "SECTION B-B", "SCALE 1 : 5")
    zmax = max(q[1] for f in d["parts"]["Ox_dome"]["faces"] for q in f["outer"])
    zbody = max(q[1] for f in d["parts"]["Injector_body_fuel_plenum"]["faces"] for q in f["outer"])
    s.dim_linear(P(-od / 2, 0), P(-110, zmax), base=P(-345, 0), angle=90, scale=5.0)
    s.dim_linear(P(-od / 2, 0), P(-R_fp - 31, zbody), base=P(-318, 0), angle=90, scale=5.0)
    s.arrowhead(P(-150, -2), P(-150, -30), 3.5, 1.2)
    s.line(P(-150, -2), P(-150, -30), "THIN")
    s.text("C", (P(-150, -30)[0] - 3.5, P(-150, -30)[1]), 5.0, "MIDDLE_CENTER")
    s.leader(P(-295, 150 + mm(D["ducts"]["fuel_hot_gas"]) / 2), (182.0, 246.0),
             ["FUEL-RICH GAS", f"%%c{fmt(mm(D['ducts']['fuel_hot_gas']))}"], h=2.0)
    s.leader(P(200, 395 + mm(D["ducts"]["ox_hot_gas"]) / 2), (282.0, 276.0), ["OX-RICH GAS", f"%%c{fmt(mm(D['ducts']['ox_hot_gas']))}"], h=2.0)
    s.balloon((214.0, 262.0), "5", ml.face_extreme(v, "Ox_dome", 0, (-1, 1)))
    s.balloon((214.0, 150.0), "1", P(-265, 0))
    s.balloon((240.0, 150.0), "2", P(-60, 0))
    s.balloon((256.0, 150.0), "3", P(-27 - d_p / 2, 6))
    s.balloon((272.0, 150.0), "4", P(120, 240))
    s.detail_circle(P(27.0 + 0.5, 9.0), v.L(16.0), "D")

    # ---- DETAIL D: one coaxial element, 5:1 (ring 1 element at x = pitch, in the plane)
    x_el = mm(rings[1]["r_m"])
    wx0, wx1 = x_el - 8.8, x_el + 11.6
    win = ml.rect_poly(wx0, -5.0, wx1, 23.0)
    vd = ml.View(s, d, 0.2, at=(357.0, 202.0), ref=(0.5 * (wx0 + wx1), 9.0), clip=win)
    Q = vd.P
    xt20 = Q(x_el + 10.2, 10.0)
    vd.sections(base=2.0, solid_below=0.3, masks=[(xt20[0] - 3.4, xt20[1] - 4.0, xt20[0] - 0.3, xt20[1] + 4.0)])
    vd.visible()
    s.view_title(307, 285, "DETAIL D", "SCALE 5 : 1   COAXIAL ELEMENT")
    s.centerline(Q(x_el, -5.0), Q(x_el, 23.0), ext=2.0)
    for x0, y0, x1, y1 in ((wx0, -5, wx1, -5), (wx0, 23, wx1, 23), (wx0, -5, wx0, 23), (wx1, -5, wx1, 23)):
        ml.break_line(s, Q(x0, y0), Q(x1, y1), amp=1.2)
    s.dim_linear(Q(x_el - d_b / 2, 16), Q(x_el + d_b / 2, 16), base=Q(0, 16), angle=0, scale=0.2, text="%%c<>")
    s.dim_linear(Q(x_el - d_p / 2, 6), Q(x_el + d_p / 2, 6), base=Q(0, -2.2), angle=0, scale=0.2, text="%%c<>")
    s.dim_linear(Q(x_el - d_a / 2, 0), Q(x_el + d_a / 2, 0), base=Q(0, -4.0), angle=0, scale=0.2, text="%%c<>")
    s.dim_linear(Q(x_el - d_b / 2, 6), Q(x_el - d_a / 2, 0), base=Q(x_el - 3.0, 0), angle=90, scale=0.2)
    ml.dim_lin(s, Q(x_el + d_a / 2, 0), Q(x_el + d_a / 2, 20), base=Q(x_el + 10.2, 0), angle=90, scale=0.2)
    s.notes(306.0, 129.0, [f"POST TIP RECESSED 6 FROM THE FACE. PITCH {fmt(pitch, 2)} TO THE",
                           "NEXT ELEMENT (RING TABLE). OX-RICH GAS IN THE POST,",
                           "FUEL-RICH GAS IN THE ANNULUS."], h=1.9, gap=1.2, numbered=False)

    # ---- tables
    ring_rows = [[str(i), fmt(mm(r["r_m"]), 2), str(r["count"]), fmt(360.0 / r["count"], 2) if r["count"] > 1 else "-",
                  fmt(2 * math.pi * mm(r["r_m"]) / r["count"], 1) if r["count"] > 1 else "-"] for i, r in enumerate(rings)]
    ring_rows.append(["TOTAL", "", str(INJ["n_elements"]), "", ""])
    yb = s.table(22, 69.0, [("RING", 12), ("RADIUS", 17), ("ELEMENTS", 19), ("ANGLE DEG", 20), ("ARC PITCH", 19)],
                 ring_rows, title="RING TABLE (mm)", row_h=4.0, text_h=1.9)
    cyc = D["cycle"]
    e1 = [["ELEMENTS, COAXIAL GAS-GAS", str(INJ["n_elements"]), "-"],
          ["PITCH", fmt(pitch, 2), "mm"],
          ["PITCH / ANNULUS OD", fmt(INJ["pitch_over_d_annulus"], 2), "-"],
          ["POST BORE / POST OD", f"{fmt(d_b, 2)} / {fmt(d_p, 2)}", "mm"],
          ["ANNULUS OD", fmt(d_a, 2), "mm"],
          ["OPEN AREA FRACTION", fmt(INJ["open_area_fraction"], 2), "-"],
          ["THRUST PER ELEMENT", fmt(INJ["thrust_per_element_kN"], 2), "kN"],
          ["OUTER RING (WALL LAYER)", f"{INJ['n_outer_ring']} AT O/F {fmt(D['config']['injector']['bl_mixture_ratio'])}", "-"]]
    e2 = [["PRESSURE DROP", fmt(INJ["dp_Pa"] / 1e5, 1), "bar"],
          ["DISCHARGE COEFFICIENT", fmt(INJ["cd"], 2), "-"],
          ["OX-RICH GAS VELOCITY", fmt(INJ["v_ox_m_s"], 1), "m/s"],
          ["FUEL-RICH GAS VELOCITY", fmt(INJ["v_fu_m_s"], 1), "m/s"],
          ["VELOCITY RATIO FU / OX", fmt(INJ["velocity_ratio_fu_ox"], 2), "-"],
          ["MOMENTUM FLUX RATIO", fmt(INJ["momentum_flux_ratio"], 2), "-"],
          ["MEAN OX-RICH FLOW / ELEMENT", fmt(cyc["mdot_opb"] / INJ["n_elements"], 2), "kg/s"],
          ["MEAN FUEL-RICH FLOW / ELEMENT", fmt(cyc["mdot_fpb"] / INJ["n_elements"], 2), "kg/s"]]
    cols = [("QUANTITY", 52), ("VALUE", 22), ("UNIT", 11)]
    s.table(232, 113.0, cols, e1, title="ELEMENT DATA", row_h=4.0, text_h=1.9)
    s.table(321, 113.0, cols, e2, title="", row_h=4.0, text_h=1.9)

    items = [["1", "INJECTOR_BODY_FUEL_PLENUM", "FUEL-RICH GAS PLENUM, CHAMBER FLANGE", "INCONEL 718", "3"],
             ["1", "INJECTOR_FACEPLATE", f"FACEPLATE, {INJ['n_elements']} HOLES %%c{fmt(d_a, 2)}", "INCONEL 718", "3"],
             [str(INJ["n_elements"]), "INJECTOR_OX_POSTS", f"OX POST %%c{fmt(d_b, 2)} / %%c{fmt(d_p, 2)}", "INCONEL 718", "3"],
             ["1", "INJECTOR_INTERPROPELLANT_PLATE", "SEPARATES FUEL PLENUM AND OX DOME", "INCONEL 718", "3"],
             ["1", "OX_DOME", "OX-RICH GAS DOME, GIMBAL PAD", "INCONEL 718", "3"],
             ["1", "TVC_LUG_PITCH", "TVC ACTUATOR LUG, +Y", "INCONEL 718", "3"],
             ["1", "TVC_LUG_YAW", "TVC ACTUATOR LUG, -Y", "INCONEL 718", "3"]]
    s.table(22, 110.0, [("ITEM", 9), ("QTY", 9), ("PART NO.", 50), ("DESCRIPTION", 64), ("MATERIAL", 22), ("SHEET", 11)],
            lom_rows(items), title="LIST OF MATERIAL", row_h=4.0, text_h=1.9)
    s.balloon((126.0, 116.0), "6", vc.P(9, -300))
    s.balloon((126.0, 272.0), "7", vc.P(9, 300))
    notes = ["VIEW C FROM -Z. ELEMENT k OF A RING AT 360 k / n DEG FROM +X (DESIGN.JSON).",
             "SECTION B-B: PLANE Y = 0, SEEN FROM -Y. EDGES BEYOND THE CUT BY HLR.",
             "FACEPLATE AND POSTS WELDED TO THE BODY (MODEL NOTE).",
             f"OUTER RING: WALL LAYER, BL MASS FRACTION {fmt(D['config']['injector']['bl_mass_fraction'], 2)}.",
             "FLANGE BOLTING: SHEET 2 DETAIL B AND SHEET 6."]
    s.notes(112, 69.0, notes, h=1.9, gap=1.4)
    s.boxed_note(112, 13.0, 116, "ITERATION 1 LAYOUT CAD, NOT FOR MANUFACTURE.", h=2.0)
    s.publish_name = "MFE280-INJ-003"
    return s


# ============================================================================ sheets 4 and 5: turbopumps
def sheet_tpa(side):
    ox = side == "ox"
    pre, view, letter = ("LOX_", "tpo", "E") if ox else ("CH4_", "tpf", "F")
    sheet_no, dwg = (4, "MFE280-TPO-004") if ox else (5, "MFE280-TPF-005")
    s = Sheet("A3")
    s.frame(title(sheet_no, dwg, ["LOX TURBOPUMP (TPO)" if ox else "CH4 TURBOPUMP (TPF)",
                                  "OX-RICH PREBURNER" if ox else "FUEL-RICH PREBURNER", f"SECTION {letter}-{letter}"]))
    d = ml.load_view(view)
    pm, tb, sh = CY[f"{side}_pump"], CY[f"{side}_turbine"], CY[f"{side}_shaft"]
    pb = D["opb" if ox else "fpb"]
    parts = d["parts"]

    def ext(n):
        pts = [q for f in parts[n]["faces"] for q in f["outer"]]
        return min(q[0] for q in pts), min(q[1] for q in pts), max(q[0] for q in pts), max(q[1] for q in pts)

    def proxy(n, sgn):
        for px in d["proxies"]:
            if px["name"] == pre + n:
                ys = [q[1] for q in px["loop"]]
                if (sum(ys) > 0) == (sgn > 0):
                    xs = [q[0] for q in px["loop"]]
                    return min(xs), min(ys), max(xs), max(ys)

    X0 = ext(pre + "inlet_housing")[0]
    X1 = ext(pre + "preburner_injector_head")[2]
    Ymax = max(max(abs(ext(n)[1]), abs(ext(n)[3])) for n in parts if parts[n]["faces"])
    den = 5.0
    y0 = 193.0 if ox else 200.0
    v = ml.View(s, d, den, at=(25.0 - X0 / den, y0))
    P = v.P

    # dimension positions first, so the hatch keeps their text clear
    pi_ = proxy("inducer_blades", 1)
    xi = pi_[0] + 0.78 * (pi_[2] - pi_[0])                    # clear of the balloon leader at the proxy centre
    hb = ext(pre + "impeller1_hub")
    xp = 0.5 * (hb[0] + hb[2])
    xr = proxy("turbine_stator_vanes", 1)[0] - 4.0
    D_ind, D2, Dm = mm(pm["inducer_D_m"]), mm(pm["D2_m"]), mm(tb["Dm_m"])
    dims_v = [(xi, D_ind, -11.0), (xp, D2, -14.0), (xr, Dm, 14.0)]
    masks = []
    for xx, dd, sh_ in dims_v:
        masks.append(ml.dim_text_mask(P(xx, 0)[0], y0 + sh_, "D" + fmt(dd)))

    v.sections(base=1.5, solid_below=0.6, masks=masks)
    v.bearings()
    v.visible()
    s.centerline(P(X0 - 20, 0), P(X1 + 20, 0), ext=0)
    s.view_title(24, 285, f"SECTION {letter}-{letter}", "SCALE 1 : 5")
    for (xx, dd, sh_) in dims_v:
        ml.dim_lin(s, P(xx, -dd / 2), P(xx, dd / 2), base=P(xx, 0), angle=90, scale=den, text="%%c<>", shift=sh_)
    yt, yb = y0 + Ymax / den + 4.75, y0 - Ymax / den - 4.75
    yl = yt + 6.0
    s.dim_linear(P(X0, ext(pre + "inlet_housing")[3]), P(X1, ext(pre + "preburner_injector_head")[3]),
                 base=(0, yl), angle=0, scale=den)

    # ---- balloons
    def top_pt(n, sgn=1, dirn=None):
        return ml.face_extreme(v, pre + n, sgn, dirn or (0, sgn))

    def prox_pt(n, sgn):
        b = proxy(n, sgn)
        return P(0.5 * (b[0] + b[2]), b[3] if sgn > 0 else b[1])

    fast = {}
    for f in d["fasteners"]:
        bb = f["bbox"]
        key = f["name"][len(pre) + len("bolts_"):]
        if (bb[1] + bb[3]) > 0:
            fast[key] = P(0.5 * (bb[0] + bb[2]), bb[3])
        else:
            fast[key + "_lo"] = P(0.5 * (bb[0] + bb[2]), bb[1])
    gl = ml.grade_label
    items, top, bot = [], [], []

    def add(row, side_, tgt):
        items.append(row)
        (top if side_ > 0 else bot).append((str(len(items)), tgt))

    m = lambda n: ml.mat_label(parts[pre + n]["material"])
    add(["1", pre + "INLET_HOUSING", "INDUCER HOUSING AND INLET DUCT", m("inlet_housing"), str(sheet_no)], 1, top_pt("inlet_housing"))
    add(["1", pre + "INDUCER_HUB", "INDUCER HUB", m("inducer_hub"), str(sheet_no)], -1, top_pt("inducer_hub", -1, (-1, -1)))
    add(["3", pre + "INDUCER_BLADES", f"HELICAL INDUCER BLADE, TIP %%c{fmt(D_ind)}", m("inducer_hub"), str(sheet_no)], -1,
        prox_pt("inducer_blades", -1))
    nst = pm["stages"]
    sfx = " (2 STAGES)" if nst > 1 else ""
    add([str(nst), pre + "IMPELLER1" + ("/2" if nst > 1 else "") + "_HUB", f"IMPELLER HUB DISC, D2 {fmt(D2)}{sfx}",
         m("impeller1_hub"), str(sheet_no)], 1, top_pt("impeller1_hub"))
    add([str(nst), pre + "IMPELLER1" + ("/2" if nst > 1 else "") + "_SHROUD", "IMPELLER SHROUD", m("impeller1_shroud"),
         str(sheet_no)], -1, top_pt("impeller1_shroud", -1))
    add([str(nst), pre + "IMPELLER1" + ("/2" if nst > 1 else "") + "_BLADES", "6 + 6 SPLITTER BLADES PER STAGE",
         m("impeller1_hub"), str(sheet_no)], 1, prox_pt("impeller1_blades", 1))
    vol_note = "PUMP CASING + VOLUTE" + (", WELDED COVER" if JI[f"{side}_pump_volute_cover"]["welded"] else "")
    add(["1", pre + "PUMP_VOLUTE_CASING", vol_note, m("pump_volute_casing"), str(sheet_no)], -1, top_pt("pump_volute_casing", -1))
    if ox:
        add(["1", pre + "KICK_STAGE_HOUSING", f"KICK STAGE, +{fmt(CY['p_kick_rise_Pa'] / 1e5)} bar TO THE FPB",
             m("kick_stage_housing"), str(sheet_no)], 1, top_pt("kick_stage_housing"))
    add(["1", pre + "BEARING_HOUSING", "BEARING HOUSING", m("bearing_housing"), str(sheet_no)], -1, top_pt("bearing_housing", -1))
    add(["2", pre + "BEARING_1, _2", "ANGULAR-CONTACT BEARING, PROPELLANT-COOLED", m("bearing_1"), str(sheet_no)], 1,
        top_pt("bearing_1"))
    add(["1", pre + "SHAFT", f"SHAFT %%c{fmt(math.ceil(mm(sh['D_m']) / 5) * 5)} (DESIGN %%c{fmt(mm(sh['D_m']))})",
         m("shaft"), str(sheet_no)], -1, top_pt("shaft", -1, (0.2, -1)))
    add(["1", pre + "EXHAUST_COLLECTOR", "TURBINE EXHAUST COLLECTOR", m("exhaust_collector"), str(sheet_no)], 1,
        top_pt("exhaust_collector", 1, (-1, 0.3)))
    add(["1", pre + "TURBINE_DISK", "TURBINE DISK (BLISK HUB)", m("turbine_disk"), str(sheet_no)], -1,
        top_pt("turbine_disk", -1, (-1, -0.2)))
    add([str(tb["n_rotor"]), pre + "TURBINE_ROTOR_BLADES", f"ROTOR BLADE, h {fmt(mm(tb['blade_h_m']))}",
         m("turbine_disk"), str(sheet_no)], 1, prox_pt("turbine_rotor_blades", 1))
    add([str(tb["n_stator"]), pre + "TURBINE_STATOR_VANES", "NOZZLE VANE", m("turbine_disk"), str(sheet_no)], -1,
        prox_pt("turbine_stator_vanes", -1))
    add(["1", pre + "STATOR_SHROUDS", "NOZZLE RING SHROUDS", m("stator_shrouds"), str(sheet_no)], 1, top_pt("stator_shrouds"))
    th_j = JI[f"{side}_turbine_housing"]
    add(["1", pre + "TURBINE_HOUSING", "TURBINE INLET HOUSING" + (", WELDED TO THE PB" if th_j["welded"] else ""),
         m("turbine_housing"), str(sheet_no)], -1, top_pt("turbine_housing", -1, (0.3, -1)))
    add(["1", pre + "PREBURNER_SHELL", f"{'OX' if ox else 'FUEL'}-RICH PREBURNER SHELL", m("preburner_shell"),
         str(sheet_no)], 1, top_pt("preburner_shell", 1, (-0.3, 1)))
    add(["1", pre + "PREBURNER_INJECTOR_HEAD", "PREBURNER INJECTOR HEAD + MAIN PORT", m("preburner_injector_head"),
         str(sheet_no)], -1, top_pt("preburner_injector_head", -1))
    add(["1", pre + "PREBURNER_CROSSFEED_PORT", "CROSS-FEED INLET BOSS", m("preburner_crossfeed_port"), str(sheet_no)], -1,
        top_pt("preburner_crossfeed_port", -1))
    if not ox:
        # the outboard return boss lies wholly in the removed half: ISO 128-2 type 05.1 outline
        # (part in front of the cutting plane), seen end-on as a circle
        bb = parts[pre + "preburner_return_port"]["bbox"]
        c_rp = P(0.5 * (bb[0] + bb[2]), 0.5 * (bb[1] + bb[3]))
        r_rp = 0.5 * (bb[2] - bb[0]) / den
        s.circle(c_rp, r_rp, layer="PHANTOM")
        add(["1", pre + "PREBURNER_RETURN_PORT", f"NOZZLE-CIRCUIT RETURN BOSS (IN FRONT OF {letter}-{letter})", m("preburner_return_port"),
             str(sheet_no)], -1, (c_rp[0] + 0.5 * r_rp, c_rp[1] - 0.866 * r_rp))
    add(["1", pre + "TORCH_IGNITER", "SPARK-TORCH IGNITER (GOX / GCH4)", m("torch_igniter"), str(sheet_no)], 1,
        top_pt("torch_igniter", 1, (0, 1)))
    joints = [(f"{side}_pump_inlet_housing", "INLET HOUSING"), (f"{side}_bearing_housing", "BEARING HOUSING"),
              (f"{side}_pump_volute_cover", "VOLUTE COVER"), (f"{side}_turbine_housing", "TURBINE HOUSING")]
    k = 0
    for jn, lab in joints:
        jj = JI[jn]
        if jj["welded"]:
            continue
        key = jn
        tgt = fast.get(key) if k % 2 == 0 else fast.get(key + "_lo")
        add([str(jj["n_bolts"]), f"ISO 4017 {jj['bolt']}", f"HEX SCREW, {lab}, INTO TAPPED CASING, L OPEN", gl(jj["grade"]), "6"],
            1 if k % 2 == 0 else -1, tgt)
        k += 1

    # balloon rows: keep clear of the tall exhaust collector and the volute
    xc0, _, xc1, _ = ext(pre + "exhaust_collector")
    xv0, yv0, xv1, yv1 = ext(pre + "pump_volute_casing")
    gaps = []

    def allowed(lo, hi):
        out, cur = [], lo
        for a, b in sorted(gaps):
            if a > cur:
                out.append((cur, a))
            cur = max(cur, b)
        if cur < hi:
            out.append((cur, hi))
        return out
    x_lo, x_hi = 30.0, P(X1, 0)[0] - 4
    ml.balloon_rows(s, top, bot, yt, yb, allowed(x_lo, x_hi), allowed(x_lo, x_hi), pitch=9.5)

    # ---- list of material (bottom left)
    lom_top = yb - 10.5
    cols = [("ITEM", 9), ("QTY", 9), ("PART NO.", 52), ("DESCRIPTION", 76), ("MATERIAL", 22), ("SHEET", 11)]
    rh = min(4.0, (lom_top - 13.0) / (len(items) + 1))
    s.table(22, lom_top, cols, lom_rows(items), title="LIST OF MATERIAL",
            row_h=rh, text_h=min(1.9, rh - 1.6))

    # ---- turbopump data (right column)
    xT = P(X1, 0)[0] + 5.0
    k_w = min(1.0, (406.0 - xT) / 85.0)                    # keep the data column inside the frame (x = 410)
    cw = [("QUANTITY", 47 * k_w), ("VALUE", 23 * k_w), ("UNIT", 15 * k_w)]
    pump = [["PROPELLANT", "LOX" if ox else "CH4", "-"], ["MASS FLOW", fmt(pm["mdot"], 1), "kg/s"],
            ["SPEED", fmt(pm["N_rpm"], 0), "rpm"], ["HEAD", fmt(pm["head_m"], 0), "m"],
            ["INLET / DISCHARGE p", f"{fmt(pm['p_in'] / 1e5, 1)} / {fmt(pm['p_out'] / 1e5, 1)}", "bar"],
            ["POWER", fmt(pm["power_W"] / 1e6, 1), "MW"], ["EFFICIENCY", fmt(pm["eta"], 3), "-"],
            ["STAGES", str(pm["stages"]) + (" + KICK" if ox else ""), "-"],
            ["NPSH AVAILABLE", fmt(pm["npsh_a_m"], 1), "m"], ["Nss (US UNITS)", fmt(pm["Nss_us"], 0), "-"],
            ["Ns (US UNITS)", fmt(pm["Ns_us"], 0), "-"], ["IMPELLER D2 / b2", f"{fmt(D2, 1)} / {fmt(mm(pm['b2_m']), 1)}", "mm"],
            ["INDUCER D", fmt(D_ind, 1), "mm"]]
    turb = [["MASS FLOW", fmt(tb["mdot"], 1), "kg/s"], ["INLET T", fmt(tb["T_in"], 0), "K"],
            ["INLET p", fmt(tb["p_in"] / 1e5, 1), "bar"], ["PRESSURE RATIO", fmt(tb["PR"], 3), "-"],
            ["EFFICIENCY", fmt(tb["eta"], 3), "-"], ["POWER", fmt(tb["power_W"] / 1e6, 1), "MW"],
            ["MEAN DIAMETER", fmt(Dm, 1), "mm"], ["BLADE HEIGHT", fmt(mm(tb["blade_h_m"]), 2), "mm"],
            ["VANES / BLADES", f"{tb['n_stator']} / {tb['n_rotor']}", "-"], ["U / C0", fmt(tb["velocity_ratio"], 2), "-"],
            ["SHAFT TORQUE", fmt(sh["torque_Nm"] / 1e3, 1), "kN m"]]
    pbr = [["TEMPERATURE", fmt(pb["T_K"], 0), "K"], ["PRESSURE", fmt(pb["p_Pa"] / 1e5, 1), "bar"],
           ["MIXTURE RATIO O/F", fmt(CY["mr_opb" if ox else "mr_fpb"], 3), "-"],
           ["RESIDENCE TIME", fmt(pb["tau_s"] * 1e3, 1), "ms"],
           ["D X L", f"{fmt(mm(pb['D_m']), 1)} X {fmt(mm(pb['L_m']), 1)}", "mm"]]
    y = 278.0
    y = s.table(xT, y, cw, pump, title="PUMP DATA", row_h=3.8, text_h=1.8) - 8.0
    y = s.table(xT, y, cw, turb, title="TURBINE DATA", row_h=3.8, text_h=1.8) - 8.0
    y = s.table(xT, y, cw, pbr, title=("OX" if ox else "FUEL") + "-RICH PREBURNER", row_h=3.8, text_h=1.8)
    s.text("VALUES FROM RESULTS/DESIGN.JSON (CYCLE).", (xT, y - 1.5), 1.8, "TOP_LEFT", width=0.9)

    # ---- notes
    notes = [f"SECTION {letter}-{letter}: PLANE THROUGH THE TURBOPUMP AXIS (LOCAL X = 0, CUT ON SHEET 1), SEEN FROM "
             f"LOCAL -X. FRAME: APP::PART {pre}TURBOPUMP, TURBINE ROTOR AT LOCAL Z = 0.",
             "VISIBLE EDGES BEYOND THE CUT SHOWN (EXACT HLR). BLADE ROWS, IMPELLER AND INDUCER BLADES SHOWN AS "
             "MERIDIONAL OUTLINES, NOT HATCHED.",
             "SHAFT, IGNITER AND SCREWS NOT HATCHED (ISO 128-44); SCREWS ROTATED INTO THE PLANE. BEARINGS: ISO 8826-1 "
             "GENERAL SIMPLIFIED REPRESENTATION.",
             "SCREW LENGTH OPEN: THE TAPPED-HOLE DEPTH IS NOT MODELLED. WELDED JOINTS: SHEET 6."]
    for jn, lab in joints:
        if JI[jn]["welded"]:
            why = JI[jn].get("reason", "").split(": ")[-1].upper()
            notes.append(f"{lab} JOINT WELDED, NO SCREWS" + (f" ({why})" if why else "") + ".")
    xn = 232.0
    ml.wrapped_notes(s, xn, min(yb - 6.5, y - 8.0), notes, chars=150, h=1.8, gap=1.2)
    s.boxed_note(xn, 78.0, 176.0, "ITERATION 1 LAYOUT CAD, NOT FOR MANUFACTURE.", h=2.0)
    s.publish_name = dwg
    return s


# ============================================================================ sheet 1: general arrangement
def sheet_ga():
    s = Sheet("A3")
    s.frame(title(1, "MFE280-GA-001", ["MFE-280 ENGINE", "GENERAL ARRANGEMENT", "FRONT, SIDE, TOP"], scale="1 : 25"))
    den = 25.0
    fr, sd, tp = ml.load_view("ga_front"), ml.load_view("ga_side"), ml.load_view("ga_top")

    def ext(d):
        xs = [q[0] for pl in d["visible"] for q in pl]
        ys = [q[1] for pl in d["visible"] for q in pl]
        return min(xs), min(ys), max(xs), max(ys)
    fx0, fz0, fx1, fz1 = ext(fr)
    sy0, _, sy1, _ = ext(sd)
    _, ty0, _, ty1 = ext(tp)
    xf, yf = 92.0, 30.0 - fz0 / den
    gap = 17.0
    vf = ml.View(s, fr, den, at=(xf, yf))
    vs = ml.View(s, sd, den, at=(xf + fx1 / den + gap - sy0 / den, yf))
    vt = ml.View(s, tp, den, at=(xf, yf + fz1 / den + gap - ty0 / den))
    for v in (vf, vs, vt):
        v.visible()
    X_lox, X_ch4 = ml.LAYOUT["X_lox_tpa_mm"], ml.LAYOUT["X_ch4_tpa_mm"]
    # centre lines: engine axis, turbopump axes
    s.centerline(vf.P(0, fz0 - 30), vf.P(0, fz1 + 30), ext=0)
    s.centerline(vs.P(0, fz0 - 30), vs.P(0, fz1 + 30), ext=0)
    for xa, (z0, z1) in ((X_lox, (-560, 1300)), (X_ch4, (-560, 900))):
        s.centerline(vf.P(xa, z0), vf.P(xa, z1), ext=0)
        s.centerline(vt.P(xa, -420), vt.P(xa, 790), ext=0)
    s.centerline(vt.P(0, -790), vt.P(0, 790), ext=0)
    s.centerline(vt.P(fx0 - 30, 0), vt.P(fx1 + 30, 0), ext=0)
    # cutting planes for the section sheets
    s.cut_plane(vt.P(fx0 - 20, 0), vt.P(fx1 + 20, 0), "A", (0.0, 1.0))
    s.cut_plane(vt.P(X_lox, -690), vt.P(X_lox, 690), "E", (1.0, 0.0))
    s.cut_plane(vt.P(X_ch4, -690), vt.P(X_ch4, 690), "F", (-1.0, 0.0))

    s.view_title(24, 285, "GENERAL ARRANGEMENT", "SCALE 1 : 25   THIRD-ANGLE PROJECTION   HIDDEN LINES OMITTED")
    s.text("FRONT VIEW (FROM -Y)", (vf.P(fx0, 0)[0], vf.P(0, fz1)[1] + 3.0), 2.5, "BOTTOM_LEFT")
    s.text("RIGHT SIDE VIEW (FROM +X)", (vs.P(sy0, 0)[0], vs.P(0, fz1)[1] + 3.0), 2.5, "BOTTOM_LEFT")
    s.text("TOP VIEW (FROM +Z)", (vt.P(fx0, 0)[0], vt.P(0, ty1)[1] + 13.0), 2.5, "BOTTOM_LEFT")

    # ---- overall dimensions (reference)
    z_flange = ml.LAYOUT["bbox_mm"][5]               # LOX inlet flange face (layout.json)
    z_bot = ml.LAYOUT["bbox_mm"][4]
    xe, Re = mm(G["x_exit_m"]), mm(G["Re_m"])
    piv = 0.5 * (fr["parts"]["Gimbal_pins"]["bbox"][1] + fr["parts"]["Gimbal_pins"]["bbox"][3])
    xl = vs.P(sy0, 0)[0] - 6.0
    s.dim_linear(vs.P(0, z_bot), vs.P(sy0 * 0 - 120, z_flange), base=(xl, 0), angle=90, scale=den, text="(<>)")
    s.dim_linear(vs.P(0, piv), vs.P(Re, -xe), base=(vs.P(sy1, 0)[0] + 7.0, 0), angle=90, scale=den, text="(<>)")
    s.dim_linear(vf.P(fx0, 0), vf.P(fx1, 0), base=(0, vf.P(0, fz0)[1] - 8.0), angle=0, scale=den, text="(<>)")
    s.dim_linear(vs.P(sy0, -1990), vs.P(sy1, -1990), base=(0, vs.P(0, fz0)[1] - 14.0), angle=0, scale=den, text="(<>)")
    s.dim_linear(vs.P(-Re, -xe), vs.P(Re, -xe), base=(0, vs.P(0, fz0)[1] - 6.0), angle=0, scale=den, text="(%%c<>)")
    yd = vt.P(0, ty1)[1] + 8.0
    s.dim_linear(vt.P(X_ch4, 790), vt.P(0, 790), base=(0, yd), angle=0, scale=den, text="(<>)")
    s.dim_linear(vt.P(0, 790), vt.P(X_lox, 790), base=(0, yd), angle=0, scale=den, text="(<>)")
    s.leader(vs.P(0, piv), (vs.P(sy1, 0)[0] - 1.0, vs.P(0, piv)[1] + 16.0), ["GIMBAL", "PIVOT"], h=2.0)

    # ---- balloons (sub-assemblies)
    P = vf.P
    s.balloon((30.0, P(0, 150)[1] + 6), "5", P(-895, 150))
    s.balloon((30.0, P(0, 418)[1] + 14), "7", P(-850, 418))
    s.balloon((30.0, P(0, -1000)[1]), "6", P(-956, -1000))
    s.balloon((vs.P(sy0, 0)[0] - 13.0, P(0, -1500)[1]), "1", P(ml.wall_mid(1500) + 15, -1500))
    yb = vf.P(0, fz1)[1] + 9.5
    s.balloon((P(0, 0)[0] + 7, yb), "3", P(0, 738))
    s.balloon((P(0, 0)[0] + 17, yb), "2", P(200, 440))
    s.balloon((P(X_lox, 0)[0] + 9, yb), "4", P(776, 1150))

    # ---- list of material (sub-assembly level) and key data
    asm = [("1", "MFE280-TCA", "THRUST CHAMBER: CHAMBER, NOZZLE, MANIFOLDS, JUMPERS", "Thrust_Chamber", "2"),
           ("1", "MFE280-INJ", "MAIN INJECTOR HEAD, OX DOME, CHAMBER-JOINT BOLTS", "Injector_Head", "3"),
           ("1", "MFE280-GIM", "GIMBAL: BLOCK, PINS, YOKE, PAD BOLTS", "Gimbal", "-"),
           ("1", "MFE280-TPO", "LOX TURBOPUMP + OX-RICH PREBURNER", "LOX_Turbopump", "4"),
           ("1", "MFE280-TPF", "CH4 TURBOPUMP + FUEL-RICH PREBURNER", "CH4_Turbopump", "5"),
           ("1", "MFE280-PLB", "DUCTS, MOV / MFV / FPOV / OPFV, DUCT JOINTS", "Plumbing", "6"),
           ("5", "MFE280-INS", "PRESSURE AND SPEED TRANSDUCERS (PID-001)", "Instrumentation", "-")]
    rows = [[str(i + 1), q, pn, de, fmt(ml.asm_mass(a), 1), sh] for i, (q, pn, de, a, sh) in enumerate(asm)]
    rows.append(["", "", "TOTAL (BOM.CSV)", "MODELLED MASS", fmt(sum(ml.asm_mass(a[3]) for a in asm), 1), ""])
    yb_lom = s.table(232, 278.0, [("ITEM", 9), ("QTY", 9), ("PART NO.", 26), ("DESCRIPTION", 92), ("MASS kg", 17),
                                  ("SHEET", 12)], rows, title="LIST OF MATERIAL", row_h=4.4, text_h=2.0)
    perf = D["performance"]
    key = [["SEA-LEVEL THRUST (DESIGN INPUT)", fmt(perf["thrust_sl_N"] / 1e3, 0), "kN"],
           ["VACUUM THRUST", fmt(perf["thrust_vac_N"] / 1e3, 0), "kN"],
           ["ISP SEA LEVEL / VACUUM", f"{fmt(perf['isp_sl'], 1)} / {fmt(perf['isp_vac'], 1)}", "s"],
           ["CHAMBER PRESSURE", fmt(perf["pc"] / 1e5, 0), "bar"],
           ["MIXTURE RATIO O/F", fmt(perf["mr"], 2), "-"],
           ["PROPELLANT FLOW (OX + FUEL)", f"{fmt(perf['mdot'], 1)} ({fmt(perf['mdot_ox'], 1)} + {fmt(perf['mdot_fuel'], 1)})", "kg/s"],
           ["EXPANSION RATIO", fmt(perf["eps"], 0), "-"],
           ["THROAT / EXIT DIAMETER", f"{fmt(2 * mm(G['Rt_m']), 1)} / {fmt(2 * Re, 1)}", "mm"],
           ["MODELLED MASS (BOM.CSV)", fmt(sum(ml.asm_mass(a[3]) for a in asm), 1), "kg"],
           ["CYCLE", "FULL-FLOW STAGED COMB.", "-"],
           ["PROPELLANTS", "LOX / LCH4", "-"]]
    yk = s.table(232, yb_lom - 9.0, [("QUANTITY", 74), ("VALUE", 68), ("UNIT", 23)], key, title="KEY DATA",
                 row_h=4.4, text_h=2.0)
    notes = ["THIRD-ANGLE PROJECTION, SCALE 1 : 25. VISIBLE OUTLINES ONLY (EXACT HLR OF THE FREECAD MODEL); "
             "NUTS, WASHERS, SEALS AND PARTS INSIDE CASINGS LEFT OUT OF THE HLR.",
             "GLOBAL FRAME: Z UP, INJECTOR FACE AT Z = 0, ENGINE AXIS ALONG -Z, LOX TURBOPUMP AT +X, CH4 TURBOPUMP AT -X.",
             "ALL DIMENSIONS REFERENCE. HEIGHT TO THE LOX INLET FLANGE FACE (LAYOUT.JSON)"
             + (f"; BOLT HEADS ADD {fmt(fz1 - z_flange, 1)}" if fz1 - z_flange > 0.5 else "")
             + f". Y ENVELOPE FROM THE EXACT SILHOUETTE (LAYOUT.JSON LISTS "
             f"{fmt(ml.LAYOUT['envelope_width_y_mm'], 1)} FROM A LOOSE BOUNDING BOX OF THE EXIT MANIFOLD).",
             "GIMBAL PIVOT: CROSSING OF THE PITCH AND YAW PIN AXES. CUTS A-A, E-E, F-F: SHEETS 2, 4, 5.",
             "MASSES FROM CAD/OUTPUT/BOM.CSV; PERFORMANCE FROM RESULTS/DESIGN.JSON."]
    ml.wrapped_notes(s, 232.0, yk - 4.0, notes, chars=140, h=1.9, gap=1.3)
    s.boxed_note(232.0, 78.0, 176.0, STATUS_NOTE, h=2.0)
    s.publish_name = "MFE280-GA-001"
    return s


# ============================================================================ sheet 6: bolted-joint schedule
JOINT_INFO = {
    "lox_inlet": ("LOX PUMP INLET, VEHICLE INTERFACE", 1), "ch4_inlet": ("CH4 PUMP INLET, VEHICLE INTERFACE", 1),
    "lox_discharge": ("LOX DISCHARGE DUCT, PUMP AND OPB", 2), "ch4_discharge": ("CH4 DISCHARGE DUCT, PUMP AND JACKET", 2),
    "fpb_feed": ("JACKET CIRCUIT A TO FPB", 2), "nozzle_return": ("JACKET CIRCUIT B TO FPB", 2),
    "ox_crossfeed": ("KICK STAGE, FPOV, FPB", 2), "fuel_crossfeed": ("CH4 DISCHARGE TAP, OPFV, OPB", 2),
    "ox_hot_gas": ("OPB TURBINE EXHAUST TO OX DOME", 1), "fuel_hot_gas": ("FPB TURBINE EXHAUST TO FUEL PLENUM", 1),
    "injector_chamber": ("INJECTOR HEAD TO CHAMBER (SHEET 2)", 1), "nozzle_joint": ("CHAMBER TO NOZZLE, EPS 12 (SHEET 2)", 1),
    "coolant_jumper": ("COOLANT JUMPERS ACROSS THE NOZZLE JOINT", 4), "igniter": ("PREBURNER TORCH IGNITERS", 2),
    "ox_pump_inlet_housing": ("LOX INLET HOUSING TO PUMP CASING", 1), "ox_pump_volute_cover": ("LOX PUMP VOLUTE COVER", 1),
    "fuel_pump_inlet_housing": ("CH4 INLET HOUSING TO PUMP CASING", 1), "fuel_pump_volute_cover": ("CH4 PUMP VOLUTE COVER", 1),
    "ox_turbine_housing": ("LOX TURBINE HOUSING", 1), "fuel_turbine_housing": ("CH4 TURBINE HOUSING", 1),
    "ox_bearing_housing": ("LOX BEARING HOUSING", 1), "fuel_bearing_housing": ("CH4 BEARING HOUSING", 1)}
TAPPED = {"igniter", "ox_pump_inlet_housing", "fuel_pump_inlet_housing", "fuel_pump_volute_cover", "fuel_turbine_housing",
          "ox_bearing_housing", "fuel_bearing_housing"}


def sheet_jnt():
    s = Sheet("A3")
    s.frame(title(6, "MFE280-JNT-006", ["MFE-280 ENGINE", "BOLTED-JOINT SCHEDULE", "TYPICAL FLANGED JOINT"],
                  doc_type="REFERENCE DWG", scale="NONE"))
    cols = [("JOINT", 10), ("LOCATION", 66), ("NO.", 8), ("MEOP bar", 16), ("SEAL %%c", 15), ("FASTENER", 36),
            ("QTY", 10), ("GRADE", 13), ("BCD", 15), ("SP / d", 12), ("F SEP kN", 16), ("PRELOAD kN", 18),
            ("TORQUE N m", 19), ("STRESS R.", 16), ("FLANGE OD X t", 28), ("SEAL / JOINT", 40)]
    rows, welded_tags = [], {}
    allj = [(j, False) for j in D["joints"]] + [(j, True) for j in D["internal_joints"]]
    for i, (j, internal) in enumerate(allj):
        n = j["name"]
        loc, nj = JOINT_INFO[n]
        tag = f"J{i + 1:02d}"
        if j.get("welded"):
            why = "NO TOOL ACCESS" if "tool access" in j.get("reason", "") else "NO ISO SIZE FITS"
            welded_tags.setdefault(why, []).append(tag)
            rows.append([tag, loc, str(nj), fmt(j["p_meop_Pa"] / 1e5, 1), fmt(mm(j["D_seal_m"]), 1), "WELDED",
                         "-", "-", "-", "-", "-", "-", "-", "-", "-", "WELDED, " + why])
            continue
        d = mm(j["d_m"])
        if n in TAPPED:
            fast = f"ISO 4017 {j['bolt']}, TAPPED"
        else:
            fast = ml.through_bolt(d, mm(j["flange_t_m"]))["bolt"]
        rows.append([tag, loc, str(nj), fmt(j["p_meop_Pa"] / 1e5, 1), fmt(mm(j["D_seal_m"]), 1), fast,
                     str(j["n_bolts"] * nj), ml.grade_label(j["grade"]), fmt(mm(j["bcd_m"]), 1), fmt(j["spacing_over_d"], 2),
                     fmt(j["F_sep_proof_N"] / 1e3, 1), fmt(j["preload_N"] / 1e3, 1), fmt(ml.torque_Nm(j["preload_N"], j["d_m"]), 0),
                     fmt(j["bolt_stress_ratio"], 3), f"{fmt(mm(j['flange_od_m']), 1)} X {fmt(mm(j['flange_t_m']), 1)}",
                     "METALLIC C-SEAL"])
    yb = s.table(22, 278.0, cols, rows, title="BOLTED-JOINT SCHEDULE", row_h=4.5, text_h=1.95)

    # ---- typical flanged joint (generic, symbolic), half section, pipe axis vertical
    s.view_title(24, yb - 6.0, "TYPICAL FLANGED JOINT", "NOT TO SCALE   HALF SECTION, SYMBOLIC DIMENSIONS")
    ax, yj = 40.0, 102.0                     # pipe axis x, joint plane y
    r_b, w, R_od, r_bcd, r_seal, t, hub, d = 24.0, 5.0, 96.0, 74.0, 46.0, 15.0, 22.0, 9.0
    for sg, ang in ((1, 45.0), (-1, 135.0)):
        y_face, y_back = yj, yj + sg * t
        flange = [(ax + r_b, y_face), (ax + R_od, y_face), (ax + R_od, y_back), (ax + r_b + w + 8, y_back),
                  (ax + r_b + w, y_back + sg * 8), (ax + r_b + w, y_back + sg * hub), (ax + r_b, y_back + sg * hub)]
        hole = [(ax + r_bcd - 0.55 * d, y_face), (ax + r_bcd + 0.55 * d, y_face), (ax + r_bcd + 0.55 * d, y_back),
                (ax + r_bcd - 0.55 * d, y_back)]
        groove = ([(ax + r_seal - 3.0, yj), (ax + r_seal + 3.0, yj), (ax + r_seal + 3.0, yj - 2.4), (ax + r_seal - 3.0, yj - 2.4)]
                  if sg < 0 else None)
        # split the flange outline at the bolt hole so the hatch leaves the hole open
        left = [(ax + r_b, y_face), (ax + r_bcd - 0.55 * d, y_face), (ax + r_bcd - 0.55 * d, y_back),
                (ax + r_b + w + 8, y_back), (ax + r_b + w, y_back + sg * 8), (ax + r_b + w, y_back + sg * hub),
                (ax + r_b, y_back + sg * hub)]
        right = [(ax + r_bcd + 0.55 * d, y_face), (ax + R_od, y_face), (ax + R_od, y_back), (ax + r_bcd + 0.55 * d, y_back)]
        if groove:
            left = [(ax + r_b, y_face), (ax + r_seal - 3.0, yj), (ax + r_seal - 3.0, yj - 2.4), (ax + r_seal + 3.0, yj - 2.4),
                    (ax + r_seal + 3.0, yj)] + left[1:]
        for lp in (left, right):
            ml.hatch_loops(s, [lp], angle=ang, spacing=2.0)
            s.poly(lp, "VISIBLE", closed=True)
        # pipe beyond the hub
        s.poly([(ax + r_b, y_back + sg * hub), (ax + r_b, y_back + sg * (hub + 14))], "VISIBLE")
        s.poly([(ax + r_b + w, y_back + sg * hub), (ax + r_b + w, y_back + sg * (hub + 14))], "VISIBLE")
        ml.break_line(s, (ax + r_b - 3, y_back + sg * (hub + 14)), (ax + r_b + w + 3, y_back + sg * (hub + 14)), amp=1.0)
    # C-seal in the groove (solid, opening toward the bore / pressure side)
    cx, cy, rs = ax + r_seal, yj - 1.2, 1.15
    pts = [(cx + rs * math.cos(math.radians(a)), cy + rs * math.sin(math.radians(a))) for a in range(30, 331, 15)]
    s.poly(pts, "VISIBLE")
    # bolt (not hatched), washers, nut
    hx, hk, wt, nm_, Lb = 0.5 * 16.0, 6.0, 1.6, 8.0, 2 * t + 2 * 1.6 + 8.0 + 3.5
    xb = ax + r_bcd
    s.poly([(xb - d / 2, yj + t + wt), (xb - d / 2, yj + t + wt - Lb), (xb + d / 2, yj + t + wt - Lb), (xb + d / 2, yj + t + wt)],
           "VISIBLE")
    for y0_, h_ in ((yj + t, wt), (yj - t - wt, wt)):
        s.rect(xb - d, y0_, 2 * d, h_, "VISIBLE")
    s.rect(xb - hx, yj + t + wt, 2 * hx, hk, "VISIBLE")
    s.line((xb - hx / 2, yj + t + wt), (xb - hx / 2, yj + t + wt + hk), "VISIBLE")
    s.line((xb + hx / 2, yj + t + wt), (xb + hx / 2, yj + t + wt + hk), "VISIBLE")
    s.rect(xb - hx, yj - t - wt - nm_, 2 * hx, nm_, "VISIBLE")
    s.line((xb - hx / 2, yj - t - wt - nm_), (xb - hx / 2, yj - t - wt), "VISIBLE")
    s.line((xb + hx / 2, yj - t - wt - nm_), (xb + hx / 2, yj - t - wt), "VISIBLE")
    s.centerline((xb, yj + t + wt + hk + 2), (xb, yj - t - wt - nm_ - 4), ext=0)
    s.centerline((ax, yj + t + hub + 18), (ax, yj - t - hub - 18), ext=0)
    s.line((ax + r_b, yj), (ax + r_b - 6, yj), "THIN")

    # symbolic dimensions
    def half_dia(r, y, label):
        s.line((ax - 4.0, y), (ax + r, y), "DIM")
        s.arrowhead((ax + r, y), (ax, y))
        s.text(label, (ax + r - 1.0, y + 0.8), 2.5, "BOTTOM_RIGHT")
    for r, y, lab in ((R_od, yj + t + hub + 8, "%%cOD"), (r_bcd, yj + t + hub + 2, "%%cBCD"),
                      (r_seal, yj - t - hub - 4, "%%cD SEAL")):
        s.line((ax + r, yj + (t if y > yj else -t) * (1 if r != r_seal else 0)), (ax + r, y + (1.5 if y > yj else -1.5)), "DIM")
        half_dia(r, y, lab)
    s.dim_linear((ax + R_od, yj), (ax + R_od, yj + t), base=(ax + R_od + 6, 0), angle=90, text="t")
    s.dim_linear((ax + R_od, yj - t), (ax + R_od, yj), base=(ax + R_od + 6, 0), angle=90, text="t")
    s.dim_linear((xb + hx, yj + t + wt), (xb + hx, yj + t + wt - Lb), base=(ax + R_od + 14, 0), angle=90, text="L")
    s.leader((xb + d / 2, yj - t - wt - nm_ - 2.5), (xb + 20, yj - t - hub - 10),
             ["ISO 4014 Md X L, ISO 4032 NUT,", "2X ISO 7089 WASHER"], h=2.0)
    s.leader((cx + 0.6, cy - 0.8), (ax + 4.0, yj - t - hub - 14), ["METALLIC C-SEAL AT D SEAL"], h=2.0)
    s.text("PRESSURE SIDE", (ax + 2.0, yj + 2.0), 2.0, "BOTTOM_LEFT")

    # ---- notes on the sizing method (ffsc/structures.py, config/baseline.yaml)
    cfg = D["config"]["structures"]
    notes = [
        "J01-J14: DESIGN.JSON JOINTS; J15-J22: INTERNAL_JOINTS (TURBOPUMP CASINGS). SIZING (VDI 2230-STYLE, FFSC/STRUCTURES.PY): "
        "SEPARATING FORCE AT PROOF PRESSURE F = 1.2 X MEOP X PI X D SEAL X D SEAL / 4.",
        f"PRELOAD Fv = {fmt(cfg['preload_frac_proof'] * 100, 0)} % OF PROOF LOAD (PROOF STRENGTH A286 760 MPa, IN718 1030 MPa) "
        "X TENSILE STRESS AREA. JOINT FACTOR 0.25 (SHARE OF THE EXTERNAL LOAD SEEN BY THE BOLT).",
        f"BOLT COUNT n >= {fmt(cfg['separation_safety'], 1)} X (1 - 0.25) X F / Fv (SEPARATION SAFETY "
        f"{fmt(cfg['separation_safety'], 1)}), EVEN; SPACING ON THE BCD 2.5 d TO 6 d (WRENCH ACCESS / SEAL LOAD).",
        "BCD = D SEAL + 2 (0.9 d + 4); FLANGE OD = BCD + AF + 5 + d; FLANGE t FROM RING BENDING AT "
        f"{fmt(cfg['closeout_allow_MPa'], 0)} MPa, NOT BELOW d. STRESS R. = (Fv + 0.25 F / n) / PROOF LOAD.",
        f"TIGHTENING TORQUE T = K X Fv X d WITH K = {ml.K_TORQUE} (MOS2-LUBRICATED A286 / IN718 THREADS, ASSUMED).",
        "THROUGH-BOLTED JOINTS: ISO 4014 BOLT, ISO 4032 NUT, 2X ISO 7089 WASHERS; L = 2 t + 2 WASHERS + NUT + 2 PITCH, "
        "ROUNDED UP TO THE ISO LENGTH SERIES. TAPPED JOINTS: ISO 4017 SCREW, L OPEN (HOLE DEPTH NOT MODELLED).",
        "ALL BOLTED JOINTS SEAL WITH A METALLIC C-SEAL AT D SEAL. WELDED: "
        + "; ".join(f"{' AND '.join(t)} ({w})" for w, t in welded_tags.items())
        + ". NO TOOL ACCESS = BOLT CIRCLE UNDER THE TURBINE EXHAUST COLLECTOR.",
        "QTY = BOLTS PER JOINT X NO. OF JOINTS. MEOP, F SEP, PRELOAD AND FLANGE SIZES FROM RESULTS/DESIGN.JSON.",
    ]
    ml.wrapped_notes(s, 162.0, yb - 8.0, notes, chars=128, h=1.9, gap=1.4)
    s.boxed_note(162.0, 82.0, 246.0, "JOINT SIZING: FIRST-ORDER (ITERATION 1), SUBJECT TO UPDATE.", h=2.0)
    s.publish_name = "MFE280-JNT-006"
    return s


SHEETS = {"ga": sheet_ga, "tca": sheet_tca, "inj": sheet_inj, "tpo": lambda: sheet_tpa("ox"), "tpf": lambda: sheet_tpa("fuel"), "jnt": sheet_jnt}

ORDER = ["ga", "tca", "inj", "tpo", "tpf", "jnt"]

if __name__ == "__main__":
    which = sys.argv[1:] or ORDER
    for k in which:
        sh = SHEETS[k]()
        publish(sh, sh.publish_name)
        print("published", sh.publish_name)
    names = ["MFE280-GA-001", "MFE280-TCA-002", "MFE280-INJ-003", "MFE280-TPO-004", "MFE280-TPF-005", "MFE280-JNT-006"]
    pdfs = [OUT / "pdf" / f"{n}.pdf" for n in names]
    if all(p.exists() for p in pdfs):
        merge(pdfs, OUT / "MFE280-DWG-SET.pdf")
        print("merged", OUT / "MFE280-DWG-SET.pdf")
