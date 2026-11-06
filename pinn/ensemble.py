"""Score every saved 2-D seed against both Euler meshes, and write the fields that cfd/render_pinn.py draws.

usage: python -m pinn.ensemble [--fields results/pinn/fields_I2C_euler_r15.npz]
Runs on the CPU. Writes results/pinn/step3_axisym_scores.json and prints the seed table of pinn/README.md.
The fields come from the seed closest to the mean Cd, and carry the Mach spread over all seeds.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from . import axisym as a
from .quasi1d import Nozzle
from .score import CFD

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "pinn"
ROWS = {"euler": 90, "euler_r15": 135, "nozzle": 90}      # cells across the nozzle, in each reference mesh


def load_seeds(nz):
    out = {}
    for f in sorted((RES / "weights").glob("axisym_seed*.pt")):
        m = a.Axisym(nz, 0, nx=16, nr=8, width=64, depth=5)
        m.load_state_dict(torch.load(f, weights_only=True))
        out[int(f.stem.removeprefix("axisym_seed"))] = m
    return out


def reference(tag, nz):
    return a.load_ref(str(RES / f"reference_I2C_{tag}.npz"), nz)


def columns(ref, nr):
    """The meshes are structured: sort the cells by x, cut into columns of nr cells, sort each column by r."""
    g = np.argsort(ref["x"]).reshape(-1, nr)
    return np.take_along_axis(g, np.argsort(ref["r"][g], axis=1), axis=1)


def axis_shock(ref, nz, nr):
    """Peak, trough and 90-10 % width of the Mach drop along the row of cells next to the axis."""
    row = columns(ref, nr)[:, 0]
    x = (ref["x"][row] - nz.x_t) / nz.Rt
    M = ref["Ma"][row]
    k = int(np.argmax(M))
    after = np.where((x > x[k]) & (x < x[k] + 2.5))[0]
    j = int(after[np.argmin(M[after])])
    hi, lo = float(M[k]), float(M[j])
    w, n = x[k:j + 1], M[k:j + 1]
    return {"peak": hi, "xi_peak": float(x[k]), "trough": lo, "xi_trough": float(x[j]),
            "width": float(w[np.argmax(n < lo + 0.1 * (hi - lo))] - w[np.argmax(n < lo + 0.9 * (hi - lo))])}


def training():
    rows = {}
    for name in ("step3_axisym_seed0.json", "step3_axisym_seeds1to4.json"):
        for r in json.loads((RES / name).read_text())["runs"]:
            rows[r["seed"]] = {"seconds": r["seconds"], "steps": r["final"]["step"], "loss": r["final"]["total"]}
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fields", default=str(RES / "fields_I2C_euler_r15.npz"))
    args = ap.parse_args()
    torch.set_num_threads(2)
    nz = Nozzle()
    seeds = load_seeds(nz)
    refs = {t: reference(t, nz) for t in ("euler", "euler_r15")}
    train = training()
    out = {"seeds": list(seeds), "cfd": {t: CFD[t] for t in refs}, "training": train, "runs": {},
           "axis_shock": {t: axis_shock(r, nz, ROWS[t]) for t, r in refs.items()}}
    preds = {t: {} for t in refs}
    for s, m in seeds.items():
        row = dict(m.integrals())
        for t, ref in refs.items():
            row[t] = a.compare(m, ref)
            preds[t][s] = m.predict(ref["x"], ref["r"])
        out["runs"][s] = row

    Cd = np.array([out["runs"][s]["Cd"] for s in seeds])
    Cf = np.array([out["runs"][s]["eta_cf_vac"] for s in seeds])
    pct = lambda v, t, k: 100 * (v / CFD[t][k] - 1)
    out["mean"] = {"Cd": float(Cd.mean()), "Cd_std": float(Cd.std(ddof=1)), "eta_cf_vac": float(Cf.mean()), "eta_cf_vac_std": float(Cf.std(ddof=1)),
                   "isp_ratio": float((Cf / Cd).mean()), "isp_ratio_cfd": CFD["euler_r15"]["eta_cf_vac"] / CFD["euler_r15"]["Cd"]}
    for t, ref in refs.items():
        w = ref["vol"]
        row = {"dCd_pct": pct(Cd.mean(), t, "Cd"), "dCf_pct": pct(Cf.mean(), t, "eta_cf_vac")}
        for name, q, r in (("Ma", np.mean([p["Ma"] for p in preds[t].values()], 0), ref["Ma"]),
                           ("T", np.mean([p["T"] for p in preds[t].values()], 0), ref["T"]),
                           ("rho", np.mean([p["rho"] for p in preds[t].values()], 0), ref["rho"]),
                           ("lnp", np.mean([np.log(p["p"]) for p in preds[t].values()], 0), np.log(ref["p"]))):
            row[f"l2_{name}"] = float(np.linalg.norm(q - r) / np.linalg.norm(r))
            row[f"l2v_{name}"] = float(np.sqrt(np.sum(w * (q - r) ** 2) / np.sum(w * r ** 2)))
            if name == "Ma":
                row["max_err_Ma"] = float(np.abs(q - r).max())
        out[f"ensemble_{t}"] = row
    (RES / "step3_axisym_scores.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    t = "euler_r15"
    print("| Seed | Cd | Cd error | Cf ratio | Cf error | Mach L2 | Mach L2, by volume | Largest Mach error | Training |")
    print("|---|---|---|---|---|---|---|---|---|")
    for s, r in out["runs"].items():
        c = r[t]
        print(f"| {s} | {r['Cd']:.5f} | {pct(r['Cd'], t, 'Cd'):+.3f} % | {r['eta_cf_vac']:.5f} | {pct(r['eta_cf_vac'], t, 'eta_cf_vac'):+.3f} % | "
              f"{100 * c['l2_Ma']:.2f} % | {100 * c['l2v_Ma']:.2f} % | {c['max_err_Ma']:.2f} | {train[s]['seconds'] / 60:.0f} min |")
    e = out[f"ensemble_{t}"]
    print(f"| Mean field | {Cd.mean():.5f} | {e['dCd_pct']:+.3f} % | {Cf.mean():.5f} | {e['dCf_pct']:+.3f} % | {100 * e['l2_Ma']:.2f} % | {100 * e['l2v_Ma']:.2f} % | {e['max_err_Ma']:.2f} | |")
    print(json.dumps({"mean": out["mean"], "ensemble": e, "axis_shock": out["axis_shock"]}, indent=1))
    print("against the coarse mesh:", json.dumps(out["ensemble_euler"]))

    best = min(seeds, key=lambda s: abs(out["runs"][s]["Cd"] - Cd.mean()))
    q, ref = preds[t][best], refs[t]
    M = np.stack([p["Ma"] for p in preds[t].values()])
    gas = ref["meta"]["gas"]
    np.savez_compressed(args.fields, x=ref["x"], r=ref["r"], Ma=q["Ma"], p=q["p"] * a.P0, T=q["T"] * a.T0,
                        rho=q["rho"] * a.P0 / (gas["R"] * a.T0), Ma_std=M.std(0, ddof=1))
    print(f"fields of seed {best}, Mach spread mean {M.std(0, ddof=1).mean():.4f}, largest {M.std(0, ddof=1).max():.4f}: {args.fields}")


if __name__ == "__main__":
    main()
