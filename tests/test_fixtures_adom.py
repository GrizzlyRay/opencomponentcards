#!/usr/bin/env python3
"""Checks tests/fixtures/adom/*.json. No pytest and no network.

Run: python3 tests/test_fixtures_adom.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "adom"
NOTE = "synthetic test fixture, invented values, not from wiki.adom.inc"
EXPECTED = {
    "synthetic-mosfet.json",
    "synthetic-passive.json",
    "synthetic-no-manufacturer.json",
    "synthetic-no-rows.json",
    "synthetic-no-license.json",
}
failures = 0


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    failures += not cond


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def page_rows(page):
    meta = page.get("metadata")
    if not isinstance(meta, dict) or "characteristics" not in meta:
        return []
    chars = meta.get("characteristics")
    if not isinstance(chars, dict):
        return []
    got = chars.get("rows")
    return got if isinstance(got, list) else []


def differs_only_in_conditions(a, b):
    if a.get("conditions") == b.get("conditions"):
        return False
    keys = (set(a) | set(b)) - {"conditions"}
    return all(a.get(key) == b.get(key) for key in keys)


pages = {}
found = sorted(p.name for p in FIX.glob("*.json")) if FIX.is_dir() else []
check("fixture directory has the five synthetic pages", found == sorted(EXPECTED))

for name in sorted(EXPECTED):
    path = FIX / name
    check(f"{name} exists", path.is_file())
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8")
    # The required _note names the wiki only to say the file is not from there.
    outside_note = text.replace(NOTE, "")
    check(f"{name} does not cite wiki.adom.inc outside the marker", "wiki.adom.inc" not in outside_note)
    try:
        page = json.loads(text)
    except json.JSONDecodeError:
        check(f"{name} parses as JSON", False)
        continue
    check(f"{name} parses as JSON", isinstance(page, dict))
    if not isinstance(page, dict):
        continue
    pages[name] = page
    check(f"{name} has the synthetic _note", page.get("_note") == NOTE)
    check(f"{name} owner starts with synthetic-", str(page.get("owner", "")).startswith("synthetic-"))
    check(f"{name} slug starts with synthetic-", str(page.get("slug", "")).startswith("synthetic-"))


mosfet = pages.get("synthetic-mosfet.json")
if mosfet is None:
    check("synthetic-mosfet.json edge cases", False)
else:
    rows = page_rows(mosfet)
    component = mosfet.get("component") or {}
    check("mosfet manufacturer is Example Semi", component.get("manufacturer") == "Example Semi")
    check("mosfet category is Transistor", component.get("category") == "Transistor")
    check("mosfet license is CC-BY-SA-4.0", mosfet.get("license") == "CC-BY-SA-4.0")

    groups = {}
    for row in rows:
        groups.setdefault((row.get("name"), row.get("symbol"), row.get("kind")), []).append(row)
    paired = any(
        differs_only_in_conditions(group[i], group[j])
        for group in groups.values()
        for i in range(len(group))
        for j in range(i + 1, len(group))
    )
    check("mosfet has two rows sharing name, symbol, and kind that differ only in conditions", paired)

    idss_units = {row.get("unit") for row in rows if row.get("symbol") == "IDSS"}
    check("IDSS is stored in µA (U+00B5) and in nA", {"\u00b5A", "nA"} <= idss_units)

    units = [row.get("unit") or "" for row in rows]
    check("a unit uses micro sign U+00B5", any("\u00b5" in unit and "\u03bc" not in unit for unit in units))
    check("a unit uses Greek mu U+03BC", any("\u03bc" in unit and "\u00b5" not in unit for unit in units))
    check("an Ohm unit uses Greek omega U+03A9", any("\u03a9" in unit and "\u2126" not in unit for unit in units))
    check("an Ohm unit uses ohm sign U+2126", any("\u2126" in unit and "\u03a9" not in unit for unit in units))
    check("gFS is in mS", any(row.get("symbol") == "gFS" and row.get("unit") == "mS" for row in rows))
    check("RθJA is in °C/W", any(row.get("symbol") == "R\u03b8JA" and row.get("unit") == "\u00b0C/W" for row in rows))
    check("a max-only row is present", any(row.get("min") is None and row.get("typ") is None and is_num(row.get("max")) for row in rows))
    check("a typ-only row is present", any(row.get("min") is None and row.get("max") is None and is_num(row.get("typ")) for row in rows))
    kinds = {row.get("kind") for row in rows}
    check("an absolute_maximum row is present", "absolute_maximum" in kinds)
    check("a recommended_operating row is present", "recommended_operating" in kinds)
    check("a thermal row is present", "thermal" in kinds)
    check("a row has min greater than max", any(is_num(row.get("min")) and is_num(row.get("max")) and row["min"] > row["max"] for row in rows))
    check(
        "VGS(th) has min, max, and the stated conditions",
        any(
            row.get("symbol") == "VGS(th)"
            and is_num(row.get("min"))
            and is_num(row.get("max"))
            and row.get("conditions") == "VDS = VGS, ID = 250\u00b5A"
            for row in rows
        ),
    )


passive = pages.get("synthetic-passive.json")
if passive is None:
    check("synthetic-passive.json edge cases", False)
else:
    rows = page_rows(passive)
    check("passive category is Resistor", (passive.get("component") or {}).get("category") == "Resistor")
    check("passive license is present", bool(passive.get("license")))
    check(
        "tolerance row is ±1% stored as min -1 and max 1",
        any(row.get("kind") == "tolerance" and row.get("unit") == "%" and row.get("min") == -1 and row.get("max") == 1 for row in rows),
    )
    check(
        "temperature_coefficient row is ppm/℃ with min -100 and max 100",
        any(
            row.get("kind") == "temperature_coefficient"
            and row.get("unit") == "ppm/\u2103"
            and row.get("min") == -100
            and row.get("max") == 100
            for row in rows
        ),
    )
    check("a resistance row is in kΩ", any(row.get("unit") == "k\u03a9" for row in rows))
    check("a capacitance row is in nF", any(row.get("unit") == "nF" for row in rows))
    check("a voltage_coefficient row is present", any(row.get("kind") == "voltage_coefficient" for row in rows))
    check("a timing row is in ns", any(row.get("kind") == "timing" and row.get("unit") == "ns" for row in rows))


bare = pages.get("synthetic-no-manufacturer.json")
if bare is None:
    check("synthetic-no-manufacturer.json edge cases", False)
else:
    component = bare.get("component") or {}
    check("no-manufacturer page has a manufacturer key", "manufacturer" in component)
    check("no-manufacturer page has an empty manufacturer", component.get("manufacturer") == "")


empty = pages.get("synthetic-no-rows.json")
if empty is None:
    check("synthetic-no-rows.json edge cases", False)
else:
    meta = empty.get("metadata")
    check("no-rows page has no metadata.characteristics", not isinstance(meta, dict) or "characteristics" not in meta)


unlicensed = pages.get("synthetic-no-license.json")
if unlicensed is None or passive is None:
    check("synthetic-no-license.json matches passive without license", False)
else:
    expected = {key: value for key, value in passive.items() if key != "license"}
    check("no-license page has no license field", "license" not in unlicensed)
    check("no-license page matches passive with the license field removed", unlicensed == expected)


print(f"\n{'all tests passed' if not failures else f'{failures} test(s) failed'}")
sys.exit(1 if failures else 0)
