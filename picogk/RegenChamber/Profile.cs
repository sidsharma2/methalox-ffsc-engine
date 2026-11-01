using System.Globalization;

namespace RegenChamber;

/// <summary>
/// Liner cross-section at one axial position. Lengths in mm.
/// The K values are cos(local surface angle to the axis); they turn a radial
/// offset into a wall-normal distance for the signed-distance function.
/// </summary>
public readonly record struct Section(
    double R,       // gas-side (inner) radius
    double Rf,      // channel floor radius   = R  + t_hot
    double Rc,      // channel ceiling radius = Rf + H
    double Ro,      // outer closeout radius  = Rc + t_closeout
    double W,       // channel width at the floor (parallel side walls)
    double KGas,
    double KFloor,
    double KCeil,
    double KOut);

/// <summary>
/// Channel layout at one axial position: N channels around the circumference.
/// Split is 1 for plain channels. Inside a bifurcation blend (0 &lt;= Split &lt; 1)
/// each pair of the N channels still shares one parent channel at Split = 0.
/// </summary>
public readonly record struct Layout(int N, double Split);

/// <summary>
/// N -> 2N bifurcation starting at Z (mm). Over the blend length L each new pair
/// diverges from the parent channel: the splitter rib grows from a knife edge at
/// the parent centre plane to its full width, and the outer walls swing out to
/// their final angle. Every channel stays at most W wide during the blend.
/// </summary>
public readonly record struct Bifurcation(double Z, double L, int NBefore, int NAfter);

/// <summary>
/// Copper-zone (zone 0) channel geometry from the 1-D regen model.
/// Input CSVs are in metres; everything here is in mm.
/// Gas-side radius comes from the fine contour; t_hot, H, t_closeout and W are
/// linearly interpolated between sizing stations; N switches half way between the
/// two stations where it changes (the start of the bifurcation blend).
/// </summary>
public sealed class Profile
{
    const double M = 1000.0;    // m -> mm

    readonly double[] m_zC, m_rC;                       // gas-side contour
    readonly double[] m_zS, m_tHot, m_h, m_tClose, m_w; // sizing stations
    readonly double[] m_rS, m_rib;                      // station radius and rib (cross-checks only)
    readonly int[]    m_n;

    public double ZJoint  { get; }                      // bolted joint, end of zone 0
    public double ZThroat { get; }
    public double RThroat { get; }
    public IReadOnlyList<Bifurcation> Bifurcations { get; }
    public int NBase => m_n[0];

    Profile(double[] zC, double[] rC, double[] zS, double[] rS, double[] tHot, double[] h,
            double[] tClose, double[] w, double[] rib, int[] n, double zJoint, double dBlendMM)
    {
        m_zC = zC; m_rC = rC;
        m_zS = zS; m_rS = rS; m_tHot = tHot; m_h = h; m_tClose = tClose; m_w = w; m_rib = rib; m_n = n;
        ZJoint = zJoint;

        var bif = new List<Bifurcation>();
        for (int i = 1; i < n.Length; i++)
        {
            if (n[i] == n[i - 1]) continue;
            if (n[i] != 2 * n[i - 1])
                throw new InvalidDataException($"Only N -> 2N bifurcations are modelled ({n[i - 1]} -> {n[i]})");
            bif.Add(new Bifurcation(0.5 * (zS[i - 1] + zS[i]), dBlendMM, n[i - 1], n[i]));
        }
        Bifurcations = bif;

        int iT = 0;
        for (int i = 1; i < rC.Length; i++) if (rC[i] < rC[iT]) iT = i;
        ZThroat = zC[iT]; RThroat = rC[iT];
    }

