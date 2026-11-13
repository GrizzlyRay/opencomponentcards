#!/usr/bin/env python3
"""Map an Adom wiki page.json into an OpenComponentCards v0.2 card (Apache-2.0).

Datasheet files are not downloaded. A page.json is read with --from-file or
fetched from the wiki blob URL. Draft cards are written only under out/.
Printed units become the closed OCC unit list, with a scale into that unit.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import validate as vd
import yaml

# Skip kinds are never imported, even when a caller lists them.
IMPORT_KINDS = frozenset({
    "electrical",
    "tolerance",
    "temperature_coefficient",
    "voltage_coefficient",
    "timing",
})
SKIP_KINDS = frozenset({
    "absolute_maximum",
    "recommended_operating",
    "thermal",
})

# Canonical micro sign is U+00B5 and canonical ohm is U+03A9.
# mS is millisiemens, which is not an OCC unit. ms is milliseconds.
_CANON = str.maketrans({"\u03bc": "\u00b5", "\u2126": "\u03a9"})
_UNITS = {}


def _add(occ, scale, printed):
    for unit in printed:
        _UNITS[unit.translate(_CANON)] = (occ, scale)


_add("V", 1, ("V",))
_add("V", 1e-3, ("mV",))
_add("V", 1e-6, ("\u00b5V",))
_add("A", 1, ("A",))
_add("A", 1e-3, ("mA",))
_add("A", 1e-6, ("\u00b5A",))
_add("A", 1e-9, ("nA",))
_add("A", 1e-12, ("pA",))
_add("Ohm", 1, ("\u03a9",))
_add("Ohm", 1e3, ("k\u03a9",))
_add("Ohm", 1e6, ("M\u03a9",))
_add("Ohm", 1e-3, ("m\u03a9",))
_add("F", 1, ("F",))
_add("F", 1e-6, ("\u00b5F",))
_add("F", 1e-9, ("nF",))
_add("F", 1e-12, ("pF",))
_add("H", 1, ("H",))
_add("H", 1e-3, ("mH",))
_add("H", 1e-6, ("\u00b5H",))
_add("H", 1e-9, ("nH",))
_add("W", 1, ("W",))
_add("W", 1e-3, ("mW",))
_add("s", 1, ("s",))
_add("s", 1e-3, ("ms",))
_add("s", 1e-6, ("\u00b5s",))
_add("s", 1e-9, ("ns",))
_add("Hz", 1, ("Hz",))
_add("Hz", 1e3, ("kHz",))
_add("Hz", 1e6, ("MHz",))
_add("degC", 1, ("\u00b0C", "\u2103"))
_add("1", 0.01, ("%",))
_add("ppm/K", 1, ("ppm/\u00b0C", "ppm/\u2103"))

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_ASSIGN = re.compile(r"([A-Za-z]+)\s*=\s*(.*)")
_VALUE = re.compile(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(\S+)")
_COND_UNIT = {"VGS": "V", "VDS": "V", "ID": "A", "f": "Hz", "T": "degC"}
_COND_KEY = {"VGS": "vgs_v", "VDS": "vds_v", "ID": "id_a", "f": "frequency_hz", "T": "temperature_c"}


def normalize_unit(unit):
    """Return (OCC unit, scale) for a printed unit, or None when it cannot be imported."""
    if not isinstance(unit, str):
        return None
    return _UNITS.get(unit.translate(_CANON))


def row_key(row):
    """Identity of a spec row. Unit is not part of it: µA and nA can share a key."""
    return (row.get("name"), row.get("symbol"), row.get("kind"), row.get("conditions"))


def _base_name(symbol):
    text = symbol.lower() if isinstance(symbol, str) else ""
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if not text or not ("a" <= text[0] <= "z"):
        text = ("p_" + text) if text else "p"
    if not _NAME.fullmatch(text):
        return "p"
    return text


def assign_names(rows):
    """Parameter names from symbols, in row order. Collisions gain _2, _3, ..."""
    used = set()
    names = []
    for row in rows:
        base = _base_name(row.get("symbol"))
        name = base
        number = 2
        while name in used:
            name = f"{base}_{number}"
            number += 1
        used.add(name)
        names.append(name)
    return names


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def select_rows(rows, kinds):
    """Split rows into importable limits and skips.

    A usable row has an import kind the caller asked for, a known unit, and
    both min and max with min < max after scaling into the OCC unit.
    """
    requested = set(kinds)
    usable = []
    skipped = []
    for row in rows:
        kind = row.get("kind")
        if kind in SKIP_KINDS:
            skipped.append({"row": row, "reason": "skipped kind"})
            continue
        if kind not in IMPORT_KINDS:
            skipped.append({"row": row, "reason": "unknown kind"})
            continue
        if kind not in requested:
            skipped.append({"row": row, "reason": "kind not requested"})
            continue
        norm = normalize_unit(row.get("unit"))
        if norm is None:
            skipped.append({"row": row, "reason": "unknown unit"})
            continue
        occ, scale = norm
        low, high = row.get("min"), row.get("max")
        if not _number(low) or not _number(high):
            skipped.append({"row": row, "reason": "one-sided limits"})
            continue
        scaled_low, scaled_high = low * scale, high * scale
        if not scaled_low < scaled_high:
            skipped.append({"row": row, "reason": "min not less than max"})
            continue
        usable.append({"row": row, "unit": occ, "scale": scale, "min": scaled_low, "max": scaled_high})
    return usable, skipped


def _clause(clause):
    matched = _ASSIGN.fullmatch(clause.strip())
    if not matched:
        return None
    lhs, rhs = matched.group(1), matched.group(2).strip()
    if lhs == "VDS" and rhs == "VGS":
        return ("vds_eq_vgs", True)
    if lhs not in _COND_UNIT:
        return None
    value = _VALUE.fullmatch(rhs)
    if not value:
        return None
    norm = normalize_unit(value.group(2))
    if norm is None or norm[0] != _COND_UNIT[lhs]:
        return None
    return (_COND_KEY[lhs], float(value.group(1)) * norm[1])


def parse_conditions(text):
    """Pull unambiguous standard condition keys out of free text.

    Only temperature_c, vgs_v, vds_v, id_a, frequency_hz, and vds_eq_vgs.
    A key that appears as two different values is omitted.
    """
    if not isinstance(text, str) or not text.strip():
        return {}
    found = {}
    blocked = set()
    for clause in text.split(","):
        parsed = _clause(clause)
        if parsed is None:
            continue
        key, value = parsed
        if key in blocked:
            continue
        if key in found and found[key] != value:
            blocked.add(key)
            del found[key]
            continue
        found.setdefault(key, value)
    return found


class InputError(ValueError):
    """The page or options are not enough to build a card."""


class Options:
    """Inputs for one import.

    date is YYYY-MM-DD. category and manufacturer, when set, replace the page
    values. category is an OCC category, not an Adom label. warnings collects
    messages such as an unmapped category.
    """

    def __init__(self, date, category=None, manufacturer=None, kinds=None):
        self.date = date
        self.category = category
        self.manufacturer = manufacturer
        self.kinds = IMPORT_KINDS if kinds is None else kinds
        self.warnings = []


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID_PART = re.compile(r"[A-Za-z0-9._-]+")
_CATEGORY = {
    "resistor": "resistor",
    "resistors": "resistor",
    "capacitor": "capacitor",
    "capacitors": "capacitor",
    "inductor": "inductor",
    "inductors": "inductor",
    "diode": "diode",
    "diodes": "diode",
}
_COND_ORDER = ("temperature_c", "frequency_hz", "vgs_v", "vds_v", "vds_eq_vgs", "id_a")
_EPISTEMIC = frozenset({"temperature_coefficient", "voltage_coefficient"})


def _slug(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        raise InputError(f"manufacturer {text!r} has no characters usable in a card id")
    return slug


def _manufacturer(page, opts):
    override = opts.manufacturer
    if isinstance(override, str) and override.strip():
        return override.strip()
    raw = (page.get("component") or {}).get("manufacturer")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    raise InputError("component.manufacturer is empty and opts.manufacturer is not set")


def _category(raw, opts):
    if isinstance(opts.category, str) and opts.category.strip():
        return opts.category.strip(), None
    label = raw.strip() if isinstance(raw, str) else ""
    mapped = _CATEGORY.get(label.lower())
    if mapped:
        return mapped, None
    shown = label or "(missing)"
    return "other", f"Category {shown!r} is not an OCC category; imported as other."


def _license(page):
    if "license" not in page or not isinstance(page.get("license"), str) or not page["license"].strip():
        raise InputError("page has no license")
    return page["license"].strip()


def _mpn_token(mpn):
    token = mpn.lower()
    if _ID_PART.fullmatch(token):
        return token
    token = re.sub(r"[^a-z0-9._-]+", "-", token).strip("-")
    if not token:
        raise InputError(f"mpn {mpn!r} has no characters usable in a card id")
    return token


def _page_evidence(usable):
    pages = []
    for item in usable:
        number = item["row"].get("source_page")
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            continue
        if isinstance(number, float) and not number.is_integer():
            continue
        pages.append(int(number))
    pages = sorted(set(pages))
    if not pages:
        return "datasheet"
    return ", ".join(f"p.{number}" for number in pages)


def _basis(row):
    conditions = row.get("conditions") or ""
    page_no = row.get("source_page")
    page_bit = page_no if page_no is not None else "?"
    return (
        f"Adom row '{row.get('name', '')}' ({row.get('symbol', '')}, {row.get('kind', '')}), "
        f"conditions '{conditions}', datasheet p.{page_bit}. "
        "Shape not published; uniform over the published limits."
    )


def _nominal(row, low, high):
    # A percent is a spread around the part's value, so the card nominal is 0
    # in the dimensionless unit. Other rows use the midpoint of the limits.
    if row.get("unit") == "%":
        return 0
    return (low + high) / 2


def _conditions(text):
    found = parse_conditions(text)
    return {key: found[key] for key in _COND_ORDER if key in found}


def _parameter(name, item):
    row = item["row"]
    low, high = item["min"], item["max"]
    dist_kind = "epistemic" if row.get("kind") in _EPISTEMIC else "population"
    parameter = {
        "name": name,
        "unit": item["unit"],
        "nominal": _nominal(row, low, high),
        "distributions": [{
            "scope": "total",
            "type": "uniform",
            "applies_to": "value",
            "kind": dist_kind,
            "params": {"min": low, "max": high},
            "basis": _basis(row),
            "confidence": "low",
        }],
    }
    conditions = _conditions(row.get("conditions"))
    if conditions:
        parameter["conditions"] = conditions
    parameter["limits"] = {"min": low, "max": high, "source_ref": "wiki1"}
    parameter["source_refs"] = ["wiki1"]
    return parameter


def build_card(page, opts):
    """Build an OCC v0.2 card dict from one Adom page.json object."""
    if not isinstance(page, dict):
        raise InputError("page must be a JSON object")
    if not isinstance(getattr(opts, "date", None), str) or not _DATE.fullmatch(opts.date):
        raise InputError("opts.date must be YYYY-MM-DD")
    component = page.get("component") if isinstance(page.get("component"), dict) else {}
    manufacturer = _manufacturer(page, opts)
    license_id = _license(page)
    mpn = component.get("mpn")
    if not isinstance(mpn, str) or not mpn.strip():
        raise InputError("component.mpn is empty")
    category, warning = _category(component.get("category"), opts)
    if warning:
        opts.warnings.append(warning)
    rows = characteristic_rows(page)
    if not rows:
        raise InputError("no rows")
    usable, _skipped = select_rows(rows, opts.kinds)
    if not usable:
        raise InputError("no usable rows")
    names = assign_names([item["row"] for item in usable])
    owner = page.get("owner") if isinstance(page.get("owner"), str) else ""
    slug = page.get("slug") if isinstance(page.get("slug"), str) else ""
    version = page.get("version") if isinstance(page.get("version"), str) else ""
    updated = page.get("updated_at") if isinstance(page.get("updated_at"), str) else ""
    notes = f"Adom page version {version}, updated_at {updated}."
    if warning:
        notes = f"{notes} {warning}"
    part = {"manufacturer": manufacturer, "mpn": mpn.strip(), "category": category}
    title = page.get("title")
    if isinstance(title, str) and title:
        part["description"] = title
    package = component.get("package")
    if isinstance(package, str) and package:
        part["package"] = package
    ds1 = {"ref": "ds1", "kind": "datasheet"}
    datasheet = component.get("datasheet")
    if isinstance(datasheet, str) and datasheet:
        ds1["uri"] = datasheet
    ds1["evidence"] = _page_evidence(usable)
    ds1["confidence"] = "high"
    # The wiki URI is recorded as the derived source. The page is not fetched.
    wiki1 = {
        "ref": "wiki1",
        "kind": "derived",
        "derived_from": ["ds1"],
        "uri": f"https://wiki.adom.inc/{owner}/{slug}",
        "evidence": "metadata.characteristics.rows",
        "confidence": "high",
    }
    return {
        "card_version": "0.2",
        "id": f"occ:{category}/{_slug(manufacturer)}-{_mpn_token(mpn)}@0.1.0",
        "part": part,
        "model_files": [],
        "parameters": [_parameter(name, item) for name, item in zip(names, usable)],
        "derivation": {
            "kind": "data",
            "method": "Uniform distribution over each published min and max. The datasheet does not state the shape.",
        },
        "validation": {"maturity": "0.1", "tested_simulators": [], "comparisons": []},
        "sources": [ds1, wiki1],
        "provenance": {
            "author": (
                "Jacob Warren and GrizzlyRay LLC, imported from the Adom wiki page "
                f"{owner}/{slug} (Adom, wiki.adom.inc)"
            ),
            "created": opts.date,
            "previous_version": None,
            "signatures": [],
        },
        "license": license_id,
        "notes": notes,
    }


def dump_card(card):
    """YAML for a card. Dict insertion order is kept, so one card always dumps the same bytes."""
    text = yaml.safe_dump(card, sort_keys=False, allow_unicode=True, default_flow_style=False, width=4096)
    if not text.endswith("\n"):
        text += "\n"
    return text


REPO = Path(__file__).resolve().parent.parent
_OUT = REPO / "out"
_SCHEMA = REPO / "schema" / "card.schema.json"
_SLUG = re.compile(r"[A-Za-z0-9._-]+")
_PAGE_URL = "https://wiki.adom.inc/blob/component/{slug}/page.json"
_USER_AGENT = "opencomponentcards adom_import (+https://github.com/GrizzlyRay/opencomponentcards)"


def characteristic_rows(page):
    """The characteristics rows, or an empty list when the page has none."""
    if not isinstance(page, dict):
        return []
    meta = page.get("metadata")
    if not isinstance(meta, dict):
        return []
    chars = meta.get("characteristics")
    if not isinstance(chars, dict):
        return []
    rows = chars.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def parse_slug(target):
    """Slug from a bare slug, owner/slug, a wiki page URL, or a /blob/... URL."""
    text = (target or "").strip()
    if not text:
        raise InputError("missing slug")
    if "://" not in text and not text.startswith("/"):
        if "/" not in text:
            if not _SLUG.fullmatch(text):
                raise InputError(f"not a slug: {target!r}")
            return text
        bits = text.split("/")
        if len(bits) == 2 and _SLUG.fullmatch(bits[0]) and _SLUG.fullmatch(bits[1]):
            return bits[1]
        raise InputError(f"not a slug: {target!r}")
    path = urllib.parse.urlsplit(text).path if "://" in text else text
    path = path.rstrip("/") or "/"
    patterns = (
        r"/blob/component/(?P<slug>[A-Za-z0-9._-]+)(?:/page\.json)?",
        r"/blob/(?P<owner>[A-Za-z0-9._-]+)/(?P<slug>[A-Za-z0-9._-]+)(?:/page\.json)?",
        r"/(?P<owner>[A-Za-z0-9._-]+)/(?P<slug>[A-Za-z0-9._-]+)",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, path)
        if match:
            return match.group("slug")
    raise InputError(f"could not read a slug from {target!r}")


def parse_kinds(text):
    """Import kinds the caller asked to keep. Skipped kinds cannot be added back."""
    if text is None:
        return IMPORT_KINDS
    names = [part.strip() for part in text.split(",") if part.strip()]
    if not names:
        raise InputError("--kinds is empty")
    skipped = [name for name in names if name in SKIP_KINDS]
    if skipped:
        raise InputError("--kinds cannot include " + ", ".join(skipped) + "; those kinds are never imported")
    unknown = [name for name in names if name not in IMPORT_KINDS]
    if unknown:
        raise InputError("--kinds has unknown kind " + ", ".join(unknown))
    return frozenset(names)


def output_path(slug, given):
    """Card path. The default is out/adom/<slug>.yaml. Anything outside out/ is refused."""
    root = _OUT.resolve()
    if given is None:
        safe = slug if _SLUG.fullmatch(slug) else "page"
        path = root / "adom" / f"{safe}.yaml"
    else:
        raw = Path(given)
        path = raw.resolve() if raw.is_absolute() else (Path.cwd() / raw).resolve()
    if path == root or root not in path.parents:
        raise InputError(f"--out {given or path} is outside out/")
    return path


def _json_hint(body):
    """The wiki's hint string from a 404 body, or the body itself when it has none."""
    text = body.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text or "not found"
    if isinstance(data, dict):
        hint = data.get("hint")
        if isinstance(hint, str) and hint.strip():
            return hint.strip()
        if hint is not None and not isinstance(hint, str):
            return json.dumps(hint, ensure_ascii=False)
    return text or "not found"


