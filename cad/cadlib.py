"""Geometry primitives for the engine assembly (FreeCAD Part workbench, units mm).

Every builder returns a Part.Shape in a local frame with its axis along +z unless the
docstring says otherwise. Placement into the assembly happens in build_engine.py.
"""

import math

import FreeCAD as App
import Part
from FreeCAD import Vector as V

# ISO 4032 nut height ~0.84 d, ISO 7089 washer OD ~2 d, thickness ~0.16 d
HEX_K = 0.65         # head height / d


def rot_to(direction):
    """Rotation that maps +z onto direction."""
    d = V(direction)
    d.normalize()
    return App.Rotation(V(0, 0, 1), d)


def placed(shape, base=V(0, 0, 0), direction=V(0, 0, 1), spin_deg=0.0):
    """Copy of shape (built along +z) spun about z, aligned to direction, moved to base."""
    s = shape.copy()
    if spin_deg:
        s.rotate(V(0, 0, 0), V(0, 0, 1), spin_deg)
    s.Placement = App.Placement(V(base), rot_to(direction)).multiply(s.Placement)
    return s


def cyl(r, h, z0=0.0):
    return Part.makeCylinder(r, h, V(0, 0, z0))


def tube(r_in, r_out, h, z0=0.0):
    return cyl(r_out, h, z0).cut(cyl(r_in, h + 2, z0 - 1))


def hexagon(af, h, z0=0.0):
    r = af / 2 / math.cos(math.radians(30))
    pts = [V(r * math.cos(math.radians(30 + 60 * i)), r * math.sin(math.radians(30 + 60 * i)), z0) for i in range(7)]
    return Part.Face(Part.makePolygon(pts)).extrude(V(0, 0, h))


def revolve_rz(pts, angle=360.0):
    """Revolve a closed polygon given as (r, z) pairs about the z axis."""
    vs = [V(r, 0, z) for r, z in pts]
    if (vs[0] - vs[-1]).Length > 1e-9:
        vs.append(vs[0])
    face = Part.Face(Part.makePolygon(vs))
    return face.revolve(V(0, 0, 0), V(0, 0, 1), angle)


def revolve_splines(inner, outer, angle=360.0):
    """Solid of revolution between two (r, z) polylines that share end stations."""
    ei = Part.BSplineCurve()
    ei.interpolate([V(r, 0, z) for r, z in inner])
    eo = Part.BSplineCurve()
    eo.interpolate([V(r, 0, z) for r, z in outer])
    a = Part.LineSegment(V(inner[0][0], 0, inner[0][1]), V(outer[0][0], 0, outer[0][1]))
    b = Part.LineSegment(V(inner[-1][0], 0, inner[-1][1]), V(outer[-1][0], 0, outer[-1][1]))
    wire = Part.Wire(Part.__sortEdges__([ei.toShape(), b.toShape(), eo.toShape(), a.toShape()]))
    return Part.Face(wire).revolve(V(0, 0, 0), V(0, 0, 1), angle)


def torus(R, r):
    return Part.makeTorus(R, r)


def torus_tube(R, r_out, wall):
    return Part.makeTorus(R, r_out).cut(Part.makeTorus(R, r_out - wall))


# ---------------------------------------------------------------- fasteners

def bolt(d, length, af):
    """Hex bolt, head on top (z = 0 .. k), shank down to z = -length."""
    head = hexagon(af, HEX_K * d)
    shank = cyl(d / 2, length, -length)
    return head.fuse(shank).removeSplitter()


def nut(d, af):
    return hexagon(af, 0.84 * d).cut(cyl(d / 2, 0.84 * d + 2, -1))


def washer(d, t=None):
    t = t or 0.16 * d
    return tube(0.55 * d, 1.0 * d, t)


def bolt_circle_holes(n, bcd, d_hole, h, z0, phase_deg=0.0):
    holes = []
    for i in range(n):
        a = math.radians(phase_deg + 360.0 * i / n)
        holes.append(cyl(d_hole / 2, h + 2, z0 - 1).translate(V(bcd / 2 * math.cos(a), bcd / 2 * math.sin(a), 0)))
    return Part.makeCompound(holes)


