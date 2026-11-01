using System.Numerics;
using System.Text.Json.Nodes;
using PicoGK;

namespace RegenChamber;

/// <summary>
/// Voxel occupancy through Voxels.bIsInside, which tests the voxel nearest to the
/// point: it shows which voxels are copper and steps in whole voxels.
/// Sub-voxel wall positions are taken from the extracted mesh instead (ProbeLine).
/// Voxels.GetVoxelSlice, bRayCastToSurface and bClosestPointOnSurface were tried
/// first and are not used: the slice buffer did not map to world XY as the source
/// suggests, and ray and closest-point hits were 0.1-0.3 mm off at 0.15 mm.
/// </summary>
public sealed class FieldProbe(Voxels vox)
{
    public bool bSolid(double x, double y, double z)
        => vox.bIsInside(new Vector3((float)x, (float)y, (float)z));

    /// <summary>Distances from p0 (mm) along p0 -> p1 at height z where occupancy changes.</summary>
    public List<double> Crossings(Vector2 p0, Vector2 p1, double z, double dStep)
    {
        double len  = Vector2.Distance(p0, p1);
        Vector2 dir = (p1 - p0) / (float)len;
        bool At(double t) { Vector2 p = p0 + dir * (float)t; return bSolid(p.X, p.Y, z); }

        var res = new List<double>();
        int n = Math.Max(2, (int)Math.Ceiling(len / dStep));
        bool prev = At(0);
        for (int k = 1; k <= n; k++)
        {
            bool cur = At(len * k / n);
            if (cur != prev) res.Add(len * (k - 0.5) / n);
            prev = cur;
        }
        return res;
    }
}

/// <summary>
/// Straight probe segment A -> B in the plane z = Z. MeshCheck cuts every triangle
/// that spans that plane and passes the cut here; Hits are the distances from A
/// (mm) where the extracted surface crosses the segment.
/// </summary>
public sealed class ProbeLine(Vector2 a, Vector2 b, double z)
{
    public readonly Vector2 A = a, B = b;
    public readonly double  Z = z;
    public readonly List<double> Hits = new();

    public double Length => Vector2.Distance(A, B);

    /// <summary>Record the crossing with the 2-D segment P -> Q, if any.</summary>
    public void Intersect(double px, double py, double qx, double qy)
    {
        double rx = B.X - A.X, ry = B.Y - A.Y;          // along the probe
        double sx = qx - px,   sy = qy - py;            // along the triangle cut
        double den = rx * sy - ry * sx;
        if (den == 0) return;
        double ax = px - A.X, ay = py - A.Y;
        double t = (ax * sy - ay * sx) / den;
        double u = (ax * ry - ay * rx) / den;
        if (t >= 0 && t <= 1 && u >= 0 && u < 1) Hits.Add(t * Length);
    }
}

/// <summary>
/// Minimum-feature retention at one axial station.
/// Occupancy (nearest voxel): channel voids counted on the mid-height arc, and
/// gas | wall | channel | closeout | outside on the radial line through every
/// channel centre. Dimensions (sub-voxel): the same radial lines and one line
/// across every channel at mid height are intersected with the extracted mesh.
/// Everything is compared with the analytic section at the same z.
/// </summary>
public sealed class StationProbe
{
    readonly Section m_s;
    readonly Layout  m_lay;
    readonly int     m_nExp;
    readonly double  m_z, m_h, m_sectorRad;
    readonly List<ProbeLine> m_radial = new(), m_across = new();
    readonly List<double>    m_hotOcc = new();
    int m_nVoids, m_nBadOccupancy;

    public IEnumerable<ProbeLine> Lines => m_radial.Concat(m_across);

    public StationProbe(Profile prof, RegenSectorImplicit imp, double z, double h)
    {
        m_s   = prof.oSectionAt(z);
        m_lay = prof.oLayoutAt(z);
        if (m_lay.Split < 1.0) throw new ArgumentException("Probe stations must lie outside a bifurcation blend");
        m_z = z; m_h = h; m_sectorRad = imp.SectorRad;
        m_nExp = Profile.nChannelsInSector(m_lay.N, imp.SectorRad);

        double pitch = 2 * Math.PI / m_lay.N, rMid = 0.5 * (m_s.Rf + m_s.Rc);
        for (int j = 0; j < m_nExp; j++)
        {
            double phi = (j + 0.5) * pitch;
            var u = new Vector2((float)Math.Cos(phi), (float)Math.Sin(phi));
            var v = new Vector2(-u.Y, u.X);
            m_radial.Add(new ProbeLine(u * (float)(m_s.R - 1.5), u * (float)(m_s.Ro + 1.5), z));
            float half = (float)(0.49 * rMid * pitch);              // ends inside the neighbouring ribs
            m_across.Add(new ProbeLine(u * (float)rMid - v * half, u * (float)rMid + v * half, z));
        }
    }

