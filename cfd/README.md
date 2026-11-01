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
| Mesh | 178 374 cells at `--res 1` (blockMesh, 9 blocks), checkMesh OK |
| Gas | one calorically perfect gas, gamma 1.1250, cp 3216.6 J/(kg K), MW 23.257 |
| Inlet | total pressure 350 bar, total temperature 3785.1 K |
| Ambient | 101 325 Pa, 288 K, same gas |

Status: two runs in the Ubuntu-22.04 ext4 home, 8 ranks each, since 2026-10-31: `~/runs/mfe280_sl_axi` (iteration 1) and `~/runs/mfe280_I2C_sl_axi` (iteration 2, I2-C, generated with `--results results/iterations/I2-C`). Each takes about 1.2 s per iteration with both running, so about 13 h for 40,000 iterations. `post_compare.py` reads the exit-plane monitors of both and compares thrust and Isp with the 1-D model.

## Files

| Path | Content |
|---|---|
| `make_case.py` | Case generator. Reads `results/design.json` and `results/contour.csv`. |
| `cases/mfe280_sl_axi/` | Generated case (full thrust). |
| `cases/mfe280_sl_axi/case_info.json` | All chosen and derived numbers: gas study, stations, y+ estimates, BC values, 1-D references. |
| `cases/mfe280_sl_axi/Allmesh` | blockMesh, checkMesh, topoSet (exit-plane faceZone), cell centres. Does not run the solver. |
| `cases/mfe280_sl_axi/Allrun` | decomposePar, three-stage parallel run, reconstructPar. |
| `cases/mfe280_sl_axi/Allclean` | Removes mesh, results and logs. Keeps `0.orig`, `constant/*Properties` and `system/`. |

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
| `--lip-mm`, `--down-de`, `--rad-re`, `--up-re` | 20, 12, 5, 1.5 | Lip thickness and size of the external region. |

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
| Plume region | x from 2.05 m to 18.49 m (12 De), r up to 3.42 m (5 Re) |

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
| outer plume (to 5 Re) | 408 x 197 |
| outside the nozzle | 66 x 197 |
| Total | 178 374 (177 484 hex, 890 prisms on the axis) |

Axial cell size: 4 mm at the inlet, 1 mm at the throat, 10 mm at eps 15, 4 mm at the
exit, then growing to 150 mm at the outlet. The radial core size is 1.7 mm at the
throat and 8.5 mm at the exit.

checkMesh (v2306, default checks):

| Check | Result |
|---|---|
| Cells | 178 374 |
| Max non-orthogonality | 31.2 deg (average 7.3) |
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
| `ambient_inlet` (x = 1.023 m, outside the nozzle), `ambient_side` (r = 5 Re) | `waveTransmissive` 101 325 Pa | `pressureInletOutletVelocity` | `inletOutlet` 288 K | `inletOutlet` k = 0.01, omega = 154 (nu_t/nu = 5) | calculated |
| `outlet` (x = 18.49 m) | `waveTransmissive`, relaxes to 101 325 Pa over lInf = 16.4 m | `inletOutlet` | `inletOutlet` 288 K | `inletOutlet` | calculated |
| `axis` | empty (0 faces) | | | | |
| `front`, `back` | wedge | | | | |

The hot-gas walls are adiabatic. This matches the 1-D model, where the regen heat goes
back into the flow, and it keeps the first run simple. A fixed wall-temperature profile
from the regen model is available through `--wall-thermal profile`.

The ambient boundaries let the plume entrain the external gas through total-pressure
inlet/outlet conditions. The outlet is non-reflecting, so that the plume core can leave
supersonic.

## Numerics and run control

- Kurganov central-upwind fluxes, with van Leer reconstruction of rho, U and T.
  `limitedLinear 1` for k and omega. `limited corrected 0.5` on Laplacians and surface
  normal gradients.
- Local time stepping (`ddtSchemes localEuler`, supported by v2306 `rhoCentralFoam`). One
  time unit is one iteration. `rDeltaTSmoothingCoeff 0.2` limits the ratio of local time
  steps between neighbouring cells to 1.2. That is about the mesh growth rate, so the
  small wall cells do not slow down the core.
- CFL ramp in `Allrun`: maxCo 0.1 to iteration 2,000, 0.15 to 8,000, 0.3 to 16,000, then 0.5 to 40,000.
- Far field: `ambient_inlet` and `ambient_side` hold the ambient static pressure (`waveTransmissive`, 101,325 Pa) with `inletOutlet` 288 K. The first runs used `totalPressure` / `inletOutletTotalTemperature`, which set p = p0 − ρU²/2 on inflow. The plume's starting vortex drove fast entrainment through the r = 5 Re patch near x = 8.5 m, the static pressure there went towards vacuum, and the density turned negative (floating-point exception at iterations 2,116 and 2,198).
  `Allrun` edits `maxCo` and `endTime` with `foamDictionary`. This removes the comments
  from `controlDict` and expands its `$` macros; the result is the same.
- Initial field (`make_case.py --init-only`): the 1-D isentropic solution in the nozzle,
  subsonic before the throat and supersonic after it. The flow angle varies linearly
  from 0 at the axis to the wall angle. Downstream of the exit, a column of exit-state
  flow (r < Re, 4 De long) sits in still ambient gas. This avoids the starting
  transient of a 350 bar diaphragm burst.
- Transient alternative (`--time-mode transient`): the 20 um throat cells limit the
  explicit time step to about 6e-9 s. 5 ms of physical time would need about 8e5 steps,
  roughly 30 h on 8 cores. Do not use it for the first run.

Expected run time: 40 000 iterations x 178 k cells at an assumed 5 us per
cell-iteration on one core, with 8 ranks at 75 % efficiency, gives about 1.7 h. Expect 1
to 4 h. The laptop (i7-11800H) has 8 physical cores and 16 threads, so use 8 ranks.
Hyper-threads add little to a memory-bound solver. After stage 1 starts, read
`ExecutionTime` in `log.rhoCentralFoam.1` over 200 iterations and scale up. The internal
nozzle flow should settle within the first 10 000 iterations. The slow entrainment field
far from the plume takes longest. Call the run converged when the inlet and exit mass
flows agree within 0.1 % and the exit momentum flux changes by less than 0.1 % over
2000 iterations. If not, raise `endTime` and run `Allrun` again.

## Outputs

The case is a 5 deg sector. Multiply every integrated flow, force and area by
360/5 = 72. The wedge uses chords instead of arcs, so areas come out 0.03 % below a
full revolution. That error is the same for mass flow and thrust and cancels in Isp.

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
  separation, and no start-up transient.
- The viscosity fit error is up to 5.6 %, and the Prandtl number is 0.73 against 0.64.

## Next steps

1. Run this case, then a mesh study with `--res 0.7 / 1.0 / 1.5` for mdot, Isp and pe.
   Check the y+ distribution against the table above.
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
