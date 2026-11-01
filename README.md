# MFE-280: methalox full-flow staged-combustion engine

A personal design study of a sea-level methane/oxygen engine in the 280 tf class. The requirements come from the public Raptor 3 numbers (280 tf at sea level, 350 s, about 350 bar, O/F 3.6, 1,525 kg); the layout and every sizing decision are my own. I wanted to see how close a first iteration built from open physics models gets, where it falls short, and which changes improve it without adding much complexity.

| Assembly | Half section through the chamber and turbopump axes |
|---|---|
| ![MFE-280 assembly](figures/cad_iso.png) | ![MFE-280 section](figures/cad_section.png) |

Everything is generated from one design basis (`config/baseline.yaml`):

```
config/baseline.yaml ─► ffsc/ (0-D / 1-D Python models) ─► results/design.json, cooling_profile.csv, contour.csv
                                                         ├─► cad/build_engine.py      FreeCAD assembly, STEP, BOM, clash check
                                                         ├─► picogk/RegenChamber      voxel model of the cooled chamber
                                                         ├─► drawings/src/make_pid_set.py      P&ID set (ISO 10628, ISA-5.1) -> AutoCAD DWG + PDF
                                                         ├─► drawings/src/make_mech_drawings.py engineering drawings -> AutoCAD DWG + PDF
                                                         ├─► cfd/make_case.py         OpenFOAM axisymmetric case
                                                         └─► iteration 2: config/options.yaml ─► run_options / run_pac / run_pc_ceiling
                                                                          ─► run_economics (config/costs.yaml, components.yaml) ─► run_iterations
```

## Results at a glance

