"""Build the MFE-280 engine assembly in FreeCAD from results/design.json.

Run headless:   "C:\\Program Files\\FreeCAD 1.1\\bin\\freecadcmd.exe" cad\\build_engine.py
Run with GUI (colours, TechDraw):  set FFSC_GUI=1 and run freecad.exe on this file.

Units: FreeCAD mm. design.json is SI. Global frame: z up, origin at the injector face
centre, chamber axis along -z. LOX turbopump at +x, CH4 turbopump at -x (rotated 180 deg).
Outputs (cad/output): MFE280.FCStd, MFE280_assembly.step, one STEP per sub-assembly,
bom.csv, mass_summary.json, clash_report.json, layout.json.
"""

import csv
import json
import math
import os
import sys
import time

import FreeCAD as App
import Part
from FreeCAD import Vector as V

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() \
    else os.path.join(os.environ.get("FFSC_ROOT", r"D:\Research\projects\methalox-ffsc-engine"), "cad")
sys.path.insert(0, HERE)
import cadlib as cl  # noqa: E402

ROOT = os.path.dirname(HERE)
RES = os.environ.get("FFSC_RESULTS", os.path.join(ROOT, "results"))
OUT = os.environ.get("FFSC_CAD_OUT", os.path.join(HERE, "output"))
os.makedirs(OUT, exist_ok=True)
T0 = time.time()

D = json.load(open(os.path.join(RES, "design.json"), encoding="utf-8"))
J = {j["name"]: j for j in D["joints"]}
JI = {j["name"]: j for j in D["internal_joints"]}
CY = D["cycle"]
# iteration-2 CAD switches (config "cad"); empty for iteration 1
CADF = D["config"].get("cad", {}) or {}
WELDED = set(CADF.get("welded_joints", []))           # I1, I3: butt welds instead of flange pairs
INTEGRAL = bool(CADF.get("integral_manifolds"))       # I2: D-section manifolds printed onto the jacket
ONEPIECE = bool(CADF.get("single_piece_injector"))    # I4: injector printed in one piece
IGNITION = CADF.get("ignition", "torch")              # N2: "laser" replaces the spark-torch igniters
BEARINGS = CADF.get("bearings", {}) or {}             # C1 / C2 per side: "hybrid_Si3N4" or "hydrostatic"
PROF = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(open(os.path.join(RES, "cooling_profile.csv")))]
CONT = [(float(r["x_m"]), float(r["r_m"])) for r in csv.DictReader(open(os.path.join(RES, "contour.csv")))]
mm = lambda m: 1000.0 * m

DENSITY = {"M50/Si3N4 hybrid": 7200, "GRCop-42": 8790, "Inconel 718": 8190, "SX500": 8100, "MAR-M-247": 8540, "Ti-6Al-4V": 4430,
           "A286": 7940, "304L": 7900, "PTFE/Inconel seal": 8000}
COLOR = {"M50/Si3N4 hybrid": (0.30, 0.30, 0.36), "GRCop-42": (0.78, 0.42, 0.22), "Inconel 718": (0.63, 0.63, 0.66), "SX500": (0.52, 0.56, 0.62),
         "MAR-M-247": (0.45, 0.43, 0.40), "Ti-6Al-4V": (0.72, 0.74, 0.78), "A286": (0.30, 0.30, 0.33),
         "304L": (0.80, 0.80, 0.83), "PTFE/Inconel seal": (0.9, 0.85, 0.3)}

doc = App.newDocument("MFE280")
BOM = []
SOLIDS = []          # (assembly, name, shape) for the clash check


def asm(name, parent=None, base=V(0, 0, 0), rot_deg=0.0):
    a = doc.addObject("App::Part", name)
    a.Placement = App.Placement(base, App.Rotation(V(0, 0, 1), rot_deg))
    if parent is not None:
        parent.addObject(a)
    return a


def add(group, name, shape, material, qty=1, note="", mass_kg=None, clash=True):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    obj.addProperty("App::PropertyString", "Material", "Engineering").Material = material
    obj.addProperty("App::PropertyInteger", "Quantity", "Engineering").Quantity = qty
    obj.addProperty("App::PropertyString", "Note", "Engineering").Note = note
    group.addObject(obj)
    if App.GuiUp:
        obj.ViewObject.ShapeColor = COLOR.get(material, (0.6, 0.6, 0.6))
    vol = shape.Volume * 1e-9
    m = mass_kg if mass_kg is not None else vol * DENSITY.get(material, 8000)
    BOM.append({"assembly": group.Name, "part": name, "material": material, "qty": qty,
                "volume_cm3": round(vol * 1e6, 1), "mass_kg": round(m, 2), "note": note})
    if clash:
        SOLIDS.append((group, name, obj))
    return obj


def add_joint(group, tag, joint, d_pipe, P, d, note=""):
    """Flanged pair centred on mating plane P with normal d (global or group-local)."""
    fp = cl.flanged_pair(joint, d_pipe)
    spec = f"{joint['n_bolts']}x {joint['bolt']} {joint['grade']}"
    add(group, f"{tag}_flanges", cl.placed(fp["flanges"], P, d), "Inconel 718", 2, f"{joint['name']} flange pair")
    add(group, f"{tag}_seal", cl.placed(fp["seal"], P, d), "PTFE/Inconel seal", 1, "metallic C-seal", clash=False)
    add(group, f"{tag}_bolts", cl.placed(fp["bolts"], P, d), joint["grade"], joint["n_bolts"], spec)
    add(group, f"{tag}_nuts_washers", cl.placed(fp["hardware"], P, d), joint["grade"], 3 * joint["n_bolts"],
        f"{joint['n_bolts']} nuts + {2 * joint['n_bolts']} washers")


def weld_bead(r_od, P, d, h=6.0):
    """Butt-weld cap: a shallow ring proud of the pipe OD, centred on the weld plane."""
    return cl.placed(cl.tube(r_od - 1.0, r_od + 2.5, h, -h / 2), P, d)


def valve_body(d_pipe, length):
    r = d_pipe / 2
    body = cl.cyl(r + 22, length, -length / 2).fuse(Part.makeSphere(r + 38))
    stem = cl.cyl(18, 90).rotate(V(0, 0, 0), V(0, 1, 0), 90).translate(V(r + 20, 0, 0))
    act = Part.makeBox(110, 90, 140, V(r + 105, -45, -70))
    return body.fuse(stem).fuse(act).cut(cl.cyl(r, length + 2, -length / 2 - 1)).removeSplitter()


def instrument(tag_len=45):
    return cl.cyl(10, tag_len).fuse(cl.hexagon(22, 12, 8))


# ======================================================================== numbers
G = D["geometry"]
Rt, Rc = mm(G["Rt_m"]), mm(G["Rc_m"])
x_j, x_e = mm(G["x_joint_m"]), mm(G["x_exit_m"])
INJ = D["injector"]
R_ib = Rc + 32.0                      # injector body outer radius
ZONE_T = {0: None, 1: None}

# outer jacket radius along the contour: liner + channel + closeout, conservative envelope
px = [mm(r["x"]) for r in PROF]
pro = [mm(r["r"] + r["t_hot"] + r["H"] + r["t_closeout"]) for r in PROF]
env = [max(pro[max(0, i - 6):i + 7]) for i in range(len(pro))]
# I2: integral manifolds are centred on the jacket surface, so their inner half must be cut away by
# everything inside the jacket (wall and gas bore), not only by the wall solid.
TCA_ENV = cl.revolve_rz([(0.0, 5.0), (env[0], 5.0)] + [(r, -x) for x, r in zip(px, env)] + [(0.0, -px[-1])]) if INTEGRAL else None


def integral_cut(shape):
    return shape.cut(TCA_ENV) if INTEGRAL else shape


def r_outer(x):
    return float(App.Base.Vector(0, 0, 0).x + __interp(x, px, env))


def __interp(x, xs, ys):
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def r_inner(x):
    return __interp(x, [mm(a) for a, _ in CONT], [mm(b) for _, b in CONT])


# ======================================================================== engine tree
ENGINE = asm("MFE280_Engine")
TCA = asm("Thrust_Chamber", ENGINE)
INJH = asm("Injector_Head", ENGINE)
GIM = asm("Gimbal", ENGINE)
PLUMB = asm("Plumbing", ENGINE)
INSTR = asm("Instrumentation", ENGINE)

