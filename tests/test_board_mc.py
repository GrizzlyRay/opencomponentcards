#!/usr/bin/env python3
"""Tests for tools/board_mc.py. No pytest, no network, and no simulator.

Run: python3 tests/test_board_mc.py
"""
import contextlib
import io
import math
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import board_mc as bm  # noqa: E402
import validate as vd  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "board"
failures = 0


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    failures += not cond


def validation_report(path):
    """Run tools/validate.py. The rules stay in that module."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = vd.main(["--schema", str(ROOT / "schema" / "card.schema.json"), str(path)])
    return code, buf.getvalue()


def raises_input(path):
    try:
        bm.read_bom(path)
    except bm.InputError as exc:
        return str(exc)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


rows = bm.read_bom(FIX / "filter.csv")
by_line = {}
for row in rows:
    by_line.setdefault(row["line"], []).append(row["refdes"])
check(
    "a hyphen range expands to separate rows",
    by_line.get(6) == ["R8", "R9", "R10"] and all(row["mpn"] == "RC0603-4K7" for row in rows if row["line"] == 6),
)
check(
    "a comma cell expands to separate rows",
    by_line.get(7) == ["C3", "C4"] and all(row["value"] == "100n" for row in rows if row["line"] == 7),
)
indexed = {row["refdes"]: row for row in rows}
check("refdes stay unique and keep their spelling", list(indexed) == ["R1", "C1", "R2", "R3", "R8", "R9", "R10", "C3", "C4", "D1"])

duplicate = raises_input(FIX / "duplicate.csv")
check("a duplicate refdes names the line", "line 3" in duplicate and "line 2" in duplicate and "r1" in duplicate.lower())
if "line 3" not in duplicate:
    print(f"  {duplicate}")

bad_range = raises_input(FIX / "bad-range.csv")
check("a bad range names the line", "line 2" in bad_range and "R4-R1" in bad_range)
if "line 2" not in bad_range:
    print(f"  {bad_range}")

(ROOT / "out").mkdir(exist_ok=True)
tmpdir = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="board-mc-"))
calls = []


def importer(slug, dest):
    """Stand-in for the Adom importer. It writes a draft and does not fetch."""
    calls.append((slug, Path(dest).resolve()))
    path = Path(dest) / "adom" / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stub: true\n", encoding="utf-8")
    return path


try:
    resolved = bm.resolve(rows, FIX / "cards", tmpdir, importer)
    found = {item["refdes"]: item for item in resolved}
    local = found["R1"]
    yageo = (FIX / "cards" / "yageo-10k.yaml").resolve()
    check(
        "a local card match beats Adom and fallback",
        local["found"] == "local"
        and Path(local["path"]).resolve() == yageo
        and all(slug != "should-not-fetch" for slug, _dest in calls),
    )
    adom = found["C1"]
    check(
        "the Adom path uses the stubbed importer and does not fetch",
        adom["found"] == "adom"
        and calls == [("synthetic-cap", tmpdir.resolve())]
        and Path(adom["path"]).resolve() == (tmpdir / "adom" / "synthetic-cap.yaml").resolve()
        and Path(adom["path"]).is_file(),
    )
    fallback = found["R2"]
    fallback_path = Path(fallback["path"]) if fallback.get("path") else None
    card = yaml.safe_load(fallback_path.read_text(encoding="utf-8")) if fallback_path and fallback_path.is_file() else {}
    dist = ((card.get("parameters") or [{}])[0].get("distributions") or [{}])[0]
    nominal = (card.get("parameters") or [{}])[0].get("nominal")
    params = dist.get("params") or {}
    notes = card.get("notes")
    code, report = validation_report(fallback_path) if fallback_path and fallback_path.is_file() else (1, "no card")
    if code != 0:
        print(report)
    check(
        "a fallback card is uniform over value plus or minus tolerance",
        fallback["found"] == "fallback"
        and fallback_path is not None
        and tmpdir.resolve() in fallback_path.resolve().parents
        and "cards" in fallback_path.parts
        and dist.get("type") == "uniform"
        and dist.get("confidence") == "low"
        and isinstance(nominal, (int, float))
        and math.isclose(nominal, 10000)
        and math.isclose(params.get("min", 0), 9900)
        and math.isclose(params.get("max", 0), 10100),
    )
    check(
        "a fallback card is marked as a fallback and validates",
        notes == "fallback from BOM tolerance, not from a datasheet"
        and (card.get("validation") or {}).get("maturity") == "0.1"
        and card.get("license") == "CC-BY-4.0"
        and (card.get("provenance") or {}).get("author") == "Jacob Warren and GrizzlyRay LLC"
        and code == 0
        and "PASS" in report
        and "ERROR" not in report,
    )
    unresolved = found["R3"]
    check(
        "missing tolerance with no card is unresolved",
        unresolved["found"] == "unresolved"
        and not unresolved.get("path")
        and "tolerance" in unresolved.get("reason", "").lower()
        and not (tmpdir / "cards" / "R3.yaml").exists(),
    )
finally:
    shutil.rmtree(tmpdir)

source = (ROOT / "tools" / "board_mc.py").read_text(encoding="utf-8")
check("the resolver has no network client", "urllib" not in source and "urlopen" not in source and "wiki.adom.inc" not in source)

netlist = (FIX / "filter.cir").read_text(encoding="utf-8")
matched = bm.match_netlist(netlist, ["R1", "R2", "C1", "D1", "R3"])
missing_net = matched["netlist_not_in_bom"]
check(
    "both mismatch lists are reported",
    matched["bom_not_in_netlist"] == ["D1", "R3"] and missing_net == ["R99", "C2", "D2"],
)
check(
    "subckt-internal names are not counted as board parts",
    all(name not in missing_net for name in ("Rin", "Ccomp", "Qint", "XU1", "V1")),
)
if matched["bom_not_in_netlist"] != ["D1", "R3"] or missing_net != ["R99", "C2", "D2"]:
    print(f"  {matched}")

print(f"\n{'all tests passed' if not failures else f'{failures} test(s) failed'}")
sys.exit(1 if failures else 0)
