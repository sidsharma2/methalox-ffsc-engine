# MFE-280 sea-level nozzle and plume: first CFD case

This folder holds the first CFD case for the MFE-280 thrust chamber: a steady RANS
run of the nozzle and its sea-level plume. It checks three results of the 0-D/1-D
design models in `ffsc/`:

- the exit pressure (1-D: 1.195 bar at full thrust, 0.49 bar at 40 % throttle),
- the delivered Isp and the throat mass flow, and
- whether the bell stays attached at sea level.

| Item | Value |
|---|---|
| OpenFOAM | v2306 (ESI), `/usr/lib/openfoam/openfoam2306`, WSL distro `Ubuntu-22.04` |
| Solver | `rhoCentralFoam`, Kurganov flux, local time stepping (LTS) |
| Turbulence | k-omega SST, wall functions |
| Geometry | 2-D axisymmetric wedge, 5 deg, one cell thick |
| Mesh | 248 526 cells at `--res 1` (blockMesh, 9 blocks), checkMesh OK; nozzle-only runs 43 380 |
| Gas | one calorically perfect gas, gamma 1.1250, cp 3216.6 J/(kg K), MW 23.257 |
| Inlet | total pressure 350 bar, total temperature 3785.1 K |
| Ambient | 101 325 Pa, 288 K, same gas |

Status (2026-11-02): all runs are done. Thrust and Isp come from the nozzle-only runs
(`~/runs/mfe280_sl_axi_nozzle`, `~/runs/mfe280_I2C_sl_axi_nozzle`, converged at iteration
24,000). The plume runs (`~/runs/mfe280_sl_axi`, `~/runs/mfe280_I2C_sl_axi`, run 4, 4 ranks
each) reached iteration 20,000 on 2026-11-02: I2-C at 05:28 MST, and I1 at 07:55 MST after a
restart with a new side boundary (run 4c, see "Run history"). The numbers are under
"Results" and the images under "Plume images". I2-C cases are generated with
`--results results/iterations/I2-C`. `post_compare.py` reads the exit-plane monitors of all
runs and compares thrust and Isp with the 1-D model.

On 2026-11-04 inviscid Euler runs and a PINN comparison were added. See "Inviscid runs and the
PINN comparison".

## Files

| Path | Content |
|---|---|
| `make_case.py` | Case generator. Reads `results/design.json` and `results/contour.csv`. |
| `cases/mfe280_sl_axi/` | Generated case (full thrust). |
| `cases/mfe280_sl_axi/case_info.json` | All chosen and derived numbers: gas study, stations, y+ estimates, BC values, 1-D references. |
| `cases/mfe280_sl_axi/Allmesh` | blockMesh, checkMesh, topoSet (exit-plane faceZone), cell centres. Does not run the solver. |
| `cases/mfe280_sl_axi/Allrun` | decomposePar, three-stage parallel run, reconstructPar. |
| `cases/mfe280_sl_axi/Allclean` | Removes mesh, results and logs. Keeps `0.orig`, `constant/*Properties` and `system/`. |
| `nozzle_only.sh` | Cuts a saved plume-run time down to the chamber and nozzle, makes the exit plane the outlet and continues the solver. |
| `plume_from_nozzle.sh` | Maps a converged nozzle-only solution onto time 0 of a plume case. |
| `hisa_nozzle.sh` | HiSA (implicit) version of a nozzle-only case from the same saved time, for the solver comparison. |
| `post_compare.py` | Thrust, Isp and mass-flow comparison with the 1-D model; discharge coefficient and vacuum Cf ratio; figure 15. |
| `euler_nozzle.sh` | Euler restart of a nozzle-only run: slip walls, no viscosity, no turbulence model. |
| `check_wedge.py` | Measures the inlet and outlet patch areas against pi R^2, for the two sector factors. |
| `render_pinn.py` | CFD and PINN contours on the real mesh, with errors, close-ups and the seed spread. |
| `plume_composition.py` | Exit-plane gas composition for the emission images (shifting equilibrium from the core chamber state to the design exit pressure); writes `results/plume_exit_composition.json`. |
| `render_plume.py` | Field images on the x-r plane (Mach number, temperature, log pressure, schlieren of ln rho), a Mach/schlieren split and a path-traced cutaway, through AetherCFD. |
| `render_los.py` | Line-of-sight images across the plume: knife-edge schlieren with two edge directions, shadowgraph, optically thin H2O + CO2 emission and its optical depth. |
| `render_volume.py` | The same thin emission seen from an oblique camera: perspective ray march through the revolved field on the GPU (CuPy). |
| `plume_steadiness.py` | Compares three saves of a plume run cell by cell and along the centreline, to show where the plume has settled. |
| `side_bc.py` | Replaces `ambient_side` in `p` files with the characteristic `exprMixed` switch (I1 run 4c). |

## Commands

Generate, mesh and initialise. Run this in PowerShell from the project root. Before it
meshes, it checks every running WSL distro for OpenFOAM processes and skips meshing if
it finds any.

```powershell
.venv\Scripts\python.exe cfd\make_case.py --force --mesh
```

Or do the same in three manual steps:

```powershell
.venv\Scripts\python.exe cfd\make_case.py --force
wsl -d Ubuntu-22.04 -e bash -lc "bash /mnt/d/Research/projects/methalox-ffsc-engine/cfd/cases/mfe280_sl_axi/Allmesh"
.venv\Scripts\python.exe cfd\make_case.py --init-only
```

Run the solver from a WSL shell. On 8 ranks the run takes about 11 h (about 1 s per iteration), so detach it:

```bash
cd /mnt/d/Research/projects/methalox-ffsc-engine/cfd/cases/mfe280_sl_axi
nohup bash Allrun 8 > log.Allrun 2>&1 &
tail -f log.rhoCentralFoam.1 | grep -E "^Time|Courant|ExecutionTime"
```

`Allrun` refuses to start while another `*Foam` process runs in the same distro.
`FORCE=1 bash Allrun 8` skips that check. It cannot see the other distros
(`LMAE-OpenFOAM`, `Agora`), so check those by hand. When run again, `Allrun` continues
from the latest processor time and skips the stages that are done.

Useful generator options (`--help` lists all of them):

