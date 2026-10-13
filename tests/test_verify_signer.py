#!/usr/bin/env python3
"""Tests for tools/verify_signer.py. Needs cosign. Run: python3 tests/test_verify_signer.py

A second signer is simulated with a test policy entry ("second-signer") that
trusts the same workflow identity, so its copy of the registry bundle is a real,
valid cosign signature without needing another OIDC login.
"""
import copy
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import verify_signer as vs  # noqa: E402

CARD = "cards/real/royalohm-0603waf470kt5e.yaml"
REG = "grizzlyray-sign-workflow.sigstore.json"
failures = 0


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    failures += not cond


def with_card(fn, extra=None, tamper=False):
    """Copy the card and its .sigs into a temp folder inside cards/ so paths stay in scope."""
    tmp = Path(tempfile.mkdtemp(dir=ROOT / "cards/real", prefix="tmp-test-"))
    try:
        card = tmp / Path(CARD).name
        shutil.copy(ROOT / CARD, card)
        shutil.copytree(ROOT / f"{CARD}.sigs", f"{card}.sigs")
        for n in extra or []:
            shutil.copy(ROOT / f"{CARD}.sigs/{REG}", f"{card}.sigs/{n}.sigstore.json")
        if tamper:
            with open(card, "a") as f:
                f.write("# edited after signing\n")
        return fn(str(card))
    finally:
        shutil.rmtree(tmp)


base, problems = vs.load_policy(ROOT / "trust/signers.yaml", ROOT / "schema/signers.schema.json")
check("repo policy is valid", not problems)

two = copy.deepcopy(base)
second = copy.deepcopy(base["signers"][0])
second.update(id="second-signer", name="Test second signer", kind="community")
two["signers"].append(second)
two["policies"] = [{"id": "two-sigs", "paths": ["cards/real/**"], "require": {"min_signers": 2}}]

ok, out = vs.verify(str(ROOT / CARD), base, "registry")
check("migrated card passes with one registry signature", ok)

ok, out = vs.verify(str(ROOT / CARD), two, "registry")
check("policy needing 2 signers fails with only 1", not ok and "two-sigs" in out[0])

ok, out = with_card(lambda c: vs.verify(c, two, "registry"), extra=["second-signer"])
check("policy needing 2 signers passes with 2 valid signatures", ok and out[0].startswith("highest valid level community"))

ok, out = with_card(lambda c: vs.verify(c, two, "community"), extra=["second-signer"])
check("--min-level community passes via the second signer", ok)

kinds = copy.deepcopy(two)
kinds["policies"][0]["require"]["kinds"] = ["verified"]
kinds["policies"][0]["require"]["min_signers"] = 1
ok, out = with_card(lambda c: vs.verify(c, kinds, "registry"), extra=["second-signer"])
check("policy needing a verified signer fails without one", not ok)

ok, out = with_card(lambda c: vs.verify(c, base, "registry"), extra=["nobody"])
check("unknown signer bundle is reported but card still passes", ok and any("unknown signer" in l for l in out))
ok, out = with_card(lambda c: vs.verify(c, base, "registry", strict=True), extra=["nobody"])
check("unknown signer bundle fails the card with --strict", not ok)

ok, out = with_card(lambda c: vs.verify(c, two, "registry"), extra=["second-signer"], tamper=True)
check("tampered card fails and every bundle is flagged stale", not ok and sum("doesn't verify" in l for l in out) == 2)

scoped = copy.deepcopy(two)
scoped["signers"][1]["scope"] = {"manufacturers": ["Samsung Electro-Mechanics"]}
ok, out = with_card(lambda c: vs.verify(c, scoped, "registry"), extra=["second-signer"])
check("out-of-scope signer is flagged and doesn't count", not ok and any("outside" in l for l in out))

ok, out = vs.verify(str(ROOT / "cards/real/does-not-exist.yaml"), base, "registry")
check("card with no .sigs folder fails", not ok)

print(f"\n{'all tests passed' if not failures else f'{failures} test(s) failed'}")
sys.exit(1 if failures else 0)
