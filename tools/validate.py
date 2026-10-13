#!/usr/bin/env python3
"""OpenComponentCards validator (v0.2 in progress) (Apache-2.0).

Usage: python3 validate.py [--schema PATH] CARD.yaml [CARD.yaml ...]
Checks the JSON Schema plus rules a schema cannot express:
per-type distribution params, applies_to semantics, correlation matrix
(symmetric, unit diagonal, positive semidefinite), SPDX license id,
units, quoted ISO dates, references, nominal-vs-mean consistency,
published limits (min <= typ <= max, distribution support inside them),
standard conditions keys (non-standard keys warn), and model_binding
transforms (required fields per type, unit match; free text warns),
derived source chains, and lot/device scopes in the distributions list.
Family cards (card_type: family) are checked for declared selectors, rule
overrides that target real parameters, and rules that overlap ambiguously,
and each rule is resolved and validated. Part cards with a family ref are
resolved first (the family must exist under cards/ and match its sha256),
then the resolved card is validated. See docs/family-cards.md.
v0.1 'distribution' and 'spread_components' fail with a pointer to
docs/migration-v0.1-to-v0.2.md.
Exit code 1 on any ERROR. WARN lines do not fail the run.
"""
import argparse, datetime, difflib, json, math, os, re, sys
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
REQ = {"normal": [{"mean", "sigma"}, {"mean", "sigma_pct"}], "uniform": [{"min", "max"}],
       "lognormal": [{"mu", "sigma"}], "triangular": [{"min", "mode", "max"}],
       "empirical": [{"samples_uri", "sha256"}, {"bins"}]}
APPLIES = {"value", "additive_offset", "relative_offset"}
UNITS = {"Ohm", "F", "H", "V", "A", "W", "s", "Hz", "K", "degC", "1", "ppm/K", "V/K", "1/K"}
# Small allowlist of SPDX ids that suit card data or code. Extend as needed.
SPDX = {"CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "CDLA-Permissive-2.0", "ODC-By-1.0",
        "Apache-2.0", "MIT", "BSD-3-Clause"}
# Standard condition keys (docs/conditions.md). Units are in the key name.
COND_KEYS = {"temperature_c", "temperature_min_c", "temperature_max_c", "reference_span_c",
             "frequency_hz", "ac_vrms", "dc_bias_v", "bias_v", "vgs_v", "vds_v", "vds_eq_vgs",
             "id_a", "humidity_pct", "duration_h", "preconditioning"}

def check_conditions(where, cond, W):
    """Unknown keys stay legal for backward compatibility, but get a warning and a suggestion."""
    for k in (cond or {}):
        if k in COND_KEYS: continue
        close = difflib.get_close_matches(k, sorted(COND_KEYS), n=1, cutoff=0.5)
        hint = f"; did you mean {close[0]!r}?" if close else "; see docs/conditions.md"
        W.append(f"{where}: non-standard conditions key {k!r}{hint}")

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

def support(t, p, tr):
    """Range a value distribution can produce, after truncation."""
    lo, hi = -math.inf, math.inf
    if t in ("uniform", "triangular"): lo, hi = p["min"], p["max"]
    elif t == "lognormal": lo = 0.0
    elif t == "empirical" and "bins" in p:
        vs = [b["value"] for b in p["bins"]]; lo, hi = min(vs), max(vs)
    elif t == "empirical": return None
    return max(lo, tr.get("min", -math.inf)), min(hi, tr.get("max", math.inf))

def check_limits(n, p, d, refs, E, W):
    lim = p.get("limits")
    if not lim: return
    vals = [(k, lim[k]) for k in ("min", "typ", "max") if k in lim]
    for (k1, v1), (k2, v2) in zip(vals, vals[1:]):
        if v1 > v2: E.append(f"{n}: limits need min <= typ <= max, got {k1} {v1:g} > {k2} {v2:g}")
    if "source_ref" in lim and lim["source_ref"] not in refs: E.append(f"{n}: limits.source_ref {lim['source_ref']!r} is unknown")
    if d["applies_to"] != "value": return  # offsets live in a different space than the limit
    sup = support(d["type"], d["params"], d.get("truncate", {}))
    if sup is None: return
    lo, hi = sup; eps = 1e-9 * max(abs(lim.get("min", 0)), abs(lim.get("max", 0)), 1e-30)
    if "min" in lim and lo < lim["min"] - eps:
        W.append(f"{n}: distribution can go below limits.min {lim['min']:g} (support starts at {lo:g}); add a truncate or check the modeling choice")
    if "max" in lim and hi > lim["max"] + eps:
        W.append(f"{n}: distribution can go above limits.max {lim['max']:g} (support ends at {hi:g}); add a truncate or check the modeling choice")