| Option | Default | Effect |
|---|---|---|
| `--res` | 1.0 | Scales the cell counts in both directions. 0.7 gives about 90 k cells, 1.5 about 400 k. Wall first-cell heights stay fixed. |
| `--yplus` | 50 | Target cell-centre y+ used to size the wall cells. |
| `--pc-frac` | 1.0 | Fraction of the 350 bar chamber pressure. `0.4` writes `cases/mfe280_sl_axi_pc040`. |
| `--gas` | equivalent | `frozen` uses the frozen chamber gamma (1.188) instead. |
| `--wall-thermal` | adiabatic | `profile` imposes Twg(x) from `results/cooling_profile.csv` (`fixedProfile`). |
| `--time-mode` | lts | `transient` sets up time-accurate Euler stepping. |
| `--iters` | 40000 | End of stage 3 (LTS iterations). |
| `--lip-mm`, `--down-de`, `--rad-re`, `--up-re` | 20, 12, 8, 1.5 | Lip thickness and size of the external region (`--rad-re` was 5 for runs 1 and 2). |

For a 3 h or longer run, copy the case to the WSL home (ext4). Disk I/O on `/mnt/d` is
slower. Each write holds about 30 MB of ascii fields. `purgeWrite 4` keeps the last
four.

## Geometry and domain

x is the axial coordinate from the injector face; r is the radius.

| Region | Extent |
|---|---|
| Inlet plane | x = 0.0306 m (L_cyl/4), r = Rc = 0.2034 m |
| Throat | x = 0.3513 m, Rt = 0.1174 m |
| Exit | x = 2.0500 m, Re = 0.6848 m (eps 34, Rao 80 % bell) |
| Lip | 20 mm thick, flat base at the exit plane. The outer nozzle surface is the inner contour plus 20 mm, from x = 1.023 m (1.5 Re upstream of the exit). |
| Plume region | x from 2.05 m to 18.49 m (12 De), r up to 5.48 m (8 Re) |

The inner wall is a `polyLine` through the points of `contour.csv`, so the mesh follows
the design contour exactly. The internal part is split into five blocks at stations: the
inlet, the end of the cylinder, the throat, eps = 4, eps = 15 and the exit. Each station
has its own radial wall layer. The external part has four blocks: plume core, lip wake,
outer plume and the region outside the nozzle.

### Mesh (res = 1)

| Block | Cells (axial x radial) |
|---|---|
| inlet to end of cylinder | 26 x 90 |
| cylinder to throat | 126 x 90 |
| throat to eps 4 | 106 x 90 |
| eps 4 to eps 15 | 79 x 90 |
| eps 15 to exit | 145 x 90 |
| plume core (axis to Re) | 408 x 90 |
| lip wake (Re to Re + 20 mm) | 408 x 12 |
| outer plume (to 8 Re) | 408 x 345 |
| outside the nozzle | 66 x 345 |
| Total | 248 526 (247 636 hex, 890 prisms on the axis) |

Axial cell size: 4 mm at the inlet, 1 mm at the throat, 10 mm at eps 15, 4 mm at the
exit, then growing to 150 mm at the outlet. The radial core size is 1.7 mm at the
throat and 8.5 mm at the exit.

checkMesh (v2306, default checks):

| Check | Result |
|---|---|
| Cells | 248 526 |
| Max non-orthogonality | 31.2 deg (average 6.6) |
| Max skewness | 0.91 |
| Max aspect ratio | 90 |
| Wedge | front and back at 2.5 deg each, planar |
| Failed checks | none ("Mesh OK") |
| Axis patch | `empty`, 0 faces (collapsed vertices, `mergeType points`) |

Vertices and the mesh are written with 16 to 17 significant digits. At 9 digits,
OpenFOAM printed "wedge patch not planar" warnings on the 20 um wall faces.

### Wall spacing and y+

The first-cell height h at each station targets a cell-centre y+ of 50 (OpenFOAM
measures y at h/2 and uses wall properties). The wall shear comes from a turbulent
flat-plate correlation, cf = 0.0592 Re_x^-0.2, with Eckert reference-temperature
properties. x is the wall arc length from the inlet plane, and the wall is adiabatic
(T_w = T_aw, recovery factor Pr^(1/3)). The flow state is the 1-D isentropic solution of
the CFD gas. Treat the y+ values as +/-30 % estimates and check them against the
`yPlus` field after the run.

| Station | x [m] | M | T_aw [K] | Re_x | cf | u_tau [m/s] | h [um] | y+ (est.) |
|---|---|---|---|---|---|---|---|---|
| inlet / cylinder end | 0.031 / 0.122 | 0.20 | 3784 | 5.6e6 | 2.65e-3 | 9.1 | 45 | 50 |
| throat | 0.351 | 1.00 | 3763 | 6.1e7 | 1.64e-3 | 34.6 | 19.9 | 50 |
| eps 4 | 0.580 | 2.51 | 3679 | 2.3e7 | 1.99e-3 | 86 | 89 | 50 |
| eps 15 | 1.100 | 3.30 | 3632 | 1.1e7 | 2.32e-3 | 113 | 358 | 50 |
| exit | 2.050 | 3.75 | 3609 | 8.2e6 | 2.45e-3 | 126 | 833 | 48 |

Throat check by hand: p = 203 bar, T = 3562 K, u = 1197 m/s, tau_w = 18 kPa,
rho_w = 15.1 kg/m3, nu_w = 6.9e-6 m2/s. That gives u_tau = 34.6 m/s and a cell-centre
y+ of 9.95e-6 x 34.6 / 6.9e-6 = 50. At the exit, h is capped at 0.5 x lip / 12 = 0.83 mm
so that the lip block can cluster to the same size. The wall functions are
`nutUSpaldingWallFunction` (valid for all y+) and `omegaWallFunction`. A drift of
y+ between about 20 and 150 is acceptable.

With `--wall-thermal profile`, the wall is near 900 K and the wall density is about 4
times higher. The same y+ of 50 then needs a 2.9 um throat cell (7 times thinner) and a
40-cell wall layer. That mesh also passes checkMesh (227 k cells), but check the h
values that `make_case.py` prints before you run it.

## Gas model

The hot gas is a single calorically perfect gas (`hePsiThermo`, `hConst`, `perfectGas`,
`sensibleInternalEnergy`). The data come from `ffsc.thermo` (Cantera, CEA thermo data) at
the core-stream chamber state: pc = 350 bar, O/F_core = 3.824, Tc = 3785.1 K. The frozen
chamber mixture has MW 23.257, cp 2262 J/(kg K) and gamma 1.188. Mole fractions:
H2O 0.511, CO2 0.167, CO 0.134, OH 0.072, H2 0.047, O2 0.045, H 0.013, O 0.011.

With constant cp and MW, choosing gamma fixes cp. The table runs four candidates through
an ideal 1-D nozzle at eps = 34 and compares them with the shifting-equilibrium solution (pe 1.195 bar, Te 2217 K, ue 3374 m/s, c* 1832.0 m/s,
Isp_sl 347.3 s, Isp_vac 365.7 s):

