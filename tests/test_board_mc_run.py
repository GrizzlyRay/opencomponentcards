#!/usr/bin/env python3
"""Tests for the board Monte Carlo command line. No pytest and no network.

ngspice is used only when it is already on PATH. Otherwise that check is SKIP.

Run: python3 tests/test_board_mc_run.py
"""
import csv
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import board_mc as bm  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "board"
RC_NET = FIX / "rc-lowpass.cir"
RC_BOM = FIX / "rc-lowpass.csv"
failures = 0


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    failures += not cond


def cli(args, timeout=120):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "board_mc.py"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def remove_path(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def subckt_lines(text):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().lower().startswith(".subckt"))
    end = next(i for i, line in enumerate(lines) if line.strip().lower().startswith(".ends"))
    return lines[start:end + 1]


def write_card(folder, name, parameters):
    card = {
        "id": f"occ:other/{name}@0.1.0",
        "parameters": [
            {
                "name": param,
                "unit": "1",
                "nominal": 1.0,
                "distributions": [{"scope": "total"}],
            }
            for param in parameters
        ],
    }
    path = folder / f"{name}.yaml"
    path.write_text(yaml.safe_dump(card, sort_keys=False), encoding="utf-8")
    return path


def decks(folder):
    found = {}
    for path in sorted(folder.glob("run_*.cir")) + sorted(folder.glob("run_*.param")):
        found[path.name] = path.read_bytes()
    return found


(ROOT / "out").mkdir(exist_ok=True)
cleanup = []
filter_text = (FIX / "filter.cir").read_text(encoding="utf-8")
model_line = ".model DMOD D (Is=1e-14)"
# A plain ".end" replace also rewrites ".ends" and drops the model inside the subckt.
board_text, model_count = re.subn(r"(?m)^\.end$", model_line + "\n.end", filter_text, count=1)
if model_count != 1:
    raise SystemExit(f"model insert changed {model_count} lines")
cards = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="board-bind-cards-"))
cleanup.append(cards)
r_card = write_card(cards, "r-card", ["resistance"])
c_card = write_card(cards, "c-card", ["capacitance"])
both_card = write_card(cards, "both-card", ["resistance", "capacitance"])
none_card = write_card(cards, "none-card", ["tcr"])
resolved = [
    {"refdes": "R1", "path": r_card, "found": "local", "reason": "test resistance"},
    {"refdes": "R2", "path": r_card, "found": "local", "reason": "test resistance"},
    {"refdes": "C1", "path": c_card, "found": "local", "reason": "test capacitance"},
    {"refdes": "R99", "path": both_card, "found": "local", "reason": "two primaries"},
    {"refdes": "C2", "path": none_card, "found": "local", "reason": "no primary"},
]
try:
    bound_board = bm.bind_netlist(board_text, resolved)
except Exception as exc:
    bound_board = exc

if isinstance(bound_board, dict):
    rewritten = bound_board["netlist"]
    by_ref = {item["refdes"].casefold(): item for item in bound_board["bound"]}
    left = {item["refdes"].casefold(): item for item in bound_board["left_alone"]}
    lines = {line.split()[0]: line for line in rewritten.splitlines() if line.split()}
    only_rc = set(by_ref) == {"r1", "r2", "c1"}
    values_ok = (
        lines.get("r1") == "r1 /in /mid {p_r1_resistance}"
        and lines.get("R2") == "R2 /mid /fb {p_r2_resistance}"
        and lines.get("C1") == "C1 /mid 0 {p_c1_capacitance}"
        and by_ref["r1"]["param"] == "resistance"
        and by_ref["c1"]["param"] == "capacitance"
        and by_ref["r1"]["placeholder"] == "p_r1_resistance"
    )
    untouched = (
        subckt_lines(filter_text) == subckt_lines(rewritten)
        and lines.get("R99") == "R99 /out 0 1k"
        and lines.get("C2") == "C2 /out 0 10p"
        and lines.get("D2") == "D2 /out /vcc DMOD"
        and lines.get("V1") == "V1 /vcc 0 DC 5"
        and lines.get("XU1") == "XU1 /mid /fb /vcc 0 /out opamp"
        and model_line in rewritten.splitlines()
        and '.include "opamp.lib"' in rewritten.splitlines()
    )
    subckt_names = ("Rin", "Ccomp", "Qint")
    reported = set(by_ref) | set(left)
    clear = (
        "no clear primary" in left.get("r99", {}).get("reason", "")
        and "no clear primary" in left.get("c2", {}).get("reason", "")
        and all(name.casefold() not in reported for name in subckt_names)
        and "{" not in "\n".join(subckt_lines(rewritten))
    )
    check(
        "the synthetic RC plus op-amp board binds only R and C values and leaves the subckt alone",
        only_rc and values_ok and untouched and clear,
    )
    if not (only_rc and values_ok and untouched and clear):
        print(f"  bound {sorted(by_ref)}")
        print(f"  left { {key: item.get('reason') for key, item in left.items()} }")
        print(rewritten)
