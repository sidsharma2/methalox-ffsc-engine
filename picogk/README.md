# RegenChamber: voxel model of the regen-cooled copper chamber

This folder turns the output of the 1-D regenerative-cooling model into a voxel solid with PicoGK. The geometry comes straight from `results/cooling_profile.csv`, station by station, so a change in the cooling sizing changes the part when you run this again.

## What it builds

A periodic angular sector of the GRCop-42 chamber liner (zone 0), from the injector face (z = 0) to the bolted joint (z = 976.15 mm, area ratio about 12). The sector holds 8 of the 384 base channels, so it spans 7.5 deg. Downstream of the bifurcation it holds 16 of 768. The solid is liner + ribs + closeout. The channels are voids and are open at both end faces. The two cut faces are radial planes through rib centres, so copies of the sector rotated by 7.5 deg tile the full ring.

Per axial position z (all lengths in mm):

| Quantity | Definition |
|---|---|
| r | gas-side radius, linear interpolation of `results/contour.csv` |
| r_f = r + t_hot | channel floor (circular) |
| r_c = r_f + H | channel ceiling (circular) |
| r_o = r_c + t_closeout | outer surface |
| W | channel width; the side walls are planes parallel to the channel centre plane, so W holds from floor to ceiling and the rib gets wider with radius |
| channel k of N | centred at (k + 0.5) 2 pi / N |

t_hot, H, t_closeout and W are interpolated linearly between the sizing stations. From the last copper station (z = 971.06 mm) to the joint they are held constant. The radial offsets follow the brief, so the wall-normal hot-wall thickness on the 30 deg convergent cone is 0.6 cos 30 = 0.52 mm.

### Bifurcation blend (deviation from the brief)

N goes from 384 to 768 between stations 119 (z = 597.33 mm) and 120 (z = 602.21 mm). If N simply switches at that z, the new splitter rib sits on the old channel centre and is 1.017 mm wide. That is wider than the 1.0 mm channel it should split, so the coolant path would be closed. The model therefore uses a 10 mm blend that starts half way between the two stations (z = 599.77 mm). Over the blend, each pair of new channels rotates out of the parent channel: the splitter grows from a knife edge to 1.017 mm and the outer walls swing out to their final angle. No channel is ever wider than W = 1.0 mm, so the liner bending limit from the sizing still holds. With `BlendMM = 0` in `Program.cs` you get the plain switch; the field then jumps at that plane, so the step face is placed only to within a voxel.

Frame: Z is the engine axis. The sector runs from theta = 0 (+X) towards +Y. STL units are mm.

## How to run

The project needs the local .NET 9 SDK; the system dotnet is 8.0 and cannot build PicoGK 2.3.

```
D:\Research-Software\tools\dotnet9\dotnet.exe run -c Release --project D:\Research\projects\methalox-ffsc-engine\picogk\RegenChamber
```

This builds PicoGK (`D:\Research-Software\repos\leap71\PicoGK`, only its bin/obj are written) and RegenChamber. It runs one child process per voxel size (0.15 mm, then 0.10 mm), so each size has its own peak memory, and then writes `output/report.json`. A full run takes about 12 minutes (3 at 0.15 mm, 9 at 0.10 mm) and writes 6.3 GB of STL.

Single steps, after a build:

```
set EXE=D:\Research\projects\methalox-ffsc-engine\picogk\RegenChamber\bin\Release\net9.0\RegenChamber.dll
D:\Research-Software\tools\dotnet9\dotnet.exe %EXE% build 0.10    one voxel size -> output/run_0p10mm.json
D:\Research-Software\tools\dotnet9\dotnet.exe %EXE% report        report.json from existing run files
D:\Research-Software\tools\dotnet9\dotnet.exe %EXE% diag 0.15     sampling cost, topology of short pieces, throat probe
```

Model parameters (sector size, blend length, chunk length, voxel sizes, probe stations) are named constants at the top of `RegenChamber/Program.cs`.

## Files

