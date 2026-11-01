"""Extract 2-D drawing geometry from the FreeCAD model (run with freecadcmd).

    set MFE_VIEWS=tca,inj,tpo,tpf,ga_front,ga_side,ga_top   (default: all)
    "C:\\Program Files\\FreeCAD 1.1\\bin\\freecadcmd.exe" drawings\\src\\extract_views.py

The model file is copied to a temporary folder and opened from there, so the
original cad/output/MFE280.FCStd is never written. Each view is written to
drawings/build/<view>.json in view coordinates (model mm, x right, y up):

  visible   exact HLR (TechDraw.projectEx) of everything beyond the cutting plane:
            sharp edges + silhouettes, as polylines
  parts     per part: cut faces in the plane (outer loop + holes), category,
            material, qty, note, an anchor point inside the cut face, projected bbox
  proxies   simplified blade rows (meridional outline) drawn in the plane
  hatch     greedy hatch-style index per part so that touching cut faces differ

Section views use the conventional representation for fasteners on bolt circles:
one bolt per side is rotated into the cutting plane, drawn whole (not cut), and
the holes it passes through are drilled in the cut faces.
"""

import json
import math
import os
import shutil
import tempfile
import time

import FreeCAD as App
import Part
import TechDraw
from FreeCAD import Vector as V

ROOT = os.environ.get("MFE_ROOT", r"D:\Research\projects\methalox-ffsc-engine")
SRC = os.path.join(ROOT, "cad", "output", "MFE280.FCStd")
OUT = os.path.join(ROOT, "drawings", "build")
os.makedirs(OUT, exist_ok=True)
D = json.load(open(os.path.join(ROOT, "results", "design.json"), encoding="utf-8"))
J = {j["name"]: j for j in D["joints"]}
JI = {j["name"]: j for j in D["internal_joints"]}

tmp = tempfile.mkdtemp(prefix="mfe_dwg_")
shutil.copy2(SRC, os.path.join(tmp, "MFE280_readonly_copy.FCStd"))
doc = App.openDocument(os.path.join(tmp, "MFE280_readonly_copy.FCStd"))
OBJ = {o.Name: o for o in doc.Objects if o.TypeId == "Part::Feature"}
BIG = 20000.0


def log(*a):
    print("[extract]", *a, flush=True)


def group_of(o):
    p = o.getParentGeoFeatureGroup()
    return p.Name if p else ""


PRE_ROT = {}          # object name -> angle (deg) about the global z axis (conventional rotation)
# The jumper pipes carry a 31 cm3 sliver inside the inlet manifold (boolean trim left it);
# the drawing shows the trimmed pipe as intended in build_engine.py (largest solid only).
LARGEST_SOLID_ONLY = {"Coolant_jumper_1", "Coolant_jumper_2", "Coolant_jumper_3", "Coolant_jumper_4"}


def shape_in(o, frame):
    """Copy of the object's shape in the global frame or in its App::Part frame."""
    s = o.Shape.copy()
    if o.Name in LARGEST_SOLID_ONLY and len(s.Solids) > 1:
        s = max(s.Solids, key=lambda x: x.Volume).copy()     # features in this group have identity placement
    if frame == "global":
        s.Placement = o.getGlobalPlacement()
        if o.Name in PRE_ROT:
            s.rotate(V(0, 0, 0), V(0, 0, 1), PRE_ROT[o.Name])
    return s


def view_matrix(right, up, origin):
    r, u = V(right), V(up)
    t = r.cross(u)
    m = App.Matrix(r.x, r.y, r.z, 0, u.x, u.y, u.z, 0, t.x, t.y, t.z, 0, 0, 0, 0, 1)
    o = m.multVec(V(origin))
    m.A14, m.A24, m.A34 = -o.x, -o.y, -o.z
    return m


def to_view(shape, m):
    s = shape.copy()
    s.Placement = App.Placement(m).multiply(s.Placement)
    return s