# ---------------------------------------------------------------- thrust chamber
jic = J["injector_chamber"]
t_icf = mm(jic["flange_t_m"])
jn = J["nozzle_joint"]
t_nf = mm(jn["flange_t_m"])


def body_between(x0, x1, step=3):
    """Wall solid between x0 and x1: the gas side follows every contour.csv point (so the
    throat stays at the design station), the outer side the profile envelope."""
    xi = sorted(set([x0] + [mm(a) for a, _ in CONT if x0 < mm(a) < x1] + [x1]))
    xs = [x for x in px if x0 <= x <= x1]
    xo = sorted(set([x0] + xs[::step] + [x1]))
    inner = [(r_inner(x), -x) for x in xi]
    outer = [(r_outer(x), -x) for x in xo]
    return cl.revolve_splines(inner, outer)


def liner_mass(x0, x1, zone_filter):
    """Analytic mass of liner+ribs (zone material) and closeout (Inconel) from the profile."""
    m_liner = m_close = 0.0
    for a, b in zip(PROF[:-1], PROF[1:]):
        xa = a["x"]
        if not (x0 <= mm(xa) <= x1) or int(a["zone"]) not in zone_filter:
            continue
        dx = math.hypot(b["x"] - a["x"], b["r"] - a["r"])
        mat = "GRCop-42" if int(a["zone"]) == 0 else "Inconel 718"
        r = a["r"]
        a_liner = 2 * math.pi * (r + a["t_hot"] / 2) * a["t_hot"] + a["N"] * a["rib"] * a["H"]
        r_c = r + a["t_hot"] + a["H"]
        a_close = 2 * math.pi * (r_c + a["t_closeout"] / 2) * a["t_closeout"]
        m_liner += a_liner * dx * DENSITY[mat]
        m_close += a_close * dx * DENSITY["Inconel 718"]
    return m_liner, m_close


ch_body = body_between(0.0, x_j)
ch_top_flange = cl.flange_ring(Rc + 1, mm(jic["flange_od_m"]), t_icf, jic["n_bolts"], mm(jic["bcd_m"]), mm(jic["d_m"]), -t_icf)
r_jo = r_outer(x_j)
ch_joint_flange = cl.flange_ring(r_inner(x_j) + 1, mm(jn["flange_od_m"]), t_nf, jn["n_bolts"], mm(jn["bcd_m"]), mm(jn["d_m"]), -x_j)
chamber = ch_body.fuse([ch_top_flange, ch_joint_flange]).removeSplitter()
ml, mc = liner_mass(0, x_j, (0,))
add(TCA, "Chamber_GRCop42_regen", chamber, "GRCop-42", 1,
    f"L-PBF GRCop-42 liner + ribs ({ml:.0f} kg) with Inconel 718 closeout ({mc:.0f} kg); "
    f"channels modelled in PicoGK", mass_kg=ml + mc)

nz_body = body_between(x_j, x_e)
nz_flange = cl.flange_ring(r_inner(x_j) + 1, mm(jn["flange_od_m"]), t_nf, jn["n_bolts"], mm(jn["bcd_m"]), mm(jn["d_m"]), -x_j - t_nf)
nozzle = nz_body.fuse(nz_flange).removeSplitter()
ml2, mc2 = liner_mass(x_j, x_e, (1,))
add(TCA, "Nozzle_In718_regen", nozzle, "Inconel 718", 1,
    f"channel-wall nozzle eps {G['eps_joint']:.0f}-{D['config']['nozzle']['expansion_ratio']:.0f}, "
    f"liner+ribs {ml2:.0f} kg, closeout {mc2:.0f} kg", mass_kg=ml2 + mc2)

# nozzle joint bolts (through both flanges)
b, hw = cl.bolt_set(jn["n_bolts"], mm(jn["bcd_m"]), mm(jn["d_m"]), mm(jn["across_flats_m"]), 2 * t_nf, -x_j + t_nf)
add(TCA, "Nozzle_joint_bolts", b, jn["grade"], jn["n_bolts"], f"{jn['n_bolts']}x {jn['bolt']}")
add(TCA, "Nozzle_joint_nuts_washers", hw, jn["grade"], 3 * jn["n_bolts"])

# coolant manifolds
ducts = D["ducts"]
def man_wall(p_Pa, r_in):
    return max(1.2 * p_Pa * r_in / 520e6, 3.0)


p_jk_in = CY["jacket_in_p_Pa"]
p_jk_out = D["cooling"]["p_out_Pa"]
# I2 (integral): a semicircular passage centred on the jacket surface with the same flow area as
# the round tube, so the arc radius is sqrt(2) times larger and the hoop wall grows with it.
K_INT = math.sqrt(2.0) if INTEGRAL else 1.0
ri_om = K_INT * mm(ducts["jacket_outlet"]) / 2 / math.sqrt(2)       # flow arrives from both sides of the port
w_om = man_wall(p_jk_out, ri_om)
r_om = ri_om + w_om
z_om = -t_icf - (0.32 + 0.84) * mm(jic["d_m"]) - 8.0 - max(r_om, mm(ducts["fpb_feed"]) / 2)   # below washer, nut, protrusion
R_om = r_outer(-z_om) + (0.0 if INTEGRAL else r_om - 6)
man_out = cl.torus_tube(R_om, r_om, w_om).translate(V(0, 0, z_om))
d_fpb = mm(ducts["fpb_feed"])
a_om = math.radians(200.0)
u_om = V(math.cos(a_om), math.sin(a_om), 0)
L_os = r_om + 40.0 if INTEGRAL else 70.0
stub_out = cl.placed(cl.tube(d_fpb / 2 - w_om, d_fpb / 2, L_os), u_om * R_om + V(0, 0, z_om), u_om)
add(TCA, "Coolant_outlet_manifold", integral_cut(man_out.fuse(stub_out).cut(chamber)).removeSplitter(), "Inconel 718", 1,
    "collects chamber circuit A at the injector end" + ("; D-section printed onto the jacket (I2)" if INTEGRAL else ""))
P_om_port = u_om * (R_om + L_os + mm(J["fpb_feed"]["flange_t_m"])) + V(0, 0, z_om)

ri_jm = K_INT * mm(ducts["ch4_discharge"]) / 2 / math.sqrt(2)
w_jm = man_wall(p_jk_in, ri_jm)
r_jm = ri_jm + w_jm
z_jm_n = -x_j - t_nf - r_jm - 25
R_jm_n = r_outer(-z_jm_n) + (0.0 if INTEGRAL else r_jm - 8)
ri_jc = ri_jm * math.sqrt(1 - D["config"]["cooling"]["nozzle_circuit_fraction"]) / math.sqrt(2)  # fed by 4 jumpers
w_jc = man_wall(p_jk_in, ri_jc)
r_jm_c = ri_jc + w_jc
z_jm_c = -x_j + t_nf + r_jm_c + 25
R_jm_c = r_outer(-z_jm_c) + (0.0 if INTEGRAL else r_jm_c - 6)
man_in = cl.torus_tube(R_jm_n, r_jm, w_jm).translate(V(0, 0, z_jm_n))
a_in = math.radians(225)
d_cd = mm(ducts["ch4_discharge"])
L_pin = r_jm + 60.0 if INTEGRAL else 110.0
port_in = cl.tube(d_cd / 2 - w_jm, d_cd / 2, L_pin).rotate(V(0, 0, 0), V(0, 1, 0), 90).rotate(V(0, 0, 0), V(0, 0, 1), 225)
port_in = port_in.translate(V(R_jm_n * math.cos(a_in), R_jm_n * math.sin(a_in), z_jm_n))
add(TCA, "Coolant_inlet_manifold_nozzle", integral_cut(man_in.fuse(port_in).cut(nozzle)).removeSplitter(), "Inconel 718", 1,
    "split-flow inlet at the liner joint (eps 12); feeds circuit B down the nozzle and the jumpers")