| File | Content |
|---|---|
| `RegenChamber/Profile.cs` | reads the CSVs, section and channel layout at any z, analytic volume |
| `RegenChamber/RegenSectorImplicit.cs` | signed-distance function of the sector (PicoGK `IImplicit`) |
| `RegenChamber/SectorBuilder.cs` | voxelizes the implicit in axial chunks |
| `RegenChamber/MeshCheck.cs` | watertightness, Euler characteristic, mesh volume, probe-line crossings |
| `RegenChamber/Probes.cs` | minimum-feature checks at single stations |
| `RegenChamber/VoxelVolume.cs` | PicoGK voxel volume with less peak memory |
| `RegenChamber/Images.cs` | cross-section and unrolled pictures |
| `RegenChamber/Program.cs` | parameters, run sequence, report |
| `output/report.json` | all validation numbers |
| `output/regen_sector_0p15mm.stl`, `output/regen_sector_0p10mm.stl` | binary STL, mm |
| `output/slice_throat_*.png`, `slice_z0060_*.png`, `slice_z0900_*.png` | cross-sections at the probe stations |
| `output/bifurcation_unrolled_*.png` | the bifurcation blend, unrolled at mid-channel height |
| `output/run_*.json`, `output/run_*.log` | per voxel size run data and log |

In the pictures, copper marks voxels whose centre is inside, so you see the staircase. The thin dark-blue line is the zero contour of the analytic implicit. The bar at the bottom left is 1 mm.

## Voxel size

PicoGK works in mm. The smallest features that must survive are the 0.6 mm hot wall and the 1.0 mm channel width (the narrowest rib is 0.93 mm). At 0.15 mm the hot wall is 4 voxels thick and the channel is 6.7 voxels wide. At 0.10 mm the figures are 6 and 10. Both sizes were built and compared.

## Validation

Run of 2026-10-31, PicoGK 2.3.0 with runtime 26.2.0. All numbers are in `output/report.json`.

The analytic reference integrates the sector area (annulus sector minus the channel areas, with the blend) along z on a 0.005 mm grid. It uses the same interpolation as the implicit and gives 419,172.5 mm3. A trapezoid over the 1-D stations alone (station radius, N W H channels, no blend) gives 418,695.0 mm3, which is 0.11 % lower.

| | 0.15 mm | 0.10 mm |
|---|---|---|
| PicoGK voxel volume, mm3 (error vs analytic) | 419,492.8 (+0.076 %) | 418,739.4 (-0.103 %) |
| Mesh volume, mm3 (error vs analytic) | 419,471.8 (+0.071 %) | 419,306.5 (+0.032 %) |
| Bounding box min, mm (analytic 116.441, 0, 0) | 116.470, 0, 0 | 116.456, 0, 0 |
| Bounding box max, mm (analytic 423.237, 55.244, 976.147) | 423.175, 55.213, 976.147 | 423.210, 55.222, 976.147 |
| Triangles | 38,921,056 | 87,628,320 |
| Boundary / non-manifold / misoriented edges | 0 / 0 / 0 | 0 / 0 / 0 |
| Components, genus | 1, 23 | 1, 16 |
| Run time (voxelize), s | 171 (54) | 524 (152) |
| Peak working set, GB | 4.71 | 10.64 |
| STL size, GB | 1.95 | 4.38 |

- Voxel volume is PicoGK's own definition (the `CalculateProperties` steps: mesh, re-voxelize, count voxels). Mesh volume is the divergence-theorem volume of the extracted surface, which is the interpolated zero level of the voxel field. The mesh volume error falls from 0.071 % to 0.032 % (ratio 2.2, close to (0.15/0.10)^2 = 2.25), which fits rounding at the voxel scale of the many concave channel corners. The voxel count sits within about 0.1 % at both sizes but does not converge monotonically, because it steps in whole voxels.
- Watertight here means that every edge of the indexed mesh is shared by exactly two triangles with opposite direction. PicoGK does not report this, so `MeshCheck.cs` checks it. Vertex-manifoldness is not checked. The 0.10 mm mesh has 10 zero-area triangles. They do not break the edge test.
- Expected genus: 8 straight channels through a block give genus 8, and each Y-split adds one, so the ideal part has genus 16. The 0.10 mm mesh has 16. The 0.15 mm mesh has 23 because the first part of the splitter knife edge is thinner than a voxel and comes out perforated. Short pieces confirm this: z = 40 to 80 mm gives genus 8 at both sizes, and z = 590 to 630 mm gives 23 at 0.15 mm and 16 at 0.10 mm (`diag`).
- Peak memory at 0.10 mm comes from the voxel-volume step (mesh to volume). Without it the peak would be the meshing step, 7.2 GB.

Minimum-feature retention, same result at both voxel sizes:

| Station | Channels found | Hot wall (nominal 0.600 mm) | Channel width (nominal 1.000 mm) | Height, closeout vs nominal |
|---|---|---|---|---|
| z = 60 mm, chamber | 8 of 8 | 0.600 mm on every channel | 1.000 mm | within 0.0004 mm |
| z = 351.3 mm, throat | 8 of 8 | 0.600 mm | 1.000 mm | within 0.0004 mm |
| z = 900 mm, near joint | 16 of 16 | 0.600 mm | 1.000 mm | within 0.0004 mm |

Channels are counted along the mid-height arc with `bIsInside` (nearest voxel). Every radial line through a channel centre must show gas, wall, channel, closeout and outside in that order. Wall thicknesses and widths are where those lines cross the extracted mesh. On flat and gently curved walls the field holds the exact signed distance, so the linear zero crossing lands on the wall to about 1e-4 mm and the measured values match nominal. Read in whole voxels with `bIsInside`, the hot wall is 0.45 to 0.60 mm at 0.15 mm (3 to 4 voxels) and 0.50 to 0.63 mm at 0.10 mm (5 to 6 voxels, longer on lines oblique to the grid). The pictures `slice_throat_*.png` show this staircase against the analytic outline.

### Full 360 deg model

The full ring was not built. Scaled from the 0.15 mm sector, a full ring at 0.3 mm would need about 8.5 GB of voxels and 8.4 GB of mesh (467 million triangles, a 23 GB STL), over the 12 GB budget. The side walls of 384 to 768 channels, each 12 mm high, account for most of the surface. At 0.3 mm the 1.0 mm channels would also be only 3.3 voxels wide, so the result would only be good for viewing.

## How PicoGK is used headless

- `Library.Go` opens the viewer window, so it is not called. `new Library(voxelSize)` creates a library instance. All PicoGK objects take that instance explicitly (`new Voxels(lib, implicit, box)`, `new Mesh(vox)`), so no global library, log or viewer is needed.
- The native runtime and its DLLs (`picogk.26.2.dll`, `tbb12.dll`, `blosc.dll`, `lz4.dll`, `z.dll`, `zstd.dll`) are copied from `PicoGK\native\win-x64` into the output folder by the csproj. PicoGK.csproj packs them but does not copy them.
- `RenderImplicit` evaluates the implicit at every voxel of the box it gets, on the calling thread, at about 300 ns per call. One box over the full length would be mostly empty, so the part is rendered in 10 mm axial chunks with tight boxes and unioned with `BoolAdd`. Rendering chunks on parallel threads gave the same voxels as serial rendering in a test and in two full runs, then corrupted the native heap (exit 0xC0000374) in the third, so the chunks are rendered one after another.
- `Voxels.GetVoxelSlice` did not return values at the world XY positions that the source suggests, and `bRayCastToSurface` and `bClosestPointOnSurface` were 0.1 to 0.3 mm off at 0.15 mm. These are not used. Channel counts use `bIsInside`, which tests the nearest voxel. Wall positions are taken where probe lines cross the extracted mesh.
- `Voxels.CalculateProperties` meshes the field, re-voxelizes the mesh and counts voxels. On the full field this costs about 4 GB extra at 0.15 mm, and would cost about 11 GB at 0.10 mm. `VoxelVolume.dFromMesh` runs the same steps on the exported mesh after the field has been freed. It gives the same number (checked on a 40 mm throat piece). It calls the native `Voxels_fCalculateVolume` and reads PicoGK's internal handles by reflection.

## Limits

- This is a geometry model. Do not infer CFD or FEA mesh quality from the surface appearance or from the STL. The STL is a fine triangle surface of a voxel field. It is not an analysis mesh, and its sharp edges are rounded at the voxel scale.
- Hot wall, channel height and closeout are radial offsets, as in the 1-D model. On the 30 deg convergent cone the wall-normal hot wall is therefore 0.52 mm.
- The channel shape is idealised: flat parallel side walls, circular floor and ceiling, sharp corners, no fillets or manufacturing radii.
- The bifurcation blend geometry (length, linear swing) is a modelling choice; the 1-D model has no blend.
- At 0.15 mm the first part of each splitter knife edge is thinner than a voxel and is lost or perforated, which shows up as extra handles in the topology (see Validation). 0.10 mm resolves it.
- Injector face, manifolds, joint flange and the Inconel nozzle (zone 1) are not modelled. The channels end open at both end faces.