def pts2d(edge_or_wire, tol):
    try:
        p = edge_or_wire.discretize(Deflection=tol)
    except Exception:
        p = [v.Point for v in edge_or_wire.Vertexes]
    return [[round(q.x, 4), round(q.y, 4)] for q in p]


def faces_out(faces, tol):
    out = []
    for f in faces:
        loops = [pts2d(f.OuterWire, tol)]
        for w in f.Wires:
            if not w.isSame(f.OuterWire):
                loops.append(pts2d(w, tol))
        out.append({"outer": loops[0], "holes": loops[1:], "area": f.Area,
                    "perim": f.OuterWire.Length + sum(w.Length for w in f.Wires if not w.isSame(f.OuterWire))})
    return out


def hlr(shapes, tol, hidden=False):
    if not shapes:
        return [], []
    comp = Part.makeCompound(shapes)
    r = TechDraw.projectEx(comp, V(0, 0, 1))
    vis = []
    for k in (0, 3):                       # V (sharp) and VO (silhouettes)
        if r[k] and not r[k].isNull():
            vis += [pts2d(e, tol) for e in r[k].Edges]
    hid = []
    if hidden:
        for k in (5, 8):
            if r[k] and not r[k].isNull():
                hid += [pts2d(e, tol) for e in r[k].Edges]
    return vis, hid


def crease_lines(shapes, tol, max_deg=12.0):
    """Projected circular edges where two faces meet almost tangentially (faceted
    revolutions such as the ox dome). Their HLR lines are construction artefacts."""
    out = []
    for sh in shapes:
        for e in sh.Edges:
            if not isinstance(e.Curve, Part.Circle):
                continue
            fs = sh.ancestorsOfType(e, Part.Face)
            if len(fs) != 2:
                continue
            p = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
            try:
                n = [f.normalAt(*f.Surface.parameter(p)) for f in fs]
            except Exception:
                continue
            a = math.degrees(n[0].getAngle(n[1]))
            a = min(a, 180.0 - a)
            if a < max_deg:
                out.append(pts2d(e, tol))
    return out


def drop_creases(vis, creases, tol=0.08):
    if not creases:
        return vis
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import unary_union
    buf = unary_union([LineString(c) for c in creases if len(c) >= 2]).buffer(tol)
    keep = []
    for pl in vis:
        if len(pl) >= 2 and buf.contains(LineString(pl)):
            continue
        keep.append(pl)
    return keep


def rotated_instances(comp_shape, axis_pt, target_deg, n_pick=1):
    """Solids of a compound whose centre is angularly nearest to target_deg about the z
    axis through axis_pt, rotated exactly onto target_deg. Returns list of shapes."""
    sols = comp_shape.Solids
    def ang(s):
        c = s.BoundBox.Center
        return math.degrees(math.atan2(c.y - axis_pt.y, c.x - axis_pt.x))
    def dist(a):
        d = (a - target_deg + 180.0) % 360.0 - 180.0
        return abs(d), d
    best = min(sols, key=lambda s: dist(ang(s))[0])
    a0 = ang(best)
    out = []
    for s in sols:
        if abs(((ang(s) - a0 + 180.0) % 360.0) - 180.0) < 0.5:
            c = s.copy()
            c.rotate(axis_pt, V(0, 0, 1), -((a0 - target_deg + 180.0) % 360.0 - 180.0))
            out.append(c)
    return out