R_port = R_jm_n + L_pin + mm(J["ch4_discharge"]["flange_t_m"])
P_jm_port = V(R_port * math.cos(a_in), R_port * math.sin(a_in), z_jm_n)
add(TCA, "Coolant_distribution_manifold_chamber", integral_cut(cl.torus_tube(R_jm_c, r_jm_c, w_jc).translate(V(0, 0, z_jm_c)).cut(chamber)),
    "Inconel 718", 1, "feeds circuit A up the copper chamber")
# four jumpers across the bolted joint, outside the bolt circle; trimmed to the manifold surfaces
jj = J["coolant_jumper"]
d_jump = 45.0
R_jump = mm(jn["flange_od_m"]) / 2 + 62
tori = [cl.torus(R_jm_n, r_jm).translate(V(0, 0, z_jm_n)), cl.torus(R_jm_c, r_jm_c).translate(V(0, 0, z_jm_c))]
for k, ang in enumerate([45, 135, 225 + 22, 315]):
    a = math.radians(ang)
    c, s = math.cos(a), math.sin(a)
    # start and end 3 mm inside the manifold tubes, then trim to their outer surfaces
    r0, r1 = R_jm_n + r_jm - 3.0, R_jm_c + r_jm_c - 3.0
    pts = [V(r0 * c, r0 * s, z_jm_n), V(R_jump * c, R_jump * s, z_jm_n), V(R_jump * c, R_jump * s, z_jm_c),
           V(r1 * c, r1 * s, z_jm_c)]
    jumper = cl.pipe(pts, d_jump, 5, 70).cut(tori[0]).cut(tori[1]).cut(man_in)
    jumper = max(jumper.Solids, key=lambda sol: sol.Volume)       # drop trim slivers
    add(TCA, f"Coolant_jumper_{k + 1}", jumper, "Inconel 718", 1, "jumper across nozzle joint")
    add_joint(TCA, f"Jumper_{k + 1}", jj, d_jump, V(R_jump * c, R_jump * s, 0.5 * (z_jm_n + z_jm_c)), V(0, 0, 1))

ri_em = K_INT * mm(ducts["nozzle_return"]) / 2 / math.sqrt(2)
w_em = man_wall(p_jk_in, ri_em)
r_em = ri_em + w_em
z_em = -x_e + r_em + 25
R_em = r_outer(-z_em) + (0.0 if INTEGRAL else r_em - 6)
d_nr = mm(ducts["nozzle_return"])
L_ep = r_em + 40.0 if INTEGRAL else 60.0
add(TCA, "Coolant_exit_manifold", cl.torus_tube(R_em, r_em, w_em).translate(V(0, 0, z_em)).fuse(
    cl.tube(d_nr / 2 - w_em, d_nr / 2, L_ep).rotate(V(0, 0, 0), V(0, 1, 0), -90).translate(V(-R_em, 0, z_em))).cut(nozzle).cut(TCA_ENV).removeSplitter()
    if INTEGRAL else cl.torus_tube(R_em, r_em, w_em).translate(V(0, 0, z_em)).fuse(
    cl.tube(d_nr / 2 - w_em, d_nr / 2, L_ep).rotate(V(0, 0, 0), V(0, 1, 0), -90).translate(V(-R_em, 0, z_em))).cut(nozzle).removeSplitter(),
    "Inconel 718", 1, "collects circuit B at the nozzle exit; stiffens the exit lip")
P_em_port = V(-R_em - L_ep - mm(J["nozzle_return"]["flange_t_m"]), 0, z_em)

# ---------------------------------------------------------------- injector head
t_face, z_fp_top, z_ipp_top = 20.0, 240.0, 265.0
body_top = 295.0
inj_body = cl.revolve_rz([(Rc + 1, 0), (mm(jic["flange_od_m"]) / 2, 0), (mm(jic["flange_od_m"]) / 2, t_icf),
                          (R_ib, t_icf), (R_ib, body_top), (R_ib - 30, body_top), (R_ib - 30, t_icf + 10),
                          (Rc + 1, t_icf)])           # flat flange face out to the OD: washers seat on it
inj_body = inj_body.cut(cl.bolt_circle_holes(jic["n_bolts"], mm(jic["bcd_m"]), mm(jic["d_m"]) * 1.1, t_icf, 0, 180.0 / jic["n_bolts"]))
# ports: fuel-rich gas into the lower plenum (-x), ox-rich gas into the dome (+x)
jfh, joh = J["fuel_hot_gas"], J["ox_hot_gas"]
d_fh, d_oh = mm(ducts["fuel_hot_gas"]), mm(ducts["ox_hot_gas"])
z_fport = t_icf + 12 + d_fh / 2 + 22
z_oport = body_top + 100.0
L_istub = 25.0
# the fuel flange must sit outside the injector/chamber flange OD
L_fstub = mm(jic["flange_od_m"]) / 2 + 12 - R_ib
fuel_stub = cl.tube(d_fh / 2, d_fh / 2 + 10, L_fstub + 30).rotate(V(0, 0, 0), V(0, 1, 0), -90).translate(V(-R_ib + 30, 0, z_fport))
inj_body = inj_body.fuse(fuel_stub).cut(cl.cyl(d_fh / 2, L_fstub + 40).rotate(V(0, 0, 0), V(0, 1, 0), -90).translate(V(-R_ib + 40, 0, z_fport)))
inj_body = inj_body.removeSplitter()
if not ONEPIECE:
    add(INJH, "Injector_body_fuel_plenum", inj_body, "Inconel 718", 1,
        "fuel-rich gas plenum, injector/chamber flange; welded faceplate and posts")
P_fport = V(-R_ib - L_fstub - mm(jfh["flange_t_m"]), 0, z_fport)

face = cl.cyl(Rc + 1, t_face)
holes, posts = [], []
for ring in INJ["rings"]:
    for k in range(ring["count"]):
        a = 2 * math.pi * k / ring["count"]
        x, y = mm(ring["r_m"]) * math.cos(a), mm(ring["r_m"]) * math.sin(a)
        holes.append(cl.cyl(mm(INJ["d_annulus_outer_m"]) / 2, t_face + 2, -1).translate(V(x, y, 0)))
        posts.append(cl.tube(mm(INJ["d_ox_post_m"]) / 2, mm(INJ["d_post_outer_m"]) / 2, z_ipp_top - 6, 6).translate(V(x, y, 0)))
face = face.cut(Part.makeCompound(holes))
ipp = cl.cyl(R_ib - 29, z_ipp_top - z_fp_top, z_fp_top).cut(
    Part.makeCompound([cl.cyl(mm(INJ["d_post_outer_m"]) / 2, 40, z_fp_top - 5).translate(V(h.BoundBox.Center.x, h.BoundBox.Center.y, 0)) for h in holes]))
if ONEPIECE:
    # one L-PBF build: same solids, so the same mass; what goes is 176 parts and 346 brazed or welded joints
    add(INJH, "Injector_AM_single_piece", Part.makeCompound([inj_body, face, Part.makeCompound(posts), ipp]), "Inconel 718", 1,
        f"single-piece L-PBF injector (I4): plenum, faceplate, {INJ['n_elements']} posts, interpropellant plate")
else:
    add(INJH, "Injector_faceplate", face, "Inconel 718", 1,
        f"{INJ['n_elements']} gas-gas coax elements on {len(INJ['rings'])} rings, pitch {mm(INJ['pitch_m']):.1f} mm")
    add(INJH, "Injector_ox_posts", Part.makeCompound(posts), "Inconel 718", INJ["n_elements"],
        f"ox-rich gas posts, ID {mm(INJ['d_ox_post_m']):.1f} mm, recess 6 mm", clash=False)
    add(INJH, "Injector_interpropellant_plate", ipp, "Inconel 718", 1, "separates fuel plenum and ox dome", clash=False)