def flange_ring(r_bore, od, t, n, bcd, d_bolt, z0=0.0, phase_deg=None):
    """Flat flange ring along +z from z0 with a drilled bolt circle."""
    phase = 180.0 / n if phase_deg is None else phase_deg
    ring = tube(r_bore, od / 2, t, z0)
    return ring.cut(bolt_circle_holes(n, bcd, d_bolt * 1.1, t, z0, phase))


def bolt_set(n, bcd, d, af, grip, z_top, phase_deg=None, with_nuts=True, flip=False):
    """Through-bolts on a circle: washer + head on z_top, nut + washer below the grip.
    flip=True mirrors the set about z_top (head below the face, shank going up), for
    screws inserted from underneath a flange. Returns (bolts, nuts_and_washers) compounds."""
    phase = 180.0 / n if phase_deg is None else phase_deg
    tw = 0.16 * d
    length = grip + 2 * tw + (0.84 * d + 1.5 * 2.0 if with_nuts else 0.0) + 2.0
    b0 = bolt(d, length, af).translate(V(0, 0, z_top + tw))
    hw = [washer(d).translate(V(0, 0, z_top))]
    if with_nuts:
        hw.append(washer(d).translate(V(0, 0, z_top - grip - tw)))
        hw.append(nut(d, af).translate(V(0, 0, z_top - grip - tw - 0.84 * d)))
    hw0 = Part.makeCompound(hw)
    if flip:
        m = App.Matrix()
        m.move(V(0, 0, -z_top))
        m.scale(1, 1, -1)
        m.move(V(0, 0, z_top))
        b0, hw0 = b0.transformGeometry(m), hw0.transformGeometry(m)
    bolts, rest = [], []
    for i in range(n):
        ang = phase + 360.0 * i / n
        a = math.radians(ang)
        off = V(bcd / 2 * math.cos(a), bcd / 2 * math.sin(a), 0)
        bolts.append(b0.copy().translate(off))
        rest.append(hw0.copy().translate(off))
    return Part.makeCompound(bolts), Part.makeCompound(rest)


# ---------------------------------------------------------------- piping

def route_wire(points, bend_r):
    """Polyline with circular fillets of radius bend_r at every interior vertex."""
    P = [V(p) for p in points]
    edges = []
    start = P[0]
    for i in range(1, len(P) - 1):
        a, b, c = P[i - 1], P[i], P[i + 1]
        u1 = (b - a)
        u1.normalize()
        u2 = (c - b)
        u2.normalize()
        cosang = max(-1.0, min(1.0, u1.dot(u2)))
        theta = math.acos(cosang)
        if theta < 1e-6:
            continue
        t = bend_r * math.tan(theta / 2)
        t = min(t, 0.45 * (b - a).Length, 0.45 * (c - b).Length)
        p1 = b - u1 * t
        p2 = b + u2 * t
        bis = (u2 - u1)
        bis.normalize()
        r_eff = t / math.tan(theta / 2)
        mid = b + bis * (r_eff / math.cos(theta / 2) - r_eff)
        if (p1 - start).Length > 1e-6:
            edges.append(Part.LineSegment(start, p1).toShape())
        edges.append(Part.Arc(p1, mid, p2).toShape())
        start = p2
    edges.append(Part.LineSegment(start, P[-1]).toShape())
    return Part.Wire(edges)


def pipe_solid(points, d, bend_r=None):
    """Solid swept cylinder along a filleted polyline (outer envelope of a pipe)."""
    w = route_wire(points, bend_r or 1.5 * d)
    e0 = w.Edges[0]
    c = Part.Wire(Part.makeCircle(d / 2, e0.valueAt(e0.FirstParameter), e0.tangentAt(e0.FirstParameter)))
    return w.makePipeShell([c], True, True)


def pipe(points, d_out, wall, bend_r=None):
    """Hollow swept tube along a filleted polyline."""
    bend_r = bend_r or 1.5 * d_out
    return pipe_solid(points, d_out, bend_r).cut(pipe_solid(points, d_out - 2 * wall, bend_r))


