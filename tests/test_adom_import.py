#!/usr/bin/env python3
"""Tests for the pure functions in tools/adom_import.py. No pytest and no network.

Run: python3 tests/test_adom_import.py
"""
import contextlib
import io
import json
import math
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import adom_import as ai  # noqa: E402
import validate as vd  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "adom"
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
failures = 0


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    failures += not cond


def near(got, exp):
    return isinstance(got, (int, float)) and not isinstance(got, bool) and math.isclose(got, exp, rel_tol=0, abs_tol=1e-12)


def rows_of(filename):
    page = json.loads((FIX / filename).read_text(encoding="utf-8"))
    return page["metadata"]["characteristics"]["rows"]


def reasons_for(skipped, symbol):
    return [item["reason"] for item in skipped if item["row"]["symbol"] == symbol]


def same_cond(got, exp):
    if set(got) != set(exp):
        return False
    for key, value in exp.items():
        if isinstance(value, bool):
            if got[key] is not value:
                return False
        elif isinstance(value, (int, float)):
            if not near(got[key], value):
                return False
        elif got[key] != value:
            return False
    return True


# Printed unit -> (OCC unit, scale). None means the printed unit is not imported.
UNIT_CASES = [
    ("V", ("V", 1)),
    ("mV", ("V", 1e-3)),
    ("\u00b5V", ("V", 1e-6)),
    ("\u03bcV", ("V", 1e-6)),
    ("A", ("A", 1)),
    ("mA", ("A", 1e-3)),
    ("\u00b5A", ("A", 1e-6)),
    ("\u03bcA", ("A", 1e-6)),
    ("nA", ("A", 1e-9)),
    ("pA", ("A", 1e-12)),
    ("\u03a9", ("Ohm", 1)),
    ("\u2126", ("Ohm", 1)),
    ("k\u03a9", ("Ohm", 1e3)),
    ("k\u2126", ("Ohm", 1e3)),
    ("M\u03a9", ("Ohm", 1e6)),
    ("M\u2126", ("Ohm", 1e6)),
    ("m\u03a9", ("Ohm", 1e-3)),
    ("m\u2126", ("Ohm", 1e-3)),
    ("F", ("F", 1)),
    ("\u00b5F", ("F", 1e-6)),
    ("\u03bcF", ("F", 1e-6)),
    ("nF", ("F", 1e-9)),
    ("pF", ("F", 1e-12)),
    ("H", ("H", 1)),
    ("mH", ("H", 1e-3)),
    ("\u00b5H", ("H", 1e-6)),
    ("\u03bcH", ("H", 1e-6)),
    ("nH", ("H", 1e-9)),
    ("W", ("W", 1)),
    ("mW", ("W", 1e-3)),
    ("s", ("s", 1)),
    ("ms", ("s", 1e-3)),
    ("\u00b5s", ("s", 1e-6)),
    ("\u03bcs", ("s", 1e-6)),
    ("ns", ("s", 1e-9)),
    ("Hz", ("Hz", 1)),
    ("kHz", ("Hz", 1e3)),
    ("MHz", ("Hz", 1e6)),
    ("\u00b0C", ("degC", 1)),
    ("\u2103", ("degC", 1)),
    ("%", ("1", 0.01)),
    ("ppm/\u00b0C", ("ppm/K", 1)),
    ("ppm/\u2103", ("ppm/K", 1)),
    ("mS", None),
    ("S", None),
    ("\u00b0C/W", None),
    ("ppm/V", None),
    ("", None),
]

schema = json.loads((ROOT / "schema" / "card.schema.json").read_text(encoding="utf-8"))
occ_units = set(schema["$defs"]["unit"]["enum"])

for printed, expected in UNIT_CASES:
    got = ai.normalize_unit(printed)
    if expected is None:
        ok = got is None
    else:
        ok = got is not None and got[0] == expected[0] and got[0] in occ_units and near(got[1], expected[1])
    check(f"normalize_unit({printed!r})", ok)

check("normalize_unit(None) is None", ai.normalize_unit(None) is None)
check("ms is milliseconds and mS is not", ai.normalize_unit("ms") == ("s", 1e-3) and ai.normalize_unit("mS") is None)

mosfet = rows_of("synthetic-mosfet.json")
passive = rows_of("synthetic-passive.json")