# Machine-readable model binding (docs/model-binding.md).
TRANSFORM_FIELDS = {"offset": (set(), {"reference", "param_unit"}),
                    "scale": (set(), {"reference", "param_unit"}),
                    "replace": (set(), {"param_unit"}),
                    "affine": ({"factor", "offset"}, {"param_unit"})}

def check_binding(n, p, E, W):
    mb = p.get("model_binding")
    if not mb: return
    tf = mb["transform"]
    if isinstance(tf, str):
        kind = tf.split(":", 1)[0].strip().lower()
        hint = f"type: {kind}" if kind in TRANSFORM_FIELDS else "type: offset | scale | replace | affine"
        W.append(f"{n}: model_binding.transform is free text; use the structured form ({{{hint}, ...}}) and move the prose to note. See docs/model-binding.md")
        return
    t = tf["type"]; need, opt = TRANSFORM_FIELDS[t]; have = set(tf) - {"type"}
    for k in sorted(need - have): E.append(f"{n}: {t} transform needs {k!r}")
    for k in sorted(have - need - opt): E.append(f"{n}: {t} transform does not use {k!r}")
    if t == "scale":
        ref = tf.get("reference", p["nominal"])
        if ref == 0: E.append(f"{n}: scale transform needs a nonzero reference (nominal is 0)")
    if t == "affine" and tf.get("factor") == 0: W.append(f"{n}: affine factor 0 ignores the sample")
    pu = tf.get("param_unit")
    if pu is None:
        if t in ("offset", "replace"): W.append(f"{n}: {t} transform has no param_unit; assuming {p['unit']!r}")
        return
    if pu not in UNITS: W.append(f"{n}: param_unit {pu!r} not in unit list, unit check skipped")
    elif t in ("offset", "replace") and pu != p["unit"]:
        E.append(f"{n}: {t} transform needs param_unit to match the card unit {p['unit']!r}, got {pu!r} (use affine to convert)")

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

PRIMARY_KINDS = {"datasheet", "measurement", "standard"}

def check_sources(srcs, E, W):
    """derived_from must name known refs, form no cycle, and reach a primary source."""
    by = {}
    for s in srcs:
        if s["ref"] in by: E.append(f"sources: duplicate ref {s['ref']!r}")
        by[s["ref"]] = s
    for s in srcs:
        r, up = s["ref"], s.get("derived_from", [])
        if up and s["kind"] != "derived": W.append(f"sources.{r}: derived_from is set but kind is {s['kind']!r}, not 'derived'")
        for u in up:
            if u not in by: E.append(f"sources.{r}: derived_from {u!r} is unknown")
            elif u == r: E.append(f"sources.{r}: derived_from points to itself")
    state = {}
    def visit(r, path):
        if state.get(r) == 1:
            E.append("sources: derived_from cycle " + " -> ".join(path[path.index(r):] + [r])); return
        if state.get(r) == 2: return
        state[r] = 1
        for u in by[r].get("derived_from", []):
            if u in by: visit(u, path + [r])
        state[r] = 2
    for r in by: visit(r, [])
    def reaches_primary(r, seen):
        if r in seen or r not in by: return False
        s = by[r]
        if s["kind"] in PRIMARY_KINDS: return True
        return any(reaches_primary(u, seen | {r}) for u in s.get("derived_from", []))
    for r, s in by.items():
        if s["kind"] == "derived" and not reaches_primary(r, set()):
            W.append(f"sources.{r}: derived source has no upstream primary source (datasheet, measurement, or standard)")

SCOPES = {"total", "lot", "device"}
MIGRATE = "see docs/migration-v0.1-to-v0.2.md"

def check_v01(c):
    """v0.1 shapes that v0.2 removed. Reported before the schema so the message is clear."""
    E = []
    for i, p in enumerate(c.get("parameters") or []):
        if not isinstance(p, dict): continue
        n = p.get("name", f"parameters[{i}]")
        if "distribution" in p: E.append(f"{n}: v0.1 'distribution' replaced by 'distributions' list; {MIGRATE}")
        if "spread_components" in p: E.append(f"{n}: 'spread_components' was removed; put lot and device entries in 'distributions'; {MIGRATE}")
        for j, d in enumerate(p.get("distributions") or []):
            if isinstance(d, dict) and "informational" in d:
                E.append(f"{n}.distributions[{j}]: 'informational' was removed; a parameter has either one total or lot/device entries, not both; {MIGRATE}")
    return E

