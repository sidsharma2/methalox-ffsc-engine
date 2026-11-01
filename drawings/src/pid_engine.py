"""MFE280-PID-001: engine P&ID on an A2 sheet (layout in sheet mm).

Iteration switches (pid_data): laser igniters with electric signal lines from XC-206 / XC-306
replace the torch igniters and their supplies; the CH4 hydrostatic-bearing loop (supply 309 via
FO-309, drain 310) is drawn on the fuel turbopump shaft; welded lines are listed in a note."""

import itercfg as IT
import pid_lib as L
from pid_data import D, line_tag, LASER, HYDRO, WELDED_LINES
from sheet import Sheet


def engine_pid(info):
    s = Sheet("A2")
    s.frame(info(1, ["MFE-280 ENGINE", "P&ID, MAINSTAGE", "DESIGN POINT"], "P&ID", 2))
    s.view_title(296, 405, "ENGINE P&ID", "100 % THRUST, SEA LEVEL")
    s.poly([(32, 80), (578, 80), (578, 382), (32, 382)], "BOUNDARY", closed=True)
    s.text("ENGINE / VEHICLE INTERFACE LIMIT", (36, 378), 2.5, "TOP_LEFT")
    s.text("VEHICLE SIDE", (36, 386), 2.5, "BOTTOM_LEFT")

    xo, xf, xc = 140.0, 485.0, 310.0
    top = 392.0                                   # line ends at the vehicle side

    # ---------------------------------------------------------------- TC-101 and regen jacket HX-101
    s.rect(xc - 35, 245, 70, 24, "SYMBOL")
    s.text("MAIN INJECTOR", (xc, 262), 2.5, "MIDDLE_CENTER")
    s.text(f"{D['injector']['n_elements']} GAS-GAS COAX ELEMENTS", (xc, 255), 2.0, "MIDDLE_CENTER")
    s.text("ORG POSTS / FRG ANNULI", (xc, 250), 2.0, "MIDDLE_CENTER")
    s.poly([(xc - 24, 245), (xc + 24, 245), (xc + 24, 215), (xc + 10, 190), (xc + 40, 100), (xc - 40, 100), (xc - 10, 190),
            (xc - 24, 215)], "SYMBOL", closed=True)
    s.text("TC-101", (xc, 232), 3.0, "MIDDLE_CENTER")
    s.text("MAIN CHAMBER", (xc, 226), 2.0, "MIDDLE_CENTER")
    s.text(f"{D['performance']['pc'] / 1e5:.0f} bar", (xc, 221), 2.0, "MIDDLE_CENTER")
    s.text("NOZZLE", (xc, 125), 2.0, "MIDDLE_CENTER")
    s.text(f"EPS {D['config']['nozzle']['expansion_ratio']:.0f}", (xc, 120), 2.0, "MIDDLE_CENTER")
    for sg in (-1, 1):
        s.poly([(xc + sg * 27, 241), (xc + sg * 27, 216), (xc + sg * 13, 189), (xc + sg * 18, 161)], "SYMBOL_THIN")
        s.poly([(xc + sg * 18, 161), (xc + sg * 43, 103)], "SYMBOL_THIN")
    s.line((xc - 30, 161), (xc + 30, 161), "SYMBOL")
    s.text("JOINT EPS 12", (xc - 32, 161), 2.0, "MIDDLE_RIGHT")
    s.text("HX-101A", (xc + 33, 208), 2.5, "MIDDLE_LEFT")
    s.text("CIRCUIT A, GRCOP-42 LINER", (xc + 33, 203), 2.0, "MIDDLE_LEFT")
    s.text("HX-101B", (xc + 48, 140), 2.5, "MIDDLE_LEFT")
    s.text("CIRCUIT B, IN718 LINER", (xc + 48, 135), 2.0, "MIDDLE_LEFT")
    man_out, man_in, man_exit = (xc + 27, 238), (xc + 21, 161), (xc + 43, 103)
    for p in (man_out, man_in, man_exit):
        L.tee(s, p)
    L.instrument(s, (xc - 50, 222), "PT-101", conn=(xc - 24, 222))

    # ---------------------------------------------------------------- oxidiser train (left)
    L.pipe(s, [(xo, top), (xo, 347)], arrows=(0,), label=line_tag("201"), side=-1, at=0.55)
    L.valve(s, (xo, 386), "v", "ball", tag="PV-V01 VEHICLE", tag_side=1)
    L.connector(s, (xo, top), "FROM LOX TANK", "up")
    L.instrument(s, (xo - 22, 362), "PT-201", conn=(xo, 362))
    L.instrument(s, (xo + 22, 366), "TT-201", conn=(xo, 366))
    L.pump(s, (xo, 340), 7, "right", "P-201", "LOX PUMP", "left")
    L.pipe(s, [(xo + 7, 340), (200, 340), (200, 160), (xo, 160), (xo, 172)], arrows=(0, 1, 2), label=line_tag("202"),
           seg=1, side=1, at=0.22)
    a_mov = L.valve(s, (200, 300), "v", "ball", act="M", act_side=1, tag="PV-101A MOV", tag_side=-1, fail="FC")
    L.instrument(s, (222, 316), "ZT-101A", conn=(a_mov[0] + 1.5, a_mov[1] + 2.2))
    L.instrument(s, (160, 356), "PT-202", conn=(160, 340))
    L.tee(s, (186, 340))
    L.pipe(s, [(186, 340), (186, top)], minor=True, arrows=(0,), label=line_tag("207"), side=1, at=0.72, h=1.9)
    L.valve(s, (186, 356), "v", "ball", act="S", act_side=1, tag="XV-210", tag_side=-1, fail="FC")
    L.connector(s, (186, top), "CHILL-DOWN BLEED", "up")
    # kick stage on the LOX shaft feeds the FPB oxidiser cross-feed
    L.tee(s, (200, 322))
    L.pipe(s, [(200, 322), (170, 322), (170, 284.5)], minor=True)
    L.pump(s, (170, 280), 4.5, "down")
    s.text("P-202", (176, 283), 2.6, "BOTTOM_LEFT")
    s.text("KICK STAGE", (176, 279), 2.0, "TOP_LEFT")
    L.shaft(s, (xo, 280), (165.5, 280))
    L.pipe(s, [(170, 275.5), (170, 94), (560, 94), (560, 155), (492, 155), (492, 172)], minor=True, arrows=(0, 1, 3),
           label=line_tag("203"), seg=1, side=1, at=0.16, h=1.9)
    a_fpov = L.valve(s, (560, 128), "v", "globe", act="M", act_side=-1, tag="TV-303 FPOV", tag_side=1, fail="FC")
    # OPB, turbine and ox-rich gas
    L.vessel(s, (xo, 192), 24, 40, "B-201", "OPB")
    s.text(f"{D['cycle']['p_opb_Pa'] / 1e5:.0f} bar", (xo, 184), 2.0, "TOP_CENTER")
    s.text(f"{D['config']['cycle']['T_opb_K']:.0f} K", (xo, 180), 2.0, "TOP_CENTER")
    L.instrument(s, (166, 202), "PT-203", conn=(xo + 12, 202))
    L.pipe(s, [(xo, 212), (xo, 242.5)], arrows=(0,))
    L.instrument(s, (xo - 30, 228), "TT-203", conn=(xo, 228))
    L.turbine(s, (xo, 248), tag="T-201", desc="OX TURBINE", tag_pos="right")
    L.shaft(s, (xo, 253.5), (xo, 333))
    L.instrument(s, (xo - 30, 296), "ST-204", conn=(xo, 296))
    L.instrument(s, (xo - 30, 316), "VT-205", conn=(xo, 316))
    L.pipe(s, [(xo, 253.5), (xo, 262), (xc - 35, 262)], arrows=(1,), label=line_tag("205"), seg=1, side=1, at=0.28)
    L.hx(s, (225, 262), tag="HX-201", tag_pos="below")
    # GOX pressurant
    L.tee(s, (200, 282))
    L.pipe(s, [(200, 282), (218, 282), (218, 266)], minor=True)
    L.orifice(s, (208, 282), "h", "FO-204", tag_side=1)
    L.valve(s, (218, 274.5), "v", "ball", act="S", act_side=1, tag="XV-204", tag_side=-1)
    L.pipe(s, [(232, 266), (232, top)], minor=True, arrows=(0,), label=line_tag("206"), side=1, at=0.78, h=1.9)
    L.connector(s, (232, top), "TO LOX TANK PRESSURISATION", "up")
    s.circle((xo - 30, 178), 4.0, "SYMBOL")
    s.text("IG", (xo - 30, 178), 2.4, "MIDDLE_CENTER")
    s.line((xo - 26, 178), (xo - 12, 178), "SYMBOL")
    s.text("IG-201", (xo - 25.5, 179.5), 2.2, "BOTTOM_LEFT")
    if LASER:
        # laser igniter IG-201, fired by the ECU ignition command XC-206 (ISA-5.1 electric signal)
        s.text("LASER", (xo - 25.5, 176.5), 1.9, "TOP_LEFT")
        L.instrument(s, (xo - 30, 160), "XC-206", kind="computer", r=5.5)
        L.signal(s, [(xo - 30, 165.5), (xo - 30, 174)])
    else:
        # torch igniter IG-201, torch propellants from the vehicle
        s.text("EX-201", (xo - 25.5, 176.5), 1.9, "TOP_LEFT")
        L.pipe(s, [(40, 182), (xo - 33.5, 182)], minor=True, arrows=(0,), label=line_tag("403"), side=1, at=0.62, h=1.8)
        L.pipe(s, [(40, 174), (xo - 33.5, 174)], minor=True, arrows=(0,), label=line_tag("404"), side=-1, at=0.62, h=1.8)
        L.valve(s, (52, 182), "h", "ball", act="S", act_side=1, tag="XV-206", tag_side=1)
        L.valve(s, (66, 174), "h", "ball", act="S", act_side=-1, tag="XV-207", tag_side=-1)
        L.connector(s, (32, 182), "GOX", "right", w=8)
        L.connector(s, (32, 174), "GCH4", "right", w=8, side=-1)
    # OPB temperature loop TIC-203 -> TV-203 (OPFV)
    L.instrument(s, (78, 240), "TIC-203", kind="computer", r=6.0)
    L.signal(s, [(xo - 35, 229.5), (83.5, 238)])

    # ---------------------------------------------------------------- fuel train (right)
    L.pipe(s, [(xf, top), (xf, 347)], arrows=(0,), label=line_tag("301"), side=1, at=0.55)
    L.valve(s, (xf, 386), "v", "ball", tag="PV-V02 VEHICLE", tag_side=-1)
    L.connector(s, (xf, top), "FROM CH4 TANK", "up")
    L.instrument(s, (xf + 22, 362), "PT-301", conn=(xf, 362))
    L.instrument(s, (xf - 22, 366), "TT-301", conn=(xf, 366))
    L.pump(s, (xf, 340), 7, "left", "P-301", "CH4 PUMP, 2 STAGES", "right")
    L.pipe(s, [(xf - 7, 340), (430, 340), (430, 161), (man_in[0], 161)], arrows=(0, 1, 2), label=line_tag("302"), seg=1, side=-1, at=0.3)
    a_mfv = L.valve(s, (430, 300), "v", "ball", act="M", act_side=-1, tag="PV-101B MFV", tag_side=1, fail="FC")
    L.instrument(s, (408, 316), "ZT-101B", conn=(a_mfv[0] - 1.5, a_mfv[1] + 2.2))
    L.instrument(s, (456, 326), "PT-302", conn=(456, 340))
    L.tee(s, (444, 340))
    L.pipe(s, [(444, 340), (444, top)], minor=True, arrows=(0,), label=line_tag("308"), side=-1, at=0.72, h=1.9)
    L.valve(s, (444, 356), "v", "ball", act="S", act_side=-1, tag="XV-310", tag_side=1, fail="FC")
    L.connector(s, (444, top), "CHILL-DOWN BLEED", "up", side=-1)
    # fuel cross-feed to the OPB
    L.tee(s, (468, 340))
    L.pipe(s, [(468, 340), (468, 89), (58, 89), (58, 145), (xo - 6, 145), (xo - 6, 172)], minor=True, arrows=(0, 1, 2, 3),
           label=line_tag("303"), seg=1, side=-1, at=0.6, h=1.9)
    a_opfv = L.valve(s, (58, 118), "v", "globe", act="M", act_side=-1, tag="TV-203 OPFV", tag_side=1, fail="FC")
    L.signal(s, [(78, 234), (78, 106), (a_opfv[0], 106), (a_opfv[0], a_opfv[1] - 2.6)])
    # jacket circuits A and B to the FPB
    L.pipe(s, [man_out, (410, man_out[1]), (410, 150), (xf - 7, 150), (xf - 7, 172)], arrows=(0, 2),
           label=line_tag("304"), seg=0, side=1, at=0.42)
    L.pipe(s, [man_exit, (410, man_exit[1]), (410, 150)], minor=True, arrows=(0, 1), label=line_tag("305"), seg=0, side=-1, at=0.55, h=1.9)
    L.tee(s, (410, 150))
    L.orifice(s, (410, 125), "v", "FO-301", tag_side=1)
    L.instrument(s, (378, 222), "TT-306", conn=(378, man_out[1]))
    L.instrument(s, (396, 222), "PT-306", conn=(396, man_out[1]))
    # GCH4 pressurant
    L.tee(s, (362, man_out[1]))
    L.pipe(s, [(362, man_out[1]), (362, top)], minor=True, arrows=(0,), label=line_tag("307"), side=1, at=0.86, h=1.9)
    L.valve(s, (362, 316), "v", "ball", act="S", act_side=-1, tag="XV-304", tag_side=1)
    L.orifice(s, (362, 336), "v", "FO-304", tag_side=1)
    L.connector(s, (362, top), "TO CH4 TANK PRESSURISATION", "up")
    # FPB, turbine and fuel-rich gas
    L.vessel(s, (xf, 192), 24, 40, "B-301", "FPB")
    s.text(f"{D['cycle']['p_fpb_Pa'] / 1e5:.0f} bar", (xf, 184), 2.0, "TOP_CENTER")
    s.text(f"{D['config']['cycle']['T_fpb_K']:.0f} K", (xf, 180), 2.0, "TOP_CENTER")
    L.instrument(s, (xf + 30, 198), "PT-303", conn=(xf + 12, 198))
    L.pipe(s, [(xf, 212), (xf, 242.5)], arrows=(0,))
    L.instrument(s, (xf + 30, 228), "TT-303", conn=(xf, 228))
    L.turbine(s, (xf, 248), tag="T-301", desc="FUEL TURBINE", tag_pos="right")
    L.shaft(s, (xf, 253.5), (xf, 333))
    L.instrument(s, (xf + 30, 296), "ST-304", conn=(xf, 296))
    L.instrument(s, (xf + 30, 324 if HYDRO else 316), "VT-305", conn=(xf, 324 if HYDRO else 316))
    L.pipe(s, [(xf, 253.5), (xf, 258), (xc + 35, 258)], arrows=(1,), label=line_tag("306"), seg=1, side=1, at=0.62)
    s.circle((xf + 30, 172), 4.0, "SYMBOL")
    s.text("IG", (xf + 30, 172), 2.4, "MIDDLE_CENTER")
    s.line((xf + 26, 172), (xf + 12, 172), "SYMBOL")
    s.text("IG-301", (xf + 25.5, 173.5), 2.2, "BOTTOM_RIGHT")
    if LASER:
        s.text("LASER", (xf + 25.5, 170.5), 1.9, "TOP_RIGHT")
        L.instrument(s, (xf + 55, 172), "XC-306", kind="computer", r=5.5)
        L.signal(s, [(xf + 49.5, 172), (xf + 34, 172)])
    else:
        s.text("EX-301", (xf + 25.5, 170.5), 1.9, "TOP_RIGHT")
        L.pipe(s, [(570, 176), (xf + 33.5, 176)], minor=True, arrows=(0,))
        L.pipe(s, [(570, 168), (xf + 33.5, 168)], minor=True, arrows=(0,))
        L.valve(s, (530, 176), "h", "ball", act="S", act_side=1, tag="XV-306", tag_side=1)
        L.valve(s, (556, 168), "h", "ball", act="S", act_side=-1, tag="XV-307", tag_side=-1)
        L.connector(s, (578, 176), "GOX", "left", w=8)
        L.connector(s, (578, 168), "GCH4", "left", w=8, side=-1)
    if HYDRO:
        # CH4 hydrostatic bearings BRG-301 on the P-301 / T-301 shaft: supply 309 from the P-301
        # discharge (line 302 upstream of the MFV) through FO-309, drain 310 to the P-301 suction
        yb_ = 312.0
        s.rect(xf - 5, yb_ - 3, 10, 6, "SYMBOL")
        s.line((xf - 5, yb_ - 3), (xf + 5, yb_ + 3), "SYMBOL_THIN")
        s.line((xf - 5, yb_ + 3), (xf + 5, yb_ - 3), "SYMBOL_THIN")
        s.text("BRG-301", (xf + 7, yb_ + 1.2), 2.2, "BOTTOM_LEFT")
        L.tee(s, (430, yb_))
        L.pipe(s, [(430, yb_), (xf - 5, yb_)], minor=True, arrows=(0,), label=line_tag("309"), side=-1, at=0.22, h=1.8)
        L.orifice(s, (458, yb_), "h", "FO-309", tag_side=1)
        L.instrument(s, (440, 322), "PT-309", conn=(440, yb_))
        L.pipe(s, [(xf + 5, yb_), (527, yb_), (527, 352), (xf, 352)], minor=True, arrows=(0, 1, 2), label=line_tag("310"),
               seg=1, side=1, at=0.5, h=1.8)
        L.tee(s, (xf, 352))
    # FPB temperature loop TIC-303 -> TV-303 (FPOV)
    L.instrument(s, (545, 240), "TIC-303", kind="computer", r=6.0)
    L.signal(s, [(xf + 35, 229.5), (539.5, 238)])
    L.signal(s, [(545, 234), (545, 128), (a_fpov[0] - 2.6, 128)])

    # ---------------------------------------------------------------- thrust control and interlock
    L.instrument(s, (xc - 50, 300), "PIC-101", kind="computer", r=6.0)
    L.signal(s, [(xc - 50, 227), (xc - 50, 294)])
    L.signal(s, [(xc - 56, 300), (a_mov[0] + 2.6, 300)])
    L.signal(s, [(xc - 44, 300), (a_mfv[0] - 2.6, 300)])
    L.instrument(s, (xc - 42, 340), "UZ-100", kind="logic", r=5.0)
    s.text("SHUTDOWN INTERLOCK IN ECU-100", (xc - 33, 343), 2.0, "BOTTOM_LEFT")
    s.text("IN: ST-204, VT-205, ST-304, VT-305, PT-202, PT-302" + (", PT-309" if HYDRO else ""), (xc - 33, 339), 1.9,
           "TOP_LEFT")
    s.text("OUT: CLOSE ALL FC VALVES", (xc - 33, 335), 1.9, "TOP_LEFT")

    # ---------------------------------------------------------------- GHe purge
    L.pipe(s, [(40, 84), (95, 84), (95, 207), (xo - 12, 207)], minor=True, arrows=(0, 1), label=line_tag("401"), seg=0,
           side=-1, at=0.78, h=1.8)
    L.connector(s, (32, 84), "GHE", "right", w=8, side=1)
    L.valve(s, (48, 84), "h", "ball", act="S", act_side=1, tag="XV-401", tag_side=1)
    L.valve(s, (62, 84), "h", "globe", act="D", act_side=1)
    s.text("PCV-401", (62, 96.5), 2.2, "BOTTOM_CENTER")
    L.valve(s, (95, 196), "v", "check", tag="NRV-402", tag_side=-1)
    L.tee(s, (95, 84))
    L.pipe(s, [(95, 84), (245, 84), (245, 249), (xc - 35, 249)], minor=True, arrows=(0, 1, 2), label=line_tag("402"), seg=0,
           side=-1, at=0.55, h=1.8)
    L.valve(s, (245, 200), "v", "check", tag="NRV-404", tag_side=-1)
    L.tee(s, (245, 84))
    L.pipe(s, [(245, 84), (572, 84), (572, 207), (xf + 12, 207)], minor=True, arrows=(0, 1, 2))
    L.valve(s, (572, 196), "v", "check", tag="NRV-403", tag_side=-1)
    L.instrument(s, (90, 101), "PT-401", conn=(90, 84))
    L.tee(s, (115, 84))
    L.pipe(s, [(115, 84), (115, 93)], minor=True)
    L.relief(s, (115, 96), tag="PSV-402")

    # ---------------------------------------------------------------- notes
    notes = [
        "SYMBOLS, IDENTIFICATION LETTERS, FLUID CODES AND PIPING CLASSES: SEE MFE280-PID-000.",
        "LINE DESIGNATION: INSIDE DIAMETER mm - FLUID - LINE No. - CLASS. LINE DATA: MFE280-PID-002.",
        "ALL TRANSMITTERS REPORT TO ECU-100. SIGNAL LINES ARE SHOWN FOR THE CONTROL LOOPS ONLY.",
        "VALVES FAIL CLOSED (FC) ON LOSS OF POWER OR ON A UZ-100 TRIP.",
        "FULL-FLOW CYCLE: NO INTER-PROPELLANT SEAL OR SEAL PURGE ON THE TURBOPUMPS.",
        "THE MAIN CHAMBER HAS NO IGNITER: ORG AND FRG IGNITE ON CONTACT AT THE INJECTOR.",
        "VEHICLE-SIDE ITEMS (PV-V01, PV-V02, GHE AND TORCH SUPPLIES) ARE OUTSIDE THE ENGINE SCOPE.",
    ]
    if LASER:
        notes[2] = "ALL TRANSMITTERS REPORT TO ECU-100. SIGNAL LINES ARE SHOWN FOR THE CONTROL LOOPS AND THE IGNITERS ONLY."
        notes[6] = "VEHICLE-SIDE ITEMS (PV-V01, PV-V02, GHE SUPPLY) ARE OUTSIDE THE ENGINE SCOPE."
        notes.append("PREBURNER IGNITION: LASER IGNITERS IG-201, IG-301 FIRED BY XC-206, XC-306 IN ECU-100 (ELECTRIC "
                     "SIGNAL). NO TORCH PROPELLANT LINES OR VALVES (OPTION N2).")
    if HYDRO:
        notes.append("CH4 TURBOPUMP ON HYDROSTATIC BEARINGS BRG-301 (OPTION C2): SUPPLY LINE 309 FROM THE P-301 "
                     "DISCHARGE THROUGH FO-309, DRAIN LINE 310 TO THE P-301 SUCTION. PT-309 LOW TRIPS UZ-100.")
    if WELDED_LINES:
        notes.append("WELDED JOINTS, NO FLANGED BREAKS (OPTIONS I1, I3): DUCT JOINTS OF LINES " + ", ".join(WELDED_LINES)
                     + " ARE BUTT WELDS (MFE280-JNT-006); THE VEHICLE INTERFACES (LINES 201, 301) STAY FLANGED.")
    s.notes(25, 72, notes, h=2.2, gap=1.4)
    s.boxed_note(25, 15, 200 if IT.IS_I1 else 230, f"{IT.LABEL}. VALUES AT THE DESIGN POINT FROM {IT.RES_TXT}DESIGN.JSON.")
    return s