| Option | gamma | cp [J/(kg K)] | pe [bar] | Te [K] | c* | Isp_sl | Isp_vac |
|---|---|---|---|---|---|---|---|
| frozen, chamber cp | 1.1877 | 2262 | 0.941 (-21 %) | 1486 (-33 %) | -1.7 % | 327.6 s (-5.7 %) | 345.7 s (-5.5 %) |
| frozen, mean cp over the frozen expansion | 1.2026 | 2122 | 0.890 (-26 %) | 1384 (-38 %) | -2.2 % | 323.4 s (-6.9 %) | 341.4 s (-6.7 %) |
| gamma_eff from pc/pt (`design.json`) | 1.1299 | 3109 | 1.173 (-1.8 %) | 1966 (-11 %) | +0.07 % | 345.9 s (-0.4 %) | 364.3 s (-0.4 %) |
| equivalent (used) | 1.1250 | 3217 | 1.195 (0.0 %) | 2013 (-9.2 %) | +0.22 % | 347.6 s (+0.07 %) | 366.0 s (+0.08 %) |

The case uses the equivalent gas. MW is the chamber value, and gamma is set so that the
perfect-gas expansion to eps = 34 gives the shifting-equilibrium exit pressure. The cp
that follows (3217) is an effective value. It includes the recombination heat that a
frozen cp of 2262 leaves out. This gas reproduces pe exactly, c* and the throat mass
flux within 0.2 %, Isp within 0.1 % and the throat pressure within 0.2 %. The cost is the
static temperature in the bell: 9 % low at the exit (2013 K against 2217 K), which makes
the density about 10 % high and the frozen-gamma Mach number 3.75 against 3.66. Any
CFD-to-1-D difference in pe, mass flow or Isp therefore measures 2-D and viscous
effects. The frozen-chamber option bounds the opposite case: frozen chemistry
from the chamber, with 21 % lower pe and 5.7 % lower Isp.

Transport: a Sutherland law fitted to the Cantera viscosity of the frozen chamber
mixture from 250 to 4000 K, As = 1.8874e-6 Pa s K^-0.5 and Ts = 434.8 K. The maximum
error is 5.6 %. At the chamber temperature the fit gives 1.04e-4 Pa s against 1.09e-4.
OpenFOAM's `sutherland` transport sets conductivity with a modified Eucken relation.
The resulting Prandtl number is 0.73; Cantera gives 0.64 for the frozen mixture.

## Boundary conditions

| Patch | p | U | T | k / omega | nut / alphat |
|---|---|---|---|---|---|
| `inlet` | `totalPressure` 350 bar (isentropic, psi, gamma) | `pressureInletOutletVelocity` | `totalTemperature` 3785.1 K | 5 % intensity (k = 236 m2/s2) / mixing length 1.9 mm, 0.07 x injector element pitch (omega = 1.5e4 1/s) | calculated |
| `wall_chamber`, `wall_bell` | zeroGradient | noSlip | zeroGradient (adiabatic) | `kqRWallFunction` / `omegaWallFunction` | `nutUSpaldingWallFunction` / `compressible::alphatJayatillekeWallFunction` (Prt 0.85) |
| `lip`, `wall_outer` | zeroGradient | noSlip | zeroGradient | wall functions | wall functions |
| `ambient_inlet` (x = 1.023 m, outside the nozzle), `ambient_side` (r = 8 Re) | `fixedValue` 101 325 Pa (static); I1 run 4c: `exprMixed` on `ambient_side`, see below | `pressureInletOutletVelocity` | `inletOutlet` 288 K | `inletOutlet` k = 0.01, omega = 154 (nu_t/nu = 5) | calculated |
| `outlet` (x = 18.49 m) | `waveTransmissive`, relaxes to 101 325 Pa over lInf = 16.4 m | `inletOutlet` | `inletOutlet` 288 K | `inletOutlet` | calculated |
| `axis` | empty (0 faces) | | | | |
| `front`, `back` | wedge | | | | |

The hot-gas walls are adiabatic. This matches the 1-D model, where the regen heat goes
back into the flow, and it keeps the first run simple. A fixed wall-temperature profile
from the regen model is available through `--wall-thermal profile`.

The ambient boundaries act as an open reservoir at the ambient static pressure: the plume
draws in as much gas as it entrains, at 288 K and with no tangential velocity. The inflow
there is a few m/s, so its dynamic pressure (about 10 Pa) is negligible. The outlet is
non-reflecting, so that the plume core can leave supersonic.

A fixed static pressure is also a pressure-release boundary: it reflects an arriving
compression wave as an expansion of the same strength. That does not matter for the weak
steady entrainment, but it does for a strong start-up shock (run 3). The initial field
therefore avoids a jet head; see "Numerics and run control".

A fixed static pressure is also wrong for supersonic outflow, where the boundary should
take its pressure from inside. In I1 run 4 the starting vortex ring drove a radial stream
at Mach 2.4 to 2.85 out through `ambient_side` near x = 10.5 m. The pressure in the
boundary cell fell to 2 to 3 kPa, the internal energy went negative, and the thermo update
stopped at iteration 7,969. A restart from 6,000 at maxCo 0.1 stopped at 8,948 in the same
cell, so the Courant number was not the cause. Run 4c restarted from 8,000 with a
characteristic switch on that patch only (`exprMixed`, written into the processor `p`
files by `side_bc.py`). With Mn the outward normal Mach number of the
adjacent cell, a face holds 101 325 Pa for Mn < 0.9, takes zero gradient for Mn > 1.1
and blends linearly in between:

```
ambient_side
{
    type            exprMixed;
    value           uniform 101325;
    variables       ( "Mn = (internalField(U) & face())/area()/sqrt(1.12504*internalField(p)/internalField(rho))" );
    valueExpr       "101325";
    gradientExpr    "0";
    fractionExpr    "(Mn < 0.9) ? 1 : ((Mn > 1.1) ? 0 : (1.1 - Mn)/0.2)";
}
```

While every face has Mn < 0.9 this is the same condition as `fixedValue`. At iteration
9,000, 15 of the 474 side faces had switched, all of them supersonic outflow next to the
failed cell. At 11,000 and 12,000 none had, and in the saves from 17,000 to 20,000
valueFraction is 1 on every face. The converged I1 solution therefore has the same
fixed-pressure side boundary as I2-C. (`codedMixed` would be the usual way to write
this, but OpenFOAM refuses to compile dynamic code when it runs as root, as it does in this
WSL distro.) `make_case.py` does not write this condition yet.

## Numerics and run control

- Kurganov central-upwind fluxes, with van Leer reconstruction of rho, U and T.
  `limitedLinear 1` for k and omega. `limited corrected 0.5` on Laplacians and surface
  normal gradients.