a_d, b_d, t_d = R_ib, 200.0, 26.0
dome_pts = [(a_d * math.cos(math.radians(t)), body_top + b_d * math.sin(math.radians(t))) for t in range(0, 91, 5)]
dome_in = [((a_d - t_d) * math.cos(math.radians(t)), body_top + (b_d - t_d) * math.sin(math.radians(t))) for t in range(90, -1, -5)]
dome = cl.revolve_rz(dome_pts + dome_in)
L_ox = R_ib + L_istub - 130.0          # boss starts clear of the gimbal pad
ox_stub = cl.tube(d_oh / 2, d_oh / 2 + 10, L_ox).rotate(V(0, 0, 0), V(0, 1, 0), 90).translate(V(130.0, 0, z_oport))
pad = cl.cyl(110, 30, body_top + b_d - 12)
dome = dome.fuse([ox_stub, pad]).cut(cl.cyl(d_oh / 2, L_ox + 10).rotate(V(0, 0, 0), V(0, 1, 0), 90).translate(V(125.0, 0, z_oport)))
dome = dome.cut(inj_body).removeSplitter()
add(INJH, "Ox_dome", dome, "Inconel 718", 1, "ox-rich gas dome, carries thrust to the gimbal pad")
P_oport = V(R_ib + L_istub + mm(joh["flange_t_m"]), 0, z_oport)
z_pad_top = body_top + b_d + 18

# TVC actuator lugs (+/-y), base kept above the injector/chamber bolt heads
z_lug = max(70.0, t_icf + 0.16 * mm(jic["d_m"]) + 0.7 * mm(jic["d_m"]) + 5.0)
for sgn, nm in [(1, "TVC_lug_pitch"), (-1, "TVC_lug_yaw")]:
    lug = Part.makeBox(70, 80, 90, V(-35, sgn * R_ib - (0 if sgn > 0 else 80), z_lug)).cut(
        cl.cyl(16, 80).rotate(V(0, 0, 0), V(0, 1, 0), 90).translate(V(-40, sgn * (R_ib + 40), z_lug + 45)))
    add(INJH, nm, lug, "Inconel 718", 1, "TVC actuator attach lug")

# injector/chamber bolts (through both flanges)
b, hw = cl.bolt_set(jic["n_bolts"], mm(jic["bcd_m"]), mm(jic["d_m"]), mm(jic["across_flats_m"]), 2 * t_icf, t_icf)
add(INJH, "Injector_chamber_bolts", b, jic["grade"], jic["n_bolts"], f"{jic['n_bolts']}x {jic['bolt']} {jic['grade']}")
add(INJH, "Injector_chamber_nuts_washers", hw, jic["grade"], 3 * jic["n_bolts"])

# ---------------------------------------------------------------- gimbal
blk = 150.0
gb = Part.makeBox(blk, blk, blk, V(-blk / 2, -blk / 2, z_pad_top + 10))
pins = cl.cyl(28, blk + 70, -(blk + 70) / 2).rotate(V(0, 0, 0), V(0, 1, 0), 90).translate(V(0, 0, z_pad_top + 10 + blk / 2))
pins = pins.fuse(cl.cyl(28, blk + 70, -(blk + 70) / 2).rotate(V(0, 0, 0), V(1, 0, 0), 90).translate(V(0, 0, z_pad_top + 10 + blk / 2)))
add(GIM, "Gimbal_block", gb.cut(pins), "Ti-6Al-4V", 1, "two-axis gimbal cross block")
add(GIM, "Gimbal_pins", pins, "A286", 2, "pitch and yaw pins")
yoke = Part.makeBox(blk + 120, 60, 50, V(-(blk + 120) / 2, -30, z_pad_top + 10 + blk + 15))
yoke = yoke.fuse(Part.makeBox(30, 60, blk * 0.8, V((blk + 120) / 2 - 30, -30, z_pad_top + 40)))
yoke = yoke.fuse(Part.makeBox(30, 60, blk * 0.8, V(-(blk + 120) / 2, -30, z_pad_top + 40)))
add(GIM, "Gimbal_upper_yoke", yoke.cut(pins), "Ti-6Al-4V", 1, "vehicle-side yoke (thrust structure interface)")
gp, gb_hw = cl.bolt_set(12, 170, 16, 24, 30, z_pad_top, with_nuts=False)
add(GIM, "Gimbal_pad_bolts", gp, "Inconel 718", 12, "12x M16 into tapped dome pad", clash=False)
add(GIM, "Gimbal_pad_washers", gb_hw, "Inconel 718", 12, clash=False)
add(GIM, "Gimbal_lower_plate", cl.cyl(110, 10, z_pad_top).cut(cl.bolt_circle_holes(12, 170, 17.6, 10, z_pad_top, 15)),
    "Ti-6Al-4V", 1, "gimbal block base plate", clash=False)


