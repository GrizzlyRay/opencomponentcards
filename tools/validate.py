#!/usr/bin/env python3
"""OpenComponentCards v0.1 validator (Apache-2.0).

Usage: python3 validate.py [--schema PATH] CARD.yaml [CARD.yaml ...]
Checks the JSON Schema plus rules a schema cannot express:
per-type distribution params, applies_to semantics, correlation matrix
(symmetric, unit diagonal, positive semidefinite), SPDX license id,
units, quoted ISO dates, references, and nominal-vs-mean consistency.
Exit code 1 on any ERROR. WARN lines do not fail the run.
"""
import argparse, datetime, json, math, os, re, sys
import yaml
from jsonschema import Draft202012Validator

HERE = os.path.dirname(os.path.abspath(__file__))
REQ = {"normal": [{"mean", "sigma"}, {"mean", "sigma_pct"}], "uniform": [{"min", "max"}],
       "lognormal": [{"mu", "sigma"}], "triangular": [{"min", "mode", "max"}],
       "empirical": [{"samples_uri", "sha256"}, {"bins"}]}
APPLIES = {"value", "additive_offset", "relative_offset"}
UNITS = {"Ohm", "F", "H", "V", "A", "W", "s", "Hz", "K", "degC", "1", "ppm/K", "V/K", "1/K"}
# Small allowlist of SPDX ids that suit card data or code. Extend as needed.
SPDX = {"CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "CDLA-Permissive-2.0", "ODC-By-1.0",
        "Apache-2.0", "MIT", "BSD-3-Clause"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def find_dates(o, path="$"):
    if isinstance(o, (datetime.date, datetime.datetime)):
        yield path
    elif isinstance(o, dict):
        for k, v in o.items(): yield from find_dates(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from find_dates(v, f"{path}[{i}]")

def centre(t, p):
    if t == "normal": return p.get("mean")
    if t == "lognormal": return math.exp(p["mu"])
    if t == "uniform": return (p["min"] + p["max"]) / 2
    if t == "triangular": return p["mode"]
    return None

def is_psd(m):
    """Cholesky with a small tolerance; returns True if positive semidefinite."""
    n = len(m); L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = m[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                if s < -1e-9: return False
                L[i][j] = math.sqrt(max(s, 0.0))
            else:
                L[i][j] = s / L[j][j] if L[j][j] > 1e-12 else 0.0
    return True

def interp(points, x=None):
    """Curve values at the given points (linear interpolation is assumed between them)."""
    return [v for _, v in sorted((p["x"], p["value"]) for p in points)]

def semantic(c):
    E, W = [], []
    params = c.get("parameters", [])
    names = [p["name"] for p in params]
    refs = {s["ref"] for s in c.get("sources", [])}
    if len(set(names)) != len(names): E.append("duplicate parameter names")
    if c.get("license") not in SPDX: E.append(f"license {c.get('license')!r} is not an allowed SPDX id")
    if not DATE_RE.match(str(c.get("provenance", {}).get("created", ""))): E.append("provenance.created must be a quoted ISO date")
    for p in params:
        n, d = p["name"], p["distribution"]; t, P = d["type"], d["params"]
        if p["unit"] not in UNITS: E.append(f"{n}: unit {p['unit']!r} not in unit list")
        ks = set(P)
        if not any(r == ks for r in REQ[t]): E.append(f"{n}: {t} params must be one of {REQ[t]}, got {sorted(ks)}")
        if d.get("applies_to") not in APPLIES: E.append(f"{n}: applies_to must be one of {sorted(APPLIES)}")
        if t == "uniform" and not P["min"] < P["max"]: E.append(f"{n}: uniform min must be < max")
        if t == "triangular" and not P["min"] <= P["mode"] <= P["max"]: E.append(f"{n}: triangular needs min <= mode <= max")
        if t in ("normal", "lognormal") and P.get("sigma", P.get("sigma_pct", 1)) <= 0: E.append(f"{n}: sigma must be > 0")
        if t == "empirical" and "bins" in P and abs(sum(b["probability"] for b in P["bins"]) - 1) > 1e-6: E.append(f"{n}: bin probabilities must sum to 1")
        tr = d.get("truncate", {})
        if "min" in tr and "max" in tr and tr["min"] >= tr["max"]: E.append(f"{n}: truncate min must be < max")
        c0 = centre(t, P)
        if c0 is not None:
            if d["applies_to"] == "value":
                if p["nominal"] and abs(c0 - p["nominal"]) / abs(p["nominal"]) > 0.02:
                    W.append(f"{n}: distribution centre {c0:g} differs from nominal {p['nominal']:g} by >2%")
                lo, hi = tr.get("min", -math.inf), tr.get("max", math.inf)
                if not lo <= p["nominal"] <= hi: E.append(f"{n}: truncate excludes nominal")
            elif abs(c0) > 0.5 * (abs(P.get("max", 0)) + abs(P.get("min", 0)) + abs(P.get("sigma", 0)) + 1e-30):
                W.append(f"{n}: offset distribution centre {c0:g} is far from 0")
        fl = p.get("final_limits")
        if fl:
            if fl["min"] >= fl["max"]: E.append(f"{n}: final_limits min must be < max")
            for dep in p.get("dependence", []):
                for v in interp(dep["points"], None):
                    val = v if fl["relative_to_nominal"] else v * p["nominal"]
                    if not fl["min"] <= val <= fl["max"]: E.append(f"{n}: curve point {v} lies outside final_limits")
        if d["applies_to"] != "value" and not p.get("dependence"):
            W.append(f"{n}: offset distribution without a dependence curve; offset is applied to nominal")
        for s in p["source_refs"]:
            if s not in refs: E.append(f"{n}: unknown source_ref {s!r}")
    corr = c.get("correlation")
    if corr:
        cp, m = corr["parameters"], corr["matrix"]; k = len(cp)
        for x in cp:
            if x not in names: E.append(f"correlation: unknown parameter {x!r}")
        if len(m) != k or any(len(r) != k for r in m): E.append(f"correlation: matrix must be {k}x{k}")
        else:
            for i in range(k):
                if abs(m[i][i] - 1) > 1e-9: E.append(f"correlation: diagonal [{i}][{i}] must be 1")
                for j in range(k):
                    if abs(m[i][j] - m[j][i]) > 1e-9: E.append(f"correlation: not symmetric at [{i}][{j}]")
            if not is_psd(m): E.append("correlation: matrix is not positive semidefinite")
    for mf in c.get("model_files", []):
        if mf["sha256"] == "PLACEHOLDER": W.append(f"placeholder sha256 for model file {mf['uri']}")
    return E, W

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default=None)
    ap.add_argument("cards", nargs="+")
    a = ap.parse_args()
    sp = a.schema or next(p for p in [os.path.join(HERE, "card.schema.json"), os.path.join(HERE, "..", "schema", "card.schema.json")] if os.path.exists(p))
    schema = json.load(open(sp))
    Draft202012Validator.check_schema(schema)
    print(f"schema {os.path.basename(sp)}: valid JSON Schema draft 2020-12")
    V = Draft202012Validator(schema)
    failed = 0
    for f in a.cards:
        raw = yaml.safe_load(open(f))
        E = [f"unquoted YAML date at {p} (quote it, e.g. \"2026-10-13\")" for p in find_dates(raw)]
        if not E:
            E += [f"schema {'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:160]}" for e in V.iter_errors(raw)]
            e2, W = semantic(raw); E += e2
        else:
            W = []
        print(f"\n{f}: {'PASS' if not E else 'FAIL'}" + (f" ({len(W)} warning(s))" if W else ""))
        for e in E: print("  ERROR", e)
        for w in W: print("  WARN ", w)
        failed += bool(E)
    print(f"\n{len(a.cards) - failed}/{len(a.cards)} cards passed")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
