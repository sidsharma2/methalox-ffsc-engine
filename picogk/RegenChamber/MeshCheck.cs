using System.Numerics;
using PicoGK;

namespace RegenChamber;

/// <summary>
/// Topology and volume of the extracted surface mesh. PicoGK does not report
/// watertightness, so it is checked here on the indexed triangles:
/// every undirected edge must be used by exactly two triangles with opposite
/// direction (closed, edge-manifold, consistently oriented).
/// </summary>
public sealed record MeshReport(
    int    Triangles,
    int    Vertices,
    long   Edges,
    long   BoundaryEdges,
    long   NonManifoldEdges,
    long   MisorientedEdges,
    long   DegenerateTriangles,
    int    Components,
    long   EulerCharacteristic,
    double VolumeMM3,
    double AreaMM2)
{
    public bool Watertight => BoundaryEdges == 0 && NonManifoldEdges == 0 && MisorientedEdges == 0;

    /// <summary>Genus of a closed orientable surface: chi = 2C - 2g.</summary>
    public double Genus => (2.0 * Components - EulerCharacteristic) / 2.0;
}

public static class MeshCheck
{
    /// <summary>
    /// Topology and volume of the mesh. Probe lines, if given, collect the points
    /// where the surface crosses them (sub-voxel wall positions of the voxel model).
    /// </summary>
    public static MeshReport oAnalyse(Mesh msh, IEnumerable<ProbeLine>? probeLines = null)
    {
        int nTri  = msh.nTriangleCount();
        int nVert = msh.nVertexCount();
        var planes = (probeLines ?? []).GroupBy(l => l.Z).Select(g => (Z: g.Key, Lines: g.ToArray())).ToArray();

        var av = new Vector3[nVert];
        for (int i = 0; i < nVert; i++) av[i] = msh.vecVertexAt(i);

        // Reference point near the part keeps the volume sum well conditioned
        BBox3 bb = msh.oBoundingBox();
        Vector3 c0 = bb.vecCenter();

        // Edge key: (min << 32) | (max << 1) | direction bit
        long[] keys = new long[3L * nTri];
        var dsu  = new DisjointSet(nVert);
        double vol = 0, area = 0;
        long nDegenerate = 0;

        for (int t = 0; t < nTri; t++)
        {
            Triangle tri = msh.oTriangleAt(t);
            int a = tri.A, b = tri.B, c = tri.C;

            Vector3 pa = av[a] - c0, pb = av[b] - c0, pc = av[c] - c0;
            double ax = pa.X, ay = pa.Y, az = pa.Z;
            double bx = pb.X, by = pb.Y, bz = pb.Z;
            double cx = pc.X, cy = pc.Y, cz = pc.Z;

            vol += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)) / 6.0;

            double ux = bx - ax, uy = by - ay, uz = bz - az;
            double wx = cx - ax, wy = cy - ay, wz = cz - az;
            double nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx;
            double dA = 0.5 * Math.Sqrt(nx * nx + ny * ny + nz * nz);
            area += dA;
            if (a == b || b == c || a == c || dA == 0) nDegenerate++;

            keys[3L * t]     = Key(a, b);
            keys[3L * t + 1] = Key(b, c);
            keys[3L * t + 2] = Key(c, a);

            foreach (var (z, lines) in planes)
                CutTriangle(av[a], av[b], av[c], z, lines);

            dsu.Union(a, b);
            dsu.Union(b, c);
        }

        Array.Sort(keys);

        long nEdges = 0, nBoundary = 0, nNonManifold = 0, nMisoriented = 0;
        for (long i = 0; i < keys.LongLength;)
        {
            long edge = keys[i] >> 1;
            long j = i;
            int nFwd = 0, nRev = 0;
            while (j < keys.LongLength && (keys[j] >> 1) == edge)
            {
                if ((keys[j] & 1) == 0) nFwd++; else nRev++;
                j++;
            }
            int nUse = nFwd + nRev;
            nEdges++;
            if (nUse == 1)                       nBoundary++;
            else if (nUse > 2)                   nNonManifold++;
            else if (nFwd != 1 || nRev != 1)     nMisoriented++;
            i = j;
        }

        // Euler characteristic over referenced vertices
        var used = new bool[nVert];
        for (long i = 0; i < keys.LongLength; i++)
        {
            used[(int)(keys[i] >> 32)] = true;
            used[(int)((keys[i] >> 1) & 0x7FFFFFFF)] = true;
        }
        int nUsed = 0, nComponents = 0;
        for (int v = 0; v < nVert; v++)
        {
            if (!used[v]) continue;
            nUsed++;
            if (dsu.Find(v) == v) nComponents++;
        }

        return new MeshReport(nTri, nVert, nEdges, nBoundary, nNonManifold, nMisoriented, nDegenerate,
                              nComponents, (long)nUsed - nEdges + nTri, vol, area);
    }

    /// <summary>Cut a triangle with the plane z = z0 and pass the 2-D cut segment to the probe lines.</summary>
    static void CutTriangle(Vector3 p0, Vector3 p1, Vector3 p2, double z0, ProbeLine[] lines)
    {
        double d0 = p0.Z - z0, d1 = p1.Z - z0, d2 = p2.Z - z0;
        bool b0 = d0 > 0, b1 = d1 > 0, b2 = d2 > 0;
        if (b0 == b1 && b1 == b2) return;

        // Exactly two edges change side; their crossing points form the cut segment
        Span<double> xy = stackalloc double[4];
        int n = 0;
        if (b0 != b1) { double t = d0 / (d0 - d1); xy[n++] = p0.X + t * (p1.X - p0.X); xy[n++] = p0.Y + t * (p1.Y - p0.Y); }
        if (b1 != b2) { double t = d1 / (d1 - d2); xy[n++] = p1.X + t * (p2.X - p1.X); xy[n++] = p1.Y + t * (p2.Y - p1.Y); }
        if (b2 != b0) { double t = d2 / (d2 - d0); xy[n++] = p2.X + t * (p0.X - p2.X); xy[n++] = p2.Y + t * (p0.Y - p2.Y); }

        foreach (ProbeLine l in lines) l.Intersect(xy[0], xy[1], xy[2], xy[3]);
    }

    static long Key(int a, int b)
        => a < b ? ((long)a << 32) | ((long)b << 1)
                 : ((long)b << 32) | ((long)a << 1) | 1L;

    sealed class DisjointSet
    {
        readonly int[] m_parent;
        public DisjointSet(int n) { m_parent = new int[n]; for (int i = 0; i < n; i++) m_parent[i] = i; }

        public int Find(int i)
        {
            while (m_parent[i] != i) { m_parent[i] = m_parent[m_parent[i]]; i = m_parent[i]; }
            return i;
        }

        public void Union(int a, int b)
        {
            int ra = Find(a), rb = Find(b);
            if (ra != rb) m_parent[Math.Max(ra, rb)] = Math.Min(ra, rb);
        }
    }
}