- Local time stepping (`ddtSchemes localEuler`, supported by v2306 `rhoCentralFoam`). One
  time unit is one iteration. `rDeltaTSmoothingCoeff 0.2` limits the ratio of local time
  steps between neighbouring cells to 1.2. That is about the mesh growth rate, so the
  small wall cells do not slow down the core.
- CFL in `Allrun`: maxCo 0.1 to iteration 1,000, then 0.15 to 20,000 (I1 run 4c: 0.1 from
  8,000 to 12,000). Higher values are not used: at 0.3 the nozzle-only runs went into a
  chamber limit cycle (see "Nozzle-only runs").
- Far field: `ambient_inlet` and `ambient_side` hold 101,325 Pa as a fixed static pressure,
  with `inletOutlet` 288 K. Runs 1 and 2 failed at this boundary; see "Run history".
  `Allrun` edits `maxCo` and `endTime` with `foamDictionary`. This removes the comments
  from `controlDict` and expands its `$` macros; the result is the same.
- Initial field (`make_case.py --init-only`): the 1-D isentropic solution in the nozzle,
  subsonic before the throat and supersonic after it. The flow angle varies linearly
  from 0 at the axis to the wall angle. Downstream of the exit, a column of exit-state
  flow (r < Re) runs to the outlet through still ambient gas, and the outlet faces inside
  r < Re carry the same state. This avoids the starting transient of a 350 bar diaphragm
  burst, and with no jet head there is no starting shock. Up to run 3 the column was 4 De
  long: its blunt end drove a shock of about 7 times ambient pressure into the ambient gas.
  With the outlet faces left at U = 0, the first iteration of run 4 treated the outlet as a
  wall for the Mach 3.75 column, and the second iteration stopped with a floating-point
  exception in the thermo update.
- Transient alternative (`--time-mode transient`): the 20 um throat cells limit the
  explicit time step to about 6e-9 s. 5 ms of physical time would need about 8e5 steps,
  roughly 30 h on 8 cores. Do not use it for the first run.

Run time: the measured cost on one core (i7-11800H in WSL, 4 ranks, parallel efficiency
included) is 2.3e-5 s per cell-iteration on the 43 k-cell nozzle-only mesh (0.25 to 0.34 s
per iteration) and 5.3e-5 s on the 249 k-cell plume mesh with two runs sharing the memory
bus (3.3 s per iteration). The plume mesh no longer fits in cache. 20,000 plume iterations
on 4 ranks take about 18 h. The laptop has 8 physical cores and 16
threads: run at most 8 ranks in total. Hyper-threads add little to a memory-bound solver.
The low-Mach chamber is the slowest part to settle. Call a run converged when the inlet and
exit mass flows agree within 0.1 % and the exit momentum flux changes by less than 0.1 % over
2000 iterations. If not, raise `endTime` and run `Allrun` again.

GPU: OpenFOAM's GPU options (AmgX or PETSc offload) only speed up the linear solves of
pressure-based solvers. `rhoCentralFoam` is explicit, with no large linear solve to offload.
The laptop GPU (RTX 3050 Ti, 4 GB, shared with Ollama) also has 1/64-rate FP64, below the
CPU's double-precision throughput, and this flow needs double precision (20 Pa to 35 MPa).

## Nozzle-only runs

At sea level the nozzle is under-expanded (pe/pa = 1.18) and the exit flow is supersonic,
so nothing in the plume can travel upstream of the exit plane, and the wall boundary layer
sees no adverse ambient pressure. Thrust and Isp therefore need only the chamber and the
nozzle. `nozzle_only.sh` takes a saved time of a plume run, keeps the cells upstream of the
exit plane (the connected region that holds the throat axis, 43 380 cells for I1), makes
the exit plane the `outlet` patch (zeroGradient p and T, `inletOutlet` U) and continues
`rhoCentralFoam`. Since nozzle-only runs have no plume, they also have no starting vortex
and no far-field boundary.

```bash
bash cfd/nozzle_only.sh ~/runs/mfe280_sl_axi_run2 ~/runs/mfe280_sl_axi_nozzle 4000 4 24000
bash cfd/plume_from_nozzle.sh ~/runs/mfe280_sl_axi ~/runs/mfe280_sl_axi_nozzle   # before the first Allrun
```

`PREP_ONLY=1` stops `nozzle_only.sh` after the mesh cut. The plume mesh has the same
chamber and nozzle blocks as the nozzle-only mesh, so `plume_from_nozzle.sh` copies the
converged interior exactly and the plume run only has to develop the external flow.

The nozzle-only runs use maxCo 0.15. At 0.3 the wall cells next to the injector face went
into a numerical limit cycle: static pressure up to 43 MPa against the 35 MPa inlet total
pressure, and the inlet mass flow swung by about 13 %. Those 2,000 iterations are kept in
`processor*/6000.maxCo03`, `postProcessing.maxCo03` and `maxCo03/`.

`post_compare.py` also reports a vacuum Isp from the exit plane alone,
(momentum flux + pressure force) / exit mass flow. For a fixed T0 and area ratio this
does not depend on the chamber pressure, so it is a stable measure while the chamber is
still settling.

## Implicit solver test (HiSA)

HiSA (gitlab.com/hisa/hisa, tag `validated-v2306`, version 1.9.6, GPLv3) is an implicit,
density-based coupled solver for OpenFOAM: AUSM+up fluxes, a Jacobian of the coupled
rho/rhoU/rhoE system, LU-SGS-preconditioned GMRES, and a pseudo-time Courant number that
grows as the residual falls (here from 5 to at most 100, against 0.15 for `rhoCentralFoam`).
It is built into the WSL user's OpenFOAM tree (`/root/OpenFOAM/hisa-validated-v2306`). The
source audit is in ResearchOS `cfg/open_source_review.yaml`.

`hisa_nozzle.sh` turns a nozzle-only case into a HiSA case from the same saved time, so the
two solvers start from the same state on the same 43 380-cell mesh:

```bash
bash cfd/hisa_nozzle.sh ~/runs/mfe280_sl_axi_nozzle ~/runs/mfe280_sl_axi_hisa 4000 4 3000
```

Changes from the `rhoCentralFoam` case: `fvSchemes` (AUSM+up with the low-Mach option for the
M ~ 0.2 chamber, dual-time pseudo-steady ddt), `fvSolution` (GMRES, pseudo-time control), the
inlet and the walls. The wedges keep `type wedge`: HiSA's library registers its coupled wedge
under that name and replaces the standard one when it loads (`libs` in `controlDict`).

