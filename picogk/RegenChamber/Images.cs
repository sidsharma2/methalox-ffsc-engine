using PicoGK;

namespace RegenChamber;

/// <summary>
/// Pictures for the documentation. Copper = voxel centre inside (nearest voxel,
/// so the voxel staircase is visible), light = void, thin dark-blue line =
/// boundary of the analytic implicit. A 1 mm scale bar sits bottom left.
/// </summary>
public static class SliceImage
{
    /// <summary>Cross-section at the voxel plane nearest to zTarget.</summary>
    public static string strSave(Voxels vox, RegenSectorImplicit imp, Profile prof, double zTarget,
                                 double h, string strPath)
    {
        double z  = Math.Round(zTarget / h) * h;            // voxel centres sit at integer multiples of h
        Section s = prof.oSectionAt(z);
        double xMin = s.R * Math.Cos(imp.SectorRad) - 1.0, xMax = s.Ro + 1.0;
        double yMin = -1.0, yMax = s.Ro * Math.Sin(imp.SectorRad) + 1.0;

        return strRender(imp, xMin, xMax, yMin, yMax, strPath,
                         (x, y) => (x, y, z),
                         (x, y) => (Math.Round(x / h) * h, Math.Round(y / h) * h, z),
                         new FieldProbe(vox), bScaleBar: true);
    }

    /// <summary>
    /// Developed view on the mid-height cylinder around a bifurcation:
    /// horizontal = z, vertical = arc length (theta scaled by the largest mid radius).
    /// Voxels are sampled where the mapped point falls (not snapped).
    /// </summary>
    public static string strSaveUnrolled(Voxels vox, RegenSectorImplicit imp, Profile prof,
                                         double za, double zb, string strPath)
    {
        double rRef = 0;
        for (int i = 0; i <= 20; i++)
        {
            Section sec = prof.oSectionAt(za + (zb - za) * i / 20.0);
            rRef = Math.Max(rRef, 0.5 * (sec.Rf + sec.Rc));
        }
        (double, double, double) Map(double z, double arc)
        {
            Section sec = prof.oSectionAt(z);
            double rMid = 0.5 * (sec.Rf + sec.Rc), th = arc / rRef;
            return (rMid * Math.Cos(th), rMid * Math.Sin(th), z);
        }
        return strRender(imp, za, zb, 0, rRef * imp.SectorRad, strPath, Map, Map, new FieldProbe(vox), bScaleBar: false);
    }

    /// <summary>Raster a 2-D window (u, v) mapped to 3-D points; 1600 px wide, square pixels.</summary>
    static string strRender(RegenSectorImplicit imp, double uMin, double uMax, double vMin, double vMax, string strPath,
                            Func<double, double, (double, double, double)> mapExact,
                            Func<double, double, (double, double, double)> mapVoxel,
                            FieldProbe probe, bool bScaleBar)
    {
        const int nW = 1600;
        double px = (uMax - uMin) / nW;
        int nH    = (int)Math.Ceiling((vMax - vMin) / px);

        var analytic = new bool[nW, nH];
        var cache    = new Dictionary<(double, double, double), bool>();
        var img      = new ImageRgba32(nW, nH);

        for (int i = 0; i < nW; i++)
            for (int j = 0; j < nH; j++)
            {
                var (x, y, z) = mapExact(uMin + (i + 0.5) * px, vMin + (j + 0.5) * px);
                analytic[i, j] = imp.dSignedDistance(x, y, z) <= 0;
            }

        for (int i = 0; i < nW; i++)
            for (int j = 0; j < nH; j++)
            {
                bool bEdge = (i + 1 < nW && analytic[i + 1, j] != analytic[i, j])
                          || (j + 1 < nH && analytic[i, j + 1] != analytic[i, j]);
                var key = mapVoxel(uMin + (i + 0.5) * px, vMin + (j + 0.5) * px);
                if (!cache.TryGetValue(key, out bool bSolid))
                    cache[key] = bSolid = probe.bSolid(key.Item1, key.Item2, key.Item3);
                img.SetRgba32(i, nH - 1 - j, bEdge ? Line : (bSolid ? Copper : Void));   // +v up
            }

        if (bScaleBar)
        {
            int nBar = (int)Math.Round(1.0 / px), nTh = Math.Max(3, nBar / 12);
            for (int i = 20; i < 20 + nBar; i++)
                for (int j = nH - 20 - nTh; j < nH - 20; j++)
                    img.SetRgba32(i, j, new ColorRgba32(0, 0, 0));
        }
        return strWrite(img, strPath);
    }

    static readonly ColorRgba32 Copper = new(184, 115, 51);
    static readonly ColorRgba32 Void   = new(246, 246, 246);
    static readonly ColorRgba32 Line   = new(20, 50, 150);

    static string strWrite(ImageRgba32 img, string strPath)
    {
        if (File.Exists(strPath)) File.Delete(strPath);   // Image.SavePng does not truncate an existing file
        try
        {
            img.SavePng(strPath);
        }
        catch (Exception)
        {
            strPath = Path.ChangeExtension(strPath, ".tga");
            TgaIo.SaveTga(strPath, img);
        }
        return strPath;
    }
}