def pipe_flange(joint, d_pipe, t_scale=1.0):
    """Weld-neck style flange along +z, bore = pipe OD, sized from a joint record."""
    od, t = joint["flange_od_m"] * 1e3, joint["flange_t_m"] * 1e3 * t_scale
    return flange_ring(d_pipe / 2, od, t, joint["n_bolts"], joint["bcd_m"] * 1e3, joint["d_m"] * 1e3)


def flanged_pair(joint, d_pipe):
    """Two mating flanges (z = -t .. t) with bolts, washers and nuts. Returns dict of shapes."""
    t = joint["flange_t_m"] * 1e3
    f = pipe_flange(joint, d_pipe)
    upper = f.copy()
    lower = f.copy().translate(V(0, 0, -t))
    gasket = tube(d_pipe / 2, d_pipe / 2 + 4.0, 0.8, -0.4)
    bolts, hw = bolt_set(joint["n_bolts"], joint["bcd_m"] * 1e3, joint["d_m"] * 1e3,
                         joint["across_flats_m"] * 1e3, 2 * t, t)
    return {"flanges": upper.fuse(lower), "seal": gasket, "bolts": bolts, "hardware": hw}


# ---------------------------------------------------------------- turbomachinery

def impeller(D2, b2, D_eye, D_hub, n_blades=6, splitters=True, bore=None):
    """Shrouded centrifugal impeller; flow enters along -z at the eye, exits radially.
    Hub disc at z = 0 .. t_hub, blades z = t_hub .. t_hub + b2, shroud on top.
    bore: shaft diameter (hub bore); the hub keeps at least 8 mm of wall around it."""
    R2, Re = D2 / 2, D_eye / 2
    rb = (bore / 2) if bore else 0.55 * D_hub / 2
    Rh = max(D_hub / 2, rb + 8.0)
    t_hub = 0.06 * D2
    t_sh = 0.03 * D2
    hub = revolve_rz([(rb, 0), (R2, 0), (R2, t_hub * 0.5), (Re, t_hub), (Rh, t_hub + 0.5 * b2), (rb, t_hub + 0.5 * b2)])
    shroud = revolve_rz([(Re + 2, t_hub + b2), (R2, t_hub + b2), (R2, t_hub + b2 + t_sh), (Re + t_sh, t_hub + b2 + 2.2 * t_sh), (Re, t_hub + b2 + 2.2 * t_sh)])
    blades = []
    beta2 = math.radians(25.0)                     # backswept outlet angle from tangential
    k = 1 / math.tan(beta2)

    def blade(r0, n_pts=12):
        pts_p, pts_s = [], []
        th_w = 0.012 * D2
        for i in range(n_pts):
            r = r0 + (R2 - r0) * i / (n_pts - 1)
            th = -k * math.log(r / r0)             # logarithmic spiral
            for lst, off in [(pts_p, +th_w / 2 / r), (pts_s, -th_w / 2 / r)]:
                lst.append(V(r * math.cos(th + off), r * math.sin(th + off), 0))
        poly = Part.makePolygon(pts_p + list(reversed(pts_s)) + [pts_p[0]])
        return Part.Face(poly).extrude(V(0, 0, b2 + 1.0)).translate(V(0, 0, t_hub - 0.5))

    full = blade(Re * 0.95)
    split = blade(0.5 * (Re + R2))
    for i in range(n_blades):
        ang = 360.0 * i / n_blades
        blades.append(full.copy().rotate(V(0, 0, 0), V(0, 0, 1), ang))
        if splitters:
            blades.append(split.copy().rotate(V(0, 0, 0), V(0, 0, 1), ang + 180.0 / n_blades))
    return {"hub": hub, "shroud": shroud, "blades": Part.makeCompound(blades), "height": t_hub + b2 + 2.2 * t_sh}