    public static Profile Load(string strCoolingCsv, string strContourCsv, double dBlendMM)
    {
        var cool = ReadCsv(strCoolingCsv);
        var cont = ReadCsv(strContourCsv);

        int nZone0 = Array.FindIndex(cool["zone"], v => v != 0.0);
        if (nZone0 <= 1) throw new InvalidDataException("No copper zone (zone 0) found in cooling profile");

        // The joint is the first zone-1 station (as in ffsc/cooling.py: x_joint = x[i_joint]).
        // Channel data of the last copper station is held from there to the joint.
        double zJoint = cool["x"][nZone0] * M;
        int n = nZone0 + 1;

        double[] Take(string k, double scale, bool bValueAtJoint = false)
        {
            var a = new double[n];
            for (int i = 0; i < nZone0; i++) a[i] = cool[k][i] * scale;
            a[n - 1] = bValueAtJoint ? cool[k][nZone0] * scale : a[n - 2];
            return a;
        }

        return new Profile(
            cont["x_m"].Select(v => v * M).ToArray(),
            cont["r_m"].Select(v => v * M).ToArray(),
            Take("x", M, true), Take("r", M, true),
            Take("t_hot", M), Take("H", M), Take("t_closeout", M), Take("W", M), Take("rib", M),
            Take("N", 1.0).Select(v => (int)Math.Round(v)).ToArray(),
            zJoint, dBlendMM);
    }

    /// <summary>Liner cross-section at axial position z (mm).</summary>
    public Section oSectionAt(double z)
    {
        Interval(m_zC, z, out int iC, out double dzC, out double invC);
        Interval(m_zS, z, out int iS, out double dzS, out double invS);

        Lerp(m_rC,     iC, dzC, invC, out double r,      out double dr);
        Lerp(m_tHot,   iS, dzS, invS, out double tHot,   out double dtHot);
        Lerp(m_h,      iS, dzS, invS, out double h,      out double dh);
        Lerp(m_tClose, iS, dzS, invS, out double tClose, out double dtClose);
        Lerp(m_w,      iS, dzS, invS, out double w,      out _);

        double rf = r + tHot, rc = rf + h, ro = rc + tClose;
        double sF = dr + dtHot, sC = sF + dh, sO = sC + dtClose;   // surface slopes dr/dz

        return new Section(r, rf, rc, ro, w, K(dr), K(sF), K(sC), K(sO));
    }

    /// <summary>Channel count and bifurcation progress at z.</summary>
    public Layout oLayoutAt(double z)
    {
        int n = m_n[0];
        foreach (var b in Bifurcations)
        {
            if (z < b.Z) break;
            n = b.NAfter;
            if (z < b.Z + b.L) return new Layout(n, (z - b.Z) / b.L);
        }
        return new Layout(n, 1.0);
    }

    /// <summary>Number of channels inside a periodic sector of the given angle.</summary>
    public static int nChannelsInSector(int nTotal, double dSectorRad)
    {
        double d = nTotal * dSectorRad / (2 * Math.PI);
        int nRound = (int)Math.Round(d);
        if (Math.Abs(d - nRound) > 1e-6)
            throw new InvalidOperationException($"Sector does not hold a whole number of channels (N={nTotal})");
        return nRound;
    }

    /// <summary>
    /// Area (mm^2) of one channel between the circular floor and ceiling whose side
    /// walls are planes parallel to the channel plane at offsets -b and +a.
    /// The arc length at radius rho is rho*(asin(a/rho) + asin(b/rho)).
    /// For a plain channel a = b = W/2 and the area is W*H to within ~1e-6.
    /// </summary>
    public static double dChannelArea(in Section s, double a, double b)
    {
        static double F(double rho, double c) => c <= 0 ? 0 : rho * rho * Math.Asin(c / rho) + c * Math.Sqrt(rho * rho - c * c);
        return 0.5 * (F(s.Rc, a) - F(s.Rf, a) + F(s.Rc, b) - F(s.Rf, b));
    }

    /// <summary>Solid cross-section area (mm^2) of the sector at z.</summary>
    public double dSectorArea(double z, double dSectorRad)
    {
        Section s = oSectionAt(z);
        Layout  l = oLayoutAt(z);
        // Blend: outer wall at +W/2, splitter face at -Split*W/2 (see Bifurcation)
        double aCh = dChannelArea(s, 0.5 * s.W, 0.5 * s.W * l.Split);
        return 0.5 * dSectorRad * (s.Ro * s.Ro - s.R * s.R)
             - nChannelsInSector(l.N, dSectorRad) * aCh;
    }

