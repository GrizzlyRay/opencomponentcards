#!/usr/bin/env python3
"""Tests for the SPICE export command line. No pytest and no network.

ngspice is used only when it is already on PATH. Otherwise that check is SKIP.

Run: python3 tests/test_spice_export_run.py
"""
import csv
import io
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import spice_export as sx  # noqa: E402

EX = ROOT / "cards" / "examples"
NET = ROOT / "tests" / "fixtures" / "spice" / "rc-lowpass.cir"
NUMBER = re.compile(r"^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$")
FORBIDDEN = re.compile(r"\b(agauss|gauss|unif|mc|flat)\b")
failures = 0


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    failures += not cond


def card_binds():
    return [
        ("R1", sx.load_card(EX / "example_resistor.yaml")),
        ("C1", sx.load_card(EX / "example_capacitor.yaml")),
    ]


def bound_param_names():
    names = []
    for refdes, card in card_binds():
        for param in card["parameters"]:
            names.append(sx.param_name(refdes, param["name"]))
    return names


def cli(args, timeout=180):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "spice_export.py"), *args],
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


(ROOT / "out").mkdir(exist_ok=True)
cleanup = []
netlist = NET.read_text(encoding="utf-8")
names = bound_param_names()
missing_in_fixture = [name for name in names if "{" + name + "}" not in netlist]
check("fixture names every bound parameter", not missing_in_fixture)
check("the fixture measures f3db", sx.meas_names(netlist) == ["f3db"])
if missing_in_fixture:
    print("  missing " + ", ".join(missing_in_fixture))

try:
    sx.check_bindings("* only {p_r1_resistance}\n.end\n", ["p_r1_resistance", "p_r1_tcr"])
    one_sided = ""
except sx.ExportError as exc:
    one_sided = str(exc)
check(
    "a one-sided mismatch still lists both sides",
    "netlist parameters with no binding: (none)" in one_sided
    and "bound parameters not used in the netlist: p_r1_tcr" in one_sided,
)

mismatch_dir = ROOT / "out" / "spice-bind-mismatch"
remove_path(mismatch_dir)
bad_net = ROOT / "out" / "spice-bind-mismatch-net.cir"
cleanup.append(bad_net)
bad_net.write_text("* {p_missing_gain}\nR1 in 0 1k\n.end\n", encoding="utf-8")
mismatch = cli([
    "--netlist", str(bad_net.relative_to(ROOT)),
    "--bind", "R1=cards/examples/example_resistor.yaml",
    "--runs", "2",
    "--seed", "1",
    "--sim", "ltspice",
    "--out", "out/spice-bind-mismatch",
])
mismatch_err = mismatch.stderr
check(
    "a binding mismatch exits 2 and names both lists",
    mismatch.returncode == 2
    and "netlist parameters with no binding:" in mismatch_err
    and "p_missing_gain" in mismatch_err
    and "bound parameters not used in the netlist:" in mismatch_err
    and "p_r1_resistance" in mismatch_err
    and "p_r1_tcr" in mismatch_err
    and not mismatch_dir.exists(),
)
if mismatch.returncode != 2 or mismatch_dir.exists():
    print(mismatch.stdout)
    print(mismatch.stderr)

outside = ROOT / "cards" / "spice-export-outside"
climb = ROOT / "cards" / "spice-export-climb"
remove_path(outside)
remove_path(climb)
base_cmd = [
    "--netlist", "tests/fixtures/spice/rc-lowpass.cir",
    "--bind", "R1=cards/examples/example_resistor.yaml",
    "--bind", "C1=cards/examples/example_capacitor.yaml",
    "--runs", "1",
    "--seed", "1",
    "--sim", "ltspice",
]
refused = cli([*base_cmd, "--out", "cards/spice-export-outside"])
climbed = cli([*base_cmd, "--out", "out/../cards/spice-export-climb"])
check(
    "--out outside out/ is refused",
    refused.returncode == 2
    and "outside out/" in refused.stderr
    and not outside.exists()
    and climbed.returncode == 2
    and "outside out/" in climbed.stderr
    and not climb.exists(),
)
if outside.exists() or climb.exists() or refused.returncode != 2 or climbed.returncode != 2:
    print(refused.stderr)
    print(climbed.stderr)

