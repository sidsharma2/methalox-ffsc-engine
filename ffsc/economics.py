"""Engine cost model.

Recurring unit cost is built bottom-up from the CAD bill of materials: every part is put in a
component group (config/components.yaml) and priced along that group's route for the chosen build
strategy (config/costs.yaml). Inputs are triangular [low, nominal, high]; a Monte Carlo draws each
input once per sample, so every part in a sample sees the same shop rate, powder price and so on.

Development cost (NRE) is estimated bottom-up (design hours, development engines, hot-fire tests,
test stand, tooling or AM capital) and top-down with TRANSCOST 8.2 and NASA SVLCM for comparison.
"""

import csv
import math
import re
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
SUPERALLOYS = ("SX500", "MAR-M-247")
OUTSOURCED_INHOUSE = ("custom_igniter", "cast_superalloy", "forged_ring", "investment_cast")   # bought even when integrated
AM_ROUTES = ("lpbf", "lpbf_liner", "ded_nozzle")


def load(name):
    return yaml.safe_load(open(ROOT / "config" / name))


def read_bom(path):
    return list(csv.DictReader(open(path)))


class Sampler:
    """Draws every triangular input once per Monte Carlo sample and caches it by key."""

    def __init__(self, n=4000, seed=7, mode="mc"):
        self.n, self.mode = n, mode
        self.rng = np.random.default_rng(seed)
        self.cache = {}

    def __call__(self, key, v):
        if key in self.cache:
            return self.cache[key]
        if isinstance(v, (list, tuple)) and len(v) == 3:
            lo, mo, hi = (float(x) for x in v)
            if self.mode == "mc" and hi > lo:
                s = self.rng.triangular(lo, mo, hi, self.n)
            else:
                s = np.full(self.n, {"mc": mo, "low": lo, "nominal": mo, "high": hi}[self.mode])
        else:
            s = np.full(self.n, float(v))
        self.cache[key] = s
        return s


