"""Material data used for first-cut sizing. Values are typical handbook/literature
numbers (see docs/05_structures.md for sources); they are not design allowables."""

import numpy as np

MATERIALS = {
    # yield strength (MPa) vs temperature (K), density kg/m3, conductivity W/mK
    "GRCop-42": {"rho": 8790.0, "k": 320.0, "E_GPa": 110.0, "alpha": 17.5e-6,
                 "Ty": [(300, 190), (500, 175), (700, 155), (900, 125), (1000, 105)]},
    "Inconel 718": {"rho": 8190.0, "k": 18.0, "E_GPa": 190.0, "alpha": 14.0e-6,
                    "Ty": [(80, 1150), (300, 1030), (600, 950), (800, 900), (900, 850), (1000, 700)]},
    "SX500": {"rho": 8100.0, "k": 12.0, "E_GPa": 200.0, "alpha": 13.5e-6,     # ox-compatible superalloy, assumed similar to Mondaloy
              "Ty": [(300, 900), (800, 780), (1000, 650)]},
    "Ti-6Al-4V": {"rho": 4430.0, "k": 7.0, "E_GPa": 114.0, "alpha": 9.0e-6,
                  "Ty": [(80, 1500), (300, 880), (500, 680)]},
    "A286": {"rho": 7940.0, "k": 13.0, "E_GPa": 201.0, "alpha": 16.5e-6,
             "Ty": [(80, 900), (300, 760), (700, 650)]},
    "304L": {"rho": 7900.0, "k": 15.0, "E_GPa": 193.0, "alpha": 17.0e-6,
             "Ty": [(80, 400), (300, 210), (700, 140)]},
}


def yield_MPa(name, T):
    tab = np.array(MATERIALS[name]["Ty"], dtype=float)
    return float(np.interp(T, tab[:, 0], tab[:, 1]))