    /// <summary>Occupancy checks on the voxel field (call before the field is disposed).</summary>
    public void MeasureOccupancy(Voxels vox)
    {
        var probe = new FieldProbe(vox);
        double rMid = 0.5 * (m_s.Rf + m_s.Rc), step = m_h / 4;

        // Channel voids on the mid-height arc; the ends stay two voxels inside the cut planes
        double th0 = 2 * m_h / rMid, th1 = m_sectorRad - th0;
        int nArc = (int)Math.Ceiling(rMid * (th1 - th0) / step);
        bool bPrevVoid = false;
        for (int k = 0; k <= nArc; k++)
        {
            double th = th0 + (th1 - th0) * k / nArc;
            bool bVoid = !probe.bSolid(rMid * Math.Cos(th), rMid * Math.Sin(th), m_z);
            if (bVoid && !bPrevVoid) m_nVoids++;
            bPrevVoid = bVoid;
        }

        foreach (ProbeLine l in m_radial)
        {
            var c = probe.Crossings(l.A, l.B, m_z, step);
            if (c.Count == 4) m_hotOcc.Add(c[1] - c[0]);
            else m_nBadOccupancy++;
        }
    }

    /// <summary>Summary, once MeshCheck has filled the line hits.</summary>
    public JsonObject ToJson()
    {
        var hot = new List<double>(); var hgt = new List<double>();
        var clo = new List<double>(); var wid = new List<double>();
        int nBadMesh = 0;
        foreach (ProbeLine l in m_radial)
        {
            var c = l.Hits.Order().ToList();
            if (c.Count != 4) { nBadMesh++; continue; }
            hot.Add(c[1] - c[0]);
            hgt.Add(c[2] - c[1]);
            clo.Add(c[3] - c[2]);
        }
        foreach (ProbeLine l in m_across)
        {
            var c = l.Hits.Order().ToList();
            if (c.Count != 2) { nBadMesh++; continue; }
            wid.Add(c[1] - c[0]);
        }

        double tHot = m_s.Rf - m_s.R;
        bool bRetained = m_nVoids == m_nExp && m_nBadOccupancy == 0 && nBadMesh == 0
                      && hot.All(t => Math.Abs(t - tHot) <= 0.5 * m_h)
                      && wid.All(w => Math.Abs(w - m_s.W) <= 0.5 * m_h);

        return new JsonObject
        {
            ["z_mm"]                      = R(m_z),
            ["N_total"]                   = m_lay.N,
            ["channels_expected"]         = m_nExp,
            ["channels_counted"]          = m_nVoids,
            ["radial_occupancy_failures"] = m_nBadOccupancy,
            ["mesh_line_failures"]        = nBadMesh,
            ["hot_wall_nominal_mm"]       = R(tHot),
            ["hot_wall_nominal_voxels"]   = R(tHot / m_h),
            ["hot_wall_mm"]               = Stats(hot),
            ["hot_wall_occupied_mm"]      = Stats(m_hotOcc),
            ["channel_width_nominal_mm"]  = R(m_s.W),
            ["channel_width_mm"]          = Stats(wid),
            ["channel_height_nominal_mm"] = R(m_s.Rc - m_s.Rf),
            ["channel_height_mm"]         = Stats(hgt),
            ["closeout_nominal_mm"]       = R(m_s.Ro - m_s.Rc),
            ["closeout_mm"]               = Stats(clo),
            ["retained"]                  = bRetained,
            ["criterion"] = "every channel counted on the mid-height arc and gas|wall|channel|closeout|outside " +
                            "on every radial line (nearest-voxel occupancy); hot wall and channel width measured " +
                            "on the extracted mesh within half a voxel of nominal"
        };
    }

    static JsonObject Stats(List<double> a) => a.Count == 0
        ? new JsonObject { ["n"] = 0 }
        : new JsonObject { ["n"] = a.Count, ["min"] = R(a.Min()), ["mean"] = R(a.Average()), ["max"] = R(a.Max()) };

    static double R(double v) => Math.Round(v, 4);
}