same_a = sx.plan_export(netlist, card_binds(), 5, 99)
same_b = sx.plan_export(netlist, card_binds(), 5, 99)
deck_a = sx.render_ngspice(same_a, netlist)
deck_b = sx.render_ngspice(same_b, netlist)
lt_a = sx.render_ltspice(same_a, netlist)
lt_b = sx.render_ltspice(same_b, netlist)
other = sx.render_ngspice(sx.plan_export(netlist, card_binds(), 5, 100), netlist)
check("the same seed writes byte-identical ngspice decks", deck_a == deck_b and lt_a == lt_b)
check("a different seed changes the deck", other["run_0001.param"] != deck_a["run_0001.param"])
check("each run has its own deck", deck_a["run_0001.cir"] != deck_a["run_0002.cir"])

plain_ok = True
for text in list(deck_a.values()) + list(lt_a.values()):
    if FORBIDDEN.search(text):
        plain_ok = False
    for line in text.splitlines():
        if line.startswith(".param ") and "table(" not in line:
            body = line[len(".param "):]
            if "=" not in body or not NUMBER.fullmatch(body.split("=", 1)[1]):
                plain_ok = False
check("decks contain plain numbers only", plain_ok)
include_at = deck_a["run_0001.cir"].find(".include run_0001.param")
element_at = deck_a["run_0001.cir"].find("R1 in out {p_r1_resistance}")
check(
    "the ngspice deck includes the param file before the netlist",
    include_at > 0 and element_at > include_at and deck_a["run_0001.cir"].rstrip().endswith(".end"),
)
check("the param file does not end the deck", ".end" not in deck_a["run_0001.param"])

resistor = sx.load_card(EX / "example_resistor.yaml")
capacitor = sx.load_card(EX / "example_capacitor.yaml")
res_runs = sx.sample(resistor, 5, 99, ["R1"])
cap_runs = sx.sample(capacitor, 5, 99, ["C1"])
expected = {}
for index in range(5):
    for pname, value in res_runs[index]["instances"][0]["values"].items():
        expected[(sx.param_name("R1", pname), index)] = sx._format(value)
    for pname, value in cap_runs[index]["instances"][0]["values"].items():
        expected[(sx.param_name("C1", pname), index)] = sx._format(value)
table_ok = "Untested in LTspice." in lt_a["ltspice.cir"]
table_ok = table_ok and ".step param run 1 5 1" in lt_a["ltspice.cir"]
for spice_name in same_a["order"]:
    match = re.search(
        rf"(?m)^\.param {re.escape(spice_name)} = table\(run, (.+)\)$",
        lt_a["ltspice.cir"],
    )
    if not match:
        table_ok = False
        continue
    parts = [part.strip() for part in match.group(1).split(",")]
    if len(parts) != 10:
        table_ok = False
        continue
    for index in range(5):
        if parts[2 * index] != str(index + 1) or parts[2 * index + 1] != expected[(spice_name, index)]:
            table_ok = False
check("the LTspice table has N entries matching the sampled values", table_ok)

dir_a = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="spice-lt-a-"))
dir_b = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="spice-lt-b-"))
cleanup.extend([dir_a, dir_b, mismatch_dir])
rel_a = dir_a.relative_to(ROOT).as_posix()
rel_b = dir_b.relative_to(ROOT).as_posix()
lt_cmd = [
    "--netlist", "tests/fixtures/spice/rc-lowpass.cir",
    "--bind", "R1=cards/examples/example_resistor.yaml",
    "--bind", "C1=cards/examples/example_capacitor.yaml",
    "--runs", "5",
    "--seed", "99",
    "--sim", "ltspice",
]
proc_a = cli([*lt_cmd, "--out", rel_a])
proc_b = cli([*lt_cmd, "--out", rel_b])
files_a = {path.relative_to(dir_a).as_posix(): path.read_bytes() for path in dir_a.rglob("*") if path.is_file()}
files_b = {path.relative_to(dir_b).as_posix(): path.read_bytes() for path in dir_b.rglob("*") if path.is_file()}
check(
    "two LTspice runs with the same seed write the same files",
    proc_a.returncode == 0 and proc_b.returncode == 0 and files_a == files_b and "ltspice.cir" in files_a,
)
if proc_a.returncode != 0 or proc_b.returncode != 0:
    print(proc_a.stderr)
    print(proc_b.stderr)