def section(name, frame, right, up, origin, parts, rotate_in=(), proxies=(), tol=0.05, do_hlr=True,
            cut=True, hidden=False):
    """parts: list of (object name, category). Categories:
       hatch    cut faces hatched; drilled by fasteners and 'solid' parts
       solid    cut lengthwise but not hatched (shafts, igniters); drills others
       bearing  cut faces drawn with the simplified bearing symbol
       hlr      no cut faces (drawn by HLR only)
       none     ignored for HLR (only listed)
    rotate_in: list of dicts {bolts, hardware, axis, angles, hole_d} (names of compound objects)."""
    t0 = time.time()
    m = view_matrix(right, up, origin)
    plane = Part.makePlane(2 * BIG, 2 * BIG, V(-BIG, -BIG, 0))
    half = Part.makeBox(2 * BIG, 2 * BIG, BIG, V(-BIG, -BIG, -BIG))
    # fasteners rotated into the plane (frame coordinates first, then view)
    fast, drills, fast_info = [], [], []
    for spec in rotate_in:
        for ang in spec["angles"]:
            for key in ("bolts", "hardware"):
                if spec.get(key):
                    for s in rotated_instances(shape_in(OBJ[spec[key]], frame), V(spec["axis"]), ang):
                        fast.append(to_view(s, m))
                        fb = fast[-1].BoundBox
                        fast_info.append({"name": spec[key], "angle": ang, "bbox": [fb.XMin, fb.YMin, fb.XMax, fb.YMax]})
                        if key == "bolts":
                            bb = s.BoundBox
                            c = bb.Center
                            hd = spec.get("hole_d", 0.0)
                            if hd:
                                drills.append(to_view(Part.makeCylinder(hd / 2, bb.ZLength + 2, V(c.x, c.y, bb.ZMin - 1)), m))
                            drills.append(to_view(s, m))
    rec = {"name": name, "frame": frame, "right": list(right), "up": list(up), "origin": list(origin),
           "parts": {}, "visible": [], "hidden": [], "fasteners_in_plane": len(fast), "fasteners": fast_info}
    solids_for_drill = [to_view(shape_in(OBJ[n], frame), m) for n, c in parts if c == "solid"]
    hl = []
    for n, cat in parts:
        o = OBJ[n]
        s = to_view(shape_in(o, frame), m)
        info = {"group": group_of(o), "material": o.Material, "qty": o.Quantity, "note": o.Note, "cat": cat,
                "faces": [], "bbox": None}
        if cat == "none":
            rec["parts"][n] = info
            continue
        sd = s
        if cut and cat in ("hatch", "cutonly", "bearing"):
            for d in drills + solids_for_drill:
                if sd.BoundBox.intersect(d.BoundBox):
                    sd = sd.cut(d)
        if cut and cat in ("hatch", "cutonly", "solid", "bearing"):
            try:
                cf = sd.common(plane)
                info["faces"] = faces_out(cf.Faces, tol)
            except Exception as err:
                log("cut failed", n, err)
        kept = sd
        if cut:
            if s.BoundBox.ZMin > 1e-6:
                kept = None
            elif s.BoundBox.ZMax > -1e-6:
                try:
                    kept = sd.common(half)
                except Exception as err:
                    log("half failed", n, err)
        if kept is not None and not kept.isNull() and kept.Solids:
            if cat != "cutonly":
                hl.append(kept)
            bb = kept.BoundBox
            info["bbox"] = [bb.XMin, bb.YMin, bb.XMax, bb.YMax]
        rec["parts"][n] = info
    # proxies: thin plates in the plane standing in for blade rows (frame coords: list of 4 corners in plane)
    rec["proxies"] = []
    for px in proxies:
        loop = []
        for p in px["pts"]:
            q = m.multVec(V(p))
            loop.append([round(q.x, 4), round(q.y, 4)])
        rec["proxies"].append({"name": px["name"], "loop": loop})
        w = Part.makePolygon([V(x, y, 0) for x, y in loop] + [V(loop[0][0], loop[0][1], 0)])
        hl.append(Part.Face(w).extrude(V(0, 0, -0.3)))
    hl += fast
    t1 = time.time()
    if do_hlr:
        rec["visible"], rec["hidden"] = hlr(hl, tol, hidden)
        n0 = len(rec["visible"])
        rec["visible"] = drop_creases(rec["visible"], crease_lines(hl, tol))
        if n0 != len(rec["visible"]):
            log(f"{name}: dropped {n0 - len(rec['visible'])} crease lines")
    log(f"{name}: {len(parts)} parts, {len(fast)} in-plane fastener solids, cut {t1 - t0:.1f} s, HLR {time.time() - t1:.1f} s, "
        f"{len(rec['visible'])} visible edges")
    return rec


