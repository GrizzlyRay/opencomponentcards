#!/usr/bin/env python3
"""Verify a card's Sigstore bundle against trust/signers.yaml.

Usage: tools/verify_signer.py [--policy trust/signers.yaml] [--min-level registry|community|verified] CARD...
       tools/verify_signer.py --check-policy [--policy trust/signers.yaml]

A card passes when cosign verifies its <card>.sigstore.json bundle against a
signer whose identity matches and whose scope covers the card, at or above
--min-level. Needs cosign on PATH (not needed for --check-policy).
"""
import argparse
import fnmatch
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


def in_scope(signer, card_rel, card_data):
    scope = signer["scope"]
    if "paths" in scope and not any(
        fnmatch.fnmatchcase(card_rel, g) or (g.endswith("/**") and card_rel.startswith(g[:-2]))
        for g in scope["paths"]
    ):
        return False
    if "manufacturers" in scope:
        mfr = ((card_data or {}).get("part") or {}).get("manufacturer") or (card_data or {}).get("manufacturer")
        if mfr not in scope["manufacturers"]:
            return False
    return True


def cosign_ok(card, bundle, signer):
    r = subprocess.run(
        ["cosign", "verify-blob", str(card), "--bundle", str(bundle),
         "--certificate-identity-regexp", signer["identity"]["san_regex"],
         "--certificate-oidc-issuer", signer["identity"]["issuer"]],
        capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def verify(card, policy, min_level):
    bundle = Path(f"{card}.sigstore.json")
    if not bundle.exists():
        return False, f"no bundle at {bundle}"
    card_rel = rel(card)
    try:
        data = yaml.safe_load(Path(card).read_text())
    except Exception:
        data = None
    floor = LEVELS.index(min_level)
    candidates = [s for s in policy["signers"]
                  if LEVELS.index(s["kind"]) >= floor and in_scope(s, card_rel, data)]
    if not candidates:
        return False, f"no trusted signer at level {min_level} or above has {card_rel} in scope"
    last = ""
    for s in sorted(candidates, key=lambda s: -LEVELS.index(s["kind"])):
        ok, msg = cosign_ok(card, bundle, s)
        if ok:
            return True, f"signed by {s['name']} (id {s['id']}), level {s['kind']}"
        last = msg
    return False, f"signature doesn't match any trusted signer in scope ({last.splitlines()[-1] if last else 'cosign failed'})"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cards", nargs="*")
    ap.add_argument("--policy", default=str(ROOT / "trust/signers.yaml"))
    ap.add_argument("--schema", default=str(ROOT / "schema/signers.schema.json"))
    ap.add_argument("--min-level", choices=LEVELS, default="registry")
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
    if not shutil.which("cosign"):
        print("cosign not found; install it from https://docs.sigstore.dev/cosign/system_config/installation/")
        return 2
    failed = 0
    for card in a.cards:
        ok, msg = verify(card, policy, a.min_level)
        print(f"{'OK  ' if ok else 'FAIL'} {card}: {msg}")
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
