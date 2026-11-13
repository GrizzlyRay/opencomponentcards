#!/usr/bin/env python3
"""Map an Adom wiki page.json into an OpenComponentCards v0.2 card (Apache-2.0).

No network and no command-line interface. Datasheet files are not downloaded.
Printed units become the closed OCC unit list, with a scale into that unit.
"""
import re

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
    rows = ((page.get("metadata") or {}).get("characteristics") or {}).get("rows") or []
    if not isinstance(rows, list):
        rows = []
    usable, _skipped = select_rows(rows, opts.kinds)
    if not usable:
        raise InputError("no importable characteristic rows")
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