def check_scopes(n, ds, E, W):
    """Lot vs device spread (#5): exactly one total, OR lot and/or device with no total."""
    seen = {}
    for i, x in enumerate(ds):
        sc = x["scope"]
        if sc in seen: E.append(f"{n}: duplicate scope {sc!r} in distributions[{seen[sc]}] and distributions[{i}]")
        else: seen[sc] = i
        if sc != "total" and x.get("kind") == "epistemic":
            W.append(f"{n}.distributions[{i}]: scope {sc!r} only makes sense for kind 'population' (this is epistemic)")
    split = {"lot", "device"} & set(seen)
    if "total" in seen and split:
        E.append(f"{n}: scope 'total' can't be combined with {sorted(split)}; give either one total or lot/device entries")
    if len(split) == 1:
        W.append(f"{n}: only a {next(iter(split))!r} spread is given; the other is treated as zero")
    if sum(1 for x in ds if x["scope"] in ("lot", "device") and x["applies_to"] == "value") > 1:
        E.append(f"{n}: lot and device can't both use applies_to 'value'; make at least one an offset so they stack")
    return bool(split)

def check_dist(n, p, d, E, W):
    t, P = d["type"], d["params"]
    ks = set(P)
    if not any(r == ks for r in REQ[t]): E.append(f"{n}: {t} params must be one of {REQ[t]}, got {sorted(ks)}"); return
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
            if d["scope"] == "total" and p["nominal"] and abs(c0 - p["nominal"]) / abs(p["nominal"]) > 0.02:
                W.append(f"{n}: distribution centre {c0:g} differs from nominal {p['nominal']:g} by >2%")
            lo, hi = tr.get("min", -math.inf), tr.get("max", math.inf)
            if not lo <= p["nominal"] <= hi: E.append(f"{n}: truncate excludes nominal")
        elif abs(c0) > 0.5 * (abs(P.get("max", 0)) + abs(P.get("min", 0)) + abs(P.get("sigma", 0)) + 1e-30):
            W.append(f"{n}: offset distribution centre {c0:g} is far from 0")

def semantic(c):
    E, W = [], []
    params = c.get("parameters", [])
    names = [p["name"] for p in params]
    refs = {s["ref"] for s in c.get("sources", [])}
    split_params = set()
    if len(set(names)) != len(names): E.append("duplicate parameter names")
    if c.get("license") not in SPDX: E.append(f"license {c.get('license')!r} is not an allowed SPDX id")
    if not DATE_RE.match(str(c.get("provenance", {}).get("created", ""))): E.append("provenance.created must be a quoted ISO date")
    for p in params:
        n, ds = p["name"], p["distributions"]
        if p["unit"] not in UNITS: E.append(f"{n}: unit {p['unit']!r} not in unit list")
        where = (lambda i, d: n if len(ds) == 1 else f"{n}.distributions[{i}] ({d['scope']})")
        for i, d in enumerate(ds): check_dist(where(i, d), p, d, E, W)
        split = check_scopes(n, ds, E, W)
        if split: split_params.add(n)
        check_conditions(f"{n}.conditions", p.get("conditions"), W)
        check_conditions(f"{n}.limits.conditions", (p.get("limits") or {}).get("conditions"), W)
        tot = next((d for d in ds if d["scope"] == "total"), None)
        if tot: check_limits(n, p, tot, refs, E, W)
        elif p.get("limits"): check_limits(n, p, {"applies_to": "split"}, refs, E, W)  # order and ref only
        check_binding(n, p, E, W)
        fl = p.get("final_limits")
        if fl:
            if fl["min"] >= fl["max"]: E.append(f"{n}: final_limits min must be < max")
            for dep in p.get("dependence", []):
                for v in interp(dep["points"], None):
                    val = v if fl["relative_to_nominal"] else v * p["nominal"]
                    if not fl["min"] <= val <= fl["max"]: E.append(f"{n}: curve point {v} lies outside final_limits")
        if tot and tot["applies_to"] != "value" and not p.get("dependence"):
            W.append(f"{n}: offset distribution without a dependence curve; offset is applied to nominal")
        for s in p["source_refs"]:
            if s not in refs: E.append(f"{n}: unknown source_ref {s!r}")
    check_sources(c.get("sources", []), E, W)
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
        mixed = [x for x in cp if x in split_params]
        if mixed and len(mixed) != len(cp):
            W.append(f"correlation: {mixed} have lot/device entries but {[x for x in cp if x not in split_params]} don't; the matrix is applied to the lot and device draws separately, and a total-only parameter joins the device draw")
    for mf in c.get("model_files", []):
        if mf["sha256"] == "PLACEHOLDER": W.append(f"placeholder sha256 for model file {mf['uri']}")
    return E, W