    /// <summary>
    /// Analytic solid volume (mm^3) of the sector between z0 and z1: the same geometry
    /// the implicit encodes, trapezoid rule on a fine grid that includes every
    /// contour point, station and blend end as a break point.
    /// </summary>
    public double dAnalyticVolume(double z0, double z1, double dSectorRad, double dzMax = 0.005)
    {
        var brk = new SortedSet<double> { z0, z1 };
        foreach (double z in m_zC.Concat(m_zS)) if (z > z0 && z < z1) brk.Add(z);
        foreach (var b in Bifurcations)
            foreach (double z in new[] { b.Z, b.Z + b.L }) if (z > z0 && z < z1) brk.Add(z);

        double vol = 0, prev = double.NaN;
        foreach (double z in brk)
        {
            if (!double.IsNaN(prev))
            {
                int nSteps = Math.Max(1, (int)Math.Ceiling((z - prev) / dzMax));
                double dz  = (z - prev) / nSteps;
                double sum = 0.5 * (dSectorArea(prev, dSectorRad) + dSectorArea(z, dSectorRad));
                for (int i = 1; i < nSteps; i++) sum += dSectorArea(prev + i * dz, dSectorRad);
                vol += sum * dz;
            }
            prev = z;
        }
        return vol;
    }

    /// <summary>
    /// Cross-check at the 1-D model's own resolution: trapezoid over the sizing
    /// stations with the station radius and rectangular channels (N*W*H), no blend.
    /// </summary>
    public double dStationTrapezoidVolume(double dSectorRad)
    {
        double Area(int i)
        {
            double rf = m_rS[i] + m_tHot[i], rc = rf + m_h[i], ro = rc + m_tClose[i];
            return 0.5 * dSectorRad * (ro * ro - m_rS[i] * m_rS[i])
                 - nChannelsInSector(m_n[i], dSectorRad) * m_w[i] * m_h[i];
        }
        double vol = 0;
        for (int i = 1; i < m_zS.Length; i++)
            vol += 0.5 * (Area(i - 1) + Area(i)) * (m_zS[i] - m_zS[i - 1]);
        return vol;
    }

    /// <summary>Largest |rib - (2*pi*Rf/N - W)| over the stations (mm): checks the CSV is self-consistent.</summary>
    public double dRibConsistencyError()
    {
        double e = 0;
        for (int i = 0; i < m_zS.Length - 1; i++)
        {
            double pitch = 2 * Math.PI * (m_rS[i] + m_tHot[i]) / m_n[i];
            e = Math.Max(e, Math.Abs(m_rib[i] - (pitch - m_w[i])));
        }
        return e;
    }

    // ---- helpers ---------------------------------------------------------

    static double K(double slope) => 1.0 / Math.Sqrt(1.0 + slope * slope);

    /// <summary>
    /// Interval lo with xs[lo] &lt;= x &lt; xs[lo+1], offset dx = x - xs[lo] and 1/(xs[lo+1] - xs[lo]).
    /// Outside the data range inv = 0, so values are held constant with zero slope.
    /// </summary>
    static void Interval(double[] xs, double x, out int lo, out double dx, out double inv)
    {
        if (x <= xs[0])  { lo = 0;             dx = 0; inv = 0; return; }
        if (x >= xs[^1]) { lo = xs.Length - 1; dx = 0; inv = 0; return; }

        lo = 0;
        int hi = xs.Length - 1;
        while (hi - lo > 1)
        {
            int mid = (lo + hi) >> 1;
            if (xs[mid] <= x) lo = mid; else hi = mid;
        }
        dx  = x - xs[lo];
        inv = 1.0 / (xs[lo + 1] - xs[lo]);
    }

    /// <summary>Piecewise-linear value and slope on the interval found by Interval.</summary>
    static void Lerp(double[] ys, int lo, double dx, double inv, out double y, out double dydx)
    {
        dydx = inv == 0 ? 0 : (ys[lo + 1] - ys[lo]) * inv;
        y    = ys[lo] + dydx * dx;
    }

    static Dictionary<string, double[]> ReadCsv(string strPath)
    {
        string[] lines = File.ReadAllLines(strPath).Where(l => l.Trim().Length > 0).ToArray();
        string[] head  = lines[0].Split(',').Select(s => s.Trim()).ToArray();
        var cols = head.ToDictionary(h => h, _ => new double[lines.Length - 1]);
        for (int i = 1; i < lines.Length; i++)
        {
            string[] f = lines[i].Split(',');
            for (int j = 0; j < head.Length; j++)
                cols[head[j]][i - 1] = double.Parse(f[j], NumberStyles.Float, CultureInfo.InvariantCulture);
        }
        return cols;
    }
}