# ======================================================================== turbopumps
def build_tpa(side):
    """Build one turbopump + preburner in its local frame (z up, turbine rotor at z=0,
    exhaust port toward local -x). Returns (shapes dict name->(shape, material, note, qty), ports)."""
    pm, tb, sh = CY[f"{side}_pump"], CY[f"{side}_turbine"], CY[f"{side}_shaft"]
    pb = D["opb" if side == "ox" else "fpb"]
    S, P = {}, {}
    Dm, h, chord = mm(tb["Dm_m"]), mm(tb["blade_h_m"]), mm(tb["chord_m"])
    r_tip = Dm / 2 + h / 2
    d_sh = math.ceil(mm(sh["D_m"]) / 5) * 5
    blade_mat = "SX500" if side == "ox" else "MAR-M-247"
    t_disk = max(0.12 * Dm, 30.0)
    S["turbine_disk"] = (cl.turbine_disk(Dm, h, d_sh, t_disk), blade_mat, "turbine disk (blisk hub)", 1)
    S["turbine_rotor_blades"] = (cl.axial_blade_row(Dm, h, tb["n_rotor"], chord, 65, 25, -chord / 2), blade_mat,
                                 f"{tb['n_rotor']} rotor blades, h {h:.1f} mm", tb["n_rotor"])
    z_st = -2.6 * chord
    S["turbine_stator_vanes"] = (cl.axial_blade_row(Dm, h, tb["n_stator"], chord, 55, -35, z_st), blade_mat,
                                 f"{tb['n_stator']} nozzle vanes", tb["n_stator"])
    S["stator_shrouds"] = (cl.tube(Dm / 2 - h / 2 - 8, Dm / 2 - h / 2, chord, z_st).fuse(
        cl.tube(r_tip, r_tip + 8, chord, z_st)), blade_mat, "nozzle ring shrouds", 1)
    # housing around rotor + stator, inlet plenum cone down to the preburner
    r_pb_out = mm(pb["D_m"]) / 2 + mm(pb["wall_t_m"])
    z_h0, z_h1 = z_st - 12, chord / 2 + 6
    t_h = 16.0
    z_pl = z_h0 - 75.0
    # inner wall steps from the stator outer shroud (r_tip + 8) down to the rotor tip gap
    r_st, r_gap = r_tip + 8.0, r_tip + 1.5
    z_step = z_st + chord + 1.0
    housing = cl.revolve_rz([(r_st, z_h0), (r_st, z_step), (r_gap, z_step), (r_gap, z_h1), (r_st + t_h, z_h1),
                             (r_st + t_h, z_h0), (r_pb_out, z_pl), (r_pb_out - mm(pb["wall_t_m"]), z_pl)])
    hj = JI[f"{side}_turbine_housing"]
    S["turbine_housing"] = (housing, "Inconel 718" if side == "fuel" else "SX500",
                            "turbine inlet housing; " + ("welded to preburner" if hj["welded"] else f"bolted {hj['n_bolts']}x {hj['bolt']}"), 1)
    # exhaust collector (scroll approximated by a torus) with a port toward -x
    d_hg = mm(ducts[f"{side}_hot_gas"])
    r_c = d_hg / 2 + 8
    z_c = z_h1 + r_c - 10
    R_c = r_tip + r_c * 0.55
    coll = cl.torus_tube(R_c, r_c, 9).translate(V(0, 0, z_c))
    L_cs = 15.0
    jhg = J[f"{side}_hot_gas"]
    stub = cl.tube(r_c - 9, r_c, R_c + r_c + L_cs - R_c).rotate(V(0, 0, 0), V(0, 1, 0), -90).translate(V(-R_c, 0, z_c))
    S["exhaust_collector"] = (coll.fuse(stub).removeSplitter(), "Inconel 718", "turbine exhaust collector", 1)
    P["exhaust"] = (V(-(R_c + r_c + L_cs + mm(jhg["flange_t_m"])), 0, z_c), V(-1, 0, 0))
    # bearing housing and shaft
    z_b0 = z_c + r_c + 5
    L_b = max(0.55 * mm(pm["D2_m"]), 140.0)
    r_bh = d_sh / 2 + 32
    S["bearing_housing"] = (cl.tube(d_sh / 2 + 18, r_bh, L_b, z_b0).fuse(
        cl.tube(d_sh / 2 + 18, r_bh + 30, 14, z_b0)).fuse(cl.tube(d_sh / 2 + 18, r_bh + 30, 14, z_b0 + L_b - 14)),
        "Inconel 718", "bearing housing", 1)
    btype = BEARINGS.get(side, "steel")
    for k, zb in enumerate([z_b0 + 25, z_b0 + L_b - 45]):
        if btype == "hydrostatic":                  # C2: journal sleeve, 0.08 mm radial clearance, 6 supply orifices
            sleeve = cl.tube(d_sh / 2 + 0.08, d_sh / 2 + 16, 30, zb - 4)
            for a6 in range(6):
                orf = cl.cyl(1.5, 20).rotate(V(0, 0, 0), V(0, 1, 0), 90).rotate(V(0, 0, 0), V(0, 0, 1), 60 * a6)
                sleeve = sleeve.cut(orf.translate(V(0, 0, zb + 11)))
            S[f"hydrostatic_bearing_{k + 1}"] = (sleeve, "Inconel 718",
                                                 "hydrostatic journal bearing, fed from CH4 pump discharge (C2)", 1)
        elif btype == "hybrid_Si3N4":               # C1: M50 rings, Si3N4 balls
            S[f"bearing_{k + 1}"] = (cl.tube(d_sh / 2, d_sh / 2 + 16, 22, zb), "M50/Si3N4 hybrid",
                                     "hybrid angular-contact bearing, Si3N4 balls (C1)", 1)
        else:
            S[f"bearing_{k + 1}"] = (cl.tube(d_sh / 2, d_sh / 2 + 16, 22, zb), "A286", "angular-contact bearing (cryogenic, propellant-cooled)", 1)
    z_k = z_b0 + L_b + 6
    if side == "ox":
        r_k = 0.32 * mm(pm["D2_m"])
        kick = cl.tube(d_sh / 2 + 6, r_k, 45, z_k)
        kport = cl.tube(14, 24, 72).rotate(V(0, 0, 0), V(1, 0, 0), 90).translate(V(0, -(r_k - 2), z_k + 22))
        S["kick_stage_housing"] = (kick.fuse(kport).removeSplitter(), "Inconel 718",
                                   f"kick stage: +{CY['p_kick_rise_Pa'] / 1e5:.0f} bar for the ox flow to the FPB", 1)
        P["kick"] = (V(0, -(r_k + 70 + mm(J["ox_crossfeed"]["flange_t_m"])), z_k + 22), V(0, -1, 0))
        z_k += 100
    # pump stages
    imp = cl.impeller(mm(pm["D2_m"]), mm(pm["b2_m"]), mm(pm["D_eye_m"]), mm(pm["D_hub_m"]), bore=d_sh)
    z_p0 = z_k + 20                      # casing bottom face seats on the bearing-housing flange
    stages = []
    for s_i in range(pm["stages"]):
        zs = z_p0 + s_i * (imp["height"] + 45)
        for part in ("hub", "shroud", "blades"):
            stages.append((f"impeller{s_i + 1}_{part}", imp[part].copy().translate(V(0, 0, zs))))
    imp_mat = "Inconel 718" if side == "ox" else "Ti-6Al-4V"
    for nm, shp in stages:
        S[nm] = (shp, imp_mat, f"centrifugal impeller D2 {mm(pm['D2_m']):.0f} mm, 6+6 blades", 1)
    z_top_imp = z_p0 + pm["stages"] * imp["height"] + (pm["stages"] - 1) * 45
    R2 = mm(pm["D2_m"]) / 2
    r_vt = mm(pm["volute_throat_m"]) / 2
    z_v = z_p0 + imp["height"] * 0.45
    w_vol = max(1.2 * pm["p_out"] * 1.25 * r_vt / 520e6, 4.0)        # hoop wall at the discharge end
    d_dis = mm(ducts["lox_discharge" if side == "ox" else "ch4_discharge"])
    vol = cl.volute(R2 + 6, r_vt, z_v, 270.0, d_dis / 2, w_vol)
    casing = cl.revolve_rz([(mm(pm["D_eye_m"]) / 2 + 4, z_top_imp + 6), (R2 + 14, z_top_imp + 6), (R2 + 14, z_p0 - 12),
                            (d_sh / 2 + 10, z_p0 - 12), (d_sh / 2 + 10, z_p0 - 26), (R2 + 30, z_p0 - 26),
                            (R2 + 30, z_top_imp + 22), (mm(pm["D_eye_m"]) / 2 + 4, z_top_imp + 22)])
    vj = JI[f"{side}_pump_volute_cover"]
    S["pump_volute_casing"] = (casing.fuse(vol).removeSplitter(), "Inconel 718",
                               "pump casing and volute; " + ("welded (no ISO bolt pattern fits)" if vj["welded"] else f"cover bolted {vj['n_bolts']}x {vj['bolt']}"), 1)
    jd = J[f"{'lox' if side == 'ox' else 'ch4'}_discharge"]
    r_end = 1.25 * r_vt
    P["discharge"] = (V(R2 + 6 + r_end + w_vol, 270.0 + mm(jd["flange_t_m"]), z_v), V(0, 1, 0))
    # inducer, inlet housing, inlet duct + flange
    D_ind = mm(pm["inducer_D_m"])
    L_ind = 0.7 * D_ind
    z_i0 = z_top_imp + 6
    # the shaft steps down through the inducer, which carries only the inducer torque
    # (~15 % of the pump; d ~ T^(1/3) gives 0.53 d); the hub keeps an 8 mm wall
    d_stub = math.ceil(0.53 * d_sh)
    ind_hub = max(mm(pm["inducer_hub_m"]), d_stub + 16.0)
    ind = cl.inducer(D_ind, ind_hub, mm(pm["inducer_pitch_m"]), L_ind, bore=d_stub)
    S["inducer_hub"] = (ind["hub"].translate(V(0, 0, z_i0)), imp_mat, "inducer hub", 1)
    S["inducer_blades"] = (ind["blades"].translate(V(0, 0, z_i0)), imp_mat, "3-bladed helical inducer, tip angle 9 deg", 3)
    d_in = mm(ducts["lox_inlet" if side == "ox" else "ch4_inlet"])
    z_i1 = z_i0 + L_ind + 15
    inlet = cl.revolve_rz([(D_ind / 2 + 1.5, z_top_imp + 22), (D_ind / 2 + 1.5, z_i1), (d_in / 2, z_i1 + 90), (d_in / 2, z_i1 + 200),
                           (d_in / 2 + 9, z_i1 + 200), (d_in / 2 + 9, z_i1 + 90), (D_ind / 2 + 13, z_i1), (D_ind / 2 + 13, z_top_imp + 22)])
    S["inlet_housing"] = (inlet, "Inconel 718" if side == "ox" else "304L", "inducer housing and inlet duct", 1)
    ji = J["lox_inlet" if side == "ox" else "ch4_inlet"]
    P["inlet"] = (V(0, 0, z_i1 + 200 + mm(ji["flange_t_m"])), V(0, 0, 1))
    S["shaft"] = (cl.cyl(d_sh / 2, z_i0 + t_disk, -t_disk).fuse(cl.cyl(d_stub / 2, L_ind, z_i0))
                  .fuse(cl.hexagon(d_sh * 1.5, 0.6 * d_sh, -t_disk - 0.6 * d_sh)).removeSplitter(),
                  "Inconel 718", f"shaft D {d_sh:.0f} mm (inducer stub D {d_stub:.0f}), {CY[f'{side}_pump']['N_rpm']:.0f} rpm, "
                                 f"torque {sh['torque_Nm'] / 1e3:.1f} kN m", 1)
    # preburner: shell, injector head at the bottom, ports
    L_pb, r_pb = mm(pb["L_m"]), mm(pb["D_m"]) / 2
    z_pbb = z_pl - L_pb
    shell = cl.tube(r_pb, r_pb_out, L_pb, z_pbb)
    head = cl.cyl(r_pb_out + 10, 55, z_pbb - 55)
    jmain = J["lox_discharge" if side == "ox" else "fpb_feed"]
    d_main = mm(ducts["lox_discharge" if side == "ox" else "fpb_feed"])
    w_main = max(1.2 * (CY["p_ox_discharge_Pa"] if side == "ox" else D["cooling"]["p_out_Pa"]) * d_main / 2 / 520e6, 3.0)
    main_port = cl.tube(d_main / 2 - w_main, d_main / 2, 70, z_pbb - 125)
    pb_mat = "SX500" if side == "ox" else "Inconel 718"
    S["preburner_shell"] = (shell, pb_mat, f"{'ox' if side == 'ox' else 'fuel'}-rich preburner {pb['T_K']:.0f} K, "
                                           f"{pb['p_Pa'] / 1e5:.0f} bar, tau {pb['tau_s'] * 1e3:.0f} ms", 1)
    S["preburner_injector_head"] = (head.fuse(main_port).removeSplitter(), pb_mat, "preburner injector head (liquid/liquid or liquid/supercritical)", 1)
    P["pb_main"] = (V(0, 0, z_pbb - 125 - mm(jmain["flange_t_m"])), V(0, 0, -1))
    z_side = z_pbb + 45
    jx = J["fuel_crossfeed" if side == "ox" else "ox_crossfeed"]
    side_port = cl.tube(12, 22, 63).rotate(V(0, 0, 0), V(1, 0, 0), -90).translate(V(0, r_pb_out - 3, z_side))
    S["preburner_crossfeed_port"] = (side_port, pb_mat, "cross-feed inlet boss", 1)
    P["pb_cross"] = (V(0, r_pb_out + 60 + mm(jx["flange_t_m"]), z_side), V(0, 1, 0))
    if side == "fuel":
        jf = J["nozzle_return"]
        dfeed = mm(ducts["nozzle_return"])
        w_feed = max(1.2 * D["cooling"]["p_out_Pa"] * dfeed / 2 / 520e6, 3.0)
        feed_port = cl.tube(dfeed / 2 - w_feed, dfeed / 2, 53).rotate(V(0, 0, 0), V(0, 1, 0), 90).translate(V(r_pb_out - 3, 0, z_pbb + 120))
        S["preburner_return_port"] = (feed_port, pb_mat, "nozzle-circuit return inlet boss (outboard)", 1)
        P["pb_feed"] = (V(r_pb_out + 50 + mm(jf["flange_t_m"]), 0, z_pbb + 120), V(1, 0, 0))
    z_ig = z_pbb + L_pb * 0.35
    if IGNITION == "laser":                         # N2: laser head with a sapphire window, no propellant taps
        ig = cl.placed(cl.cyl(22, 40), V(0, -(r_pb_out - 3), z_ig), V(0, -1, 0))      # window port boss
        head = cl.placed(cl.cyl(14, 60), V(0, -(r_pb_out + 37), z_ig), V(0, -1, 0))   # laser spark-plug head, 28 mm
        S["laser_igniter"] = (ig.fuse(head).removeSplitter(), "Inconel 718",
                              "laser ignition head, sapphire window, fibre-fed (N2); no GOX/GCH4 supply", 1)
    else:
        ig = cl.placed(cl.cyl(22, 128), V(0, -(r_pb_out - 3), z_ig), V(0, -1, 0))
        tip = cl.placed(cl.cyl(10, 50), V(0, -(r_pb_out + 125), z_ig), V(0, -1, 0))
        S["torch_igniter"] = (ig.fuse(tip), "Inconel 718", "spark-torch igniter (GOX/GCH4)", 1)
    P["igniter"] = (V(0, -(r_pb_out + 20), z_ig), V(0, -1, 0))
    P["speed_sensor"] = (V(0, r_bh + 30, z_b0 + L_b / 2), V(0, 1, 0))
    P["z_coll"] = z_c
    P["R_env"] = max(R_c + r_c + L_cs, R2 + 30 + 2.5 * r_vt)
    P["z_top"] = z_i1 + 200
    P["z_bottom"] = z_pbb - 125
    # internal bolted casing joints
    if not vj["welded"]:                 # bolting flange for the volute cover on top of the casing
        S["pump_casing_flange"] = (cl.tube(R2 + 29.5, mm(vj["flange_od_m"]) / 2, mm(vj["flange_t_m"]),
                                           z_top_imp + 22 - mm(vj["flange_t_m"])), "Inconel 718", "volute cover bolting flange", 1)
    for jn_name, z_at, flip in [(f"{side}_pump_inlet_housing", z_top_imp + 22, False),
                                (f"{side}_bearing_housing", z_b0 + L_b - 14, True),
                                (f"{side}_pump_volute_cover", z_top_imp + 22, False),
                                (f"{side}_turbine_housing", z_h1, False)]:
        jj_ = JI[jn_name]
        if jj_["welded"]:
            continue
        bb, hh = cl.bolt_set(jj_["n_bolts"], mm(jj_["bcd_m"]), mm(jj_["d_m"]), mm(jj_["across_flats_m"]), 0, z_at,
                             with_nuts=False, flip=flip)
        S[f"bolts_{jn_name}"] = (bb, jj_["grade"], f"{jj_['n_bolts']}x {jj_['bolt']} into tapped casing", jj_["n_bolts"])
    return S, P