written = (dir_a / "ltspice.cir").read_bytes() if (dir_a / "ltspice.cir").is_file() else b""
check("the command writes the library LTspice deck", written == lt_a["ltspice.cir"].encode("utf-8"))
summary = (dir_a / "summary.txt").read_text(encoding="utf-8") if (dir_a / "summary.txt").is_file() else ""
check(
    "an LTspice summary does not pretend the simulator ran",
    "LTspice was not run." in summary and "count: 0" in summary and "failed: 0" in summary and "std: n/a" in summary,
)
csv_bytes = (dir_a / "results.csv").read_bytes() if (dir_a / "results.csv").is_file() else b""
parsed_rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))) if csv_bytes else []
check(
    "the csv keeps one written row per run",
    b"\r" not in csv_bytes and len(parsed_rows) == 5 and all(row["status"] == "written" for row in parsed_rows),
)

normal_log = "\n".join([
    "Circuit: rc lowpass",
    "f3db                =   1.59164e+00",
    "DRAM available = 12345.0",
    "Total elapsed time (seconds) = 0.012",
])
normal_values, normal_reasons = sx.parse_meas_log(normal_log, ["f3db"])
check(
    "a normal .meas line is parsed",
    normal_values == {"f3db": float("1.59164e+00")} and normal_reasons == {},
)
missing_values, missing_reasons = sx.parse_meas_log(
    "No. of Data Rows : 500\nTotal elapsed time (seconds) = 0.01\n",
    ["f3db"],
)
check(
    "a missing .meas is reported",
    missing_values == {} and missing_reasons.get("f3db") == "f3db missing",
)
failed_values, failed_reasons = sx.parse_meas_log("f3db = failed\n", ["f3db"])
failed_card_values, failed_card_reasons = sx.parse_meas_log(
    "Error: measure f3db when(WHEN) : out of interval\n.meas ac f3db WHEN v(out)=0.5 failed!\n",
    ["f3db"],
)
check(
    "a failed .meas is reported",
    failed_values == {}
    and failed_reasons.get("f3db") == "f3db failed"
    and failed_card_values == {}
    and failed_card_reasons.get("f3db") == "f3db failed",
)

kept = sx.results_csv(
    [
        {"run": 1, "seed": 3, "values": {"p_r1_resistance": 10000.0}, "meas": {"f3db": 1.5}, "status": "ok"},
        {"run": 2, "seed": 3, "values": {"p_r1_resistance": 10010.0}, "meas": {}, "status": "failed: f3db missing"},
    ],
    ["p_r1_resistance"],
    ["f3db"],
)
kept_rows = list(csv.reader(io.StringIO(kept)))
check(
    "a failed run is kept in the csv",
    len(kept_rows) == 3 and kept_rows[2][3] == "" and kept_rows[2][4].startswith("failed:"),
)
yield_rows = [
    {"meas": {"f3db": 1.5}, "status": "ok"},
    {"meas": {"f3db": 2.5}, "status": "ok"},
    {"meas": {}, "status": "failed: f3db missing"},
    {"meas": {"f3db": 1.6}, "status": "ok"},
]
yield_text = sx.summary_text(yield_rows, ["f3db"], {"f3db": (1.4, 1.7)}, "ngspice")
std_match = re.search(r"(?m)^std: (\S+)$", yield_text)
got_std = float(std_match.group(1)) if std_match else None
check(
    "yield counts in-spec runs over every run",
    "count: 3" in yield_text
    and "failed: 1" in yield_text
    and "yield: 0.5 lo=1.4 hi=1.7" in yield_text
    and got_std == statistics.stdev([1.5, 2.5, 1.6]),
)