def check_family_card(raw, VF, VP, E, W):
    """Family card: schema, rule structure, then each rule resolved and validated as a part."""
    E += [f"schema {'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:160]}" for e in VF.iter_errors(raw)]
    if E: return
    e2, w2 = resolve.check_family(raw); E += e2; W += w2
    if E: return
    f = raw["family"]
    stub = {"manufacturer": f["manufacturer"], "mpn": f"{f['series']} (family)", "category": f["category"]}
    points = [("base", [])] + [(r["id"], [r]) for r in raw["rules"]]
    for name, rules in points:
        params = {p["name"]: dict(p) for p in raw.get("parameters", [])}
        for r in rules:
            for pn, ov in r["set"].items(): params[pn].update(ov)
        done = [p for p in params.values() if {"nominal", "distributions", "source_refs"} <= set(p)]
        if not done: continue
        card = {k: raw[k] for k in ("card_version", "derivation", "validation", "sources", "provenance", "license") if k in raw}
        card.update({"id": raw["id"], "part": stub, "parameters": done})
        card.setdefault("derivation", {"kind": "physics", "method": "family"}); card.setdefault("validation", {"maturity": "1.0"})
        tag = "family" if name == "base" else f"rules.{name}"
        es = [f"{tag}: schema {'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:160]}" for e in VP.iter_errors(card)]
        if not es:
            e3, w3 = semantic(card); es = [f"{tag}: {x}" for x in e3]
            W += [f"{tag}: {x}" for x in w3 if name == "base" or any(x.startswith(pn) for r in rules for pn in r["set"])]
        E += es

def check_part_with_family(raw, VP, E, W):
    """Resolve family + part, then validate the resolved card."""
    try:
        card, info, w = resolve.resolve_part(raw)
    except resolve.ResolveError as e:
        E.append(f"family: {e}"); return
    W += w
    for n in info["incomplete"]:
        E.append(f"{n}: incomplete after resolving {raw['family']['id']} at {info['select']} (rules applied: {info['applied'] or 'none'}); no rule covers this point, so the part card must give it")
    if E: return
    E += [f"resolved: schema {'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:160]}" for e in VP.iter_errors(card)]
    if not E:
        e2, w2 = semantic(card); E += e2; W += w2

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default=None)
    ap.add_argument("cards", nargs="+")
    a = ap.parse_args(argv)
    sp = a.schema or next(p for p in [os.path.join(HERE, "card.schema.json"), os.path.join(HERE, "..", "schema", "card.schema.json")] if os.path.exists(p))
    schema = json.load(open(sp))
    Draft202012Validator.check_schema(schema)
    print(f"schema {os.path.basename(sp)}: valid JSON Schema draft 2020-12")
    V = Draft202012Validator(schema)
    reg = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    VF = Draft202012Validator({"$ref": schema["$id"] + "#/$defs/family_card"}, registry=reg)
    failed = 0
    for f in a.cards:
        raw = yaml.safe_load(open(f))
        E = [f"unquoted YAML date at {p} (quote it, e.g. \"2026-10-13\")" for p in find_dates(raw)]
        if not E: E = check_v01(raw)
        W = []
        if not E and resolve.is_family(raw):
            check_family_card(raw, VF, V, E, W)
        elif not E and isinstance(raw, dict) and "family" in raw:
            check_part_with_family(raw, V, E, W)
        elif not E:
            E += [f"schema {'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:160]}" for e in V.iter_errors(raw)]
            W = []
            if not E: e2, W = semantic(raw); E += e2  # semantic rules assume a schema-valid card
        print(f"\n{f}: {'PASS' if not E else 'FAIL'}" + (f" ({len(W)} warning(s))" if W else ""))
        for e in E: print("  ERROR", e)
        for w in W: print("  WARN ", w)
        failed += bool(E)
    print(f"\n{len(a.cards) - failed}/{len(a.cards)} cards passed")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
