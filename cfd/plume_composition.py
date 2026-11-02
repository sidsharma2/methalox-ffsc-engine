"""Exit-plane gas composition for the plume emission images (cfd/render_los.py).

The CFD gas is one equivalent species, so the plume has no composition field. This script takes the composition
the 1-D model gives at the nozzle exit (shifting equilibrium from the core chamber state, expanded at constant
entropy to the design exit pressure) and writes it to results/plume_exit_composition.json. render_los.py then
holds it frozen through the plume and dilutes it with dry air by a mixture fraction; no afterburning.

    .venv/Scripts/python.exe cfd/plume_composition.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ffsc import thermo  # noqa: E402
CASES = {"mfe280_sl_axi": ROOT / "results" / "design.json",
         "mfe280_I2C_sl_axi": ROOT / "results" / "iterations" / "I2-C" / "design.json"}


def exit_composition(pc, of, pe):
    h0 = (thermo.liquid_enthalpy("Methane", 111.643, 5e5)
          + of * thermo.liquid_enthalpy("Oxygen", 90.17, 5e5)) / (1.0 + of)
    g = thermo.equilibrium_hp(h0, pc, thermo.mixture_Y(of))
    Tc, s0 = g.T, g.entropy_mass
    g.SP = s0, pe
    g.equilibrate("SP")
    return Tc, g.T, g.mean_molecular_weight, {s: float(x) for s, x in zip(g.species_names, g.X) if x > 1e-4}


out = {}
for case, path in CASES.items():
    perf = json.loads(path.read_text())["performance"]
    Tc, Te, mw, X = exit_composition(perf["pc"], perf["mr_core"], perf["pe"])
    out[case] = {"source": str(path.relative_to(ROOT)), "pc": perf["pc"], "of_core": perf["mr_core"],
                 "pe": perf["pe"], "Tc": Tc, "Te": Te, "MW": mw, "X": X}
    print(f"{case}: Tc {Tc:.1f} K, Te {Te:.1f} K, MW {mw:.3f}, " + ", ".join(f"{s} {x:.4f}" for s, x in X.items()))
(ROOT / "results" / "plume_exit_composition.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