else:
    check("the synthetic RC plus op-amp board binds only R and C values and leaves the subckt alone", False)
    print(f"  {type(bound_board).__name__}: {bound_board}")

source = (ROOT / "tools" / "board_mc.py").read_text(encoding="utf-8")
check(
    "the board tool does not start a shell or fetch",
    "shell=True" not in source
    and "shell = True" not in source
    and "urllib" not in source
    and "urlopen" not in source
    and "wiki.adom.inc" not in source,
)
fixture = RC_NET.read_text(encoding="utf-8")
check(
    "the unity-gain fixture measures vdb inside .control",
    ".control" in fixture and "meas ac f3db WHEN vdb(out)=-3.0103" in fixture,
)

refused_dir = ROOT / "cards" / "board-mc-outside"
climb_dir = ROOT / "cards" / "board-mc-climb"
remove_path(refused_dir)
remove_path(climb_dir)
base = [
    "--bom", "tests/fixtures/board/rc-lowpass.csv",
    "--netlist", "tests/fixtures/board/rc-lowpass.cir",
    "--runs", "1",
    "--seed", "1",
    "--allow-fallback",
]
refused = cli([*base, "--out", "cards/board-mc-outside"])
climbed = cli([*base, "--out", "out/../cards/board-mc-climb"])
check(
    "--out outside out/ is refused",
    refused.returncode == 2
    and "outside out/" in refused.stderr
    and not refused_dir.exists()
    and climbed.returncode == 2
    and "outside out/" in climbed.stderr
    and not climb_dir.exists(),
)
if refused_dir.exists() or climb_dir.exists() or refused.returncode != 2 or climbed.returncode != 2:
    print(refused.stderr)
    print(climbed.stderr)

fallback_dir = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="board-nofallback-"))
cleanup.append(fallback_dir)
fallback = cli([
    "--bom", "tests/fixtures/board/rc-lowpass.csv",
    "--netlist", "tests/fixtures/board/rc-lowpass.cir",
    "--runs", "2",
    "--seed", "1",
    "--out", fallback_dir.relative_to(ROOT).as_posix(),
])
fallback_err = fallback.stderr
no_deck = not (fallback_dir / "run_0001.cir").exists() and not (fallback_dir / "board_report.md").exists()
check(
    "without --allow-fallback a fallback row exits 2",
    fallback.returncode == 2
    and "R1" in fallback_err
    and "C1" in fallback_err
    and "fallback" in fallback_err.lower()
    and "bom_not_in_netlist" in fallback_err
    and "netlist_not_in_bom" in fallback_err
    and no_deck,
)
if fallback.returncode != 2 or not no_deck:
    print(fallback.stdout)
    print(fallback.stderr)

adom_bom = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="board-noadom-"))
cleanup.append(adom_bom)
(adom_bom / "bom.csv").write_text(
    "refdes,mpn,manufacturer,value,tolerance,adom_slug\n"
    "R1,NO-SUCH,Generic,,,do-not-fetch\n",
    encoding="utf-8",
)
adom_dir = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="board-noadom-out-"))
cleanup.append(adom_dir)
try:
    adom = cli([
        "--bom", str((adom_bom / "bom.csv").relative_to(ROOT)),
        "--netlist", "tests/fixtures/board/rc-lowpass.cir",
        "--runs", "1",
        "--seed", "1",
        "--out", adom_dir.relative_to(ROOT).as_posix(),
    ], timeout=15)
    adom_err = adom.stderr
    adom_ok = (
        adom.returncode == 2
        and "R1" in adom_err
        and "adom" in adom_err.lower()
        and "C1" in adom_err
        and not (adom_dir / "run_0001.cir").exists()
        and not list(adom_dir.rglob("*.yaml"))
    )
except subprocess.TimeoutExpired:
    adom_ok = False
    adom_err = "timed out"
check("without --allow-adom a slug row exits 2 and does not fetch", adom_ok)
if not adom_ok:
    print(adom_err)

if shutil.which("ngspice") is None:
    print("SKIP the same seed writes byte-identical decks: ngspice is not on PATH")
    print("SKIP the report lists every fallback with its warning: ngspice is not on PATH")
    print("SKIP 200 ngspice runs stay within 2 percent of 1/(2*pi*R*C): ngspice is not on PATH")