idss = [row for row in mosfet if row["symbol"] == "IDSS"]
igss = next(row for row in mosfet if row["symbol"] == "IGSS")
rds = [row for row in mosfet if row["symbol"] == "RDS(on)"]
rg = next(row for row in mosfet if row["symbol"] == "RG")
resistance = next(row for row in passive if row["symbol"] == "R")
check("fixture carries both micro signs on current", idss[0]["unit"] == "\u00b5A" and igss["unit"] == "\u03bcA")
check("µA and μA both scale to amperes", ai.normalize_unit(idss[0]["unit"]) == ("A", 1e-6) and ai.normalize_unit(igss["unit"]) == ("A", 1e-6))
check("IDSS nA stays a distinct scale", ai.normalize_unit(idss[1]["unit"]) == ("A", 1e-9))
check("fixture carries both ohm signs", rds[0]["unit"] == "\u03a9" and rg["unit"] == "\u2126")
check("both ohm signs are Ohm", ai.normalize_unit(rds[0]["unit"]) == ("Ohm", 1) and ai.normalize_unit(rg["unit"]) == ("Ohm", 1))
check("resistance row is kΩ", resistance["unit"] == "k\u03a9" and ai.normalize_unit(resistance["unit"]) == ("Ohm", 1e3))

check("import kinds", set(ai.IMPORT_KINDS) == {"electrical", "tolerance", "temperature_coefficient", "voltage_coefficient", "timing"})
check("skip kinds", set(ai.SKIP_KINDS) == {"absolute_maximum", "recommended_operating", "thermal"})
check("import and skip kinds are disjoint", set(ai.IMPORT_KINDS).isdisjoint(ai.SKIP_KINDS))

names = ai.assign_names(mosfet)
check("assign_names covers every mosfet row", len(names) == len(mosfet))
check("parameter names are unique", len(names) == len(set(names)))
check("parameter names match the card pattern", all(NAME.fullmatch(name) for name in names))
check(
    "symbols become parameter names with _2 on collisions",
    names == ["rds_on", "rds_on_2", "idss", "idss_2", "igss", "rg", "gfs", "r_ja", "coss", "vdss", "vgs", "vsw", "vgs_th"],
)
check("VGS(th) becomes vgs_th", names[mosfet.index(next(row for row in mosfet if row["symbol"] == "VGS(th)"))] == "vgs_th")
check("RDS rows that share name, symbol, and kind get different names", names[0] == "rds_on" and names[1] == "rds_on_2")
check("µA and nA IDSS rows get different names", names[2] == "idss" and names[3] == "idss_2")
check("IDSS rows share a key but are not collapsed", ai.row_key(idss[0]) == ai.row_key(idss[1]) and names[2] != names[3])
check("RDS rows differ in the condition part of the key", ai.row_key(rds[0]) != ai.row_key(rds[1]))
check(
    "row_key is name, symbol, kind, and conditions",
    ai.row_key(rds[0]) == (rds[0]["name"], rds[0]["symbol"], rds[0]["kind"], rds[0]["conditions"]),
)

asked = list(ai.IMPORT_KINDS) + list(ai.SKIP_KINDS)
usable, skipped = ai.select_rows(mosfet, asked)
usable_symbols = [item["row"]["symbol"] for item in usable]
check("only VGS(th) is usable on the mosfet page", usable_symbols == ["VGS(th)"])
check("usable VGS(th) keeps min and max in volts", usable[0]["unit"] == "V" and near(usable[0]["min"], 1) and near(usable[0]["max"], 2.5))
check("no skipped kind is imported", all(item["row"]["kind"] not in ai.SKIP_KINDS for item in usable))
check("absolute_maximum is skipped even when asked", reasons_for(skipped, "VDSS") == ["skipped kind"])
check("recommended_operating is skipped even when asked", reasons_for(skipped, "VGS") == ["skipped kind"])
check("thermal is skipped even when asked", reasons_for(skipped, "R\u03b8JA") == ["skipped kind"])
check("gFS mS is an unknown unit", reasons_for(skipped, "gFS") == ["unknown unit"])
check("one-sided RDS rows are skipped", reasons_for(skipped, "RDS(on)") == ["one-sided limits", "one-sided limits"])
check("µA and nA rows are skipped separately", reasons_for(skipped, "IDSS") == ["one-sided limits", "one-sided limits"])
check("typ-only Coss is skipped", reasons_for(skipped, "Coss") == ["one-sided limits"])
check("min greater than max is skipped", reasons_for(skipped, "VSW") == ["min not less than max"])
check("every mosfet row is usable or skipped", len(usable) + len(skipped) == len(mosfet))

