"""Analytic regen-channel cross-section for the TCA sheet (detail at the throat).

The geometry follows picogk/README.md: the hot wall t_hot sits on the gas-side radius r, the
channel floor is the circle r + t_hot, the ceiling r + t_hot + H, the closeout t_closeout on top.
Channel k of N is centred at k 2 pi / N; its side walls are planes parallel to the channel
centre plane at +/- W/2, so W is constant from floor to ceiling and the ribs widen with radius.
Radial direction is drawn to the right. The channel height is shown broken.
"""

import math

import mech_lib as ml


def draw(s, x0, yc, row, scale=10.0, lo_pitch=-0.5, hi_pitch=1.5, keep=1.5, gap=5.0, hatch_sp=2.0):
    """Draw the section between polar angles lo_pitch and hi_pitch (in channel pitches, channel 0
    at angle 0) with the hot surface at paper x0 and channel 0 on the line y = yc."""
    r, t, H, tc = ml.mm(row["r"]), ml.mm(row["t_hot"]), ml.mm(row["H"]), ml.mm(row["t_closeout"])
    W, N = ml.mm(row["W"]), int(round(row["N"]))
    dth = 2 * math.pi / N
    cut = H - 2 * keep
    r_f, r_c, r_o = r + t, r + t + H, r + t + H + tc
    lo, hi = r_f + keep, r_c - keep                       # radii at the two break lines
    a_lo, a_hi = lo_pitch * dth, hi_pitch * dth

    def X(rho):                                           # radial distance from the hot surface -> paper x
        if rho <= t + keep + 1e-9:
            return x0 + rho * scale
        return x0 + (rho - cut) * scale + gap

    def P(R, th):
        return (X(R * math.cos(th) - r), yc + R * math.sin(th) * scale)

    def arc(R, a0, a1, n=40):
        return [P(R, a0 + (a1 - a0) * i / n) for i in range(n + 1)]

    def wall_angle(k, sgn, R):
        """Polar angle of the side wall (offset sgn W/2 from channel k's centre plane) at radius R."""
        return k * dth + math.asin(sgn * W / 2 / R)

    half = math.asin(W / 2 / r_f)
    ks = [k for k in range(-4, 5) if k * dth - half > a_lo and k * dth + half < a_hi]

    # hatched regions: hot wall, ribs (each side of the break), closeout
    s.hatch([arc(r, a_lo, a_hi) + list(reversed(arc(r_f, a_lo, a_hi)))], angle=45.0, spacing=hatch_sp)
    for R0, R1 in ((r_f, lo), (hi, r_c)):
        starts = [(a_lo, a_lo)] + [(wall_angle(k, +1, R0), wall_angle(k, +1, R1)) for k in ks]
        stops = [(wall_angle(k, -1, R0), wall_angle(k, -1, R1)) for k in ks] + [(a_hi, a_hi)]
        for (a0_0, a0_1), (a1_0, a1_1) in zip(starts, stops):
            poly = arc(R0, a0_0, a1_0, 10) + list(reversed(arc(R1, a0_1, a1_1, 10)))
            s.hatch([poly], angle=45.0, spacing=hatch_sp)
    s.hatch([arc(r_c, a_lo, a_hi) + list(reversed(arc(r_o, a_lo, a_hi)))], angle=135.0, spacing=hatch_sp)

    # outlines
    s.poly(arc(r, a_lo, a_hi), "VISIBLE")
    s.poly(arc(r_o, a_lo, a_hi), "VISIBLE")
    s.poly(arc(r_c, a_lo, a_hi), "VISIBLE")               # liner / closeout interface (two materials)
    for k in ks:
        for R0, R1 in ((r_f, lo), (hi, r_c)):
            for sg in (-1, 1):
                s.poly([P(R0, wall_angle(k, sg, R0)), P(R1, wall_angle(k, sg, R1))], "VISIBLE")
        s.poly(arc(r_f, wall_angle(k, -1, r_f), wall_angle(k, +1, r_f), 6), "VISIBLE")
    # partial-view boundaries and the break across H (thin, zigzag)
    for a in (a_lo, a_hi):
        for R0, R1 in ((r, lo), (hi, r_o)):
            ml.break_line(s, P(R0, a), P(R1, a), amp=1.0)
    for R in (lo, hi):
        ml.break_line(s, P(R, a_lo - 0.1 * dth), P(R, a_hi + 0.1 * dth), amp=1.0)
    return dict(r=r, t=t, H=H, tc=tc, W=W, N=N, dth=dth, r_f=r_f, r_c=r_c, r_o=r_o, a_lo=a_lo, a_hi=a_hi,
                P=P, X=X, lo=lo, hi=hi, wall_angle=wall_angle, ks=ks)