else:
    same_a = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="board-same-a-"))
    same_b = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="board-same-b-"))
    other_dir = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="board-other-seed-"))
    cleanup.extend([same_a, same_b, other_dir])
    same_args = [
        "--bom", "tests/fixtures/board/rc-lowpass.csv",
        "--netlist", "tests/fixtures/board/rc-lowpass.cir",
        "--runs", "3",
        "--seed", "11",
        "--jobs", "1",
        "--allow-fallback",
        "--spec", "f3db=1.4:1.8",
    ]
    run_a = cli([*same_args, "--out", same_a.relative_to(ROOT).as_posix()])
    run_b = cli([*same_args, "--out", same_b.relative_to(ROOT).as_posix()])
    run_other = cli([
        "--bom", "tests/fixtures/board/rc-lowpass.csv",
        "--netlist", "tests/fixtures/board/rc-lowpass.cir",
        "--runs", "1",
        "--seed", "12",
        "--allow-fallback",
        "--out", other_dir.relative_to(ROOT).as_posix(),
    ])
    files_a = decks(same_a)
    files_b = decks(same_b)
    identical = (
        run_a.returncode == 0
        and run_b.returncode == 0
        and files_a
        and files_a == files_b
        and files_a.get("run_0001.cir") != files_a.get("run_0002.cir")
        and (other_dir / "run_0001.cir").is_file()
        and (other_dir / "run_0001.cir").read_bytes() != files_a.get("run_0001.cir")
    )
    check("the same seed writes byte-identical decks", identical)
    if not identical:
        print(run_a.stdout)
        print(run_a.stderr)
        print(run_b.stderr)
        print(sorted(files_a))
        print(sorted(files_b))

    report_path = same_a / "board_report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    warn_at = report.find("## Warnings")
    summary_at = report.find("## Summary")
    warn_block = report[warn_at:summary_at] if warn_at >= 0 and summary_at > warn_at else ""
    parts = report[:warn_at] if warn_at >= 0 else ""
    listed = (
        run_a.returncode == 0
        and all(ref in parts and "found: fallback" in parts and f"{ref}.yaml" in parts for ref in ("R1", "C1"))
        and all(ref in warn_block for ref in ("R1", "C1"))
        and warn_block.count("fallback from BOM tolerance, not from a datasheet") >= 2
        and "yield:" in report[summary_at:]
    )
    check("the report lists every fallback with its warning", listed)
    if not listed:
        print(report)
        print(run_a.stderr)

    long_dir = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="board-rc-200-"))
    cleanup.append(long_dir)
    try:
        long_run = cli([
            "--bom", "tests/fixtures/board/rc-lowpass.csv",
            "--netlist", "tests/fixtures/board/rc-lowpass.cir",
            "--runs", "200",
            "--seed", "7",
            "--jobs", "4",
            "--allow-fallback",
            "--spec", "f3db=1.4:1.8",
            "--out", long_dir.relative_to(ROOT).as_posix(),
        ], timeout=300)
    except subprocess.TimeoutExpired:
        long_run = None
        print("  the 200-run command timed out")
    csv_path = long_dir / "results.csv"
    rows = []
    if long_run is not None and csv_path.is_file():
        rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    values = []
    for row in rows:
        if row.get("status") != "ok":
            values = []
            break
        try:
            values.append(float(row["f3db"]))
        except (KeyError, ValueError):
            values = []
            break
    expect = 1.0 / (2.0 * math.pi * 10000.0 * 10e-6)
    got = sum(values) / len(values) if values else None
    summary_path = long_dir / "summary.txt"
    summary = summary_path.read_text(encoding="utf-8") if summary_path.is_file() else ""
    within = (
        long_run is not None
        and long_run.returncode == 0
        and len(values) == 200
        and got is not None
        and abs(got - expect) / expect <= 0.02
        and "yield: 1.0 lo=1.4 hi=1.8" in summary
    )
    if not within:
        print(f"  mean {got} expected {expect} rows {len(rows)}")
        if long_run is not None:
            print(long_run.stdout)
            print(long_run.stderr)
        logs = sorted(long_dir.glob("run_*.log"))
        if logs:
            tail = logs[0].read_text(encoding="utf-8", errors="replace").splitlines()
            print("\n".join(tail[-30:]))
    check("200 ngspice runs stay within 2 percent of 1/(2*pi*R*C)", within)

for path in cleanup:
    remove_path(path)
remove_path(refused_dir)
remove_path(climb_dir)

print(f"\n{'all tests passed' if not failures else f'{failures} test(s) failed'}")
sys.exit(1 if failures else 0)
