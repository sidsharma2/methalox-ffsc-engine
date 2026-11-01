using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicoGK;

namespace RegenChamber;

/// <summary>
/// Voxel model of the regeneratively cooled GRCop-42 chamber, built with PicoGK
/// directly from the 1-D cooling model output (results/cooling_profile.csv).
/// Runs headless: a PicoGK Library instance is created directly and Library.Go
/// (which opens the viewer window) is never called.
///
///   RegenChamber                 build every voxel size (one child process each), then report.json
///   RegenChamber build &lt;h_mm&gt;    build one voxel size, write output/run_&lt;h&gt;.json
///   RegenChamber report          rebuild report.json from the existing run files
///   RegenChamber diag &lt;h_mm&gt;     sampling cost, topology of short pieces, throat probe
/// </summary>
public static class Program
{
    // ---- model parameters (mm unless noted) --------------------------------
    const int    BaseChannelsInSector = 8;     // 8 of 384 base channels -> 7.5 deg sector
    const double BlendMM              = 10.0;  // length of each N -> 2N bifurcation blend
    const double ChunkMM              = 10.0;  // axial chunk length for voxelizing
    const double MemoryBudgetGB       = 12.0;
    static readonly double[] VoxelSizesMM = [0.15, 0.10];
    static readonly double[] ProbeZMM     = [60.0, double.NaN, 900.0];   // NaN = throat

    public static int Main(string[] args)
    {
        Paths p = Paths.Find();
        string mode = args.Length > 0 ? args[0] : "all";
        double h = args.Length > 1 ? double.Parse(args[1], CultureInfo.InvariantCulture) : 0.15;

        switch (mode)
        {
            case "build":  return RunBuild(p, h);
            case "report": WriteReport(p); return 0;
            case "diag":   return RunDiag(p, h);
            case "all":
                foreach (double hv in VoxelSizesMM)
                {
                    int rc = RunChild("build", hv.ToString(CultureInfo.InvariantCulture));
                    if (rc != 0) { Console.Error.WriteLine($"build {hv} mm failed (exit {rc})"); return rc; }
                }
                WriteReport(p);
                return 0;
            default:
                Console.Error.WriteLine("usage: RegenChamber [all | build <h_mm> | report | diag <h_mm>]");
                return 2;
        }
    }

    // ---- one voxel size -------------------------------------------------------

