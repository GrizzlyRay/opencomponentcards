#!/usr/bin/env python3
"""Resolve OpenComponentCards family cards (v0.2 in progress) (Apache-2.0).

A family card holds what a whole series shares, plus value-dependent rules.
A part card can point at a family with `family: {id, sha256, select}`.
Resolving merges them: family base -> matching rules -> the part's own fields.
See docs/family-cards.md.

Usage:
  python3 resolve.py PART.yaml                      print the resolved part card
  python3 resolve.py --family FAMILY.yaml --select resistance=1000
                                                    print what the family says at that point
Add --validate to run the validator on the result.
"""
import argparse, copy, hashlib, math, os, sys
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
INHERITED = ("model_files", "derivation", "validation", "provenance", "license")

class ResolveError(Exception):
    pass

def is_family(c):
    return isinstance(c, dict) and c.get("card_type") == "family"

def file_sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def find_family(fid, root=REPO):
    """Return (path, card) for the family card with this id, searched under cards/."""
    hits = []
    for d, _, fs in os.walk(os.path.join(root, "cards")):
        for f in sorted(fs):
            if not f.endswith(".yaml"): continue
            p = os.path.join(d, f)
            try: c = yaml.safe_load(open(p))
            except yaml.YAMLError: continue
            if is_family(c) and c.get("id") == fid: hits.append((p, c))
    if not hits: raise ResolveError(f"family {fid!r} not found under cards/")
    if len(hits) > 1: raise ResolveError(f"family {fid!r} is defined in more than one file: {[h[0] for h in hits]}")
    return hits[0]

# --- rule matching -----------------------------------------------------------

def matches(cond, v):
    if "in" in cond: return isinstance(v, str) and v in cond["in"]
    if not isinstance(v, (int, float)) or isinstance(v, bool): return False
    return (v >= cond.get("min", -math.inf) and v <= cond.get("max", math.inf)
            and v > cond.get("gt", -math.inf) and v < cond.get("lt", math.inf))

def interval(cond):
    """(lo, lo_closed, hi, hi_closed) for a numeric condition."""
    lo, lc, hi, hc = -math.inf, False, math.inf, False
    if "min" in cond: lo, lc = cond["min"], True
    if "gt" in cond and cond["gt"] >= lo: lo, lc = cond["gt"], False
    if "max" in cond: hi, hc = cond["max"], True
    if "lt" in cond and cond["lt"] <= hi: hi, hc = cond["lt"], False
    return lo, lc, hi, hc

def empty(iv):
    lo, lc, hi, hc = iv
    return lo > hi or (lo == hi and not (lc and hc))

def conds_overlap(a, b):
    if a is None or b is None: return True  # an unconstrained selector matches everything
    if "in" in a or "in" in b:
        return "in" in a and "in" in b and bool(set(a["in"]) & set(b["in"]))
    (l1, c1, h1, d1), (l2, c2, h2, d2) = interval(a), interval(b)
    lo, lc = max((l1, c1), (l2, c2), key=lambda t: (t[0], not t[1]))
    hi, hc = min((h1, d1), (h2, d2), key=lambda t: (t[0], t[1]))
    return not empty((lo, lc, hi, hc))

def rules_overlap(r1, r2):
    keys = set(r1["when"]) | set(r2["when"])
    return all(conds_overlap(r1["when"].get(k), r2["when"].get(k)) for k in keys)

def check_family(fam):
    """Structural family checks. Returns (errors, warnings)."""
    E, W = [], []
    sels = {s["name"]: s for s in fam["family"]["selectors"]}
    if len(sels) != len(fam["family"]["selectors"]): E.append("family.selectors: duplicate selector name")
    pnames = [p["name"] for p in fam.get("parameters", [])]
    if len(set(pnames)) != len(pnames): E.append("duplicate parameter names")
    ids = [r["id"] for r in fam["rules"]]
    for i in sorted({x for x in ids if ids.count(x) > 1}): E.append(f"rules: duplicate rule id {i!r}")
    for r in fam["rules"]:
        rid = r["id"]
        for k, cond in r["when"].items():
            s = sels.get(k)
            if s is None: E.append(f"rules.{rid}: 'when' uses {k!r}, which isn't a declared selector"); continue
            if "in" in cond:
                if "values" not in s: E.append(f"rules.{rid}: {k!r} is numeric, so use min/max/gt/lt, not 'in'")
                else:
                    for v in cond["in"]:
                        if v not in s["values"]: E.append(f"rules.{rid}: {k} value {v!r} isn't in the selector's values {s['values']}")
            else:
                if "values" in s: E.append(f"rules.{rid}: {k!r} is categorical, so use 'in'")
                if "min" in cond and "gt" in cond or "max" in cond and "lt" in cond:
                    E.append(f"rules.{rid}: {k} uses both an inclusive and exclusive bound on one side")
                if empty(interval(cond)): E.append(f"rules.{rid}: {k} range is empty")
        for pn in r["set"]:
            if pn not in pnames: E.append(f"rules.{rid}: overrides {pn!r}, which isn't a family parameter")
    rs = fam["rules"]
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            both = sorted(set(rs[i]["set"]) & set(rs[j]["set"]))
            if both and rules_overlap(rs[i], rs[j]):
                E.append(f"rules: {rs[i]['id']!r} and {rs[j]['id']!r} overlap and both set {both}; make the ranges disjoint")
    return E, W