TPA = {}
for side, sgn in [("ox", +1), ("fuel", -1)]:
    S, P = build_tpa(side)
    exh_local = P["exhaust"][0]
    if side == "ox":
        x_port = P_oport.x
        z_port = P_oport.z
    else:
        x_port = -P_fport.x
        z_port = P_fport.z
    X = x_port - exh_local.x            # exhaust port at local -x lands on the injector port
    z_t = z_port - exh_local.z
    base = V(sgn * X, 0, z_t)
    a = asm("LOX_Turbopump" if side == "ox" else "CH4_Turbopump", ENGINE, base, 0.0 if side == "ox" else 180.0)
    for nm, (shp, mat, note, qty) in S.items():
        add(a, f"{'LOX' if side == 'ox' else 'CH4'}_{nm}", shp, mat, qty, note)
    TPA[side] = {"asm": a, "P": P, "base": base, "rot": 0.0 if side == "ox" else 180.0}


def to_global(side, local_pt, local_dir=None):
    t = TPA[side]
    pl = App.Placement(t["base"], App.Rotation(V(0, 0, 1), t["rot"]))
    g = pl.multVec(local_pt)
    if local_dir is None:
        return g
    return g, App.Rotation(V(0, 0, 1), t["rot"]).multVec(local_dir)


# ======================================================================== plumbing
def run(name, joint_a, joint_b, d_pipe, pts, wall, mat="Inconel 718", note="", bend=None, joint_b_dir=None):
    """Pipe through pts with flanged pairs at both ends (first/last points are mating planes)."""
    pa, pb_ = V(pts[0]), V(pts[-1])
    da = V(pts[1]) - pa
    da.normalize()
    db = pb_ - V(pts[-2])
    db.normalize()
    wa = joint_a["name"] in WELDED
    wb = bool(joint_b) and joint_b["name"] in WELDED
    ta, tb = mm(joint_a["flange_t_m"]), mm(joint_b["flange_t_m"]) if joint_b else 0
    # flanged: the pipe stops at the outer face of its flange; welded: it runs back to the port end
    body = [pa + da * (-ta if wa else ta)] + [V(p) for p in pts[1:-1]] + [pb_ - db * (-tb if wb else tb)]
    add(PLUMB, name, cl.pipe(body, d_pipe, wall, bend), mat, 1, note)
    if wa:
        add(PLUMB, f"{name}_A_weld", weld_bead(d_pipe / 2 + wall, pa - da * ta, da), mat, 1,
            f"{joint_a['name']} butt weld, radiographed (I1/I3)", clash=False)
    else:
        add_joint(PLUMB, f"{name}_A", joint_a, d_pipe, pa, da)
    if joint_b and wb:
        add(PLUMB, f"{name}_B_weld", weld_bead(d_pipe / 2 + wall, pb_ + db * tb, db), mat, 1,
            f"{joint_b['name']} butt weld, radiographed (I1/I3)", clash=False)
    elif joint_b:
        add_joint(PLUMB, f"{name}_B", joint_b, d_pipe, pb_, db)