    static int RunBuild(Paths p, double h)
    {
        string tag = Tag(h);
        using var logFile = new StreamWriter(Path.Combine(p.OutDir, $"run_{tag}.log"));
        void Log(string s) { Console.WriteLine(s); logFile.WriteLine(s); logFile.Flush(); }

        var swTotal = Stopwatch.StartNew();
        var sw      = Stopwatch.StartNew();
        var timing  = new JsonObject();
        var peaks   = new JsonObject();                  // process peak working set after each stage
        var proc    = Process.GetCurrentProcess();
        void Lap(string k)
        {
            timing[k] = Math.Round(sw.Elapsed.TotalSeconds, 2);
            proc.Refresh();
            peaks[k]  = Math.Round(proc.PeakWorkingSet64 / 1e9, 2);
            sw.Restart();
        }

        Profile prof = Profile.Load(p.CoolingCsv, p.ContourCsv, BlendMM);
        double sector = BaseChannelsInSector * 2 * Math.PI / prof.NBase;
        var imp       = new RegenSectorImplicit(prof, 0.0, prof.ZJoint, sector);

        Log($"[{tag}] PicoGK {Library.strVersion()} ({Library.strBuildInfo()}), headless");
        Log($"[{tag}] sector {sector * 180 / Math.PI:F3} deg, z = 0 .. {prof.ZJoint:F2} mm, voxel {h} mm");

        var geometry  = GeometryBlock(prof, imp);
        Lap("analytic");

        using var lib = new Library((float)h);

        Voxels vox = SectorBuilder.voxBuild(lib, imp, ChunkMM, Log);
        double gbVoxels = lib.nVoxelsMemUsage() / 1e9;
        Lap("voxelize");
        Log($"[{tag}] voxelized in {timing["voxelize"]} s, voxel memory {gbVoxels:F2} GB");

        // Minimum-feature retention: occupancy now, wall positions later on the mesh
        var stations = ProbeZMM.Select(z => new StationProbe(prof, imp, double.IsNaN(z) ? prof.ZThroat : z, h)).ToList();
        foreach (StationProbe st in stations) st.MeasureOccupancy(vox);

        var images = new JsonArray();
        foreach (double z in ProbeZMM)
        {
            string name = double.IsNaN(z) ? "throat" : $"z{z:0000}";
            images.Add(Rel(p, SliceImage.strSave(vox, imp, prof, double.IsNaN(z) ? prof.ZThroat : z, h,
                                                 Path.Combine(p.OutDir, $"slice_{name}_{tag}.png"))));
        }
        foreach (var b in prof.Bifurcations)
            images.Add(Rel(p, SliceImage.strSaveUnrolled(vox, imp, prof, b.Z - 6, b.Z + b.L + 6,
                                                         Path.Combine(p.OutDir, $"bifurcation_unrolled_{tag}.png"))));
        Lap("occupancy_images");

        // Surface mesh, STL, topology and probe-line crossings
        using Mesh msh = new(vox);
        double gbMesh = lib.nMeshesMemUsage() / 1e9;
        vox.Dispose();
        Lap("mesh");

        string stl = Path.Combine(p.OutDir, $"regen_sector_{tag}.stl");
        msh.SaveToStlFile(stl, Mesh.EStlUnit.MM);
        Lap("stl_write");

        // PicoGK voxel volume (CalculateProperties recipe on the exported mesh, source field
        // already freed); done before the mesh check so its large arrays are not alive yet
        double vAnalytic = (double)geometry["analytic_volume_mm3"]!;
        double vVoxel = VoxelVolume.dFromMesh(msh);
        BBox3 bbox    = msh.oBoundingBox();
        Lap("voxel_volume");
        Log($"[{tag}] voxel volume {vVoxel:F0} mm3 vs analytic {vAnalytic:F0} mm3 ({Pct(vVoxel, vAnalytic):+0.000;-0.000} %)");

        MeshReport mr = MeshCheck.oAnalyse(msh, stations.SelectMany(s => s.Lines));
        Lap("mesh_check");
        Log($"[{tag}] mesh {mr.Triangles:N0} triangles, watertight {mr.Watertight} " +
            $"(boundary {mr.BoundaryEdges}, non-manifold {mr.NonManifoldEdges}, misoriented {mr.MisorientedEdges}), " +
            $"genus {mr.Genus}, volume {mr.VolumeMM3:F0} mm3 ({Pct(mr.VolumeMM3, vAnalytic):+0.000;-0.000} %)");

        var probes = new JsonArray();
        foreach (StationProbe st in stations)
        {
            var pr = st.ToJson();
            Log($"[{tag}] probe z {pr["z_mm"]} mm: channels {pr["channels_counted"]}/{pr["channels_expected"]}, " +
                $"hot wall {pr["hot_wall_mm"]!["min"]}..{pr["hot_wall_mm"]!["max"]} mm, " +
                $"width {pr["channel_width_mm"]!["min"]}..{pr["channel_width_mm"]!["max"]} mm, retained {pr["retained"]}");
            probes.Add(pr);
        }

        timing["total"] = Math.Round(swTotal.Elapsed.TotalSeconds, 2);
        proc.Refresh();

        var run = new JsonObject
        {
            ["voxel_size_mm"]          = h,
            ["chunk_mm"]               = ChunkMM,
            ["picogk"]                 = $"{Library.strName()} {Library.strVersion()} ({Library.strBuildInfo()})",
            ["geometry"]               = geometry,
            ["voxel_volume_mm3"]       = Math.Round(vVoxel, 1),
            ["voxel_volume_error_pct"] = Math.Round(Pct(vVoxel, vAnalytic), 4),
            ["voxel_volume_method"]    = "PicoGK CalculateProperties recipe: mesh -> voxels -> native voxel count",
            ["mesh_volume_method"]     = "divergence theorem on the extracted (watertight) surface mesh",
            ["mesh_volume_mm3"]        = Math.Round(mr.VolumeMM3, 1),
            ["mesh_volume_error_pct"]  = Math.Round(Pct(mr.VolumeMM3, vAnalytic), 4),
            ["bbox_mm"]                = BBoxJson(bbox),
            ["mesh"] = new JsonObject
            {
                ["triangles"]            = mr.Triangles,
                ["vertices"]             = mr.Vertices,
                ["edges"]                = mr.Edges,
                ["boundary_edges"]       = mr.BoundaryEdges,
                ["non_manifold_edges"]   = mr.NonManifoldEdges,
                ["misoriented_edges"]    = mr.MisorientedEdges,
                ["degenerate_triangles"] = mr.DegenerateTriangles,
                ["components"]           = mr.Components,
                ["euler_characteristic"] = mr.EulerCharacteristic,
                ["genus"]                = mr.Genus,
                ["watertight"]           = mr.Watertight,
                ["area_mm2"]             = Math.Round(mr.AreaMM2, 1),
                ["check"] = "own check on PicoGK's indexed mesh: every edge shared by exactly two " +
                            "oppositely oriented triangles; vertex-manifoldness not checked"
            },
            ["feature_retention"]      = probes,
            ["timing_s"]               = timing,
            ["memory_GB"] = new JsonObject
            {
                ["picogk_voxels"]      = Math.Round(gbVoxels, 3),
                ["picogk_mesh"]        = Math.Round(gbMesh, 3),
                ["peak_working_set"]   = Math.Round(proc.PeakWorkingSet64 / 1e9, 3),
                ["peak_private_bytes"] = Math.Round(proc.PeakPagedMemorySize64 / 1e9, 3),
                ["peak_working_set_after_stage"] = peaks
            },
            ["files"] = new JsonObject
            {
                ["stl"]    = Rel(p, stl),
                ["images"] = images,
                ["log"]    = Rel(p, Path.Combine(p.OutDir, $"run_{tag}.log"))
            }
        };
        File.WriteAllText(Path.Combine(p.OutDir, $"run_{tag}.json"), run.ToJsonString(JsonOpts));
        Log($"[{tag}] done in {timing["total"]} s, peak working set {proc.PeakWorkingSet64 / 1e9:F2} GB");
        return 0;
    }