def apply_family(fam, select):
    """Family base parameters with the matching rules applied. Returns (params by name, applied rule ids)."""
    params = {p["name"]: copy.deepcopy(p) for p in fam.get("parameters", [])}
    applied = []
    for r in fam["rules"]:
        if all(k in select and matches(c, select[k]) for k, c in r["when"].items()):
            applied.append(r["id"])
            for pn, ov in r["set"].items():
                if pn in params: params[pn].update(copy.deepcopy(ov))
    return params, applied

def merge_sources(fs, ps, W):
    out = {s["ref"]: copy.deepcopy(s) for s in fs}
    for s in ps:
        old = out.get(s["ref"])
        if old and any(old.get(k) != s.get(k) for k in ("kind", "uri", "sha256")):
            W.append(f"sources.{s['ref']}: part source points at a different document than the family source with the same ref")
        out[s["ref"]] = copy.deepcopy(s)
    return list(out.values())

def resolve_part(part, root=REPO, family=None):
    """Merge family + part into a resolved part card. Returns (card, info, warnings)."""
    W = []
    ref = part["family"]
    if family is None:
        fpath, fam = find_family(ref["id"], root)
        if "sha256" in ref:
            got = file_sha256(fpath)
            if got != ref["sha256"]:
                raise ResolveError(f"family sha256 mismatch for {ref['id']}: card says {ref['sha256']}, {os.path.relpath(fpath, root)} is {got}")
    else:
        fpath, fam = family
    sels = [s["name"] for s in fam["family"]["selectors"]]
    select = dict(ref.get("select") or {})
    own = {p["name"]: p for p in part.get("parameters", [])}
    for s in sels:
        if s not in select and s in own and "nominal" in own[s]:
            select[s] = own[s]["nominal"]
    for k in select:
        if k not in sels: raise ResolveError(f"family.select: {k!r} isn't a selector of {ref['id']} (selectors: {sels})")
    params, applied = apply_family(fam, select)
    order = [p["name"] for p in part.get("parameters", [])]
    order += [n for n in params if n not in order]
    for p in part.get("parameters", []):
        n = p["name"]
        if n in params: params[n].update(copy.deepcopy(p))
        else: params[n] = copy.deepcopy(p)
    f = fam["family"]
    pf = {"manufacturer": f["manufacturer"], "category": f["category"]}
    for k in ("package", "description"):
        if k in f: pf[k] = f[k]
    pf.update(part.get("part") or {})
    out = {"card_version": part.get("card_version", fam["card_version"]), "id": part.get("id")}
    out["part"] = pf
    for k in ("model_files",):
        if k in part or k in fam: out[k] = copy.deepcopy(part.get(k, fam.get(k)))
    out["parameters"] = [params[n] for n in order]
    if "correlation" in part: out["correlation"] = copy.deepcopy(part["correlation"])
    for k in ("derivation", "validation"):
        if k in part or k in fam: out[k] = copy.deepcopy(part.get(k, fam.get(k)))
    out["sources"] = merge_sources(fam.get("sources", []), part.get("sources", []), W)
    for k in ("provenance", "license", "notes"):
        if k in part or k in fam: out[k] = copy.deepcopy(part.get(k, fam.get(k)))
    out["family"] = copy.deepcopy(ref)
    missing = [n for n in order if not {"nominal", "distributions", "source_refs"} <= set(params[n])]
    info = {"family_path": fpath, "select": select, "applied": applied, "incomplete": missing}
    return out, info, W

def family_point(fam, select):
    """What the family alone says at one selector point (no part card)."""
    params, applied = apply_family(fam, select)
    return {"select": select, "applied_rules": applied,
            "parameters": list(params.values()),
            "incomplete": [n for n, p in params.items() if not {"nominal", "distributions", "source_refs"} <= set(p)]}

def parse_select(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        try: out[k] = float(v)
        except ValueError: out[k] = v
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", nargs="?")
    ap.add_argument("--family"); ap.add_argument("--select", action="append")
    ap.add_argument("-o", "--output"); ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    try:
        if a.family:
            fam = yaml.safe_load(open(a.family))
            if not is_family(fam): sys.exit(f"{a.family} is not a family card")
            out = family_point(fam, parse_select(a.select))
        elif a.part:
            part = yaml.safe_load(open(a.part))
            if "family" not in part: sys.exit(f"{a.part} has no family reference; nothing to resolve")
            out, info, W = resolve_part(part)
            for w in W: print("WARN", w, file=sys.stderr)
            print(f"# resolved from {os.path.relpath(info['family_path'], REPO)} with {info['select']}; rules applied: {info['applied'] or 'none'}", file=sys.stderr)
            if info["incomplete"]: print(f"# incomplete parameters: {info['incomplete']}", file=sys.stderr)
        else:
            ap.error("give a part card or --family")
    except ResolveError as e:
        sys.exit(f"ERROR {e}")
    text = yaml.safe_dump(out, sort_keys=False, allow_unicode=True)
    if a.output: open(a.output, "w").write(text)
    else: sys.stdout.write(text)
    if a.validate and a.part:
        sys.path.insert(0, HERE); import validate
        return validate.main([a.output] if a.output else [a.part])
    return 0

if __name__ == "__main__":
    sys.exit(main())