def hatch_styles(rec, tol=0.3):
    """Greedy colouring of touching cut faces so that neighbours get different styles."""
    try:
        from shapely.geometry import Polygon
    except Exception:
        return {}
    polys = {}
    for n, p in rec["parts"].items():
        if p["cat"] not in ("hatch", "cutonly") or not p["faces"]:
            continue
        g = None
        for f in p["faces"]:
            if len(f["outer"]) < 3:
                continue
            pg = Polygon(f["outer"], [h for h in f["holes"] if len(h) >= 3]).buffer(0)
            g = pg if g is None else g.union(pg)
        if g is not None and not g.is_empty:
            polys[n] = g
    names = sorted(polys, key=lambda k: -polys[k].area)
    style = {}
    for n in names:
        used = {style[k] for k in style if polys[k].distance(polys[n]) < tol}
        s = 0
        while s in used:
            s += 1
        style[n] = s
        rp = polys[n].representative_point()
        rec["parts"][n]["anchor"] = [rp.x, rp.y]
    return style


def meridional_rect(o, frame, plane_axis="x", sign=+1, pad=0.0):
    """(r, z) extent of a blade-row compound about the local z axis, as plate corners in the
    plane through the axis (plane x = 0 -> corners at y = +/- r)."""
    s = shape_in(o, frame)
    rs = [math.hypot(v.X, v.Y) for v in s.Vertexes]
    zs = [v.Z for v in s.Vertexes]
    r0, r1, z0, z1 = min(rs), max(rs), min(zs), max(zs)
    out = []
    for sg in (+1, -1):
        out.append([(0, sg * r0, z0), (0, sg * r1, z0), (0, sg * r1, z1), (0, sg * r0, z1)])
    return out, (r0, r1, z0, z1)


# ============================================================================ view definitions
def names_in(group, exclude=()):
    return [n for n, o in OBJ.items() if group_of(o) == group and not any(e in n for e in exclude)]


def view_tca():
    parts = []
    for n in names_in("Thrust_Chamber") + names_in("Injector_Head"):
        if n.endswith("_bolts") or n.endswith("_nuts_washers"):
            parts.append((n, "hlr"))
        elif n == "Injector_ox_posts":
            parts.append((n, "cutonly"))         # posts beyond the cut omitted at 1:10
        else:
            parts.append((n, "hatch"))
    jic, jn, jj = J["injector_chamber"], J["nozzle_joint"], J["coolant_jumper"]
    # jumper 1 (true position 45 deg) is rotated into the cutting plane on the -x side
    for n in ("Coolant_jumper_1", "Jumper_1_flanges", "Jumper_1_seal", "Jumper_1_bolts", "Jumper_1_nuts_washers"):
        PRE_ROT[n] = 135.0
    c = shape_in(OBJ["Jumper_1_flanges"], "global").BoundBox.Center
    rot = [dict(bolts="Jumper_1_bolts", hardware="Jumper_1_nuts_washers", axis=(c.x, c.y, 0), angles=(0.0, 180.0),
                hole_d=1.1 * jj["d_m"] * 1e3),
           dict(bolts="Injector_chamber_bolts", hardware="Injector_chamber_nuts_washers", axis=(0, 0, 0),
                angles=(0.0, 180.0), hole_d=1.1 * jic["d_m"] * 1e3),
           dict(bolts="Nozzle_joint_bolts", hardware="Nozzle_joint_nuts_washers", axis=(0, 0, 0),
                angles=(0.0, 180.0), hole_d=1.1 * jn["d_m"] * 1e3)]
    return section("tca", "global", (0, 0, -1), (1, 0, 0), (0, 0, 0), parts, rotate_in=rot, tol=0.04)