class CostModel:
    def __init__(self, bom, design, scenario, sampler, extra_welds=0, routes=None):
        """scenario: conventional | inhouse_am | hybrid; routes = {group id: route} for hybrid."""
        self.C = load("costs.yaml")
        self.groups = load("components.yaml")["groups"]
        self.routes = routes or {}
        self.bom, self.D, self.sc, self.S = bom, design, scenario, sampler
        self.extra_welds = extra_welds
        self.joints = {j["name"]: j for j in design["joints"]}
        self.bolt_d = {}
        for r in bom:
            m = re.search(r"(\d+)x M(\d+)", r["note"])
            if m:
                self.bolt_d[r["part"]] = float(m.group(2))

    # ------------------------------------------------------------------ helpers
    def p(self, path):
        node = self.C
        for k in path.split("."):
            node = node[k]
        return self.S(path, node)

    def group(self, part):
        for g in self.groups:
            if re.search(g["pattern"], part):
                return g
        raise KeyError(f"no component group for BOM part {part}")

    def mat_price(self, mat):
        key = mat if mat in self.C["material_usd_kg"] else "Inconel 718"
        return self.S(f"material.{key}", self.C["material_usd_kg"][key])

    def hours(self, m_piece, cx):
        mc = self.C["machining"]
        return mc["h0"] + mc["k"] * max(m_piece, 0.01) ** 0.6 * cx

    def lpbf_factor(self, g, mat):
        key = g.get("material_factor_key") or ("superalloy" if mat in SUPERALLOYS else mat)
        f = self.C["routes"]["lpbf"]["material_factor"].get(key)
        return self.S(f"lpbf.mf.{key}", f) if f else 1.0

    def bolt_size(self, part):
        if part in self.bolt_d:
            return self.bolt_d[part]
        stem = re.sub(r"_(nuts_washers|washers)$", "", part)
        for k, d in self.bolt_d.items():
            if k.startswith(stem) and k.endswith("bolts"):
                return d
        return 10.0

    def seal_D_mm(self, part):
        key = part.lower().replace("_seal", "")
        key = re.sub(r"_(a|b)$", "", key).replace("_line", "").replace("_duct", "").replace("_joint", "")
        key = key.replace("_interface", "")
        key = re.sub(r"^jumper_\d", "coolant_jumper", key)
        j = self.joints.get(key)
        return 1000 * j["D_seal_m"] if j else 50.0

    # ------------------------------------------------------------------ one part
    def part_cost(self, r):
        g = self.group(r["part"])
        route = self.routes.get(g["id"]) or g["routes"].get(self.sc) or g["routes"]["conventional"]
        m, q, mat, name = float(r["mass_kg"]), int(r["qty"]), r["material"], r["part"]
        R = self.C["routes"]
        shop = self.p("labor_usd_h.shop")
        if route == "cots_fastener":
            d = self.bolt_size(name)
            unit = self.p("routes.cots_fastener.a286_usd_at_M5") * (d / 5.0) ** 2
            if mat == "Inconel 718":
                unit = unit * self.p("routes.cots_fastener.in718_factor")
            if name.endswith("nuts_washers"):
                return unit * R["cots_fastener"]["nut_washer_set_factor"] * q / 3.0, route
            if name.endswith("washers"):
                return unit * 0.2 * q, route
            return unit * q, route
        if route == "cots_seal":
            return self.p("routes.cots_seal.usd_at_25mm") * (self.seal_D_mm(name) / 25.0) ** 0.8 * q, route
        if route == "cots_bearing":
            return self.p("routes.cots_bearing.usd_each") * q, route
        if route == "cots_sensor":
            return (self.p("routes.cots_sensor.PT_usd") if name.startswith("PT") else self.p("routes.cots_sensor.ST_usd")) * q, route
        if route == "custom_valve":
            return self.p("routes.custom_valve.usd_at_35kg") * (m / 35.0) ** 0.7 * q, route
        if route == "custom_igniter":
            return self.p("routes.custom_igniter.usd_each") * q, route
        if route == "turned_brazed_posts":
            return (self.p("routes.turned_brazed_posts.turn_usd_each") + self.p("routes.turned_brazed_posts.braze_usd_each")) * q, route
        if route == "lpbf":
            f = self.lpbf_factor(g, mat)
            big = R["lpbf"]["large_part_factor"] if m > R["lpbf"]["large_part_kg"] else 1.0
            return m * self.p("routes.lpbf.usd_kg") * f * big + (2 + R["lpbf"]["finish_h_k"] * m ** 0.6) * shop, route
        if route == "lpbf_liner":
            cf = g["closeout_fraction"]
            f = self.lpbf_factor(g, mat)
            return (m * (1 - cf) * self.p("routes.lpbf.usd_kg") * f * R["lpbf"]["large_part_factor"]
                    + m * cf * self.p("routes.lpbf_liner.closeout_usd_kg") + (2 + m ** 0.6) * shop), route
        if route == "ded_nozzle":
            return m * self.p("routes.ded_nozzle.usd_kg") + self.hours(m, R["ded_nozzle"]["finish_cx"]) * shop, route
        if route == "milled_channel_liner":
            cf = g["closeout_fraction"]
            ml = m * (1 - cf)
            return (ml * self.C["buy_to_fly"] * self.mat_price("GRCop-42") + self.hours(ml, R[route]["cx"]) * shop
                    + m * cf * self.p("routes.milled_channel_liner.electroform_usd_kg")), route
        if route == "milled_channel_nozzle":
            cf = g["closeout_fraction"]
            return (m * self.C["buy_to_fly"] * self.mat_price("Inconel 718") + self.hours(m, R[route]["cx"]) * shop
                    + m * cf * self.p("routes.milled_channel_nozzle.braze_usd_kg")), route
        if route == "machined_forging":
            return m * self.C["buy_to_fly"] * self.mat_price(mat) + self.hours(m / q, g.get("cx", 3)) * shop * q, route
        if route == "forged_ring":
            return m * R["forged_ring"]["btf"] * self.mat_price(mat) + self.hours(m / q, g.get("cx", 2)) * shop * q, route
        if route == "investment_cast":
            return m * self.p("routes.investment_cast.usd_kg") + self.hours(m, R[route]["finish_cx"]) * shop, route
        if route == "cast_superalloy":
            return m * self.p("routes.cast_superalloy.usd_kg") + self.hours(m, R[route]["finish_cx"]) * shop, route
        if route == "fabricated":
            fab = R["fabricated"]
            return (m * fab["btf"] * self.p("routes.fabricated.tube_usd_kg")
                    + (10 + fab["cx_hours_k"] * (m / q) ** 0.6 * g.get("cx", 2)) * shop * q), route
        raise KeyError(route)

    def category(self, route):
        if route.startswith("cots"):
            return "COTS"
        if self.sc == "conventional" or route in OUTSOURCED_INHOUSE:
            return "buy-to-print"
        if self.sc == "hybrid" and route not in AM_ROUTES + ("custom_valve",):
            return "buy-to-print"
        return "in-house"

    # ------------------------------------------------------------------ whole engine
    def unit_cost(self):
        A = self.C["assembly"]
        margin = self.p("supplier_margin.buy_to_print")
        cats = {"COTS": 0.0, "buy-to-print": 0.0, "in-house": 0.0}
        groups, rows = {}, []
        n_parts = n_joints = 0
        for r in self.bom:
            c, route = self.part_cost(r)
            cat = self.category(route)
            if cat == "buy-to-print":
                c = c * margin
            if cat != "COTS":
                c = c * (1 + A["qa_fraction"])
            cats[cat] = cats[cat] + c
            g = self.group(r["part"])["id"]
            groups[g] = groups.get(g, 0.0) + c
            rows.append({"part": r["part"], "group": g, "route": route, "category": cat, "qty": int(r["qty"]),
                         "mass_kg": float(r["mass_kg"]), "cost": c})
            if g not in ("fasteners", "seals"):
                n_parts += 1
            if r["part"].endswith("_seal"):
                n_joints += 1
        n_joints += 2 + sum(1 for r in self.bom if re.search(r"_bolts_", r["part"]))   # injector + nozzle joints, casing screw sets
        welds = (A["welds_conventional"] if self.sc == "conventional" else A["welds_inhouse_am"]) + self.extra_welds
        hrs = (A["h_per_part"] * n_parts + A["h_per_bolted_joint"] * n_joints + A["h_per_weld"] * welds
               + A["h_engine_integration"])
        assy = hrs * self.p("labor_usd_h.technician") + self.p("assembly.acceptance_test_usd")
        return {"total": sum(cats.values()) + assy, "categories": cats, "assembly_test": assy, "groups": groups,
                "rows": rows, "assembly_hours": hrs, "n_parts": n_parts, "n_bolted_joints": n_joints}

    def learning(self, uc, n_units):
        L = self.C["learning_rate"]
        parts = {"make": uc["categories"]["buy-to-print"] + uc["categories"]["in-house"],
                 "cots": uc["categories"]["COTS"], "assembly": uc["assembly_test"]}
        b = {k: math.log2(L[k]) for k in parts}
        out = {}
        for N in n_units:
            n = np.arange(1, N + 1)
            unit_N = sum(parts[k] * N ** b[k] for k in parts)
            avg = sum(parts[k] * np.mean(n ** b[k]) for k in parts)
            out[N] = {"unit": unit_N, "average": avg}
        return out

    def nre(self, uc):
        N = self.C["nre"]
        eng = self.p("labor_usd_h.engineering")
        design = sum(N["design_hours"].values()) * eng
        n_dev = self.p("nre.dev_engines")
        lr = self.learning(uc, [int(np.median(n_dev))])[int(np.median(n_dev))]["average"]
        hardware = n_dev * lr
        tests = self.p("nre.hot_fire_tests") * self.p("nre.test_cost_usd")
        stand = self.p("nre.test_stand_usd")
        if self.sc == "inhouse_am":
            special = self.p("nre.inhouse_am_capex_usd") + N["inhouse_am_process_hours"] * eng
        elif self.sc == "hybrid":
            special = self.p("nre.inhouse_am_capex_usd") + N["inhouse_am_process_hours"] * eng                 + 0.5 * self.p("nre.conventional_tooling_usd")
        else:
            special = self.p("nre.conventional_tooling_usd")
        total = design + hardware + tests + stand + special
        return {"total": total, "design": design, "dev_hardware": hardware, "hot_fire_tests": tests, "test_stand": stand,
                "tooling_or_am_capex": special}


def top_down(mass_kg, sampler):
    C = load("costs.yaml")
    T, V = C["transcost"], C["svlcm"]
    wyr = T["wyr_usd"]
    f3 = sampler("transcost.f3", T["f3"])
    dev = T["dev_a"] * mass_kg ** T["dev_b"] * T["f1"] * T["f2"] * f3 * wyr
    return {"transcost_dev": dev, "transcost_t1_A": T["prod_a"] * mass_kg ** T["prod_b"] * wyr,
            "transcost_t1_B": 1.9 * mass_kg ** 0.535 * wyr, "svlcm_nre": V["nre_a"] * mass_kg ** V["nre_b"] * 1e6,
            "svlcm_t1": V["t1_a"] * mass_kg ** V["t1_b"] * 1e6}


def pct(x, q=(10, 50, 90)):
    x = np.atleast_1d(x)
    return {f"P{k}": float(np.percentile(x, k)) for k in q}
