"""Single tag database for the P&ID set: equipment, lines, valves, instruments.

Every P&ID sheet and every register (line list, valve list, instrument index) is
generated from these records, so tags and data cannot drift apart. Numbers come from
results/design.json. Loop numbering: 1xx chamber and thrust control, 2xx oxidiser side,
3xx fuel side, 4xx purge. Line designation: <ID mm>-<fluid code>-<line no.>-<piping class>.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = json.load(open(ROOT / "results" / "design.json", encoding="utf-8"))
CY, DU, CO = D["cycle"], D["ducts"], D["cooling"]
P = D["performance"]
bar = lambda pa: pa / 1e5
idm = lambda key: round(DU[key] * 1000)
PROOF = 1.2

FLUIDS = {
    "LOX": "liquid oxygen (subcooled)",
    "LCH4": "liquid methane (subcooled)",
    "SCH4": "supercritical methane (regen jacket and return)",
    "ORG": "oxidiser-rich turbine gas (OPB products)",
    "FRG": "fuel-rich turbine gas (FPB products)",
    "GOX": "gaseous oxygen pressurant / torch supply",
    "GCH4": "gaseous methane pressurant / torch supply",
    "GHE": "gaseous helium purge",
}

CLASSES = [
    # code, service, material, design pressure (bar), design temperature, notes
    ("L1", "cryogenic suction", "304L", 12, "-196 / +50 C", "PN 16 flanges, vacuum-jacket not required (engine bay)"),
    ("O1", "LOX high pressure", "Inconel 718", round(PROOF * bar(CY["p_ox_discharge_Pa"] + CY["p_kick_rise_Pa"]), -1), "-196 / +50 C",
     "oxygen-cleaned to ASTM G93 level A, metallic C-seals"),
    ("F1", "LCH4 high pressure", "Inconel 718", round(PROOF * bar(CY["p_fuel_discharge_Pa"]), -1), "-196 / +100 C", "metallic C-seals"),
    ("F2", "SCH4 jacket return", "Inconel 718", round(PROOF * bar(CO["p_out_Pa"]), -1), "-196 / +150 C", "orifice FO-301 balances circuits A/B"),
    ("G1", "ox-rich hot gas", "SX500 / Inconel 718", round(PROOF * bar(CY["p_turbine_exit_Pa"]), -1), "+600 C", "oxygen-compatible, no elastomers"),
    ("G2", "fuel-rich hot gas", "Inconel 718", round(PROOF * bar(CY["p_turbine_exit_Pa"]), -1), "+800 C", ""),
    ("P1", "pressurant and torch supply", "316L", 60, "-196 / +450 C", "downstream of restriction orifices"),
    ("H1", "GHe purge", "316L", 60, "-60 / +80 C", "relief PSV-402 set 50 bar"),
]
CLASS_P = {c[0]: c[3] for c in CLASSES}

EQUIPMENT = [
    ("P-201", "LOX main pump", f"1 stage + inducer, {CY['ox_pump']['mdot']:.0f} kg/s, {bar(CY['ox_pump']['p_out']):.0f} bar, "
     f"{CY['ox_pump']['N_rpm']:.0f} rpm, {CY['ox_pump']['power_W'] / 1e6:.1f} MW"),
    ("P-202", "LOX kick stage", f"on P-201 shaft, {CY['mdot_ox_to_fpb']:.1f} kg/s, +{bar(CY['p_kick_rise_Pa']):.0f} bar"),
    ("T-201", "oxidiser turbine", f"1 stage reaction, PR {CY['ox_turbine']['PR']:.2f}, eta {CY['ox_turbine']['eta']:.2f}, "
     f"{CY['ox_turbine']['power_W'] / 1e6:.1f} MW"),
    ("B-201", "oxidiser-rich preburner", f"{bar(CY['p_opb_Pa']):.0f} bar, {D['config']['cycle']['T_opb_K']:.0f} K, O/F {CY['mr_opb']:.0f}"),
    ("P-301", "CH4 main pump", f"2 stages + inducer, {CY['fuel_pump']['mdot']:.0f} kg/s, {bar(CY['fuel_pump']['p_out']):.0f} bar, "
     f"{CY['fuel_pump']['N_rpm']:.0f} rpm, {CY['fuel_pump']['power_W'] / 1e6:.1f} MW"),
    ("T-301", "fuel turbine", f"1 stage reaction, PR {CY['fuel_turbine']['PR']:.2f}, eta {CY['fuel_turbine']['eta']:.2f}, "
     f"{CY['fuel_turbine']['power_W'] / 1e6:.1f} MW"),
    ("B-301", "fuel-rich preburner", f"{bar(CY['p_fpb_Pa']):.0f} bar, {D['config']['cycle']['T_fpb_K']:.0f} K, O/F {CY['mr_fpb']:.2f}"),
    ("TC-101", "main combustion chamber and nozzle", f"pc {bar(P['pc']):.0f} bar, Dt {2000 * D['geometry']['Rt_m']:.0f} mm, "
     f"eps {D['config']['nozzle']['expansion_ratio']:.0f}, F_SL {P['thrust_sl_N'] / 1e6:.2f} MN"),
    ("HX-101", "regenerative jacket, circuits A and B", f"{CO['Q_total_W'] / 1e6:.1f} MW, dP {bar(CO['dp_jacket_Pa']):.0f} bar, "
     f"split {1 - D['config']['cooling']['nozzle_circuit_fraction']:.0%} / {D['config']['cooling']['nozzle_circuit_fraction']:.0%}"),
    ("HX-201", "GOX pressurant heat exchanger", "coil in the ORG duct, LOX tap to GOX"),
    ("IG-201", "OPB spark-torch igniter", "GOX / GCH4 torch, spark exciter EX-201"),
    ("IG-301", "FPB spark-torch igniter", "GOX / GCH4 torch, spark exciter EX-301"),
    ("ECU-100", "engine control unit", "computer functions PIC-101, TIC-203, TIC-303, interlock UZ-100"),
]

# line no.: (fluid, ID mm, class, from, to, operating p bar, operating T K, flow kg/s)
LINES = {
    "201": ("LOX", idm("lox_inlet"), "L1", "vehicle LOX feed (PV-V01)", "P-201 suction", bar(CY["ox_pump"]["p_in"]), 70, P["mdot_ox"]),
    "202": ("LOX", idm("lox_discharge"), "O1", "P-201 discharge", "B-201 injector via PV-101A", bar(CY["p_ox_discharge_Pa"]),
            CY["ox_pump"]["T_out_K"], P["mdot_ox"] - CY["mdot_ox_to_fpb"]),
    "203": ("LOX", idm("ox_crossfeed"), "O1", "P-202 discharge", "B-301 injector via TV-303", bar(CY["p_ox_discharge_Pa"] + CY["p_kick_rise_Pa"]),
            CY["ox_pump"]["T_out_K"], CY["mdot_ox_to_fpb"]),
    "204": ("LOX", 10, "O1", "line 202 tap", "HX-201 via XV-204, FO-204", bar(CY["p_ox_discharge_Pa"]), 90, 1.0),
    "205": ("ORG", idm("ox_hot_gas"), "G1", "T-201 exhaust", "main injector ox dome", bar(CY["p_turbine_exit_Pa"]),
            CY["ox_turbine"]["T_out"], CY["mdot_opb"]),
    "206": ("GOX", 25, "P1", "HX-201 outlet", "vehicle LOX tank pressurisation", 8.0, 450, 1.0),
    "207": ("LOX", 40, "O1", "line 202 tap", "chill-down bleed via XV-210", bar(CY["p_ox_discharge_Pa"]), 90, 0.0),
    "301": ("LCH4", idm("ch4_inlet"), "L1", "vehicle CH4 feed (PV-V02)", "P-301 suction", bar(CY["fuel_pump"]["p_in"]), 95, P["mdot_fuel"]),
    "302": ("LCH4", idm("ch4_discharge"), "F1", "P-301 discharge", "HX-101 inlet manifold via PV-101B", bar(CY["p_fuel_discharge_Pa"]),
            CY["fuel_pump"]["T_out_K"], P["mdot_fuel"] - CY["mdot_fuel_to_opb"]),
    "303": ("LCH4", idm("fuel_crossfeed"), "F1", "line 302 tap", "B-201 injector via TV-203", bar(CY["p_fuel_discharge_Pa"]),
            CY["fuel_pump"]["T_out_K"], CY["mdot_fuel_to_opb"]),
    "304": ("SCH4", idm("fpb_feed"), "F2", "HX-101 circuit A outlet", "B-301 injector", bar(CO["p_out_A_Pa"]), CO["T_out_A_K"],
            (1 - D["config"]["cooling"]["nozzle_circuit_fraction"]) * (P["mdot_fuel"] - CY["mdot_fuel_to_opb"])),
    "305": ("SCH4", idm("nozzle_return"), "F2", "HX-101 circuit B outlet", "B-301 injector via FO-301", bar(CO["p_out_B_Pa"]), CO["T_out_B_K"],
            D["config"]["cooling"]["nozzle_circuit_fraction"] * (P["mdot_fuel"] - CY["mdot_fuel_to_opb"])),
    "306": ("FRG", idm("fuel_hot_gas"), "G2", "T-301 exhaust", "main injector fuel plenum", bar(CY["p_turbine_exit_Pa"]),
            CY["fuel_turbine"]["T_out"], CY["mdot_fpb"]),
    "307": ("GCH4", 25, "P1", "line 304 tap", "vehicle CH4 tank pressurisation via XV-304, FO-304", 6.0, CO["T_out_A_K"], 0.5),
    "308": ("LCH4", 40, "F1", "line 302 tap", "chill-down bleed via XV-310", bar(CY["p_fuel_discharge_Pa"]), 128, 0.0),
    "401": ("GHE", 15, "H1", "vehicle GHe supply", "purge header via XV-401, PCV-401", 40.0, 290, 0.2),
    "402": ("GHE", 10, "H1", "purge header", "B-201, B-301, main injector via NRV-402..404", 30.0, 290, 0.1),
    "403": ("GOX", 8, "P1", "vehicle torch supply", "IG-201, IG-301 via XV-206, XV-306", 30.0, 290, 0.05),
    "404": ("GCH4", 8, "P1", "vehicle torch supply", "IG-201, IG-301 via XV-207, XV-307", 30.0, 290, 0.02),
}


def line_tag(no):
    f, d, c = LINES[no][0], LINES[no][1], LINES[no][2]
    return f"{d}-{f}-{no}-{c}"


VALVES = [
    # tag, alias, body, actuator, line, fail position, function
    ("PV-101A", "MOV", "ball, throttling", "electromechanical", "202", "FC", "main oxidiser valve; thrust (pc) control"),
    ("PV-101B", "MFV", "ball, throttling", "electromechanical", "302", "FC", "main fuel valve; thrust (pc) control"),
    ("TV-203", "OPFV", "globe, throttling", "electromechanical", "303", "FC", "OPB fuel valve; OPB temperature control"),
    ("TV-303", "FPOV", "globe, throttling", "electromechanical", "203", "FC", "FPB oxidiser valve; FPB temperature control"),
    ("XV-204", "", "ball, on/off", "solenoid", "204", "FC", "GOX pressurant enable"),
    ("XV-304", "", "ball, on/off", "solenoid", "307", "FC", "GCH4 pressurant enable"),
    ("XV-210", "", "ball, on/off", "solenoid", "207", "FC", "LOX chill-down bleed"),
    ("XV-310", "", "ball, on/off", "solenoid", "308", "FC", "CH4 chill-down bleed"),
    ("XV-401", "", "ball, on/off", "solenoid", "401", "FC", "GHe purge supply"),
    ("PCV-401", "", "regulator, self-acting", "spring / diaphragm", "401", "-", "purge pressure 30 bar"),
    ("PSV-402", "", "relief, spring", "spring", "402", "-", "purge header relief, set 50 bar"),
    ("NRV-402", "", "check", "-", "402", "-", "purge into B-201"),
    ("NRV-403", "", "check", "-", "402", "-", "purge into B-301"),
    ("NRV-404", "", "check", "-", "402", "-", "purge into main injector"),
    ("XV-206", "", "poppet, on/off", "solenoid", "403", "FC", "IG-201 torch GOX"),
    ("XV-207", "", "poppet, on/off", "solenoid", "404", "FC", "IG-201 torch GCH4"),
    ("XV-306", "", "poppet, on/off", "solenoid", "403", "FC", "IG-301 torch GOX"),
    ("XV-307", "", "poppet, on/off", "solenoid", "404", "FC", "IG-301 torch GCH4"),
    ("FO-204", "", "restriction orifice", "-", "204", "-", "limits GOX pressurant flow"),
    ("FO-301", "", "restriction orifice", "-", "305", "-", "balances circuit B to circuit A outlet pressure"),
    ("FO-304", "", "restriction orifice", "-", "307", "-", "limits GCH4 pressurant flow"),
    ("PV-V01", "LOX prevalve", "ball, on/off", "pneumatic", "201", "FC", "vehicle side (not engine scope)"),
    ("PV-V02", "CH4 prevalve", "ball, on/off", "pneumatic", "301", "FC", "vehicle side (not engine scope)"),
]

INSTRUMENTS = [
    # tag, service, type, range, normal value, signal / destination
    ("PT-101", "main chamber pressure", "strain-gauge transmitter", "0-500 bar", f"{bar(P['pc']):.0f} bar", "ECU-100 / PIC-101"),
    ("PIC-101", "thrust (pc) control", "ECU computer function", "-", f"{bar(P['pc']):.0f} bar SP", "PV-101A, PV-101B"),
    ("ZT-101A", "MOV position", "resolver", "0-100 %", "100 %", "ECU-100"),
    ("ZT-101B", "MFV position", "resolver", "0-100 %", "100 %", "ECU-100"),
    ("PT-201", "LOX pump inlet pressure", "transmitter", "0-20 bar", f"{bar(CY['ox_pump']['p_in']):.0f} bar", "ECU-100"),
    ("TT-201", "LOX pump inlet temperature", "PRT", "60-120 K", "70 K", "ECU-100"),
    ("PT-202", "LOX pump discharge pressure", "transmitter", "0-1000 bar", f"{bar(CY['p_ox_discharge_Pa']):.0f} bar", "ECU-100"),
    ("PT-203", "OPB pressure", "transmitter", "0-1000 bar", f"{bar(CY['p_opb_Pa']):.0f} bar", "ECU-100"),
    ("TT-203", "OPB exit / ox turbine inlet temperature", "thermocouple type K", "0-1200 K", f"{D['config']['cycle']['T_opb_K']:.0f} K", "TIC-203"),
    ("TIC-203", "OPB temperature control", "ECU computer function", "-", f"{D['config']['cycle']['T_opb_K']:.0f} K SP", "TV-203"),
    ("ZT-203", "OPFV position", "resolver", "0-100 %", "-", "ECU-100"),
    ("ST-204", "LOX turbopump speed", "magnetic pick-up", "0-25 krpm", f"{CY['ox_pump']['N_rpm']:.0f} rpm", "ECU-100 / UZ-100"),
    ("VT-205", "LOX turbopump vibration", "accelerometer", "0-200 g", "-", "ECU-100 / UZ-100"),
    ("PT-301", "CH4 pump inlet pressure", "transmitter", "0-20 bar", f"{bar(CY['fuel_pump']['p_in']):.0f} bar", "ECU-100"),
    ("TT-301", "CH4 pump inlet temperature", "PRT", "80-140 K", "95 K", "ECU-100"),
    ("PT-302", "CH4 pump discharge pressure", "transmitter", "0-1200 bar", f"{bar(CY['p_fuel_discharge_Pa']):.0f} bar", "ECU-100"),
    ("PT-303", "FPB pressure", "transmitter", "0-1000 bar", f"{bar(CY['p_fpb_Pa']):.0f} bar", "ECU-100"),
    ("TT-303", "FPB exit / fuel turbine inlet temperature", "thermocouple type K", "0-1400 K", f"{D['config']['cycle']['T_fpb_K']:.0f} K", "TIC-303"),
    ("TIC-303", "FPB temperature control", "ECU computer function", "-", f"{D['config']['cycle']['T_fpb_K']:.0f} K SP", "TV-303"),
    ("ZT-303", "FPOV position", "resolver", "0-100 %", "-", "ECU-100"),
    ("ST-304", "CH4 turbopump speed", "magnetic pick-up", "0-50 krpm", f"{CY['fuel_pump']['N_rpm']:.0f} rpm", "ECU-100 / UZ-100"),
    ("VT-305", "CH4 turbopump vibration", "accelerometer", "0-200 g", "-", "ECU-100 / UZ-100"),
    ("PT-306", "jacket circuit A outlet pressure", "transmitter", "0-1200 bar", f"{bar(CO['p_out_A_Pa']):.0f} bar", "ECU-100"),
    ("TT-306", "jacket circuit A outlet temperature", "thermocouple type T", "50-600 K", f"{CO['T_out_A_K']:.0f} K", "ECU-100"),
    ("PT-401", "purge header pressure", "transmitter", "0-60 bar", "30 bar", "ECU-100"),
    ("UZ-100", "engine shutdown interlock", "ECU logic", "-", "-", "all fail-closed valves"),
]