only_skip = ai.select_rows(mosfet, ai.SKIP_KINDS)
check("asking only for skipped kinds imports nothing", only_skip[0] == [])
check("VGS(th) is not imported when its kind was not requested", reasons_for(only_skip[1], "VGS(th)") == ["kind not requested"])

pusable, pskipped = ai.select_rows(passive, ai.IMPORT_KINDS)
check("passive imports tolerance and temperature coefficient", [item["row"]["symbol"] for item in pusable] == ["Tol", "TCR"])
tol = pusable[0]
tcr = pusable[1]
check("percent limits scale into the dimensionless unit", tol["unit"] == "1" and near(tol["scale"], 0.01) and near(tol["min"], -0.01) and near(tol["max"], 0.01))
check("tolerance row is not mutated", tol["row"]["min"] == -1 and tol["row"]["max"] == 1 and tol["row"]["unit"] == "%")
check("ppm/℃ maps to ppm/K without rescaling", tcr["unit"] == "ppm/K" and near(tcr["scale"], 1) and near(tcr["min"], -100) and near(tcr["max"], 100))
check("ppm/℃ row is not mutated", tcr["row"]["unit"] == "ppm/\u2103" and tcr["row"]["min"] == -100 and tcr["row"]["max"] == 100)
check("one-sided resistance and capacitance are skipped", reasons_for(pskipped, "R") == ["one-sided limits"] and reasons_for(pskipped, "C") == ["one-sided limits"])
check("ppm/V voltage coefficient is an unknown unit", reasons_for(pskipped, "VC") == ["unknown unit"])
check("timing row is skipped as one-sided, not as a rejected kind", reasons_for(pskipped, "tr") == ["one-sided limits"])
check("every passive row is usable or skipped", len(pusable) + len(pskipped) == len(passive))

only_tol = ai.select_rows(passive, ["tolerance"])
check("unrequested import kinds are skipped", [item["row"]["symbol"] for item in only_tol[0]] == ["Tol"])
check("temperature coefficient is skipped when not requested", reasons_for(only_tol[1], "TCR") == ["kind not requested"])


def condition(rows, symbol, contains):
    found = [row["conditions"] for row in rows if row["symbol"] == symbol and contains in row["conditions"]]
    check(f"fixture condition for {symbol} containing {contains!r}", len(found) == 1)
    return found[0] if len(found) == 1 else ""


check("RDS at 4.5 V parses gate voltage and current", same_cond(ai.parse_conditions(condition(mosfet, "RDS(on)", "4.5V")), {"vgs_v": 4.5, "id_a": 5}))
check("RDS at 10 V parses gate voltage and current", same_cond(ai.parse_conditions(condition(mosfet, "RDS(on)", "10V")), {"vgs_v": 10, "id_a": 10}))
idss_text = [row["conditions"] for row in idss]
check("both IDSS rows carry the same condition text", idss_text == ["VDS = 24V, VGS = 0V", "VDS = 24V, VGS = 0V"])
check("IDSS parses drain and gate voltage", same_cond(ai.parse_conditions(idss_text[0]), {"vds_v": 24, "vgs_v": 0}))
check("gFS parses drain voltage and current", same_cond(ai.parse_conditions(condition(mosfet, "gFS", "VDS")), {"vds_v": 5, "id_a": 5}))
check("Coss parses drain voltage and frequency", same_cond(ai.parse_conditions(condition(mosfet, "Coss", "1MHz")), {"vds_v": 15, "frequency_hz": 1e6}))
vth = condition(mosfet, "VGS(th)", "VDS = VGS")
check("VGS(th) parses tied drain-gate and microamp current", same_cond(ai.parse_conditions(vth), {"vds_eq_vgs": True, "id_a": 250e-6}))
check("VGS(th) does not invent a drain voltage", "vds_v" not in ai.parse_conditions(vth) and "vgs_v" not in ai.parse_conditions(vth))
check("Greek mu in the same current clause parses the same", same_cond(ai.parse_conditions(vth.replace("\u00b5", "\u03bc")), {"vds_eq_vgs": True, "id_a": 250e-6}))
check("empty conditions parse to nothing", ai.parse_conditions(rg["conditions"]) == {})
check("prose conditions are not guessed", ai.parse_conditions(next(row["conditions"] for row in mosfet if row["symbol"] == "VSW")) == {})
check("thermal note is not guessed", ai.parse_conditions(next(row["conditions"] for row in mosfet if row["symbol"] == "R\u03b8JA")) == {})
check("T = 25°C is temperature_c", same_cond(ai.parse_conditions("T = 25\u00b0C"), {"temperature_c": 25}))
check("T = 25℃ is temperature_c", same_cond(ai.parse_conditions("T = 25\u2103"), {"temperature_c": 25}))
check("a temperature range is not guessed", ai.parse_conditions("T = -40\u00b0C to 85\u00b0C") == {})
check("conflicting values for one key are dropped", same_cond(ai.parse_conditions("VGS = 4.5V, VGS = 10V, ID = 1A"), {"id_a": 1}))