| Patch | p | T | U |
|---|---|---|---|
| `inlet` | `characteristicFarfieldPressure` | `characteristicFarfieldTemperature` | `characteristicFarfieldVelocity` |
| `wall_chamber`, `wall_bell` | `characteristicWallPressure` | `characteristicWallTemperature` (adiabatic) | `boundaryCorrectedFixedValue` 0 |
| `outlet` | zeroGradient | zeroGradient | `inletOutlet` |

The inlet's outside state is the 1-D isentropic state at the inlet plane (p = 341.9 bar,
T = 3775.4 K, u = 250.8 m/s for I1). The inflow velocity stays free, so the throat still sets
the mass flow and the total pressure can end slightly off 350 bar; the exit-plane vacuum Isp
does not depend on it. Two problems found in the smoke tests:

- `characteristicPressureInletOutletTemperature` sets the temperature reference value to 0 on
  subsonic inflow. OpenFOAM's `mixedEnergy` then evaluates he(p, T = 0), a division by zero,
  and the default floating-point trap stops the run in the first iteration. The far-field
  condition sets a real face temperature and is also non-reflecting.
- `waveTransmissive` (advective) conditions do not accept HiSA's `dualTime` ddt scheme, even on
  the 0-face plume patches left in the nozzle-only mesh; these are set to zeroGradient.

## Run history

| Run | Far field | Result |
|---|---|---|
| 1 (2026-10-31) | `totalPressure` / `inletOutletTotalTemperature` on `ambient_*`, r = 5 Re | FPE at iterations 2,116 and 2,198. The total-pressure inflow sets p = p0 − ρU²/2; the plume's starting vortex drove fast entrainment through the r = 5 Re patch near x = 8.5 m, and the density there went negative. |
| 2 (2026-10-31) | `waveTransmissive` p on `ambient_*` (relaxes to 101,325 Pa over lInf = 16.4 m), r = 5 Re | FPE in the thermo update at iterations 5,554 (I1) and 4,991 (I2-C). On inflow faces only T and the tangential velocity were fixed, so the pressure could drift: the extremes log shows the minimum p on the r = 5 Re patch falling to 19 to 23 Pa while it moved downstream. At iteration 4,000 the ambient region already had 2.3 kPa at r = 2.7 Re. The nozzle interior was not affected. |
| Nozzle-only (2026-11-01) | none (exit plane is the outlet) | Continued from run 2 at iteration 4,000. |
| 3 (2026-11-01) | `fixedValue` p on `ambient_*`, r = 8 Re | Seeded from the nozzle-only solutions. FPE in the thermo update at iterations 3,183 (I1) and 3,033 (I2-C), both next to `ambient_side` (I1: 2.3 kPa at x = 10.5 m). The 4 De exit column's blunt end drove a starting shock into the still gas (at iteration 2,000: 741 kPa and 430 m/s outward at x = 8.5 m, r = 1.1 m), followed by an expansion (15 kPa, 243 K) that moved out to r = 3 m. The fixed-pressure side face reflected the shock as an expansion. |
| 4 (2026-11-01) | as run 3 | Exit column through the whole plume region, outlet faces set to the column state, maxCo 0.1 to 1,000 then 0.15 to 20,000. Seeded from the nozzle-only solutions. I2-C reached 20,000 on 2026-11-02 at 05:28 MST. I1 stopped with an FPE at iteration 7,969 in a side-boundary cell (x = 10.53 m, r = 5.45 m): supersonic outflow through the fixed-pressure face (see "Boundary conditions"). |
| 4b (2026-11-01) | as run 3 | I1 from iteration 6,000 at maxCo 0.1. FPE at 8,948 in the same cell. |
| 4c (2026-11-01) | I1: `exprMixed` switch on `ambient_side` | I1 from iteration 8,000, maxCo 0.1 to 12,000, then 0.15. Reached 20,000 on 2026-11-02 at 07:55 MST (1.9 s per iteration at the end). |

The run-2 and run-3 directories are kept as `~/runs/*_run2` and `~/runs/*_run3`, and the
first run-4 attempt for I1 (stopped at iteration 2, then used for the diagnosis) as
`~/runs/mfe280_sl_axi_run4a`. The logs of the two I1 side-boundary failures are
`log.rhoCentralFoam.2` and `.3` in `~/runs/mfe280_sl_axi`, and the `fixedValue` p files of
time 8,000 are kept in `~/runs/mfe280_sl_axi_p8000_fixedValue`. In the I1 run-2 case (generated by an
earlier version of this script) the `exitPlane` faceZone had mixed face orientations, so
`exitMassFlow` read about half the true flow (5.5 against 10.9 kg/s per wedge). The
momentum and mass-weighted monitors use |U . n| as weight and were not affected, and Isp
uses the inlet mass flow. The current topoSet (`setAndNormalToFaceZone`) and the
nozzle-only `outlet` patch do not have this problem.

## Outputs

The case is a 5 deg sector with flat faces. A cross-section is a triangle of area
r^2 sin(theta) / 2, so multiply every integrated flow, force and area by
2 pi / sin(5 deg) = 72.0915. The arc factor 360/5 = 72 reads 0.127 % low. That error
cancels in vacuum Isp but stays in mass flow, thrust, Cd and the Cf ratio.
`post_compare.py` applies the flat-face factor.

| Function object | Output (`postProcessing/<name>/<start time>/`) |
|---|---|
| `exitMassFlow` | sum of `phi` over faceZone `exitPlane` (x = 2.05 m, axis to the inner lip edge, 90 faces, oriented +x): mdot_wedge [kg/s] |
| `inletMassFlow` | sum of `phi` on `inlet` (negative): convergence check |
| `exitMomentumFlux` | sum of rho (U . Sf) U over the exit plane: momentum flux [N], x component |
| `exitPressureForce` | sum of p \|Sf\| over the exit plane [N] |
| `exitAreaAverage` | area averages of p, T, rho and U, plus the wedge exit area (`writeArea`) |
| `exitMassAverage` | mass-flux-weighted p, T and U |
| `innerWallForces` | pressure and viscous force on `wall_chamber` + `wall_bell`, pRef = 101 325 Pa |
| `wallSurfaces` | raw p, T, Ma and yPlus on the inner wall and on lip + outer wall, at every write (wall pressure p_w(x), separation check) |
| `yPlus`, `MachNo` | fields written at write times |
| `minMax`, `probes` | p, T and U extremes; probes at the throat axis, exit axis, near the exit wall, and 2 De and 6 De downstream on the axis |

Thrust and Isp from the exit plane, with the same control volume as the 1-D model:

