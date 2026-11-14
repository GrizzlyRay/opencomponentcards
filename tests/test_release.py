#!/usr/bin/env python3
"""v0.3 is a tools release. card_version stays 0.2. No pytest and no network.

Run: python3 tests/test_release.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
failures = 0


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    failures += not cond


readme_path = ROOT / "README.md"
readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
lines = readme.splitlines()
check(
    "README line 3 says v0.3",
    len(lines) >= 3 and lines[2] == "**v0.3, feedback wanted.**",
)

changelog = readme.split("## Changelog", 1)[1] if "## Changelog" in readme else ""
v3 = changelog.find("v0.3 (2026-11-13)")
v2 = changelog.find("**v0.2")
check(
    "changelog has v0.3 (2026-11-13) above v0.2",
    v3 != -1 and v2 != -1 and v3 < v2,
)

unreleased_heading = re.compile(r"^(#{1,6}\s+.*\bUnreleased\b|\*\*Unreleased\b)", re.M)
check("no Unreleased heading remains", unreleased_heading.search(readme) is None)


def card_version_consts(node, found):
    if isinstance(node, dict):
        version = node.get("card_version")
        if isinstance(version, dict) and "const" in version:
            found.append(version["const"])
        for value in node.values():
            card_version_consts(value, found)
    elif isinstance(node, list):
        for value in node:
            card_version_consts(value, found)


schema_path = ROOT / "schema" / "card.schema.json"
schema = json.loads(schema_path.read_text(encoding="utf-8")) if schema_path.is_file() else {}
consts = []
card_version_consts(schema, consts)
check(
    "schema card_version is 0.2",
    schema_path.is_file() and bool(consts) and all(item == "0.2" for item in consts),
)

cards = sorted((ROOT / "cards").rglob("*.yaml"))
bad_cards = []
for path in cards:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    version = data.get("card_version") if isinstance(data, dict) else None
    if version != "0.2":
        bad_cards.append(f"{path.relative_to(ROOT)}={version!r}")
check("every card uses card_version 0.2", bool(cards) and not bad_cards)
for item in bad_cards:
    print(f"  {item}")

examples = sorted((ROOT / "cards" / "examples").glob("*.yaml"))
real = sorted((ROOT / "cards" / "real").glob("*.yaml"))
cmd = [
    sys.executable,
    str(ROOT / "tools" / "validate.py"),
    "--schema",
    str(ROOT / "schema" / "card.schema.json"),
    *[str(path) for path in examples],
    *[str(path) for path in real],
]
proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
check(
    "validate.py passes on cards/examples/*.yaml and cards/real/*.yaml",
    bool(examples) and bool(real) and proc.returncode == 0,
)
if proc.returncode != 0 or not examples or not real:
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)

print(f"\n{'all tests passed' if not failures else f'{failures} test(s) failed'}")
sys.exit(1 if failures else 0)