    /// <summary>Geometry and analytic reference shared by every run.</summary>
    static JsonObject GeometryBlock(Profile prof, RegenSectorImplicit imp)
    {
        BBox3 bb = imp.oBounds(imp.Z0, imp.Z1, 0.0);
        var bif  = new JsonArray();
        foreach (var b in prof.Bifurcations)
            bif.Add(new JsonObject { ["z_start_mm"] = Math.Round(b.Z, 3), ["blend_mm"] = b.L,
                                     ["N_before"] = b.NBefore, ["N_after"] = b.NAfter });
        return new JsonObject
        {
            ["frame"]                    = "Z = engine axis from the injector face; sector theta = 0..angle from +X towards +Y",
            ["z_start_mm"]               = imp.Z0,
            ["z_joint_mm"]               = Math.Round(imp.Z1, 3),
            ["sector_angle_deg"]         = Math.Round(imp.SectorRad * 180 / Math.PI, 6),
            ["N_base"]                   = prof.NBase,
            ["channels_in_sector_base"]  = BaseChannelsInSector,
            ["bifurcations"]             = bif,
            ["throat_z_mm"]              = Math.Round(prof.ZThroat, 3),
            ["throat_r_mm"]              = Math.Round(prof.RThroat, 3),
            ["bbox_analytic_mm"]         = BBoxJson(bb),
            ["analytic_volume_mm3"]      = Math.Round(prof.dAnalyticVolume(imp.Z0, imp.Z1, imp.SectorRad), 1),
            ["station_trapezoid_volume_mm3"] = Math.Round(prof.dStationTrapezoidVolume(imp.SectorRad), 1),
            ["rib_csv_consistency_mm"]   = prof.dRibConsistencyError()
        };
    }