```
mdot   = 72 * sum(phi)                                   [exitMassFlow]
F_sl   = 72 * ( Mx + P - pa * A )                         Mx [exitMomentumFlux, x], P [exitPressureForce], A [exitAreaAverage Area]
F_vac  = F_sl + 72 * pa * A
Isp_sl = F_sl / (mdot * 9.80665)
c*     = 350e5 * At / mdot,   At = 0.043333 m2
pe     = area-averaged p      [exitAreaAverage]
```

View the fields in ParaView: `touch case.foam` in the case and open that file.

## What to compare against the 1-D model (full thrust)

| Quantity | 1-D shifting equilibrium (`ffsc.thermo`, core O/F) | 1-D ideal, CFD gas | `design.json` (delivered) | Expected from the CFD |
|---|---|---|---|---|
| pe | 1.195 bar | 1.195 bar | 1.195 bar | area average near 1.2 bar. The exit profile is not uniform, so also compare the lip wall pressure from `wallSurfaces`. |
| Me | 3.66 | 3.75 | 3.66 | |
| c* | 1832.0 m/s | 1836.1 m/s | 1807.4 m/s (eta_c* 0.99, film split) | 0.5 to 1 % above 1836 (2-D sonic line, boundary layer) |
| mdot at 350 bar | 827.9 kg/s | 826.0 kg/s | 839.2 kg/s | Cd x 826.0, with Cd about 0.99 to 0.995 |
| Isp_sl | 347.3 s | 347.6 s | 333.7 s | 340 to 344 s |
| Isp_vac | 365.7 s | 366.0 s | 351.8 s | |
| F_sl | | 2.816 MN | 2.746 MN | |

How to read these:

- The CFD inflow is ideal core gas (O/F 3.82, no c* loss), so `design.json` mdot and Isp
  are not the direct comparison. The design sized At with the delivered c* (1807 m/s);
  at 350 bar and ideal core c* the same throat passes 1.6 % less mass.
- CFD Isp_sl over the ideal 1-D Isp_sl (347.6 s) is the thrust-coefficient efficiency
  of the bell: divergence (theta_e = 8.3 deg) plus wall friction. The design assumes
  eta_Cf = 0.98. This ratio is the main check of that number.
- CFD c* over 1836.1 m/s, or mdot over 826.0 kg/s, is the throat discharge coefficient.
- Separation: at full thrust pe/pa = 1.18 (Schmucker limit 0.32), so the bell must stay
  attached. Check the wall pressure p_w(x) up to the lip for a plateau or a rise. At 40 %
  throttle the 1-D model gives pe = 0.49 bar and pe/pa = 0.48. That is above the
  Schmucker limit (0.32) but close to the Summerfield value (0.4). The 40 % case
  (`--pc-frac 0.4`) tests that margin.

## Results

Exit-plane monitors, mean of the last 2,000 iterations (`post_compare.py`,
`results/cfd_compare.json`, figure 15). The 1-D reference is the ideal flow of the same gas
from the same chamber state through the same throat, so the mass-flow ratio is the
discharge coefficient Cd and Cd times the vacuum Isp ratio is the vacuum thrust-coefficient
ratio, the number the cycle model applies as eta_Cf = 0.98.

| Case | Iterations | mdot (kg/s) | Cd | F_sl (MN) | F_sl / 1-D | Isp_sl (s) | Isp_vac, exit (s) | Cf_vac / 1-D |
|---|---|---|---|---|---|---|---|---|
| I1 nozzle-only | 24,000 | 820.80 | 0.9937 | 2.7637 | 0.9816 | 343.34 | 361.94 | 0.9826 |
| I1 HiSA, nozzle-only | 7,000 | 821.35 | 0.9943 | 2.7637 | 0.9816 | 343.12 | 361.51 | 0.9821 |
| I1 plume | 20,000 | 820.79 | 0.9937 | 2.7636 | 0.9816 | 343.34 | 361.94 | 0.9826 |
| I2-C nozzle-only | 24,000 | 814.62 | 0.9937 | 2.7629 | 0.9817 | 345.85 | 362.17 | 0.9827 |
| I2-C plume | 20,000 | 814.61 | 0.9937 | 2.7630 | 0.9817 | 345.87 | 362.17 | 0.9827 |

- Correction, 2026-11-04: this table uses the flat-face sector factor. Before that date it
  used 72, which gave Cd 0.9924, Cf_vac ratio 0.9814 and F_sl ratio 0.9803. Vacuum Isp did
  not change, and sea-level Isp rose by 0.02 s.
- Nozzle efficiency: the vacuum Cf ratio is 0.983 for both iterations, against the 0.98
  the cycle model assumes. The sea-level thrust ratio is 0.982. The loss is divergence
  (exit angle 8.3 deg) and wall friction, with adiabatic walls and wall functions.
- Discharge coefficient: the throat passes 0.63 % less than the 1-D flow (2-D sonic line
  and boundary layer). In the design this sits inside the delivered c* (eta_c* = 0.99).
- Solver cross-check: HiSA (implicit, AUSM+up) on the same I1 nozzle mesh agrees with
  `rhoCentralFoam` within 0.07 % in Cd, 0.01 % in thrust and 0.12 % in exit vacuum Isp,
  after 7,000 iterations against 24,000.
- The plume runs reproduce the nozzle-only exit plane (thrust within 0.001 % for I1 and
  0.002 % for I2-C), as they must with a supersonic exit. Inlet and exit mass flows agree
  within 0.02 %.
- Separation: none at full thrust. The bell wall pressure falls to the lip with no plateau
  or rise, to 179 kPa in I1 and 200 kPa in I2-C (1.8 and 2.0 times ambient). Ripples
  along the wall stay below 1.5 kPa. The area-averaged exit pressure is 122.4 kPa in I1
  (1-D: 119.5 kPa) and 139.4 kPa in I2-C (1-D: 136.1 kPa).

Plume steadiness. Three saves of each run were compared cell by cell
(`plume_steadiness.py`): 16,000, 18,000 and 20,000 for I2-C, and 17,000, 18,000 and 20,000
for I1, whose 16,000 save was purged.

- The centreline Mach number agrees within 0.01 between the three saves from the throat to
  x = 5.1 m in I2-C and to x = 4.75 m in I1. That covers the first two shock cells. In
  I2-C the flow expands to Mach 4.13 at x = 3.1 to 3.4 m and recompresses to 3.83 at
  x = 4.3 m; in I1 the values are 4.12 at x = 3.3 to 3.7 m and 3.80 at x = 4.6 m. The I2-C
  axis probe at x = 4.48 m varies by 0.6 % in pressure over the last 2,000 iterations. The
  I1 probe at x = 4.79 m varies by 0.5 % over the same window, but it read 79 to 191 kPa
  in the 2,000 iterations before, so the steady I1 region ends close to that point.