def wall_for(p_Pa, d):
    return max(1.2 * p_Pa * d / 2 / 520e6, 2.0) + 1.0


# hot-gas spools are the flanged pairs at the injector ports (TPA collectors mate directly)
for tag, jhg_, d_hg_, P_hg, d_dir in [("Ox_hot_gas", joh, d_oh, P_oport, V(-1, 0, 0)), ("Fuel_hot_gas", jfh, d_fh, P_fport, V(1, 0, 0))]:
    if jhg_["name"] in WELDED:                      # I1: welded spool across the former flange-pair gap
        t_hg = mm(jhg_["flange_t_m"])
        spool = cl.placed(cl.tube(d_hg_ / 2, d_hg_ / 2 + 10, 2 * t_hg, -t_hg), P_hg, d_dir)
        spool = spool.fuse([weld_bead(d_hg_ / 2 + 10, P_hg - d_dir * t_hg, d_dir), weld_bead(d_hg_ / 2 + 10, P_hg + d_dir * t_hg, d_dir)])
        add(PLUMB, f"{tag}_weld", spool.removeSplitter(), "Inconel 718", 1,
            f"{jhg_['name']}: collector welded to the injector inlet through a short spool (I1)", clash=False)
    else:
        add_joint(PLUMB, f"{tag}_joint", jhg_, d_hg_, P_hg, d_dir)

# LOX: inlet flange (vehicle interface), discharge -> MOV -> OPB
for side, jname, dname in [("ox", "lox_inlet", "lox_inlet"), ("fuel", "ch4_inlet", "ch4_inlet")]:
    p, dvec = to_global(side, *TPA[side]["P"]["inlet"])
    add_joint(PLUMB, f"{'LOX' if side == 'ox' else 'CH4'}_inlet_interface", J[jname], mm(ducts[dname]), p, dvec)

p_ld, d_ld = to_global("ox", *TPA["ox"]["P"]["discharge"])
p_opb, d_opb = to_global("ox", *TPA["ox"]["P"]["pb_main"])
d_lox = mm(ducts["lox_discharge"])
w_lox = wall_for(CY["p_ox_discharge_Pa"], d_lox)
y_run = p_ld.y + 160
pts = [p_ld, V(p_ld.x, y_run, p_ld.z), V(p_ld.x, y_run, p_opb.z - 260), V(p_opb.x, p_opb.y, p_opb.z - 260), p_opb]
run("LOX_discharge_duct", J["lox_discharge"], J["lox_discharge"], d_lox, pts, w_lox, note="LOX pump -> MOV -> OPB")
add(PLUMB, "MOV_main_ox_valve", cl.placed(valve_body(d_lox, 220), V(p_ld.x, y_run, 0.5 * (p_ld.z + p_opb.z - 260)), V(0, 0, 1)),
    "Inconel 718", 1, "main oxidiser valve (ball, electromechanical actuator)")

p_fd, d_fdv = to_global("fuel", *TPA["fuel"]["P"]["discharge"])
d_ch4 = mm(ducts["ch4_discharge"])
w_ch4 = wall_for(CY["p_fuel_discharge_Pa"], d_ch4)
y_f = p_fd.y - 160
P_pre = P_jm_port + V(math.cos(a_in), math.sin(a_in), 0) * 260
pts = [p_fd, V(p_fd.x, y_f, p_fd.z), V(p_fd.x, y_f, P_jm_port.z), P_pre, P_jm_port]
run("CH4_discharge_duct", J["ch4_discharge"], J["ch4_discharge"], d_ch4, pts, w_ch4, note="CH4 pump -> MFV -> jacket inlet manifold")
z_mfv = p_fd.z - 420
add(PLUMB, "MFV_main_fuel_valve", cl.placed(valve_body(d_ch4, 220), V(p_fd.x, y_f, z_mfv), V(0, 0, 1), 180),
    "Inconel 718", 1, "main fuel valve")

# regen jacket circuit A outlet -> FPB bottom (main) port, passing beside the FPB
p_fm, d_fm = to_global("fuel", *TPA["fuel"]["P"]["pb_main"])
d_feed = mm(ducts["fpb_feed"])
p_leg = P_om_port + u_om * 140
pts = [P_om_port, p_leg, V(p_leg.x, p_leg.y, p_fm.z - 220), V(p_fm.x, p_fm.y, p_fm.z - 220), p_fm]
run("FPB_feed_duct", J["fpb_feed"], J["fpb_feed"], d_feed, pts, wall_for(D["cooling"]["p_out_Pa"], d_feed), note="jacket circuit A -> FPB")

# nozzle circuit B return -> FPB outboard side port
p_fb, d_fb = to_global("fuel", *TPA["fuel"]["P"]["pb_feed"])
d_ret = mm(ducts["nozzle_return"])
x_ret = min(P_em_port.x, p_fb.x) - 120
pts = [P_em_port, V(x_ret, 0, P_em_port.z), V(x_ret, 0, p_fb.z), p_fb]
run("Nozzle_return_duct", J["nozzle_return"], J["nozzle_return"], d_ret, pts, wall_for(D["cooling"]["p_out_Pa"], d_ret),
    note="jacket circuit B -> FPB (orificed to circuit A pressure)")

# ox cross-feed: kick stage -> FPOV -> FPB
p_k, _ = to_global("ox", *TPA["ox"]["P"]["kick"])
p_fx, d_fx = to_global("fuel", *TPA["fuel"]["P"]["pb_cross"])
d_ox_x = mm(ducts["ox_crossfeed"])
y_x = min(p_fx.y, p_k.y) - 200
z_x = p_fx.z
pts = [p_k, V(p_k.x, y_x, p_k.z), V(p_k.x, y_x, z_x), V(p_fx.x, y_x, z_x), p_fx]
run("Ox_crossfeed_line", J["ox_crossfeed"], J["ox_crossfeed"], d_ox_x, pts, wall_for(CY["p_ox_discharge_Pa"], d_ox_x), bend=60,
    note="LOX kick stage -> FPOV -> FPB")
add(PLUMB, "FPOV_fuel_preburner_ox_valve", cl.placed(valve_body(d_ox_x, 140), V(p_k.x, y_x, 0.5 * (p_k.z + z_x)), V(0, 0, 1), -90),
    "Inconel 718", 1, "fuel preburner oxidiser valve")

# fuel cross-feed: tee on the CH4 discharge -> OPFV -> OPB
p_ox_x, d_oxx = to_global("ox", *TPA["ox"]["P"]["pb_cross"])
d_fu_x = mm(ducts["fuel_crossfeed"])
t_fx = mm(J["fuel_crossfeed"]["flange_t_m"])
tee = V(p_fd.x - d_ch4 / 2 - 14 - 2 * t_fx, y_f, p_fd.z - 260)
y_far = y_f - 170
x_lane = TPA["ox"]["base"].x - mm(D["opb"]["D_m"]) / 2 - mm(D["opb"]["wall_t_m"]) - 95
pts = [tee, V(tee.x - 120, y_f, tee.z), V(tee.x - 120, y_far, tee.z), V(x_lane, y_far, tee.z), V(x_lane, y_far, p_ox_x.z),
       V(x_lane, p_ox_x.y + 200, p_ox_x.z), V(p_ox_x.x, p_ox_x.y + 200, p_ox_x.z), p_ox_x]
run("Fuel_crossfeed_line", J["fuel_crossfeed"], J["fuel_crossfeed"], d_fu_x, pts, wall_for(CY["p_fuel_discharge_Pa"], d_fu_x), bend=55,
    note="CH4 discharge tap -> OPFV -> OPB")
add(PLUMB, "OPFV_ox_preburner_fuel_valve", cl.placed(valve_body(d_fu_x, 130), V(0.5 * (tee.x + x_lane), y_far, tee.z), V(1, 0, 0), 90),
    "Inconel 718", 1, "oxidiser preburner fuel valve")