    // ---- report ---------------------------------------------------------------

    static void WriteReport(Paths p)
    {
        var runs = new JsonArray();
        foreach (double h in VoxelSizesMM)
        {
            string f = Path.Combine(p.OutDir, $"run_{Tag(h)}.json");
            if (File.Exists(f)) runs.Add(JsonNode.Parse(File.ReadAllText(f)));
        }
        if (runs.Count == 0) throw new FileNotFoundException("No run_*.json files in " + p.OutDir);

        var geometry = runs[0]!["geometry"]!.DeepClone();
        foreach (var r in runs) r!.AsObject().Remove("geometry");

        // Add file sizes now that every file exists
        foreach (var r in runs)
        {
            var files = r!["files"]!.AsObject();
            files["stl_bytes"] = new FileInfo(Path.Combine(p.Root, (string)files["stl"]!)).Length;
        }

        var report = new JsonObject
        {
            ["model"]          = "Regen-cooled GRCop-42 chamber, periodic 8-channel sector, PicoGK voxel model",
            ["generated_utc"]  = DateTime.UtcNow.ToString("u"),
            ["units"]          = "mm, mm^2, mm^3, s, GB (1e9 bytes)",
            ["inputs"] = new JsonObject
            {
                ["cooling_profile"] = new JsonObject { ["path"] = Rel(p, p.CoolingCsv), ["sha256"] = Sha256(p.CoolingCsv) },
                ["contour"]         = new JsonObject { ["path"] = Rel(p, p.ContourCsv), ["sha256"] = Sha256(p.ContourCsv) }
            },
            ["geometry"]         = geometry,
            ["runs"]             = runs,
            ["resolution_check"] = ResolutionCheck(runs),
            ["full_360"]         = Full360Estimate(runs, geometry!)
        };
        string path = Path.Combine(p.OutDir, "report.json");
        File.WriteAllText(path, report.ToJsonString(JsonOpts));
        PrintSummary(report);
        Console.WriteLine($"report: {path}");
    }

    static JsonObject ResolutionCheck(JsonArray runs)
    {
        if (runs.Count < 2) return new JsonObject { ["note"] = "needs two voxel sizes" };
        double V(int i, string k) => (double)runs[i]![k]!;
        return new JsonObject
        {
            ["voxel_volume_change_pct"] = Math.Round(Pct(V(1, "voxel_volume_mm3"), V(0, "voxel_volume_mm3")), 4),
            ["mesh_volume_change_pct"]  = Math.Round(Pct(V(1, "mesh_volume_mm3"),  V(0, "mesh_volume_mm3")),  4),
            ["note"] = "change from the coarser to the finer voxel size"
        };
    }

    /// <summary>
    /// Full 360 deg ring at 0.3 mm, estimated from the measured sector: surface area
    /// scales with the 48 sectors (minus the cut faces), triangles and voxel memory with 1/h^2.
    /// </summary>
    static JsonObject Full360Estimate(JsonArray runs, JsonNode geometry)
    {
        const double hFull = 0.3;
        var run   = runs[0]!;
        double h  = (double)run["voxel_size_mm"]!;
        double nSectors = 360.0 / (double)geometry["sector_angle_deg"]!;
        double triRatio = (double)run["mesh"]!["triangles"]! / (double)run["mesh"]!["area_mm2"]!;
        double area360  = nSectors * (double)run["mesh"]!["area_mm2"]!;      // cut faces ignored: < 10 %
        double tri360   = area360 * triRatio * (h / hFull) * (h / hFull);
        double voxGB    = nSectors * (double)run["memory_GB"]!["picogk_voxels"]! * (h / hFull) * (h / hFull);
        double meshGB   = nSectors * (double)run["memory_GB"]!["picogk_mesh"]!   * (h / hFull) * (h / hFull);
        bool bFits = voxGB + meshGB < MemoryBudgetGB;
        return new JsonObject
        {
            ["built"]                 = false,
            ["voxel_size_mm"]         = hFull,
            ["estimated_triangles"]   = Math.Round(tri360),
            ["estimated_stl_GB"]      = Math.Round(tri360 * 50 / 1e9, 1),
            ["estimated_voxels_GB"]   = Math.Round(voxGB, 1),
            ["estimated_mesh_GB"]     = Math.Round(meshGB, 1),
            ["fits_memory_budget"]    = bFits,
            ["reason"] = bFits
                ? "estimate fits the budget but the ring was not built in this run"
                : $"skipped: estimated PicoGK memory {voxGB + meshGB:F0} GB (voxels + mesh) exceeds the {MemoryBudgetGB} GB budget; " +
                  "the 384-768 channels x 2 side walls x 12 mm height dominate the surface area. " +
                  "It would also be visual-only: 1.0 mm channels are 3.3 voxels wide at 0.3 mm.",
            ["basis"] = $"scaled from the {h} mm sector run"
        };
    }