def fetch_page(slug):
    """GET the component page.json. Redirects are followed. A 404 prints the wiki hint."""
    url = _PAGE_URL.format(slug=urllib.parse.quote(slug, safe=""))
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        if exc.code == 404:
            raise InputError(_json_hint(payload)) from exc
        raise InputError(f"HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        raise InputError(f"could not fetch {url}: {exc.reason}") from exc
    try:
        page = json.loads(body)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON from {url}") from exc
    if not isinstance(page, dict):
        raise InputError(f"page from {url} is not a JSON object")
    return page


def load_page_file(path):
    file = Path(path)
    if not file.is_file():
        raise InputError(f"not found: {path}")
    try:
        page = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON in {path}") from exc
    if not isinstance(page, dict):
        raise InputError(f"{path} is not a JSON object")
    return page


def report_lines(rows, kinds):
    """One line per row: the parameter name, or skipped plus the reason."""
    usable, skipped = select_rows(rows, kinds)
    names = assign_names([item["row"] for item in usable])
    by_row = {id(item["row"]): name for item, name in zip(usable, names)}
    reason = {id(item["row"]): item["reason"] for item in skipped}
    lines = []
    for row in rows:
        if id(row) in by_row:
            lines.append(by_row[id(row)])
            continue
        symbol = row.get("symbol") or row.get("name") or "row"
        lines.append(f"skipped {symbol}: {reason.get(id(row), 'skipped')}")
    return lines


def validate_written(path):
    """Schema plus tools/validate.py semantic checks. Returns error strings."""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    validator = vd.Draft202012Validator(schema)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    errors = [f"unquoted YAML date at {where} (quote it, e.g. \"2026-10-13\")" for where in vd.find_dates(raw)]
    if not errors:
        errors = list(vd.check_v01(raw))
    if not errors and isinstance(raw, dict):
        errors += [
            f"schema {'/'.join(map(str, err.absolute_path)) or '$'}: {err.message[:160]}"
            for err in validator.iter_errors(raw)
        ]
    if not errors and isinstance(raw, dict):
        more, _warnings = vd.semantic(raw)
        errors.extend(more)
    return errors


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError(message)


def main(argv=None):
    """Import one page. Exit 0 valid, 1 written but invalid, 2 input problem."""
    parser = _Parser(prog="adom_import.py", description="Import an Adom wiki component page as an OCC card.")
    parser.add_argument("target", help="slug, https://wiki.adom.inc/<owner>/<slug>, or a /blob/... URL")
    parser.add_argument("--from-file", help="read page.json from PATH instead of the network")
    parser.add_argument("--out", help="card path inside out/ (default out/adom/<slug>.yaml)")
    parser.add_argument("--kinds", help="comma-separated import kinds to keep; skipped kinds are an error")
    parser.add_argument("--category", help="OCC category, overriding the page")
    parser.add_argument("--manufacturer", help="manufacturer, overriding the page")
    parser.add_argument("--date", help="card created date YYYY-MM-DD (default today)")
    parser.add_argument("--report", action="store_true", help="print each row's parameter name or skip reason")
    try:
        return _run(parser.parse_args(argv))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run(args):
    slug = parse_slug(args.target)
    kinds = parse_kinds(args.kinds)
    dest = output_path(slug, args.out)
    page = load_page_file(args.from_file) if args.from_file else fetch_page(slug)
    when = args.date or date.today().isoformat()
    opts = Options(date=when, category=args.category, manufacturer=args.manufacturer, kinds=kinds)
    try:
        card = build_card(page, opts)
    except InputError:
        raise
    for warning in opts.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.report:
        for line in report_lines(characteristic_rows(page), kinds):
            print(line)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(dump_card(card), encoding="utf-8")
    errors = validate_written(dest)
    if errors:
        for err in errors:
            print(f"ERROR {err}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
