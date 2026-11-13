#!/usr/bin/env python3
"""Tests for tools/spice_export.py. No pytest, no network, and no simulator.

Run: python3 tests/test_spice_export.py
"""
import copy
import json
import math
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import adom_import as ai  # noqa: E402
import spice_export as sx  # noqa: E402

EX = ROOT / "cards" / "examples"
FIX = ROOT / "tests" / "fixtures" / "adom"
N_STAT = 20000
NAME = re.compile(r"^p_[a-z][a-z0-9_]*$")
NUMBER = re.compile(r"^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$")
FORBIDDEN = re.compile(r"\b(agauss|gauss|unif|mc|flat)\b")
failures = 0


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    failures += not cond


def dist(scope, kind, applies, params, truncate=None):
    block = {
        "scope": scope,
        "type": kind,
        "applies_to": applies,
        "kind": "population",
        "params": params,
        "basis": "test",
        "confidence": "low",
    }
    if truncate is not None:
        block["truncate"] = truncate
    return block


def card(cid, parameters, correlation=None):
    raw = {"id": cid, "parameters": parameters}
    if correlation is not None:
        raw["correlation"] = correlation
    return raw


def param(name, nominal, unit, distributions, limits=None, final_limits=None):
    raw = {"name": name, "nominal": nominal, "unit": unit, "distributions": distributions}
    if limits is not None:
        raw["limits"] = limits
    if final_limits is not None:
        raw["final_limits"] = final_limits
    return raw


def mean_std(values):
    n = len(values)
    mid = sum(values) / n
    var = sum((v - mid) ** 2 for v in values) / (n - 1)
    return mid, math.sqrt(var)


def within_sampling_noise(name, values, expect_mean, expect_std):
    got_mean, got_std = mean_std(values)
    mean_tol = 8 * expect_std / math.sqrt(len(values))
    std_tol = 8 * expect_std / math.sqrt(2 * len(values))
    ok = abs(got_mean - expect_mean) <= mean_tol and abs(got_std - expect_std) <= std_tol
    if not ok:
        print(f"  {name}: mean {got_mean} (expected {expect_mean} ± {mean_tol}), stdev {got_std} (expected {expect_std} ± {std_tol})")
    check(name, ok)


def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy)


def column(runs, refdes, name):
    out = []
    for run in runs:
        for inst in run["instances"]:
            if inst["refdes"] == refdes:
                out.append(inst["values"][name])
    return out


def raises(fn, contains):
    try:
        fn()
    except sx.ExportError as exc:
        return contains in str(exc)
    except Exception as exc:
        print(f"  raised {type(exc).__name__}: {exc}")
        return False
    return False


resistor = sx.load_card(EX / "example_resistor.yaml")
capacitor = sx.load_card(EX / "example_capacitor.yaml")
mosfet = sx.load_card(EX / "example_mosfet.yaml")

check("resistor nominal, unit, limits, and lot/device scopes load",
      resistor["parameters"][0]["name"] == "resistance"
      and resistor["parameters"][0]["nominal"] == 10000
      and resistor["parameters"][0]["unit"] == "Ohm"
      and resistor["parameters"][0]["limits"]["min"] == 9900
      and resistor["parameters"][0]["limits"]["max"] == 10100
      and [item["scope"] for item in resistor["parameters"][0]["distributions"]] == ["lot", "device"]
      and resistor["parameters"][1]["distributions"][0]["type"] == "uniform")
check("capacitor triangular and mosfet lognormal load",
      capacitor["parameters"][1]["distributions"][0]["type"] == "triangular"
      and mosfet["parameters"][2]["distributions"][0]["type"] == "lognormal"
      and mosfet["correlation"]["parameters"] == ["vth", "rds_on"])
check("missing card is an error", raises(lambda: sx.load_card(EX / "missing.yaml"), "not found"))

check("param name is p_<refdes>_<param>", sx.param_name("R1", "resistance") == "p_r1_resistance")
for refdes, pname in (("R1", "resistance"), ("C10", "dc_bias_factor"), ("M2", "vth"), ("r1", "tcr")):
    got = sx.param_name(refdes, pname)
    check(
        f"{refdes} {pname} is SPICE-safe and is not the element name",
        NAME.fullmatch(got) and got != refdes and got.lower() != refdes.lower() and got != pname,
    )
many = [sx.param_name(ref, pname) for ref in ("R1", "R2", "C1", "M1") for pname in ("resistance", "tcr", "vth", "rds_on")]
check("param names are unique", len(many) == len(set(many)))

page = json.loads((FIX / "synthetic-passive.json").read_text(encoding="utf-8"))
imported = ai.build_card(page, ai.Options(date="2026-11-13"))
check("imported card is the synthetic passive", imported["id"] == "occ:resistor/example-passive-syn-r-10k@0.1.0")