    static void PrintSummary(JsonObject rep)
    {
        var g = rep["geometry"]!;
        Console.WriteLine();
        Console.WriteLine($"Analytic sector volume   {(double)g["analytic_volume_mm3"]!,14:N1} mm3");
        Console.WriteLine($"Station trapezoid (1-D)  {(double)g["station_trapezoid_volume_mm3"]!,14:N1} mm3");
        Console.WriteLine();
        Console.WriteLine(" h [mm] | voxel vol [mm3] |   err % | mesh vol [mm3] |   err % |   triangles | watertight | time [s] | peak WS [GB]");
        foreach (var r in rep["runs"]!.AsArray())
        {
            Console.WriteLine($" {(double)r!["voxel_size_mm"]!,6:F2} | {(double)r["voxel_volume_mm3"]!,15:N0} | {(double)r["voxel_volume_error_pct"]!,7:F3} | " +
                              $"{(double)r["mesh_volume_mm3"]!,14:N0} | {(double)r["mesh_volume_error_pct"]!,7:F3} | " +
                              $"{(int)r["mesh"]!["triangles"]!,11:N0} | {(bool)r["mesh"]!["watertight"]!,10} | " +
                              $"{(double)r["timing_s"]!["total"]!,8:F1} | {(double)r["memory_GB"]!["peak_working_set"]!,12:F2}");
            foreach (var pr in r["feature_retention"]!.AsArray())
                Console.WriteLine($"          z {(double)pr!["z_mm"]!,7:F1} mm: channels {pr["channels_counted"]}/{pr["channels_expected"]}, " +
                                  $"hot wall {pr["hot_wall_mm"]!["min"]}..{pr["hot_wall_mm"]!["max"]} mm (nominal {pr["hot_wall_nominal_mm"]}), " +
                                  $"width {pr["channel_width_mm"]!["min"]}..{pr["channel_width_mm"]!["max"]} mm, retained {pr["retained"]}");
        }
    }

    // ---- diagnostics ------------------------------------------------------------