def load_page(filename):
    return json.loads((FIX / filename).read_text(encoding="utf-8"))


def raises_input(filename):
    try:
        ai.build_card(load_page(filename), ai.Options(date="2026-11-13"))
    except ai.InputError:
        return True
    except Exception:
        return False
    return False


def validation_report(yaml_text):
    """Run tools/validate.py on the dumped card. Rules stay in that module."""
    path = None
    try:
        handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", encoding="utf-8", delete=False)
        path = Path(handle.name)
        handle.write(yaml_text)
        handle.close()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = vd.main(["--schema", str(ROOT / "schema" / "card.schema.json"), str(path)])
        return code, buf.getvalue()
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


DATE = "2026-11-13"
mosfet_page = load_page("synthetic-mosfet.json")
passive_page = load_page("synthetic-passive.json")
mosfet_opts = ai.Options(date=DATE)
passive_opts = ai.Options(date=DATE)
mosfet_card = ai.build_card(mosfet_page, mosfet_opts)
passive_card = ai.build_card(passive_page, passive_opts)
mosfet_yaml = ai.dump_card(mosfet_card)
passive_yaml = ai.dump_card(passive_card)

for label, text in (("mosfet", mosfet_yaml), ("passive", passive_yaml)):
    code, report = validation_report(text)
    if code != 0:
        print(report)
    check(f"{label} card passes validation with no errors", code == 0 and "ERROR" not in report)
    check(f"{label} yaml has no source sha256", "sha256" not in text)

check("mosfet license is the fixture license", mosfet_card["license"] == mosfet_page["license"] == "CC-BY-SA-4.0")
check("passive license is the fixture license", passive_card["license"] == passive_page["license"] == "CC-BY-SA-4.0")
check("maturity is 0.1", mosfet_card["validation"]["maturity"] == "0.1" and passive_card["validation"]["maturity"] == "0.1")
check("no source dict has sha256", all("sha256" not in source for source in mosfet_card["sources"] + passive_card["sources"]))
check("derivation kind is data", mosfet_card["derivation"]["kind"] == "data" and passive_card["derivation"]["kind"] == "data")
check("created is opts.date", mosfet_card["provenance"]["created"] == DATE and passive_card["provenance"]["created"] == DATE)

check("transistor category maps to other", mosfet_card["part"]["category"] == "other")
check("unmapped category is warned", mosfet_opts.warnings == ["Category 'Transistor' is not an OCC category; imported as other."])
check("warning is on the card notes", "Category 'Transistor' is not an OCC category; imported as other." in mosfet_card["notes"])
check("notes record the page version and updated_at", mosfet_page["version"] in mosfet_card["notes"] and mosfet_page["updated_at"] in mosfet_card["notes"])
check("mosfet id matches the schema shape", mosfet_card["id"] == "occ:other/example-semi-syn-mos-30v@0.1.0")
check("passive category is resistor", passive_card["part"]["category"] == "resistor")
check("passive id matches the schema shape", passive_card["id"] == "occ:resistor/example-passive-syn-r-10k@0.1.0")
check("description comes from the title", mosfet_card["part"]["description"] == mosfet_page["title"])
check("package and mpn come from the component", mosfet_card["part"]["mpn"] == "SYN-MOS-30V" and mosfet_card["part"]["package"] == "DFN 3x3")
check(
    "provenance names the wiki page",
    mosfet_card["provenance"]["author"] == (
        "Jacob Warren and GrizzlyRay LLC, imported from the Adom wiki page "
        "synthetic-example/synthetic-mosfet (Adom, wiki.adom.inc)"
    ),
)
check("mosfet imports only VGS(th)", [item["name"] for item in mosfet_card["parameters"]] == ["vgs_th"])
vth_param = mosfet_card["parameters"][0]
vth_row = next(row for row in mosfet_page["metadata"]["characteristics"]["rows"] if row["symbol"] == "VGS(th)")
check("VGS(th) limits are the published min and max in volts", near(vth_param["limits"]["min"], 1) and near(vth_param["limits"]["max"], 2.5))
check("VGS(th) nominal is the midpoint", near(vth_param["nominal"], 1.75))
check("limits cite wiki1", vth_param["limits"]["source_ref"] == "wiki1" and vth_param["source_refs"] == ["wiki1"])
vth_dist = vth_param["distributions"][0]
check("VGS(th) is a uniform population over the limits", vth_dist["scope"] == "total" and vth_dist["type"] == "uniform" and vth_dist["applies_to"] == "value" and vth_dist["kind"] == "population" and vth_dist["confidence"] == "low")
check("VGS(th) distribution matches the limits", near(vth_dist["params"]["min"], vth_param["limits"]["min"]) and near(vth_dist["params"]["max"], vth_param["limits"]["max"]))
check(
    "VGS(th) basis quotes the row",
    vth_dist["basis"] == (
        f"Adom row '{vth_row['name']}' ({vth_row['symbol']}, {vth_row['kind']}), "
        f"conditions '{vth_row['conditions']}', datasheet p.{vth_row['source_page']}. "
        "Shape not published; uniform over the published limits."
    ),
)
check("VGS(th) conditions are the parsed standard keys", vth_param["conditions"].get("vds_eq_vgs") is True and near(vth_param["conditions"].get("id_a"), 250e-6) and "vds_v" not in vth_param["conditions"])