normal_card = card("occ:other/spread-test@0.1.0", [
    param("spread_u", 1, "1", [dist("total", "uniform", "value", {"min": -2, "max": 4})]),
    param("spread_n", 5, "V", [dist("total", "normal", "value", {"mean": 5, "sigma": 1.5})]),
    param("spread_pct", 80, "Ohm", [dist("total", "normal", "value", {"mean": 80, "sigma_pct": 10})]),
    param("corr_a", 0, "1", [dist("total", "normal", "value", {"mean": 0, "sigma": 1})]),
    param("corr_b", 0, "1", [dist("total", "normal", "value", {"mean": 0, "sigma": 1})]),
], {"parameters": ["corr_a", "corr_b"], "matrix": [[1, 0.9], [0.9, 1]]})

random.seed(1)
stat_a = sx.sample(normal_card, N_STAT, 12345, ["r1"])
random.seed(99)
stat_b = sx.sample(normal_card, N_STAT, 12345, ["r1"])
check("the same seed ignores the global RNG and repeats", stat_a == stat_b)
text_a = "".join(sx.write_params(run) for run in stat_a).encode("utf-8")
text_b = "".join(sx.write_params(run) for run in sx.sample(normal_card, N_STAT, 12345, ["r1"])).encode("utf-8")
check("the same seed writes byte-identical include text", text_a == text_b)
other = "".join(sx.write_params(run) for run in sx.sample(normal_card, 4, 999, ["r1"])).encode("utf-8")
same_short = "".join(sx.write_params(run) for run in sx.sample(normal_card, 4, 12345, ["r1"])).encode("utf-8")
check("a different seed writes different text", other != same_short)

uniform_draws = column(stat_a, "r1", "spread_u")
check("uniform draws stay inside their bounds", all(-2 <= v <= 4 for v in uniform_draws))
within_sampling_noise("uniform mean and spread over 20000 runs", uniform_draws, 1, 6 / math.sqrt(12))
within_sampling_noise("normal mean and spread over 20000 runs", column(stat_a, "r1", "spread_n"), 5, 1.5)
within_sampling_noise("sigma_pct is a percent of the mean", column(stat_a, "r1", "spread_pct"), 80, 8)
rho = pearson(column(stat_a, "r1", "corr_a"), column(stat_a, "r1", "corr_b"))
check("correlated normals follow the card matrix", abs(rho - 0.9) < 0.05)
if abs(rho - 0.9) >= 0.05:
    print(f"  pearson {rho}")

imported_runs = sx.sample(imported, N_STAT, 7, ["r1"])
tol = column(imported_runs, "r1", "tol")
check("imported tolerance stays inside the published uniform bounds", all(-0.01 <= v <= 0.01 for v in tol))
within_sampling_noise("imported uniform tolerance mean and spread", tol, 0, 0.02 / math.sqrt(12))
check("imported tolerance is not stuck at the nominal 0", any(v != 0 for v in tol))

before = copy.deepcopy(resistor)
split = sx.sample(resistor, 30, 11, ["R1", "R2"])
check("sampling does not change the card", resistor == before)
lot_same = True
device_differs = True
formula = True
inside_limits = True
for run in split:
    a, b = run["instances"]
    if a["draws"]["resistance"]["lot"] != b["draws"]["resistance"]["lot"]:
        lot_same = False
    if a["draws"]["resistance"]["device"] == b["draws"]["resistance"]["device"]:
        device_differs = False
    for inst in (a, b):
        draw = inst["draws"]["resistance"]
        expect = 10000 * (1 + draw["lot"]) * (1 + draw["device"])
        if not math.isclose(inst["values"]["resistance"], expect, rel_tol=0, abs_tol=1e-9):
            formula = False
        if not 9900 <= inst["values"]["resistance"] <= 10100:
            inside_limits = False
        if inst["values"]["tcr"] != inst["draws"]["tcr"]["total"]:
            formula = False
        if not -100 <= inst["values"]["tcr"] <= 100:
            inside_limits = False
check("lot draws are equal across instances in a run", lot_same)
check("device draws differ across instances in a run", device_differs)
check("relative lot and device combine as nominal * (1 + lot) * (1 + device)", formula)
check("combined resistor samples stay inside published limits", inside_limits)
check("total scope is drawn per instance",
      all(run["instances"][0]["draws"]["tcr"]["total"] != run["instances"][1]["draws"]["tcr"]["total"] for run in split))

additive = card("occ:other/additive@0.1.0", [
    param("v", 10, "V", [
        dist("lot", "normal", "additive_offset", {"mean": 0, "sigma": 0.2}),
        dist("device", "normal", "additive_offset", {"mean": 0, "sigma": 0.2}),
    ]),
])
add_runs = sx.sample(additive, 10, 3, ["q1", "q2"])
add_ok = True
for run in add_runs:
    a, b = run["instances"]
    if a["draws"]["v"]["lot"] != b["draws"]["v"]["lot"]:
        add_ok = False
    if a["draws"]["v"]["device"] == b["draws"]["v"]["device"]:
        add_ok = False
    for inst in (a, b):
        draw = inst["draws"]["v"]
        if not math.isclose(inst["values"]["v"], 10 + draw["lot"] + draw["device"], rel_tol=0, abs_tol=1e-9):
            add_ok = False
