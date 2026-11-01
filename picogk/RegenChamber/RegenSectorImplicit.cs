using System.Numerics;
using PicoGK;

namespace RegenChamber;

/// <summary>
/// Signed distance (mm, negative inside the copper) of a periodic angular sector
/// of the regeneratively cooled liner: liner + ribs + closeout, with the cooling
/// channels as voids.
///
/// Frame: Z is the engine axis (z = 0 at the injector face, increasing downstream).
/// The sector spans theta = 0 .. SectorRad, measured from +X towards +Y. Channel k
/// of N is centred at (k + 0.5) * 2*pi/N, so both cut planes pass through rib centres.
/// Channels have parallel side walls (width W) and a circular floor and ceiling.
/// With full = false the cut planes are dropped (full 360 deg ring).
/// </summary>
public sealed class RegenSectorImplicit : IImplicit
{
    readonly Profile m_prof;
    readonly double  m_sin, m_cos;
    readonly bool    m_bSector;

    public double SectorRad { get; }
    public double Z0 { get; }
    public double Z1 { get; }

    public RegenSectorImplicit(Profile prof, double z0, double z1, double dSectorRad)
    {
        m_prof    = prof;
        Z0        = z0;
        Z1        = z1;
        SectorRad = dSectorRad;
        m_bSector = dSectorRad < 2 * Math.PI - 1e-9;
        m_sin     = Math.Sin(dSectorRad);
        m_cos     = Math.Cos(dSectorRad);
    }

    /// <summary>Same part, cut to a shorter axial range.</summary>
    public RegenSectorImplicit(RegenSectorImplicit other, double z0, double z1)
        : this(other.m_prof, z0, z1, other.SectorRad) { }

    public float fSignedDistance(in Vector3 vec) => (float)dSignedDistance(vec.X, vec.Y, vec.Z);

    public double dSignedDistance(double x, double y, double z)
    {
        Section s  = m_prof.oSectionAt(z);
        double rho = Math.Sqrt(x * x + y * y);

        // Envelope: annulus between gas wall and closeout, two end planes, two radial cut planes
        double dSolid = Math.Max((s.R - rho) * s.KGas, (rho - s.Ro) * s.KOut);
        dSolid = Math.Max(dSolid, Math.Max(Z0 - z, z - Z1));
        if (m_bSector)
            dSolid = Math.Max(dSolid, Math.Max(-y, y * m_cos - x * m_sin));

        // Subtract the nearest channel
        return Math.Max(dSolid, -dChannel(x, y, rho, s, m_prof.oLayoutAt(z)));
    }

    /// <summary>
    /// Distance to the nearest channel in the cross-section, as a rectangle in
    /// (offset from the channel plane, radius). In a bifurcation blend the channel
    /// plane is rotated part way from the parent centre towards its final angle and
    /// the splitter-side wall moves out from the parent centre plane.
    /// </summary>
    static double dChannel(double x, double y, double rho, in Section s, Layout lay)
    {
        double pitch = 2.0 * Math.PI / lay.N;
        int    k     = (int)Math.Floor(Math.Atan2(y, x) / pitch);    // angular bin of the nearest channel

        double alpha, centre = 0, half = 0.5 * s.W;
        if (lay.Split >= 1.0)
        {
            alpha = (k + 0.5) * pitch;
        }
        else
        {
            // Pair (2m, 2m+1) shares parent channel m centred at (2m + 1) * pitch
            int    sign   = (k & 1) == 1 ? 1 : -1;
            double parent = ((k >> 1) * 2 + 1) * pitch;
            alpha  = parent + sign * lay.Split * 0.5 * pitch;
            // walls at sign*v = +W/2 (outer) and -Split*W/2 (splitter face)
            centre = sign * 0.25 * s.W * (1.0 - lay.Split);
            half   = 0.25 * s.W * (1.0 + lay.Split);
        }

        (double sinA, double cosA) = Math.SinCos(alpha);
        double v     = -x * sinA + y * cosA;                          // offset from the channel plane
        double dSide = Math.Abs(v - centre) - half;
        double dRad  = Math.Max((s.Rf - rho) * s.KFloor, (rho - s.Rc) * s.KCeil);

        double ox = Math.Max(dSide, 0.0), oy = Math.Max(dRad, 0.0);
        return Math.Sqrt(ox * ox + oy * oy) + Math.Min(Math.Max(dSide, dRad), 0.0);
    }

    /// <summary>Axis-aligned bounds (mm) of the part between za and zb, grown by dMargin.</summary>
    public BBox3 oBounds(double za, double zb, double dMargin)
    {
        double rMin = double.MaxValue, rMax = 0;
        int nSamples = Math.Max(2, (int)Math.Ceiling((zb - za) / 0.05) + 1);
        for (int i = 0; i < nSamples; i++)
        {
            Section s = m_prof.oSectionAt(za + (zb - za) * i / (nSamples - 1));
            rMin = Math.Min(rMin, s.R);
            rMax = Math.Max(rMax, s.Ro);
        }

        if (!m_bSector)
            return new BBox3((float)(-rMax - dMargin), (float)(-rMax - dMargin), (float)za,
                             (float)( rMax + dMargin), (float)( rMax + dMargin), (float)zb);

        return new BBox3((float)(rMin * m_cos - dMargin), (float)(-dMargin), (float)za,
                         (float)(rMax + dMargin), (float)(rMax * m_sin + dMargin), (float)zb);
    }
}