    static int RunDiag(Paths p, double h)
    {
        Profile prof = Profile.Load(p.CoolingCsv, p.ContourCsv, BlendMM);
        double sector = BaseChannelsInSector * 2 * Math.PI / prof.NBase;
        var imp = new RegenSectorImplicit(prof, 0.0, prof.ZJoint, sector);
        using var lib = new Library((float)h);
        Console.WriteLine($"PicoGK {Library.strVersion()}  voxel {h} mm");
        Console.WriteLine("chunk z 50..60 mm:   " + SectorBuilder.strDiagnose(lib, imp, 50, 60));
        Console.WriteLine("chunk z 340..360 mm: " + SectorBuilder.strDiagnose(lib, imp, 340, 360));

        // Topology of short pieces: 8 straight channels -> genus 8; 8 Y-splits -> genus 16
        foreach ((double za, double zb) in new[] { (40.0, 80.0), (590.0, 630.0) })
        {
            var piece = new RegenSectorImplicit(imp, za, zb);
            using Voxels vox = SectorBuilder.voxBuild(lib, piece, 10, _ => { });
            using Mesh msh = new(vox);
            MeshReport mr = MeshCheck.oAnalyse(msh);
            Console.WriteLine($"piece z {za}..{zb} mm: watertight {mr.Watertight}, components {mr.Components}, genus {mr.Genus}");
        }

        // Throat piece: feature probe, and the volume measures side by side
        {
            var piece = new RegenSectorImplicit(imp, prof.ZThroat - 20, prof.ZThroat + 20);
            using Voxels vox = SectorBuilder.voxBuild(lib, piece, 10, _ => { });
            var st = new StationProbe(prof, piece, prof.ZThroat, h);
            st.MeasureOccupancy(vox);

            double vA = prof.dAnalyticVolume(piece.Z0, piece.Z1, piece.SectorRad);
            vox.CalculateProperties(out float fVolProps, out _);
            double vDirect = VoxelVolume.dDirect(vox);
            using Mesh msh = new(vox);
            double vMesh = MeshCheck.oAnalyse(msh, st.Lines).VolumeMM3;
            double vFromMesh = VoxelVolume.dFromMesh(msh);
            Console.WriteLine(st.ToJson().ToJsonString());
            Console.WriteLine($"piece volume: analytic {vA:F1}, CalculateProperties {fVolProps:F1} ({Pct(fVolProps, vA):F4} %), " +
                              $"dFromMesh {vFromMesh:F1}, direct count {vDirect:F1} ({Pct(vDirect, vA):F4} %), " +
                              $"mesh {vMesh:F1} ({Pct(vMesh, vA):F4} %)");
        }
        return 0;
    }

    // ---- helpers ----------------------------------------------------------------

    sealed record Paths(string Root, string CoolingCsv, string ContourCsv, string OutDir)
    {
        /// <summary>Engine project root = first parent of the executable that holds results/cooling_profile.csv.</summary>
        public static Paths Find()
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            while (dir != null && !File.Exists(Path.Combine(dir.FullName, "results", "cooling_profile.csv")))
                dir = dir.Parent;
            if (dir == null) throw new DirectoryNotFoundException("results/cooling_profile.csv not found above " + AppContext.BaseDirectory);

            string root = dir.FullName;
            string outDir = Path.Combine(root, "picogk", "output");
            Directory.CreateDirectory(outDir);
            return new Paths(root, Path.Combine(root, "results", "cooling_profile.csv"),
                             Path.Combine(root, "results", "contour.csv"), outDir);
        }
    }

    /// <summary>Re-run this program in a child process so each voxel size has its own peak memory.</summary>
    static int RunChild(params string[] args)
    {
        string host = Path.GetFullPath(Path.Combine(RuntimeEnvironment.GetRuntimeDirectory(), "..", "..", "..", "dotnet.exe"));
        var psi = new ProcessStartInfo(File.Exists(host) ? host : "dotnet") { UseShellExecute = false };
        psi.ArgumentList.Add(typeof(Program).Assembly.Location);
        foreach (string a in args) psi.ArgumentList.Add(a);
        using var proc = Process.Start(psi)!;
        proc.WaitForExit();
        return proc.ExitCode;
    }

    static string Tag(double h) => h.ToString("0.00", CultureInfo.InvariantCulture).Replace('.', 'p') + "mm";

    static double Pct(double v, double reference) => 100.0 * (v - reference) / reference;

    static string Rel(Paths p, string path) => Path.GetRelativePath(p.Root, path).Replace('\\', '/');

    static JsonObject BBoxJson(BBox3 b) => new()
    {
        ["min"] = new JsonArray(Math.Round(b.vecMin.X, 3), Math.Round(b.vecMin.Y, 3), Math.Round(b.vecMin.Z, 3)),
        ["max"] = new JsonArray(Math.Round(b.vecMax.X, 3), Math.Round(b.vecMax.Y, 3), Math.Round(b.vecMax.Z, 3))
    };

    static string Sha256(string path)
    {
        using var f = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(f)).ToLowerInvariant();
    }

    static readonly JsonSerializerOptions JsonOpts = new() { WriteIndented = true };
}
