using System.Collections.Concurrent;
using System.Diagnostics;
using System.Numerics;
using PicoGK;

namespace RegenChamber;

/// <summary>
/// Voxelizes the sector implicit in axial chunks. PicoGK's RenderImplicit samples
/// every voxel of the box it is given, on the calling thread, so one box over the
/// whole length would be mostly empty (the contour runs from r = 117 mm to
/// r = 421 mm) and slow. Each chunk gets a tight box and is unioned into the part.
/// Chunks overlap by a few voxels; the field is identical in the overlap, so the
/// union has no seams.
///
/// Chunks are rendered one after another. Rendering separate Voxels objects on
/// parallel threads gave identical results twice and then corrupted the native heap
/// (exit 0xC0000374) on the third run, so the PicoGK runtime is treated as
/// single-threaded here.
/// </summary>
public static class SectorBuilder
{
    public static Voxels voxBuild(Library lib, RegenSectorImplicit imp, double dChunkMM, Action<string> log)
    {
        double h       = lib.fVoxelSize;
        double overlap = Math.Max(0.5, 4 * h);
        double margin  = 0.5 + 4 * h;           // room for the outer narrow band

        Voxels voxAll = new(lib);
        int nChunks   = (int)Math.Ceiling((imp.Z1 - imp.Z0) / dChunkMM);

        for (int i = 0; i < nChunks; i++)
        {
            double za = imp.Z0 + i * dChunkMM;
            double zb = Math.Min(imp.Z1, za + dChunkMM);

            using (Voxels vox = new(lib, imp, imp.oBounds(za - overlap, zb + overlap, margin)))
                voxAll.BoolAdd(vox);

            if ((i + 1) % 10 == 0 || i == nChunks - 1)
                log($"  chunk {i + 1}/{nChunks}  z <= {zb:F1} mm  PicoGK memory {lib.nTotalMemUsage() / 1e9:F2} GB");
        }
        return voxAll;
    }

    /// <summary>
    /// Diagnostic: render one chunk and count implicit calls and calling threads,
    /// to see whether PicoGK samples the whole box and whether it calls back in parallel.
    /// </summary>
    public static string strDiagnose(Library lib, RegenSectorImplicit imp, double za, double zb)
    {
        var counter = new CountingImplicit(imp);
        BBox3 box   = imp.oBounds(za, zb, 0.5 + 4 * lib.fVoxelSize);
        Vector3 sz  = box.vecSize();
        double h    = lib.fVoxelSize;
        double nBox = (double)(sz.X / h) * (sz.Y / h) * (sz.Z / h);

        var sw = Stopwatch.StartNew();
        using Voxels vox = new(lib, counter, box);
        double tRender = sw.Elapsed.TotalSeconds;

        // Same number of evaluations directly in C#, to separate SDF cost from callback cost
        sw.Restart();
        double acc = 0;
        for (double z = box.vecMin.Z; z < box.vecMax.Z; z += h)
            for (double y = box.vecMin.Y; y < box.vecMax.Y; y += h)
                for (double x = box.vecMin.X; x < box.vecMax.X; x += h)
                    acc += imp.dSignedDistance(x, y, z);
        double tDirect = sw.Elapsed.TotalSeconds;

        return $"box {sz.X:F1} x {sz.Y:F1} x {sz.Z:F1} mm = {nBox:E3} voxels, " +
               $"calls {counter.Calls:E3} ({counter.Calls / nBox:F2} per box voxel), threads {counter.Threads}, " +
               $"render {tRender:F2} s ({1e9 * tRender / Math.Max(1, counter.Calls):F0} ns/call), " +
               $"direct C# SDF {1e9 * tDirect / nBox:F0} ns/eval [{acc:E1}]";
    }

    sealed class CountingImplicit(IImplicit inner) : IImplicit
    {
        long m_nCalls;
        readonly ConcurrentDictionary<int, byte> m_threads = new();

        public long Calls  => Interlocked.Read(ref m_nCalls);
        public int Threads => m_threads.Count;

        public float fSignedDistance(in Vector3 vec)
        {
            Interlocked.Increment(ref m_nCalls);
            m_threads.TryAdd(Environment.CurrentManagedThreadId, 0);
            return inner.fSignedDistance(vec);
        }
    }
}