- Further downstream the shock cells move between saves. The centreline Mach number at a
  given x changes by up to 2.5 in I2-C and 1.7 in I1. Over the last 2,000 iterations the
  axis probe 6 De downstream of the exit reads 124 to 790 kPa (I2-C, x = 9.59 m) and 29 to 473 kPa (I1,
  x = 10.27 m). The shear layer rolls up into large structures that convect downstream and
  send pressure waves into the ambient gas. Pressure minima reach 2.5 to 7 kPa near r = 1 m,
  x = 3 to 5 m in I2-C, and 2.2 to 11 kPa in I1, near r = 1.1 to 1.3 m at x = 3.9 to 4.8 m
  or on the axis at x = 6.8 to 7.4 m. In I2-C the induced inflow at x = 8 m, r = 2.5 m
  reaches 250 m/s.
- LTS RANS has therefore not reached a steady state in the far plume. The iteration-20,000
  field there is one state of a pseudo-time cycle; a time average would need a
  time-accurate run. Nothing upstream of the exit plane depends on it.

## Inviscid runs and the PINN comparison

`euler_nozzle.sh` restarts the I2-C nozzle-only run with slip walls, no viscosity and no
turbulence model. The inlet, gas and numerics stay the same, so the difference from the
RANS run is the viscous loss. The finer run uses `make_case.py --res 1.5` and starts from
the coarse Euler solution mapped onto the new mesh.

| Run | Cells | Iterations | Wall time | Cd | Cf_vac / 1-D | Isp_vac, exit (s) | Mass imbalance |
|---|---|---|---|---|---|---|---|
| RANS | 40,860 | 20,000 | 2 h 01 min, 4 ranks | 0.99370 | 0.98271 | 362.17 | 0.019 % |
| Euler | 40,860 | 20,000 | 46 min, 4 ranks | 0.99478 | 0.98781 | 363.66 | 0.010 % |
| Euler, finer | 91,935 | 30,000 | 2 h 10 min, 8 ranks | 0.99480 | 0.98787 | 363.67 | 0.016 % |

- Loss split on the 40,860-cell mesh: the 1.73 % nozzle loss is 1.22 % 2-D divergence and
  0.51 % viscous. The 0.63 % Cd deficit is 0.52 % from the 2-D sonic line and 0.11 % from the
  boundary layer.
- Mesh check: from the coarse to the finer mesh, Cd moves 0.002 % and the Cf ratio 0.006 %.
  Block means of the finer run's vacuum Isp scatter by 0.0004 %. Two meshes give no observed
  order of convergence.
- Internal shock: the bell has a real shock that reaches the axis near x/Rt = 10. It is not
  mesh converged. On the axis, the peak Mach number goes from 4.137 at x/Rt = 9.62 to 4.179 at
  x/Rt = 9.83, the trough from 3.279 to 3.190, and the width from 0.47 Rt to 0.22 Rt. The shock
  fills too little volume to change the integrals.
- Theory: Kliegel-Levine for a wall radius of curvature of 1.5 Rt at the throat gives Cd
  0.9947 to 0.9952, which brackets the Euler value. The I2-C wall radius of curvature is 1.5 Rt
  upstream of the throat and 0.382 Rt downstream.

A PINN trained on the same problem with no CFD data matches the finer Euler run: on five
seeds, Cd 0.99542 (+0.062 %), Cf ratio 0.98858 (+0.072 %) and Mach L2 error 0.87 %. It
smears the internal shock over about 3 Rt, and its largest Mach error is 0.47. The method,
results and figures are in `../pinn/README.md`, and the contours are in `figures/pinn/step3`.

## Plume images

All images use the iteration-20,000 save. They are in `figures/cfd/` at 1920 x 1080, with
4K originals in `figures/cfd/4k/`. The frame runs from x = 0.15 to 10.5 m. The plume core
is steady to x = 5.1 m (I2-C) and 4.75 m (I1); downstream the field is one state of a moving
pattern (see "Results").

| Image | Script | What it shows |
|---|---|---|
| `plume_<tag>_Ma`, `_T`, `_log10p` | `render_plume.py` | Mach number, temperature and log10 pressure on the x-r plane and its mirror image. |
| `plume_<tag>_schlieren` | `render_plume.py` | exp(-k \|grad ln rho\| / its 99th percentile) on the plane, k = 4. |
| `plume_<tag>_split` | `render_plume.py` | Mach number above the axis, schlieren below. |
| `plume_<tag>_cutaway` | `render_plume.py` | 270 deg revolved walls, Mach number on the cut faces where T > 700 K, translucent T = 1000 K isosurface (GPU), OptiX path tracing. |
| `los_<tag>_schlieren_x`, `_schlieren_r` | `render_los.py` | Knife-edge schlieren through the whole revolved plume, edge normal to x (axial gradients) or to r. |
| `los_<tag>_shadowgraph` | `render_los.py` | Shadowgraph through the whole revolved plume. |
| `los_<tag>_emission_thin` | `render_los.py` | Optically thin H2O + CO2 thermal radiance, an upper bound. |
| `los_<tag>_optical_depth` | `render_los.py` | Planck-mean optical depth along each ray, with tau = 1 and 3 contours. |
| `volume_<tag>_emission` | `render_volume.py` | The thin radiance from an oblique camera, GPU ray march. |

Smoothing is linear interpolation only: the cell values are averaged to the mesh points
and interpolated per pixel or per grid point, so no cell edges show and no value is added
that the solver did not compute. A shock spreads over about one cell.

Line-of-sight images. A camera looks across the plume, as a test-stand schlieren system or
an infrared camera would. `render_los.py` samples the axisymmetric fields on a regular
(x, r) grid at pixel spacing out to the side boundary and sums along each ray over annular
rings with exact chord lengths. Optics follow Settles (Schlieren and Shadowgraph
Techniques, 2001): n - 1 = K rho with one Gladstone-Dale constant, K = 2.3e-4 m3/kg;
deflection = gradient of the optical path difference; knife-edge contrast
I/I0 = 1 - (f/a) eps; shadowgraph contrast I/I0 = 1 - L lap(OPD) in the small-deflection
limit. The sensitivities f/a and L are set as an experimenter would set the knife edge, so
that the 99th percentile of the signal uses half of the grey range:

| Case | Edge normal to x: full range | Edge normal to r: full range | Shadowgraph screen distance L | Planck-mean optical depth on the axis at x = 2, 4, 5, 9 m |
|---|---|---|---|---|
| I1 | +-2.61 mrad (f/a = 383) | +-2.52 mrad | 14 m | 4.2, 5.9, 6.3, 10.3 |
| I2-C | +-2.22 mrad (f/a = 450) | +-2.29 mrad | 19 m | 4.1, 4.5, 10.8, 12.3 |