def view_inj():
    parts = []
    for n in names_in("Injector_Head"):
        parts.append((n, "hlr" if (n.endswith("_bolts") or n.endswith("_nuts_washers")) else "hatch"))
    parts = [p for p in parts if not p[0].startswith("Injector_chamber_")]
    return section("inj", "global", (1, 0, 0), (0, 0, 1), (0, 0, 0), parts, tol=0.02)


def view_inj_face():
    """Injector head seen from the chamber side (viewer at -z), no cut."""
    parts = [(n, "hlr") for n in names_in("Injector_Head") if not n.startswith("Injector_chamber_")]
    return section("inj_face", "global", (1, 0, 0), (0, -1, 0), (0, 0, 0), parts, cut=False, tol=0.05)


def view_tpa(side):
    grp = "LOX_Turbopump" if side == "ox" else "CH4_Turbopump"
    pre = "LOX_" if side == "ox" else "CH4_"
    parts, proxies, rot = [], [], []
    for n in names_in(grp):
        k = n[len(pre):]
        if k in ("turbine_rotor_blades", "turbine_stator_vanes") or k.endswith("_blades"):
            parts.append((n, "none"))
            corners, ext = meridional_rect(OBJ[n], "local")
            for c in corners:
                proxies.append({"name": n, "pts": c})
            continue
        if k.startswith("bolts_"):
            # screws into the tapped casing: one per side rotated into the plane x = 0
            parts.append((n, "none"))
            rot.append(dict(bolts=n, hardware=None, axis=(0, 0, 0), angles=(90.0, 270.0), hole_d=0.0))
            continue
        if k.startswith("bearing_") and k != "bearing_housing":
            parts.append((n, "bearing"))
        elif k in ("shaft", "torch_igniter"):
            parts.append((n, "solid"))
        else:
            parts.append((n, "hatch"))
    return section("tpo" if side == "ox" else "tpf", "local", (0, 0, -1), (0, -1, 0), (0, 0, 0), parts,
                   rotate_in=rot, proxies=proxies, tol=0.03)


EXTERIOR_EXCLUDE = ("faceplate", "ox_posts", "interpropellant", "turbine_disk", "rotor_blades", "stator_vanes",
                    "stator_shrouds", "bearing_1", "bearing_2", "impeller", "inducer", "_shaft", "nuts_washers",
                    "_seal", "Origin", "Axis", "Plane")


def view_ga(which):
    names = [n for n, o in OBJ.items() if group_of(o) and not any(e in n for e in EXTERIOR_EXCLUDE)]
    parts = [(n, "hlr") for n in names]
    spec = {"ga_front": ((1, 0, 0), (0, 0, 1)), "ga_side": ((0, 1, 0), (0, 0, 1)), "ga_top": ((1, 0, 0), (0, 1, 0))}[which]
    return section(which, "global", spec[0], spec[1], (0, 0, 0), parts, cut=False, tol=0.25)


VIEWS = {"tca": view_tca, "inj": view_inj, "inj_face": view_inj_face, "tpo": lambda: view_tpa("ox"), "tpf": lambda: view_tpa("fuel"),
         "ga_front": lambda: view_ga("ga_front"), "ga_side": lambda: view_ga("ga_side"), "ga_top": lambda: view_ga("ga_top")}

todo = [v for v in os.environ.get("MFE_VIEWS", ",".join(VIEWS)).split(",") if v]
for v in todo:
    rec = VIEWS[v]()
    rec["hatch"] = hatch_styles(rec)
    with open(os.path.join(OUT, f"{v}.json"), "w") as f:
        json.dump(rec, f)
    log("wrote", v)
App.closeDocument(doc.Name)
shutil.rmtree(tmp, ignore_errors=True)