ch4_pts = [p_fd, V(p_fd.x, y_f, p_fd.z), V(p_fd.x, y_f, P_jm_port.z), P_pre, P_jm_port]
boss = cl.placed(cl.cyl(22, 14 + t_fx + d_ch4 / 2), V(p_fd.x, y_f, tee.z), V(-1, 0, 0))
boss = boss.cut(cl.pipe_solid(ch4_pts, d_ch4, 1.5 * d_ch4))
add(PLUMB, "Fuel_crossfeed_tee", boss, "Inconel 718", 1,
    "tee boss on the CH4 discharge duct")

# igniter flanges
for side in ("ox", "fuel"):
    p_ig, d_ig = to_global(side, *TPA[side]["P"]["igniter"])
    ji = J["igniter"]
    b, hw = cl.bolt_set(ji["n_bolts"], mm(ji["bcd_m"]) + 20, mm(ji["d_m"]), mm(ji["across_flats_m"]), 0, 0, with_nuts=False)
    add(PLUMB, f"{side.upper()}_igniter_bolts", cl.placed(b, p_ig, d_ig), "Inconel 718", ji["n_bolts"], "4x M6 igniter flange", clash=False)

# ======================================================================== instrumentation (ISA-5.1 tags, see docs P&ID)
tags = [("PT-101_chamber_pressure", V(0, R_ib + 0, 120), V(0, 1, 0)),
        ("PT-201_LOX_pump_discharge", p_ld + V(0, 60, 0) + V(d_lox / 2 + 6, 0, 0), V(1, 0, 0)),
        ("PT-301_CH4_pump_discharge", p_fd + V(0, -60, 0) + V(-d_ch4 / 2 - 6, 0, 0), V(-1, 0, 0))]
for side, tg in [("ox", "ST-202_LOX_TPA_speed"), ("fuel", "ST-302_CH4_TPA_speed")]:
    p_s, d_s = to_global(side, *TPA[side]["P"]["speed_sensor"])
    tags.append((tg, p_s, d_s))
for tg, p_i, d_i in tags:
    add(INSTR, tg.replace("-", "_"), cl.placed(instrument(), p_i, d_i), "A286", 1, tg, clash=False)

# ======================================================================== checks and export
doc.recompute()
t_build = time.time() - T0


def world_shape(obj):
    s = obj.Shape.copy()
    s.Placement = obj.getGlobalPlacement()
    return s


# By-design contacts: blades rooted 0.3-0.5 mm into their hub/shroud, welded bosses and
# the collector/housing weld, screws in (unmodelled) tapped holes, fastener stacks on
# their own flanges. Everything else that overlaps is reported.
DESIGNED = [("impeller1_hub", "impeller1_blades"), ("impeller1_shroud", "impeller1_blades"),
            ("impeller2_hub", "impeller2_blades"), ("impeller2_shroud", "impeller2_blades"),
            ("turbine_disk", "turbine_rotor_blades"), ("turbine_stator_vanes", "stator_shrouds"),
            ("inducer_hub", "inducer_blades"), ("exhaust_collector", "turbine_housing"),
            ("preburner_shell", "preburner_crossfeed_port"), ("preburner_shell", "preburner_return_port"),
            ("preburner_shell", "torch_igniter"), ("preburner_shell", "laser_igniter"),
            ("pump_casing_flange", "pump_volute_casing")]
CASINGS = ("pump_volute_casing", "pump_casing_flange", "inlet_housing", "bearing_housing", "kick_stage_housing", "turbine_housing")


def designed_contact(a, b):
    a2, b2 = a.split("_", 1)[1] if a[:3] in ("LOX", "CH4") else a, b.split("_", 1)[1] if b[:3] in ("LOX", "CH4") else b
    for x, y in DESIGNED:
        if {a2, b2} == {x, y}:
            return True
    for bolt_name, other in ((a2, b2), (b2, a2)):
        if bolt_name.startswith("bolts_") and other in CASINGS:
            return True
    for n1, n2 in ((a, b), (b, a)):                       # bolts / nuts with their own flange pair
        if n1.endswith(("_bolts", "_nuts_washers")):
            stem = n1.rsplit("_bolts", 1)[0].rsplit("_nuts_washers", 1)[0]
            if n2.startswith(stem):
                return True
    return False


# clash check: solids in different sub-assemblies (bounding-box prefilter, then boolean common)
clashes = []
items = [(g.Name, n, world_shape(o)) for g, n, o in SOLIDS]
for i in range(len(items)):
    gi, ni, si = items[i]
    bi = si.BoundBox
    for k in range(i + 1, len(items)):
        gk, nk, sk = items[k]
        if gi == gk and designed_contact(ni, nk):
            continue
        bk = sk.BoundBox
        if not bi.intersect(bk):
            continue
        try:   # solid by solid: compound booleans report false overlaps on touching faces
            v = 0.0
            for a_ in (si.Solids or [si]):
                if not a_.BoundBox.intersect(bk):
                    continue
                for b_ in (sk.Solids or [sk]):
                    if a_.BoundBox.intersect(b_.BoundBox):
                        cm = a_.common(b_)
                        # OCC can misclassify a whole solid near a revolve seam; keep only overlap
                        # pieces whose centroid really lies inside both parts
                        for piece in cm.Solids:
                            p_ = piece.CenterOfMass
                            if a_.isInside(p_, 0.01, True) and b_.isInside(p_, 0.01, True):
                                v += piece.Volume
        except Exception:
            v = -1.0
        if v > 50.0 or v < 0:
            clashes.append({"a": f"{gi}/{ni}", "b": f"{gk}/{nk}", "volume_mm3": round(v, 1)})

env = ENGINE.Shape.BoundBox if hasattr(ENGINE, "Shape") else None
allshape = Part.makeCompound([s for _, _, s in items])
bb = allshape.BoundBox
mass_total = sum(r["mass_kg"] for r in BOM)
by_asm = {}
for r in BOM:
    by_asm[r["assembly"]] = by_asm.get(r["assembly"], 0.0) + r["mass_kg"]
layout = {"X_lox_tpa_mm": TPA["ox"]["base"].x, "X_ch4_tpa_mm": TPA["fuel"]["base"].x,
          "z_lox_turbine_mm": TPA["ox"]["base"].z, "z_ch4_turbine_mm": TPA["fuel"]["base"].z,
          "bbox_mm": [bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax],
          "envelope_width_x_mm": bb.XLength, "envelope_width_y_mm": bb.YLength, "height_mm": bb.ZLength,
          "max_radius_from_axis_mm": max(math.hypot(x, y) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax))}
json.dump(layout, open(os.path.join(OUT, "layout.json"), "w"), indent=2)
json.dump({"n_clashes": len(clashes), "clashes": clashes}, open(os.path.join(OUT, "clash_report.json"), "w"), indent=2)
json.dump({"total_modelled_kg": mass_total, "by_assembly_kg": by_asm, "build_s": t_build},
          open(os.path.join(OUT, "mass_summary.json"), "w"), indent=2)
with open(os.path.join(OUT, "bom.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(BOM[0].keys()))
    w.writeheader()
    w.writerows(BOM)

doc.saveAs(os.path.join(OUT, "MFE280.FCStd"))
if not os.environ.get("FFSC_NO_STEP"):                 # design-variant screening skips the STEP exports
    import Import  # noqa: E402
    Import.export([ENGINE], os.path.join(OUT, "MFE280_assembly.step"))
    for a in [TCA, INJH, GIM, PLUMB, TPA["ox"]["asm"], TPA["fuel"]["asm"]]:
        Import.export([a], os.path.join(OUT, f"MFE280_{a.Name}.step"))
    # hot-gas path (inner contour) for CFD: a solid of revolution of the gas volume
    gas = cl.revolve_rz([(0, 0)] + [(mm(r), -mm(x)) for x, r in CONT] + [(0, -mm(CONT[-1][0]))])
    gas.exportStep(os.path.join(OUT, "MFE280_hot_gas_volume.step"))
print(f"[cad] parts {len(BOM)}, modelled mass {mass_total:.0f} kg, clashes {len(clashes)}, "
      f"envelope {bb.XLength:.0f} x {bb.YLength:.0f} x {bb.ZLength:.0f} mm, {time.time() - T0:.0f} s")
for c in clashes[:40]:
    print("  clash:", c)
if os.environ.get("FFSC_GUI") and App.GuiUp:
    import FreeCADGui
    FreeCADGui.SendMsgToActiveView("ViewFit")
