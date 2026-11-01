"""Cross-check ffsc.thermo.rocket (Cantera, NASA polynomials) against NASA CEA via RocketCEA.

Both use LOX at 90.17 K and CH4(L) at 111.64 K (CEA reference liquids), shifting equilibrium.
Writes results/cea_validation.json."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rocketcea.cea_obj import CEA_Obj  # noqa: E402

from ffsc import ROOT  # noqa: E402
from ffsc.thermo import rocket  # noqa: E402

PSI = 6894.757
cea = CEA_Obj(oxName="LOX", fuelName="CH4")
rows = []
for pc_bar in (250.0, 350.0):
    for mr in (3.0, 3.6, 4.0):
        for eps in (12.0, 34.0):
            pc_psi = pc_bar * 1e5 / PSI
            r = rocket(pc_bar * 1e5, mr, eps, T_ox=90.17, T_fu=111.643, p_feed=101325.0)
            isp_vac = cea.get_Isp(Pc=pc_psi, MR=mr, eps=eps)
            isp_sl = cea.estimate_Ambient_Isp(Pc=pc_psi, MR=mr, eps=eps, Pamb=14.696)[0]
            cstar = cea.get_Cstar(Pc=pc_psi, MR=mr) * 0.3048
            tc = cea.get_Tcomb(Pc=pc_psi, MR=mr) / 1.8
            row = {"pc_bar": pc_bar, "mr": mr, "eps": eps,
                   "Tc_ffsc": r.Tc, "Tc_cea": tc, "cstar_ffsc": r.cstar, "cstar_cea": cstar,
                   "isp_vac_ffsc": r.isp_vac, "isp_vac_cea": isp_vac, "isp_sl_ffsc": r.isp_sl, "isp_sl_cea": isp_sl}
            row["err_isp_vac_pct"] = 100 * (r.isp_vac / isp_vac - 1)
            row["err_cstar_pct"] = 100 * (r.cstar / cstar - 1)
            row["err_Tc_pct"] = 100 * (r.Tc / tc - 1)
            rows.append(row)
            print(f"pc {pc_bar:5.0f} O/F {mr:3.1f} eps {eps:4.0f}: Tc {r.Tc:6.0f}/{tc:6.0f} K  c* {r.cstar:6.1f}/{cstar:6.1f}  "
                  f"Isp_vac {r.isp_vac:6.1f}/{isp_vac:6.1f}  Isp_SL {r.isp_sl:6.1f}/{isp_sl:6.1f}  "
                  f"err {row['err_Tc_pct']:+.2f} {row['err_cstar_pct']:+.2f} {row['err_isp_vac_pct']:+.2f} %")
json.dump(rows, open(ROOT / "results" / "cea_validation.json", "w"), indent=1)
worst = max(abs(r[k]) for r in rows for k in ("err_isp_vac_pct", "err_cstar_pct", "err_Tc_pct"))
print(f"worst relative difference {worst:.2f} %")