The emission model: a mixture fraction from the stagnation enthalpy,
Z = (h0 - h0_amb)/(h0_jet - h0_amb). This is valid here because the CFD has one gas with
constant cp and adiabatic walls, so h0 mixes as a passive scalar when the turbulent Prandtl
and Schmidt numbers are equal. The exit composition from `plume_composition.py` (I2-C:
H2O 0.644, CO2 0.289, CO 0.043, H2 0.018) is diluted with dry air by Z and held frozen. The
Planck-mean absorption coefficients are the RADCAL fits used by the TNF workshop, the same
numbers as in the OpenFOAM v2306 tutorial `combustion/reactingFoam/RAS/SandiaD_LTS`
(`radiationProperties`, valid 300 to 2500 K; T is clipped to that range for kappa only).
Radiance is the ray sum of kappa_P sigma T^4 / pi.

Limits of these images:

- One Gladstone-Dale constant for all the gas. The products' constant is roughly 20 %
  higher than air's, mostly from the H2O. A different K changes the stated deflection
  angles and leaves the images the same.
- The ambient is the CFD gas, at 0.99 kg/m3 instead of 1.225 kg/m3 for air, so the density
  step at the plume edge is smaller than in a real test.
- Vertical stripes at x = 1.9 to 3.5 m in the edge-normal-to-x schlieren and in the
  shadowgraph are pressure waves 4 to 5 cm long in the solution itself. A finite-difference
  check of the optical path gives the same deflection within 1 %. The waves lie where the
  axial cell spacing is fine and run normal to x; they also show as ripples in the
  mid-plane schlieren. The ray sum over up to 10 m of path makes them prominent. They are
  probably numerical.
- In the I1 schlieren and shadowgraph a single dark line at x = 2.25 m crosses the whole
  frame. It is a compression front in the ambient gas at the moment of the save: at
  r = 2.8 m the pressure rises from 97 to 119 kPa over 2 cm, and a weaker front continues
  out to r = 4.5 m. A front normal to the axis at a large radius crosses every line of sight
  below that radius, so it shows over the full image height. It is one of the waves the
  shear layer sends out (see "Results"), and the 18,000 save does not have it.
- The emission image is an upper bound. On the axis the Planck-mean optical depth is 4 to
  12, so the real plume is far from thin and its core radiance is lower than shown. No
  afterburning (the 4 % CO and 2 % H2 in the exhaust would burn with entrained air and
  heat the shear layer), no CO, OH or soot bands, and no spectral detail.
- There is no grey self-absorbing image. With the local Planck mean, a cool mixing layer
  absorbs the 2000 K core radiation as if its own 15 um CO2 band set the absorption, and
  the plume goes dark between x = 7 and 9 m. A band or weighted-sum-of-grey-gases model
  would be needed.
- The nozzle is a black (schlieren) or grey (emission) silhouette from the wall patches;
  the hot nozzle wall itself does not emit in these images.

## Limitations

- The whole flow is one frozen gas with a tuned gamma. pe, c* and Isp match the
  shifting-equilibrium 1-D solution within 0.2 %, but the bell static temperature is up
  to 9 % low and the density about 10 % high. There is no finite-rate or equilibrium
  chemistry, and the Mach number is the frozen-gamma value.
- The ambient air is the same gas (MW 23.26, gamma 1.125, 0.98 kg/m3 at 288 K; air is
  1.225 kg/m3). Entrainment density, plume mixing and afterburning of CO and H2 in air
  are not modelled. The plume temperature field is qualitative only.
- The fuel-rich film layer from the outer injector row (8 % of the flow at O/F 2.0, Tc
  2546 K) is not modelled; the whole inflow is core gas. The film-layer Isp penalty in
  the design (4.6 s) and the cooler near-wall gas are missing.
- The gas is ideal at 350 bar, with no real-gas effects. For the hot products Z is close
  to 1, so the error is small, but this case does not evaluate it.
- The chamber is treated as infinite-area: the total pressure is imposed 31 mm
  downstream of the injector face, with no combustion and no Rayleigh loss.
- The walls are adiabatic with wall functions (y+ about 50). The real wall at 880 to
  950 K gives a denser, thinner boundary layer. Wall heat flux is not computed.
- k-omega SST has no compressibility correction here. It overpredicts the spreading of
  the high-convective-Mach plume shear layer, so the supersonic core length is likely
  short.
- The case is axisymmetric and steady (LTS): no side loads, no asymmetric or unsteady
  separation, and no start-up transient. The far plume (beyond x = 5.1 m in I2-C and
  4.75 m in I1) did not settle in 20,000 LTS iterations; a time average there needs a
  time-accurate restart.
- The viscosity fit error is up to 5.6 %, and the Prandtl number is 0.73 against 0.64.

## Next steps

1. A mesh study with `--res 0.7 / 1.0 / 1.5` for mdot, Isp and pe. Check the y+
   distribution against the table above.
2. Multi-species reacting nozzle. As a middle step, fit a JANAF polynomial to the
   Cantera shifting-equilibrium enthalpy h_eq(T) along the nozzle isentrope. This
   single gas has a temperature-dependent effective cp, which fixes most of the 9 %
   static-temperature error at no extra cost. Then build frozen and equilibrium
   property tables (T, cp, gamma, MW, mu against h and p) from Cantera. After that,
   move to a multi-species case (`rhoReactingFoam` with LTS, reduced CH4/O2 mechanism)
   with air as a second stream in the plume, the fuel-rich film row as a separate inlet
   ring at O/F 2.0, and afterburning.
3. Conjugate heat transfer with the regen jacket. First a loose coupling:
   `--wall-thermal profile` imposes Twg(x) from `ffsc.cooling`; the CFD returns q(x)
   through `wallHeatFlux`; feed that back into the cooling model and repeat. Then a
   resolved 3-D periodic sector with liner, ribs and channels (`chtMultiRegionFoam`).
4. 40 % throttle separation case: `make_case.py --pc-frac 0.4 --mesh`. This gives an
   inlet at 140 bar and 3658 K, with gamma refitted to 1.1189 at that pressure (1-D pe
   0.490 bar, Isp_sl 318.6 s). Run LTS first, then restart time-accurate to
   look for free-shock or restricted-shock separation, which a Rao bell can show.
   Compare the separation point with the Schmucker and Summerfield criteria in
   `ffsc.nozzle.separation_check`, with finer wall and lip cells.
