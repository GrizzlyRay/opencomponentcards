#!/usr/bin/env python3
"""Verify a card's Sigstore bundle against trust/signers.yaml.

Usage: tools/verify_signer.py [--policy trust/signers.yaml] [--min-level LEVEL] [--strict] CARD...
       tools/verify_signer.py --check-policy [--policy trust/signers.yaml]

Each card has a folder <card>.sigs/ with one bundle per signer, named
<signer-id>.sigstore.json. Every bundle is checked with cosign against the
identity of the signer named in its file name, and against that signer's scope.

A card passes when at least one valid, in-scope signature meets --min-level and
every matching `policies` rule in signers.yaml is satisfied. Bundles that are
invalid (stale after a card edit, wrong identity, unknown signer, out of scope)
are reported as errors; with --strict they also fail the card.
Needs cosign on PATH, or set COSIGN to another binary.
"""
import argparse
import fnmatch
import os
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
LEVELS = ["registry", "community", "verified"]


def load_policy(path, schema_path):
    policy = yaml.safe_load(Path(path).read_text())
    # YAML turns 2026-10-13 into a date; keep it a string for the schema.
    for s in policy.get("signers", []) or []:
        if "added" in s and not isinstance(s["added"], str):
            s["added"] = s["added"].isoformat()
    schema = json.loads(Path(schema_path).read_text())
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(policy), key=str)
    problems = [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors]
    for i, rule in enumerate(policy.get("policies", []) or []):
        bad = [k for k in rule.get("require", {}).get("kinds", []) if k not in LEVELS]
        if bad:
            problems.append(f"policies/{i}: unknown kinds {bad}")
    ids = [s.get("id") for s in policy.get("signers", []) or []]
    problems += [f"duplicate signer id: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for s in policy.get("signers", []) or []:
        try:
            re.compile(s["identity"]["san_regex"])
        except (re.error, KeyError, TypeError) as exc:
            problems.append(f"{s.get('id')}: bad san_regex: {exc}")
    return policy, problems


def rel(card):
    p = Path(card).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return Path(card).as_posix()


def path_match(card_rel, globs):
    return any(fnmatch.fnmatchcase(card_rel, g) or (g.endswith("/**") and card_rel.startswith(g[:-2]))
               for g in globs)


def in_scope(signer, card_rel, card_data):
    scope = signer["scope"]
    if "paths" in scope and not path_match(card_rel, scope["paths"]):
        return False
    if "manufacturers" in scope:
        mfr = ((card_data or {}).get("part") or {}).get("manufacturer") or (card_data or {}).get("manufacturer")
        if mfr not in scope["manufacturers"]:
            return False
    return True


def cosign_ok(card, bundle, signer):
    r = subprocess.run(
        [os.environ.get("COSIGN", "cosign"), "verify-blob", str(card), "--bundle", str(bundle),
         "--certificate-identity-regexp", signer["identity"]["san_regex"],
         "--certificate-oidc-issuer", signer["identity"]["issuer"]],
        capture_output=True, text=True)
    msg = (r.stderr or r.stdout).strip()
    return r.returncode == 0, (msg.splitlines()[-1] if msg else "cosign failed")


def verify(card, policy, min_level, strict=False):
    """Returns (ok, lines)."""
    sigdir = Path(f"{card}.sigs")
    bundles = sorted(sigdir.glob("*.sigstore.json")) if sigdir.is_dir() else []
    if not bundles:
        return False, [f"no signatures in {sigdir}/"]
    card_rel = rel(card)
    try:
        data = yaml.safe_load(Path(card).read_text())
    except Exception:
        data = None
    signers = {s["id"]: s for s in policy["signers"]}
    valid, errors, lines = [], 0, []
    for b in bundles:
        sid = b.name[: -len(".sigstore.json")]
        s = signers.get(sid)
        if s is None:
            errors += 1
            lines.append(f"  ERROR {b.name}: unknown signer id {sid!r} (not in trust/signers.yaml)")
            continue
        if not in_scope(s, card_rel, data):
            errors += 1
            lines.append(f"  ERROR {b.name}: {card_rel} is outside {s['name']}'s scope")
            continue
        ok, msg = cosign_ok(card, b, s)
        if ok:
            valid.append(s)
            lines.append(f"  valid {b.name}: {s['name']}, level {s['kind']}")
        else:
            errors += 1
            lines.append(f"  ERROR {b.name}: doesn't verify for {s['name']}; stale after an edit or wrong identity ({msg})")
    reasons = []
    best = max((LEVELS.index(s["kind"]) for s in valid), default=-1)
    if best < LEVELS.index(min_level):
        reasons.append(f"no valid signature at level {min_level} or above")
    for rule in policy.get("policies", []) or []:
        if not path_match(card_rel, rule["paths"]):
            continue
        req = rule["require"]
        kinds = req.get("kinds", LEVELS)
        n = len({s["id"] for s in valid if s["kind"] in kinds})
        if n < req.get("min_signers", 1):
            reasons.append(f"policy {rule['id']} needs {req.get('min_signers', 1)} valid signer(s) of kind {kinds}, found {n}")
    if strict and errors:
        reasons.append(f"{errors} invalid signature(s) and --strict is set")
    summary = f"highest valid level {LEVELS[best]}" if best >= 0 else "no valid signatures"
    if errors:
        summary += f", {errors} invalid"
    if reasons:
        summary += "; " + "; ".join(reasons)
    return not reasons, [summary] + lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cards", nargs="*")
    ap.add_argument("--policy", default=str(ROOT / "trust/signers.yaml"))
    ap.add_argument("--schema", default=str(ROOT / "schema/signers.schema.json"))
    ap.add_argument("--min-level", choices=LEVELS, default="registry")
    ap.add_argument("--strict", action="store_true", help="fail a card if any of its bundles is invalid")
    ap.add_argument("--check-policy", action="store_true", help="only validate the policy file")
    a = ap.parse_args()

    policy, problems = load_policy(a.policy, a.schema)
    if problems:
        for p in problems:
            print(f"POLICY ERROR {a.policy}: {p}")
        return 1
    if a.check_policy:
        print(f"OK {a.policy}: {len(policy['signers'])} signer(s)")
        return 0
    if not a.cards:
        ap.error("give at least one card")
    if not shutil.which(os.environ.get("COSIGN", "cosign")):
        print("cosign not found; install it from https://docs.sigstore.dev/cosign/system_config/installation/")
        return 2
    failed = 0
    for card in a.cards:
        ok, lines = verify(card, policy, a.min_level, a.strict)
        print(f"{'OK  ' if ok else 'FAIL'} {card}: {lines[0]}")
        for line in lines[1:]:
            print(line)
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