source = (ROOT / "tools" / "spice_export.py").read_text(encoding="utf-8")
check("ngspice is not started through a shell", "shell=True" not in source and "shell = True" not in source)

if shutil.which("ngspice") is None:
    print("SKIP mean -3 dB frequency over 200 runs is within 2 percent of 1/(2*pi*R*C): ngspice is not on PATH")
else:
    spice_dir = Path(tempfile.mkdtemp(dir=ROOT / "out", prefix="spice-rc-"))
    cleanup.append(spice_dir)
    try:
        spice = cli([
            "--netlist", "tests/fixtures/spice/rc-lowpass.cir",
            "--bind", "R1=cards/examples/example_resistor.yaml",
            "--bind", "C1=cards/examples/example_capacitor.yaml",
            "--runs", "200",
            "--seed", "7",
            "--jobs", "4",
            "--timeout", "30",
            "--spec", "f3db=1.4:1.8",
            "--sim", "ngspice",
            "--out", spice_dir.relative_to(ROOT).as_posix(),
        ], timeout=240)
    except subprocess.TimeoutExpired:
        spice = None
        print("  the 200-run command timed out")
    csv_path = spice_dir / "results.csv"
    summary_path = spice_dir / "summary.txt"
    rows = []
    if spice is not None and csv_path.is_file():
        rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    values = []
    for row in rows:
        try:
            values.append(float(row["f3db"]))
        except (KeyError, ValueError):
            values = []
            break
    r_nom = next(param["nominal"] for param in resistor["parameters"] if param["name"] == "resistance")
    c_nom = next(param["nominal"] for param in capacitor["parameters"] if param["name"] == "capacitance")
    expect = 1.0 / (2.0 * math.pi * float(r_nom) * float(c_nom))
    # The fixture measures vdb(out)=-3.0103, the magnitude -3 dB point.
    got = sum(values) / len(values) if values else None
    statuses = {row.get("status") for row in rows}
    within = (
        spice is not None
        and spice.returncode == 0
        and len(rows) == 200
        and statuses == {"ok"}
        and got is not None
        and abs(got - expect) / expect <= 0.02
    )
    summary_text = summary_path.read_text(encoding="utf-8") if summary_path.is_file() else ""
    within = within and re.search(r"(?m)^count: 200$", summary_text) is not None
    within = within and re.search(r"(?m)^failed: 0$", summary_text) is not None
    within = within and "yield: 1.0 lo=1.4 hi=1.8" in summary_text
    plan = sx.plan_export(netlist, card_binds(), 200, 7)
    rendered = sx.render_ngspice(plan, netlist)["run_0001.cir"].encode("utf-8")
    on_disk = (spice_dir / "run_0001.cir").read_bytes() if (spice_dir / "run_0001.cir").is_file() else b""
    decks_ok = not [n for n in range(1, 201) if not (spice_dir / f"run_{n:04d}.cir").is_file()]
    decks_ok = decks_ok and (spice_dir / "run_0200.log").is_file() and on_disk == rendered
    if not within or not decks_ok:
        print(f"  mean {got} expected {expect} rows {len(rows)} statuses {statuses}")
        if spice is not None:
            print(spice.stdout)
            print(spice.stderr)
        logs = sorted(spice_dir.glob("run_*.log"))
        if logs:
            tail = logs[0].read_text(encoding="utf-8", errors="replace").splitlines()
            print("\n".join(tail[-40:]))
    check("200 ngspice runs stay within 2 percent of 1/(2*pi*R*C)", within and decks_ok)

for path in cleanup:
    remove_path(path)
remove_path(outside)
remove_path(climb)

print(f"\n{'all tests passed' if not failures else f'{failures} test(s) failed'}")
sys.exit(1 if failures else 0)
