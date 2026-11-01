"""MFE-280 P&ID set: legend (PID-000), engine P&ID (PID-001, A2), line list (PID-002),
equipment and valve list (PID-003), instrument index (PID-004). Every tag and number
comes from pid_data (itself from results/design.json).

Run: .venv\\Scripts\\python.exe drawings\\src\\make_pid_set.py [--iter ID]

Iteration 1 (default): drawings/, merged into drawings/MFE280-PID-SET.pdf as issued.
--iter ID: data from results/iterations/<ID>/design.json and the config cad switches, output in
drawings/<ID>/, merged into drawings/<ID>/MFE280-<ID>-PID-SET.pdf.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import itercfg as IT  # noqa: E402  (first: parses --iter)
import pid_lib as L  # noqa: E402
import render  # noqa: E402
from pid_data import (CLASSES, EQUIPMENT, FLUIDS, INSTRUMENTS, LINES, VALVES, WELDED_LINES, BEARING_BLEED, line_tag,  # noqa: E402
                      D, LASER, HYDRO)
from sheet import Sheet, TitleInfo  # noqa: E402
from pid_engine import engine_pid  # noqa: E402

N_SHEETS = 5
PID_STRIP = ["SYMBOLS ISO 10628-2   IDENTIFICATION ANSI/ISA-5.1   PRESENTATION ISO 10628-1",
             "LINE: ID mm - FLUID - No. - CLASS   PRESSURES bar(a)   DESIGN P = 1.2 x MEOP"]


def info(no, title, doc_type, sheet_no, scale="NONE"):
    return TitleInfo(dwg_no=f"MFE280-PID-{no:03d}", title=title, doc_type=doc_type, sheet=f"{sheet_no}/{N_SHEETS}",
                     scale=scale, projection="", strip=PID_STRIP, tech_ref=IT.PID_TECH_REF, rev=IT.REV)


# ============================================================================ PID-000 legend (A3)
def legend():
    s = Sheet("A3")
    s.frame(info(0, ["MFE-280 ENGINE", "P&ID LEGEND", "SYMBOLS AND CODES"], "P&ID LEGEND", 1))
    s.view_title(25, 282, "GRAPHICAL SYMBOLS", "ISO 10628-2 FORMS, ANSI/ISA-5.1 INSTRUMENT FUNCTIONS")
    x, y = 30.0, 258.0
    rows = []

    def item(draw, text_, dy=10.5):
        nonlocal y
        draw((x + 8, y))
        s.text(text_, (x + 24, y), 2.4, "MIDDLE_LEFT")
        y -= dy

    item(lambda p: L.pipe(s, [(p[0] - 8, p[1]), (p[0] + 12, p[1])], arrows=(0,)), "PROCESS LINE, PROPELLANT (0.7)")
    item(lambda p: L.pipe(s, [(p[0] - 8, p[1]), (p[0] + 10, p[1])], minor=True, arrows=(0,)), "SECONDARY LINE: CROSS-FEED, PURGE, PRESSURANT (0.35)")
    item(lambda p: L.signal(s, [(p[0] - 8, p[1]), (p[0] + 10, p[1])]), "ELECTRICAL SIGNAL (ISA-5.1)")
    item(lambda p: L.shaft(s, (p[0] - 8, p[1]), (p[0] + 14, p[1])), "SHAFT / MECHANICAL LINK")
    item(lambda p: s.poly([(p[0] - 8, p[1]), (p[0] + 14, p[1])], "BOUNDARY"), "INTERFACE LIMIT")
    item(lambda p: (s.line((p[0] - 8, p[1]), (p[0] + 8, p[1]), "PROCESS_MINOR"), L.tee(s, p)), "CONNECTION (TEE); CROSSING LINES ARE NOT CONNECTED")
    item(lambda p: L.pump(s, p, 5, "right"), "CENTRIFUGAL PUMP")
    item(lambda p: L.turbine(s, p, 12, 8), "TURBINE (GAS ENTERS AT THE NARROW END)")
    item(lambda p: L.vessel(s, p, 12, 8), "PREBURNER / VESSEL")
    item(lambda p: L.hx(s, p, 12, 7), "HEAT EXCHANGER")
    item(lambda p: L.valve(s, p, "h", "gate"), "VALVE, GENERAL")
    item(lambda p: L.valve(s, p, "h", "ball"), "BALL VALVE")
    item(lambda p: L.valve(s, p, "h", "globe"), "GLOBE VALVE (THROTTLING)")
    item(lambda p: L.valve(s, p, "h", "check"), "CHECK VALVE (NON-RETURN), FLOW TOWARDS THE FILLED SIDE")
    item(lambda p: L.valve(s, p, "v", "ball", act="M"), "VALVE WITH ELECTROMECHANICAL ACTUATOR (M)")
    item(lambda p: L.valve(s, p, "v", "ball", act="S"), "VALVE WITH SOLENOID ACTUATOR (S)")
    item(lambda p: L.valve(s, p, "v", "globe", act="D"), "SELF-ACTING PRESSURE REGULATOR")
    item(lambda p: L.orifice(s, p, "h"), "RESTRICTION ORIFICE")
    item(lambda p: L.relief(s, (p[0] - 2, p[1] - 2), vent=""), "SPRING-LOADED RELIEF VALVE", dy=11)
    item(lambda p: L.connector(s, (p[0] - 6, p[1]), "", "right", w=14, h=5), "INTERFACE / OFF-SHEET CONNECTOR")

    x2, y2 = 160.0, 258.0
    for tag, kind, text_ in [("PT-000", "field", "DISCRETE INSTRUMENT, FIELD MOUNTED"),
                             ("TIC-000", "computer", "COMPUTER FUNCTION (ENGINE CONTROL UNIT ECU-100)"),
                             ("UZ-000", "logic", "INTERLOCK / SHUTDOWN LOGIC")]:
        L.instrument(s, (x2 + 6, y2), tag, kind, r=5.5)
        s.text(text_, (x2 + 16, y2), 2.4, "MIDDLE_LEFT")
        y2 -= 15
    s.text("IDENTIFICATION LETTERS (ISA-5.1, USED HERE)", (x2, y2 + 2), 3.0, "BOTTOM_LEFT")
    yb = s.table(x2, y2, [("LETTER", 16), ("FIRST LETTER", 40), ("SUCCEEDING", 40)], [
        ["P", "PRESSURE", "-"], ["T", "TEMPERATURE", "TRANSMITTER"], ["S", "SPEED", "-"], ["V", "VIBRATION", "VALVE"],
        ["Z", "POSITION", "-"], ["U", "MULTIVARIABLE", "-"], ["F", "FLOW", "-"], ["X", "UNCLASSIFIED (ON/OFF)", "-"],
        ["I", "-", "INDICATE"], ["C", "-", "CONTROL"], ["Z (2nd)", "-", "SAFETY / INTERLOCK"]], row_h=4.6, text_h=2.0)
    s.text("FLUID CODES", (x2, yb - 6), 3.0, "BOTTOM_LEFT")
    yb = s.table(x2, yb - 8, [("CODE", 16), ("FLUID", 80)], [[k, v.upper()] for k, v in FLUIDS.items()], row_h=4.6, text_h=2.0)

    x3 = 270.0
    s.text("PIPING CLASSES", (x3, 260), 3.0, "BOTTOM_LEFT")
    yc = s.table(x3, 258, [("CL.", 8), ("SERVICE", 44), ("MATERIAL", 30), ("DES. P", 13), ("DES. T", 22)],
                 [[c[0], c[1].upper(), c[2].upper(), f"{c[3]:.0f}", c[4].upper()] for c in CLASSES], row_h=4.6, text_h=2.0)
    s.notes(x3, yc - 4, [n.upper() for n in [c[0] + ": " + c[5] for c in CLASSES if c[5]]], h=1.9, gap=1.2, numbered=False)
    notes = [
        "LINE No. FIRST DIGIT = LOOP GROUP: 1 CHAMBER, 2 OXIDISER, 3 FUEL, 4 PURGE/IGNITION.",
        "SIZES ARE INSIDE DIAMETERS (CUSTOM AEROSPACE TUBE, NOT PIPE SCHEDULES).",
        "DESIGN PRESSURE = 1.2 x MAXIMUM EXPECTED OPERATING PRESSURE (PROOF).",
        "EQUIPMENT TAGS: P PUMP, T TURBINE, B PREBURNER, TC THRUST CHAMBER, HX HEAT EXCHANGER, IG IGNITER.",
    ]
    if LASER:
        notes[0] = "LINE No. FIRST DIGIT = LOOP GROUP: 1 CHAMBER, 2 OXIDISER, 3 FUEL, 4 PURGE."
    if HYDRO:
        notes[3] = notes[3][:-1] + ", BRG BEARING."
    if WELDED_LINES:
        notes.append("WELDED LINE: NO FLANGED BREAK, BUTT WELDS ONLY (SEE PID-001 NOTE).")
    s.notes(x3, yc - 46, notes, h=1.9, gap=1.3)
    return s


# ============================================================================ registers (A3 tables)
def register(no, title, doc_type, sheet_no, blocks):
    s = Sheet("A3")
    s.frame(info(no, title, doc_type, sheet_no))
    for (x, y, heading, cols, rows, h) in blocks:
        s.table(x, y, cols, rows, title=heading, row_h=h, text_h=min(2.0, h * 0.44))
    return s


def line_list():
    rows = []
    for no, (fl, d, cl, frm, to, p, T, m) in LINES.items():
        rows.append([no, line_tag(no), fl, f"{d}", cl, frm.upper(), to.upper(), f"{p:.0f}", f"{T:.0f}", (f"{m:.2f}" if m < 1 else f"{m:.1f}") if m else "-",
                     f"{[c for c in CLASSES if c[0] == cl][0][3]:.0f}"])
    cols = [("No.", 9), ("DESIGNATION", 30), ("FLUID", 11), ("ID", 8), ("CL.", 7), ("FROM", 58), ("TO", 78), ("OP. P", 11),
            ("OP. T K", 12), ("kg/s", 11), ("DES. P", 12)]
    s = register(2, ["MFE-280 ENGINE", "P&ID", "LINE LIST"], "LINE LIST", 3, [(25, 270, "LINE LIST", cols, rows, 5.4)])
    notes = [
        f"OPERATING VALUES AT 100 % THRUST, SEA LEVEL, FROM {IT.RES_TXT}DESIGN.JSON. PRESSURES bar(a).",
        "DESIGN P = 1.2 x MEOP OF THE PIPING CLASS (MFE280-PID-000).",
        "LINES 204, 206, 307: PRESSURANT FLOWS ARE NOMINAL, SET BY FO-204 / FO-304 TO VEHICLE DEMAND.",
        "LINES 207, 308: CHILL-DOWN BLEED, NO FLOW AT MAINSTAGE.",
    ]
    if HYDRO:
        notes.append(f"LINES 309, 310: BEARING FLOW NOMINAL, {BEARING_BLEED:.0%} OF THE P-301 FLOW (OPTION C2, "
                     "ASSUMED); SIZES NOMINAL, SET BY FO-309.")
    if WELDED_LINES:
        notes.append("WELDED, NO FLANGED BREAKS (OPTIONS I1, I3): LINES " + ", ".join(WELDED_LINES) + ".")
    if LASER:
        notes.append("LINES 403, 404 (TORCH GOX / GCH4) REMOVED: LASER IGNITION (OPTION N2).")
    s.notes(25, 270 - 5.4 * (len(rows) + 1) - 6, notes)
    return s


def equipment_valves():
    eq = [[t, n.upper(), d.upper()] for t, n, d in EQUIPMENT]
    va = [[t, a.upper(), b.upper(), act.upper(), ln, f, fn.upper()] for t, a, b, act, ln, f, fn in VALVES]
    blocks = [(25, 270, "EQUIPMENT LIST", [("TAG", 16), ("NAME", 52), ("DATA", 120)], eq, 4.6),
              (25, 270 - 4.6 * (len(eq) + 1) - 12, "VALVE LIST",
               [("TAG", 17), ("ALIAS", 22), ("BODY", 34), ("ACTUATOR", 28), ("LINE", 10), ("FAIL", 9), ("FUNCTION", 90)], va, 4.4)]
    return register(3, ["MFE-280 ENGINE", "P&ID", "EQUIPMENT AND VALVES"], "EQUIPMENT LIST", 4, blocks)


def instrument_index():
    rows = [[t, sv.upper(), ty.upper(), rg, nv, dest.upper()] for t, sv, ty, rg, nv, dest in INSTRUMENTS]
    cols = [("TAG", 17), ("SERVICE", 62), ("TYPE", 44), ("RANGE", 22), ("NORMAL", 24), ("SIGNAL TO", 38)]
    s = register(4, ["MFE-280 ENGINE", "P&ID", "INSTRUMENT INDEX"], "INSTRUMENT INDEX", 5, [(25, 270, "INSTRUMENT INDEX", cols, rows, 5.0)])
    notes = [
        "RANGES ARE PRELIMINARY: ABOUT 1.3 x NORMAL, ROUNDED. REDUNDANCY (DUAL PT-101, TRIPLE ST) NOT SHOWN.",
        "TIC-203 AND TIC-303 TRIM THE PREBURNER VALVES; PIC-101 SETS THRUST THROUGH PV-101A/B AT FIXED O/F.",
    ]
    if LASER:
        notes.append("XC-206 AND XC-306 FIRE THE LASER IGNITERS IG-201, IG-301 IN THE START SEQUENCE (ELECTRIC SIGNAL).")
    if HYDRO:
        notes.append("PT-309 LOW TRIPS UZ-100: LOSS OF CH4 BEARING SUPPLY.")
    s.notes(25, 270 - 5.0 * (len(rows) + 1) - 6, notes)
    return s


if __name__ == "__main__":
    pdfs = [render.publish(legend(), "MFE280-PID-000"),
            render.publish(engine_pid(info), "MFE280-PID-001", paper="A2"),
            render.publish(line_list(), "MFE280-PID-002"),
            render.publish(equipment_valves(), "MFE280-PID-003"),
            render.publish(instrument_index(), "MFE280-PID-004")]
    if not IT.DXF_ONLY:
        render.merge(pdfs, IT.SET_PID)
        print("P&ID set written:", IT.SET_PID)