check("passive parameter names", [item["name"] for item in passive_card["parameters"]] == ["tol", "tcr"])
tol = passive_card["parameters"][0]
tcr = passive_card["parameters"][1]
check("percent row is dimensionless with nominal 0", tol["unit"] == "1" and tol["nominal"] == 0)
check("percent limits are scaled", near(tol["limits"]["min"], -0.01) and near(tol["limits"]["max"], 0.01))
check("percent distribution is population over the scaled limits", tol["distributions"][0]["kind"] == "population" and near(tol["distributions"][0]["params"]["min"], -0.01) and near(tol["distributions"][0]["params"]["max"], 0.01))
check("ppm row is ppm/K", tcr["unit"] == "ppm/K" and tcr["limits"]["min"] == -100 and tcr["limits"]["max"] == 100)
check("ppm nominal is the midpoint", tcr["nominal"] == 0)
check("ppm distribution is epistemic", tcr["distributions"][0]["kind"] == "epistemic" and tcr["distributions"][0]["type"] == "uniform")
check("sources are ds1 then wiki1", [item["ref"] for item in passive_card["sources"]] == ["ds1", "wiki1"])
check("datasheet uri is copied and not hashed", passive_card["sources"][0]["kind"] == "datasheet" and passive_card["sources"][0]["uri"] == passive_page["component"]["datasheet"] and passive_card["sources"][0]["evidence"] == "p.1")
check(
    "wiki source is derived from ds1",
    passive_card["sources"][1]["kind"] == "derived"
    and passive_card["sources"][1]["derived_from"] == ["ds1"]
    and passive_card["sources"][1]["uri"] == "https://wiki.adom.inc/synthetic-example/synthetic-passive"
    and passive_card["sources"][1]["evidence"] == "metadata.characteristics.rows"
    and passive_card["sources"][1]["confidence"] == "high",
)

check("missing manufacturer is an input error", raises_input("synthetic-no-manufacturer.json"))
check("missing license is an input error", raises_input("synthetic-no-license.json"))

override = ai.Options(date=DATE, category="mosfet", manufacturer="Override Co")
overridden = ai.build_card(mosfet_page, override)
check("category and manufacturer overrides win", overridden["part"]["category"] == "mosfet" and overridden["part"]["manufacturer"] == "Override Co")
check("override id uses the occ category and manufacturer slug", overridden["id"] == "occ:mosfet/override-co-syn-mos-30v@0.1.0")
check("an explicit category does not warn", override.warnings == [])

again = ai.dump_card(ai.build_card(passive_page, ai.Options(date=DATE))).encode("utf-8")
check("two passive runs give identical bytes", passive_yaml.encode("utf-8") == again)
mosfet_again = ai.dump_card(ai.build_card(mosfet_page, ai.Options(date=DATE))).encode("utf-8")
check("two mosfet runs give identical bytes", mosfet_yaml.encode("utf-8") == mosfet_again)

print(f"\n{'all tests passed' if not failures else f'{failures} test(s) failed'}")
sys.exit(1 if failures else 0)