def inducer(D, D_hub, pitch, length, n_blades=3, t_blade=None, bore=0.0):
    """Axial inducer along +z: hub (bored for the shaft stub) plus helical blades (ruled
    surface between hub and tip helices, extruded axially by the blade thickness)."""
    t_blade = t_blade or 0.02 * D
    hub = cyl(D_hub / 2, length).fuse(Part.makeCone(D_hub / 2, 0.2 * D_hub, 0.6 * D_hub, V(0, 0, length)))
    if bore:
        hub = hub.cut(cyl(bore / 2, length + 1.0, -0.5))
    blades = []
    for i in range(n_blades):
        h_tip = Part.makeHelix(pitch, length * 0.9, D / 2 - 0.5)
        h_hub = Part.makeHelix(pitch, length * 0.9, D_hub / 2 - 0.5)
        face = Part.makeRuledSurface(h_hub, h_tip)
        b = face.extrude(V(0, 0, t_blade))
        b = b.Solids[0] if b.Solids else b
        b.rotate(V(0, 0, 0), V(0, 0, 1), 360.0 * i / n_blades)
        blades.append(b)
    return {"hub": hub, "blades": Part.makeCompound(blades)}


def axial_blade_row(D_mean, h, n, chord, camber_deg, stagger_deg, z0=0.0):
    """Row of simple cambered blades (arc camber line with parabolic thickness) between
    r = Dm/2 - h/2 and Dm/2 + h/2, axial extent ~chord, built at z0."""
    r_hub = D_mean / 2 - h / 2
    pts_u, pts_l = [], []
    t_max = 0.12 * chord
    cam = math.radians(camber_deg)
    for i in range(11):
        s = i / 10
        y = chord * s
        x = 0.25 * chord * math.sin(cam) * 4 * s * (1 - s)
        t = t_max * 2 * math.sqrt(max(s * (1 - s), 1e-6)) / 1.0
        pts_u.append((x + t / 2, y))
        pts_l.append((x - t / 2, y))
    loop = pts_u + list(reversed(pts_l))
    st = math.radians(stagger_deg)
    vs = []
    for x, y in loop:
        xr = x * math.cos(st) - (y - chord / 2) * math.sin(st)
        yr = x * math.sin(st) + (y - chord / 2) * math.cos(st)
        vs.append(V(xr, 0, z0 + chord / 2 + yr))      # x = circumferential, z = axial
    vs.append(vs[0])
    face = Part.Face(Part.makePolygon(vs))
    blade = face.extrude(V(0, h + 0.6, 0)).translate(V(0, r_hub - 0.3, 0))  # radial along +y
    blades = [blade.copy().rotate(V(0, 0, 0), V(0, 0, 1), 360.0 * i / n) for i in range(n)]
    return Part.makeCompound(blades)


def turbine_disk(D_mean, h, bore, thickness):
    r_rim = D_mean / 2 - h / 2
    return revolve_rz([(bore / 2, -thickness * 0.8), (r_rim * 0.55, -thickness * 0.8), (r_rim * 0.7, -thickness * 0.35),
                       (r_rim, -thickness * 0.35), (r_rim, thickness * 0.35), (r_rim * 0.7, thickness * 0.35),
                       (r_rim * 0.55, thickness * 0.8), (bore / 2, thickness * 0.8)])


def volute(R_base, r_throat, z, discharge_len, neck_r, wall, neck_len=60.0):
    """Spiral volute approximated by a torus whose tube grows over 360 deg, then a
    tangential diffuser cone along +y ending in a straight neck of outer radius neck_r
    (the discharge pipe OD, so the flange fits). Hollow, wall `wall`."""
    n = 12
    r_end = 1.25 * r_throat
    L1 = discharge_len - neck_len
    x_axis = R_base + r_end + wall

    def body(dr):
        segs = []
        for i in range(n):
            a0, a1 = 360.0 * i / n, 360.0 * (i + 1) / n
            r = r_throat * math.sqrt((i + 1) / n) + 0.25 * r_throat
            seg = Part.makeTorus(R_base + r + wall, r + dr, V(0, 0, z), V(0, 0, 1), -180, 180, a1 - a0 + 0.5)
            seg.rotate(V(0, 0, 0), V(0, 0, 1), a0 - 90.0)
            segs.append(seg)
        b = segs[0].fuse(segs[1:])
        r_neck = neck_r - wall + dr
        cone = Part.makeCone(r_end + dr, r_neck, L1, V(x_axis, 0, z), V(0, 1, 0))
        neck = Part.makeCylinder(r_neck, neck_len + (0 if dr > 0 else 1), V(x_axis, L1, z), V(0, 1, 0))
        return b.fuse([cone, neck])
    return body(wall).cut(body(0.0)).removeSplitter()