check("additive lot and device combine as nominal + lot + device", add_ok)

screen = card("occ:other/screen@0.1.0", [
    param("x", 0, "1", [dist("total", "normal", "value", {"mean": 0, "sigma": 1})], {"min": -0.5, "max": 0.5}),
])
screened = column(sx.sample(screen, 2000, 4, ["r1"]), "r1", "x")
on_edge = sum(1 for v in screened if v in (-0.5, 0.5))
check("published limits apply to the combined value", all(-0.5 <= v <= 0.5 for v in screened))
check("published limits are not a clamp piled on the boundary", on_edge < 0.01 * len(screened))

cap_runs = sx.sample(capacitor, N_STAT, 8, ["c1"])
bias = column(cap_runs, "c1", "dc_bias_factor")
check("triangular draws stay inside the published min and max", all(0.90 <= v <= 1.05 for v in bias))
within_sampling_noise("triangular mean matches (min + mode + max) / 3", bias, 1 + (-0.10 + 0 + 0.05) / 3, math.sqrt(0.0175 / 18))

mos = sx.sample(mosfet, 2000, 6, ["m1"])
vth = column(mos, "m1", "vth")
rds = column(mos, "m1", "rds_on")
check("truncated normal stays inside truncate", all(1.2 <= v <= 2.4 for v in vth))
check("truncated lognormal stays positive and inside truncate", all(0 < v <= 0.0065 for v in rds))

bins = card("occ:other/bins@0.1.0", [
    param("d", 0, "1", [dist("total", "empirical", "value", {"bins": [{"value": 0, "probability": 0.75}, {"value": 1, "probability": 0.25}]})]),
])
discrete = column(sx.sample(bins, N_STAT, 2, ["r1"]), "r1", "d")
check("empirical bins only return listed values", set(discrete) <= {0, 1})
within_sampling_noise("empirical bin mean matches the probabilities", discrete, 0.25, math.sqrt(0.75 * 0.25))

remote = card("occ:other/remote@0.1.0", [
    param("e", 1, "1", [dist("total", "empirical", "value", {"samples_uri": "https://example.invalid/samples.csv", "sha256": "PLACEHOLDER"})]),
])
check("empirical samples_uri is refused", raises(lambda: sx.sample(remote, 1, 1, ["r1"]), "samples_uri"))
unknown = card("occ:other/unknown@0.1.0", [
    param("e", 1, "1", [dist("total", "beta", "value", {"min": 0, "max": 1})]),
])
check("an unknown distribution type is refused", raises(lambda: sx.sample(unknown, 1, 1, ["r1"]), "beta"))

first = split[0]
text = sx.write_params(first)
lines = text.splitlines()
check("include text ends with a newline", text.endswith("\n"))
check("header names the card, the seed, and the run",
      lines[1] == f"* card id: {resistor['id']}" and lines[2] == "* seed: 11" and lines[3] == "* run: 1")
check("run numbers count from 1", [run["run"] for run in split[:3]] == [1, 2, 3] and sx.write_params(split[1]).splitlines()[3] == "* run: 2")
param_lines = [line for line in lines if line.startswith(".param ")]
check("param lines follow instance order, then card order",
      [line.split("=", 1)[0] for line in param_lines] == [
          ".param p_r1_resistance",
          ".param p_r1_tcr",
          ".param p_r2_resistance",
          ".param p_r2_tcr",
      ])
parsed = {}
numbers_ok = True
for line in param_lines:
    lhs, rhs = line[len(".param "):].split("=", 1)
    if not NUMBER.fullmatch(rhs):
        numbers_ok = False
    parsed[lhs] = float(rhs)
check("param values are plain base-unit numbers", numbers_ok and FORBIDDEN.search(text) is None)
check("written numbers match the sampled values",
      math.isclose(parsed["p_r1_resistance"], first["instances"][0]["values"]["resistance"], rel_tol=0, abs_tol=1e-9)
      and math.isclose(parsed["p_r1_tcr"], first["instances"][0]["values"]["tcr"], rel_tol=0, abs_tol=1e-9)
      and math.isclose(parsed["p_r2_resistance"], first["instances"][1]["values"]["resistance"], rel_tol=0, abs_tol=1e-9))
check("the include file does not use a SPICE scale suffix",
      not any(token[-1] in "kKmMuUnNpP" and token[-1].isalpha() for line in param_lines for token in [line.split("=", 1)[1]]))

print(f"\n{'all tests passed' if not failures else f'{failures} test(s) failed'}")
sys.exit(1 if failures else 0)