| | MFE-280 baseline | Raptor 3 (public) |
|---|---|---|
| Sea-level thrust | 2.746 MN (280 tf), design input | 280 tf target (2024); 250 tf flight figure (May 2026) |
| Chamber pressure | 350 bar | ~350 bar (2023 test) |
| Mixture ratio O/F | 3.6 | ~3.6 |
| Isp, sea level / vacuum | 333.7 s / 351.8 s | 350 s quoted (see [benchmark](docs/DESIGN_REPORT.md#2-benchmark)) |
| Throat / exit diameter | 235 mm / 1,370 mm | - / ~1.3 m |
| Expansion ratio | 34 | 34.34 (Raptor 1, FAA 2019) |
| Pump discharge LOX / CH4 | 760 / 916 bar | not public |
| Modelled engine mass | 1,868 kg (CAD roll-up); 1,796 kg improved | 1,525 kg |
| Height x width | 3.36 m x 2.24 m | 3.1 m x 1.3 m |

Main findings:

- At 350 bar and O/F 3.6 even an ideal shifting-equilibrium nozzle gives at most 349 s at sea level (NASA CEA: 349.4 s; this project's solver agrees with CEA within 0.14 %). The public "350 s" therefore fits the vacuum Isp of the sea-level engine, and the model gives 351.8 s for that.
- Cooling the 120 MW/m² throat needs a fuel-rich wall layer (outer injector row at O/F 2.0). It costs 4.6 s of sea-level Isp; without it the copper liner cannot be cooled at an acceptable jacket pressure drop.
- The LOX shaft sets the chamber-pressure ceiling. With an 820 K ox-rich preburner, 400 bar does not close the power balance.
- Four low-complexity changes cut the pump discharge pressures by 50 bar (LOX) and 105 bar (CH4) at unchanged Isp: polished AM channels, a 50/50 coolant split, shrouded turbine rotors, and a close-coupled hot-gas path. The CAD mass drops by 72 kg.
- The rest of the gap to Raptor 3 is plumbing, manifolds and flanges (about 600 kg together). The cycle physics is already close to Raptor's, so the remaining mass has to come out through integration.

## Iteration 2 (in progress)

Iteration 1 is frozen as git tag `iter-1`; iteration 2 lives on branch `iter-2`. Every candidate change is in one register (`config/options.yaml`) with its physics basis, TRL and development effort, and is costed by the economics layer. Details: report sections 13 to 17, [docs/ITERATIONS.md](docs/ITERATIONS.md), [docs/COMPONENT_SELECTION.md](docs/COMPONENT_SELECTION.md).

| Candidate | Mass | T/W | First unit (hybrid build, P50) | Development (P50) |
|---|---|---|---|---|
| I1 improved | 1,796 kg | 156 | $3.37M | $0.43B |
| I2-A: weld, integrate, K1 kinetics fix (estimate) | 1,749 kg | 160 | $3.31M | $0.46B |
| I2-B: I2-A + 10 bar pump inlet (estimate) | 1,592 kg | 176 | $3.20M | $0.47B |
| I2-C: I2-B at 400 bar, built in CAD (Rev B) | 1,576 kg | 178 | $3.94M | $0.51B |

I2-C is built as full CAD (`cad/iterations/I2-C/`, 0 clashes, 131 BOM lines and 946 pieces against 178 and 1,974 for I1) with its own drawing set in `drawings/I2-C/` and an OpenFOAM run. The build corrected two estimates: the integral manifolds add 17 % at equal flow area instead of saving 45 %, and the one-piece injector removes 175 pieces but no mass.

- The largest single gain is pump inlet pressure: 10 bar instead of 6 bar lets both turbopumps run about 50 % faster, and the CAD variant is 157 kg lighter. The CH4 bearings then reach 3.1 million DN, so hydrostatic bearings come with it.
- Chamber pressure: no single enabler moves the 375 bar ceiling, because the two shafts are coupled through the cross-feeds. All four enablers together reach 400 bar (+2.6 s Isp, 22 kg more saving than the inlet change alone).
- Plasma-assisted combustion does not work at preburner pressure. Breakdown needs 450-550 kV per mm, and the shaft power it would need is far beyond any battery or reactor. The engine's own turbopumps deliver 157 kW/kg. It does work for start ignition at low pressure.
- Checking that idea properly found a real problem: at its true inlet enthalpy the fuel-rich preburner burns near 1,000 K and blows out at 3.7 ms against a 4 ms design. Option K1 (8 ms, +18 kg) fixes it. If the preburner delivers 1,000 K instead of 1,100 K, the CH4 pump needs 131 bar more.
- Economics: COTS parts are 82 of 178 BOM lines but only 3 % of the cost. The four custom main valves are a third of the first unit. AM wins for the chamber, nozzle and impellers, and casting wins for the housings. Bottom-up development is about $0.43B, against $3.2B (NASA SVLCM) and $4.4B (TRANSCOST).

Full write-up: [docs/DESIGN_REPORT.md](docs/DESIGN_REPORT.md).

## Layout

| Path | Content |
|---|---|
| `config/baseline.yaml` | design basis: every input and assumption |
| `config/options.yaml`, `iterations.yaml` | design-options register and iteration-2 candidates |
| `config/components.yaml`, `costs.yaml`, `novel.yaml` | component selection log, cost inputs (sourced or marked assumed), plasma and power-source inputs |
| `ffsc/` | models: `thermo` (Cantera equilibrium, CEA-style performance), `nozzle` (contour, separation), `cooling` (1-D regen with channel sizing), `cycle` (FFSC power balance), `turbopump`, `injector`, `structures` (bolted joints), `mass`, `design` (pipeline), `plasma` (PSR kinetics, discharge, power sources), `economics` (BOM cost model, learning, TRANSCOST/SVLCM) |
| `scripts/` | `run_design.py`, `run_trades.py`, `run_improved.py`, `make_figures.py`, `render_cad.py`, `render_sections.py`, `validate_cea.py`; iteration 2: `run_pc_ceiling.py`, `build_variant.py`, `run_pac.py`, `run_options.py`, `run_economics.py`, `run_iterations.py` |
| `results/` | `design.json`, CSV profiles, `trades.json`, `improvements.json`, `improved/`; iteration 2: `pc_ceiling.json`, `pac.json`, `options.json`, `economics.json`, `iterations.json`, `variants/` |
| `cad/` | `build_engine.py`, `cadlib.py`, `open_in_gui.py`, `export_meshes.py`; outputs in `cad/output/` (FCStd, STEP per sub-assembly, BOM, clash report) |
| `picogk/` | C# PicoGK/ShapeKernel project for the voxel regen chamber |
| `drawings/` | drawing sets as AutoCAD DWG (2018 format) and PDF. I1 (Rev A): `MFE280-DWG-SET.pdf` (8 sheets), `MFE280-PID-SET.pdf`, build-strategy addendum in `I1-addendum/`. I2-C (Rev B): `I2-C/MFE280-I2-C-DWG-SET.pdf` (11 sheets incl. MFG-009 hybrid build strategy and 3D views), `I2-C/MFE280-I2-C-PID-SET.pdf`. Sources in `drawings/src/` (template, P&ID tag database, sheet builders, `build_set.py`) |
| `figures/` | report figures (PDF + PNG) |
| `cfd/` | OpenFOAM case generator and CFD plan |
| `tests/` | pytest checks (conservation, sizing rules) |

## How to run

```bash
.venv/Scripts/python.exe scripts/run_design.py
```

```bash
.venv/Scripts/python.exe scripts/run_trades.py
```

```bash
.venv/Scripts/python.exe scripts/run_improved.py
```

```bash
.venv/Scripts/python.exe scripts/make_figures.py
```

```bash
.venv/Scripts/python.exe drawings/src/make_pid_set.py
```

Drawing sets per iteration (extraction in FreeCAD, renders, mechanical and P&ID sets through AutoCAD; I1 without `--iter`):

```bash
.venv/Scripts/python.exe drawings/src/build_set.py --iter I2-C
```

```bash
.venv/Scripts/python.exe -m pytest -q tests
```

```bash
"/c/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" cad/build_engine.py
```

```bash
"/c/Program Files/FreeCAD 1.1/bin/freecad.exe" cad/open_in_gui.py
```

Renders (tessellate in FreeCAD, draw offscreen with PyVista):

```bash
"/c/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" cad/export_meshes.py
```

```bash
.venv/Scripts/python.exe scripts/render_cad.py
```

Section views with hatched cut faces (quarter cutaway, x-z and y-z sections, both turbopumps, a horizontal cut and the injector face) go to `figures/sec_*.png`:

```bash
.venv/Scripts/python.exe scripts/render_sections.py
```

Iteration 2, in this order (each step reads the previous one's results):

```bash
.venv/Scripts/python.exe scripts/run_pc_ceiling.py
```

```bash
.venv/Scripts/python.exe scripts/build_variant.py I2_inlet10 propellants.lox.p_inlet_bar=10 propellants.lch4.p_inlet_bar=10
```

```bash
.venv/Scripts/python.exe scripts/run_options.py
```

```bash
.venv/Scripts/python.exe scripts/run_pac.py
```

```bash
.venv/Scripts/python.exe scripts/run_economics.py
```

```bash
.venv/Scripts/python.exe scripts/run_iterations.py
```

Build an iteration (design, full CAD with STEP, meshes), measure each option against the same cycle with the iteration-1 layout, and compare the CFD runs with the 1-D model:

```bash
.venv/Scripts/python.exe scripts/build_iteration.py I2-C
```

```bash
.venv/Scripts/python.exe scripts/attribute_iteration.py I2-C I2_uprate400
```

```bash
.venv/Scripts/python.exe cfd/post_compare.py
```

Report figures (pgfplots, STIX Two) are rebuilt from the results with:

```bash
.venv/Scripts/python.exe scripts/make_pgf_figures.py
```

`build_variant.py` also builds `I2_ref350` (no overrides) and `I2_uprate400` (see `config/options.yaml`, option Y2). `run_pac.py` takes about 3 min (Cantera reactor continuation). It reads the boost-pump result (N3) from `results/options.json`, and `run_options.py` copies the plasma summary (N1) from `results/pac.json`, so after changing plasma inputs run `run_options.py` once more before the economics.

The design pipeline runs in about 3 s, the trade studies in about 4 min and the CAD build in about 2 min.

Environment: Python 3.12 venv in `.venv` (numpy, scipy, matplotlib, cantera 3.2, CoolProp 8.0, pyyaml, pytest), FreeCAD 1.1, .NET 9 SDK at `D:\Research-Software\tools\dotnet9` for PicoGK 2.3.

## Status

Iteration 1 is frozen (git tag `iter-1`). Iteration 2 is in progress on branch `iter-2`: options register, economics layer and plasma study done; the first OpenFOAM run started 2026-10-31. The physics is first-order (0-D/1-D, ideal gas in the preburners, Bartz heat flux) and the CAD is a layout-level assembly. Open items are listed in [section 18 of the report](docs/DESIGN_REPORT.md#18-limitations-and-next-steps).
