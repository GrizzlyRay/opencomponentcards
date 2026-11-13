#!/usr/bin/env python3
"""Match a board BOM to component cards (Apache-2.0).

read_bom expands refdes ranges. resolve prefers a local card, then a caller
supplied importer, then a tolerance fallback written under out/. It does not
run a simulator and it does not fetch. The caller passes the importer, which
is what keeps a test from touching the network. match_netlist compares those
refdes to element names in a KiCad SPICE netlist.
"""
import csv
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

_OUT = Path(__file__).resolve().parent.parent / "out"
_TOKEN = re.compile(r"^[A-Za-z]+\d+[A-Za-z0-9]*$")
_RANGE = re.compile(r"^([A-Za-z]+)(\d+)\s*-\s*([A-Za-z]+)(\d+)$")
_VALUE = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([pnumkKMGTµμ])?\s*([A-Za-zΩΩ]*)$")
_TOLERANCE = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*%$")
_REQUIRED = ("refdes", "mpn", "manufacturer", "value")
_OPTIONAL = ("tolerance", "adom_slug")
_PREFIX = {
    "p": Decimal("1e-12"),
    "n": Decimal("1e-9"),
    "u": Decimal("1e-6"),
    "µ": Decimal("1e-6"),
    "μ": Decimal("1e-6"),
    "m": Decimal("1e-3"),
    "k": Decimal("1000"),
    "K": Decimal("1000"),
    "M": Decimal("1000000"),
    "G": Decimal("1000000000"),
    "T": Decimal("1000000000000"),
}
# Leading refdes letter, then category, parameter name, and the card unit.
_PASSIVE = {
    "R": ("resistor", "resistance", "Ohm"),
    "C": ("capacitor", "capacitance", "F"),
    "L": ("inductor", "inductance", "H"),
}
_SUFFIX_UNIT = {
    "ohm": "Ohm",
    "ohms": "Ohm",
    "ω": "Ohm",
    "Ω": "Ohm",
    "r": "Ohm",
    "f": "F",
    "h": "H",
}
_FALLBACK_NOTE = "fallback from BOM tolerance, not from a datasheet"
_BOARD_PREFIXES = set("RCLDQM")


class InputError(ValueError):
    """The BOM, a card directory, or a fallback value cannot be used."""


def read_bom(path):
    """Rows from a BOM CSV. Ranges in one cell become one row per refdes.

    refdes are unique ignoring case. A bad cell or a duplicate names its line.
    """
    file = Path(path)
    if not file.is_file():
        raise InputError(f"not found: {path}")
    with file.open(newline="", encoding="utf-8-sig") as handle:
        raw_rows = list(csv.reader(handle))
    if not raw_rows or not any(cell.strip() for cell in raw_rows[0]):
        raise InputError("line 1: BOM has no header")
    header = [cell.strip().lower() for cell in raw_rows[0]]
    if len(set(header)) != len(header):
        raise InputError("line 1: duplicate column")
    for name in _REQUIRED:
        if name not in header:
            raise InputError(f"line 1: missing column {name}")
    index = {name: pos for pos, name in enumerate(header)}
    seen = {}
    rows = []
    for line, cells in enumerate(raw_rows[1:], start=2):
        if not any(cell.strip() for cell in cells):
            continue
        if len(cells) > len(header):
            raise InputError(f"line {line}: too many columns")

        def cell(name, cells=cells):
            pos = index.get(name)
            if pos is None or pos >= len(cells):
                return ""
            return cells[pos].strip()

        for refdes in _expand_refdes(cell("refdes"), line):
            key = refdes.casefold()
            if key in seen:
                raise InputError(f"line {line}: duplicate refdes {refdes} (also on line {seen[key]})")
            seen[key] = line
            rows.append({
                "refdes": refdes,
                "mpn": cell("mpn"),
                "manufacturer": cell("manufacturer"),
                "value": cell("value"),
                "tolerance": cell("tolerance"),
                "adom_slug": cell("adom_slug"),
                "line": line,
            })
    return rows


def resolve(bom_rows, cards_dir, out_dir, importer=None):
    """Find a card for each refdes. Local, then importer, then tolerance fallback.

    out_dir is the board directory inside out/, such as out/board/<name>.
    Fallback cards are written to out_dir/cards/. The importer, when given,
    is called as importer(slug, out_dir) and must return the draft path.
    """
    given = Path(out_dir)
    _inside_out(given)
    index = _card_index(cards_dir)
    return [_resolve_row(row, index, given, importer) for row in bom_rows]


def match_netlist(netlist_text, refdes_list):
    """BOM refdes missing from the netlist, and board R/C/L/D/Q/M missing from the BOM.

    Names inside a .subckt body are not board parts. Matching ignores case.
    """
    instances = _instances(netlist_text)
    present = {name.casefold() for name in instances}
    bom_keys = {ref.casefold() for ref in refdes_list}
    net_missing = []
    seen = set()
    for name in instances:
        key = name.casefold()
        if key in seen or name[:1].upper() not in _BOARD_PREFIXES:
            continue
        seen.add(key)
        if key not in bom_keys:
            net_missing.append(name)
    return {
        "bom_not_in_netlist": [ref for ref in refdes_list if ref.casefold() not in present],
        "netlist_not_in_bom": net_missing,
    }


def _expand_refdes(cell, line):
    if not cell.strip():
        raise InputError(f"line {line}: refdes is empty")
    pieces = [part.strip() for part in cell.split(",")]
    if any(not part for part in pieces):
        raise InputError(f"line {line}: bad refdes {cell!r}")
    names = []
    for part in pieces:
        if "-" not in part:
            if not _TOKEN.fullmatch(part):
                raise InputError(f"line {line}: bad refdes {part!r}")
            names.append(part)
            continue
        match = _RANGE.fullmatch(part)
        if not match:
            raise InputError(f"line {line}: bad range {part!r}")
        left, start, right, end = match.groups()
        if left.casefold() != right.casefold():
            raise InputError(f"line {line}: bad range {part!r}")
        start_n, end_n = int(start), int(end)
        if end_n < start_n or end_n - start_n > 500:
            raise InputError(f"line {line}: bad range {part!r}")
        for number in range(start_n, end_n + 1):
            names.append(f"{left}{number}")
    return names


def _norm(text):
    return re.sub(r"[\s-]+", "", text).casefold()


def _inside_out(path):
    root = _OUT.resolve()
    resolved = Path(path).resolve()
    if resolved == root or root not in resolved.parents:
        raise InputError(f"{path} is outside out/")
    return resolved


def _card_index(cards_dir):
    root = Path(cards_dir)
    if not root.is_dir():
        raise InputError(f"not found: {cards_dir}")
    found = []
    paths = sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml"))
    for path in paths:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("part"), dict):
            continue
        mpn = raw["part"].get("mpn")
        if not isinstance(mpn, str) or not _norm(mpn):
            continue
        manufacturer = raw["part"].get("manufacturer")
        if not isinstance(manufacturer, str):
            manufacturer = ""
        found.append({"path": path, "mpn": _norm(mpn), "manufacturer": _norm(manufacturer)})
    return found


def _local_card(row, index):
    mpn = _norm(row.get("mpn") or "")
    if not mpn:
        return None
    hits = [item for item in index if item["mpn"] == mpn]
    manufacturer = (row.get("manufacturer") or "").strip()
    if manufacturer:
        want = _norm(manufacturer)
        hits = [item for item in hits if item["manufacturer"] == want]
    if not hits:
        return None
    if len(hits) > 1:
        listed = ", ".join(str(item["path"]) for item in hits)
        raise InputError(f"line {row.get('line', '?')}: more than one card matches mpn {row.get('mpn')}: {listed}")
    return hits[0]["path"]


def _resolve_row(row, index, out_dir, importer):
    refdes = row["refdes"]
    local = _local_card(row, index)
    if local is not None:
        return {"refdes": refdes, "found": "local", "path": local, "reason": f"mpn matches {local.name}"}
    slug = (row.get("adom_slug") or "").strip()
    if slug:
        if importer is None:
            return {
                "refdes": refdes,
                "found": "unresolved",
                "path": None,
                "reason": "adom_slug set but no importer was given",
            }
        drafted = importer(slug, out_dir)
        path = Path(drafted) if drafted is not None else None
        if path is None or not path.is_file():
            raise InputError(f"line {row.get('line', '?')}: importer did not write a card for {slug}")
        _inside_out(path)
        return {"refdes": refdes, "found": "adom", "path": path, "reason": f"adom slug {slug}"}
    value = (row.get("value") or "").strip()
    tolerance = (row.get("tolerance") or "").strip()
    passive = _passive(refdes)
    if value and tolerance and passive is not None:
        path = _write_fallback(row, out_dir, passive)
        return {"refdes": refdes, "found": "fallback", "path": path, "reason": _FALLBACK_NOTE}
    if value and tolerance:
        reason = f"no card, and {refdes} is not a resistor, capacitor, or inductor"
    elif not tolerance and not value:
        reason = "no card, and value and tolerance are missing"
    elif not tolerance:
        reason = "no card, and tolerance is missing"
    else:
        reason = "no card, and value is missing"
    return {"refdes": refdes, "found": "unresolved", "path": None, "reason": reason}


def _passive(refdes):
    letters = re.match(r"[A-Za-z]+", refdes)
    if not letters:
        return None
    return _PASSIVE.get(letters.group(0)[:1].upper())


def _parse_value(text, unit, line):
    match = _VALUE.fullmatch(text.strip())
    if not match:
        raise InputError(f"line {line}: bad value {text!r}")
    number, prefix, suffix = match.group(1), match.group(2), match.group(3)
    scale = _PREFIX[prefix] if prefix else Decimal(1)
    magnitude = Decimal(number) * scale
    if suffix:
        suffix_unit = _SUFFIX_UNIT.get(suffix.casefold())
        if suffix_unit is None:
            raise InputError(f"line {line}: bad value {text!r}")
        if suffix_unit != unit:
            raise InputError(f"line {line}: value unit {suffix_unit} does not match {unit}")
    if magnitude <= 0:
        raise InputError(f"line {line}: bad value {text!r}")
    return magnitude


def _parse_tolerance(text, line):
    match = _TOLERANCE.fullmatch(text.strip())
    if not match:
        raise InputError(f"line {line}: bad tolerance {text!r}")
    percent = Decimal(match.group(1))
    if percent <= 0:
        raise InputError(f"line {line}: bad tolerance {text!r}")
    return percent


def _slug(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "part"


def _write_fallback(row, out_dir, passive):
    category, parameter, unit = passive
    line = row.get("line", "?")
    magnitude = _parse_value(row["value"], unit, line)
    percent = _parse_tolerance(row["tolerance"], line)
    low = magnitude * (Decimal(100) - percent) / Decimal(100)
    high = magnitude * (Decimal(100) + percent) / Decimal(100)
    if low >= high:
        raise InputError(f"line {line}: bad tolerance {row['tolerance']!r}")
    nominal = float(magnitude)
    minimum = float(low)
    maximum = float(high)
    manufacturer = (row.get("manufacturer") or "").strip() or "unknown"
    mpn = (row.get("mpn") or "").strip() or row["refdes"]
    card = {
        "card_version": "0.2",
        "id": f"occ:{category}/{_slug(manufacturer)}-{_slug(row['refdes'])}@0.1.0",
        "part": {
            "manufacturer": manufacturer,
            "mpn": mpn,
            "category": category,
            "description": f"{row['refdes']} {row['value']} +/- {row['tolerance']} from a BOM",
        },
        "model_files": [],
        "parameters": [{
            "name": parameter,
            "unit": unit,
            "nominal": nominal,
            "distributions": [{
                "scope": "total",
                "type": "uniform",
                "applies_to": "value",
                "kind": "population",
                "params": {"min": minimum, "max": maximum},
                "basis": _FALLBACK_NOTE,
                "confidence": "low",
            }],
            "limits": {"min": minimum, "max": maximum, "source_ref": "bom1"},
            "source_refs": ["bom1"],
        }],
        "derivation": {
            "kind": "data",
            "method": "Uniform over the BOM value plus or minus the BOM tolerance.",
        },
        "validation": {"maturity": "0.1", "tested_simulators": [], "comparisons": []},
        "sources": [{
            "ref": "bom1",
            "kind": "expert_estimate",
            "evidence": "BOM value and tolerance",
            "confidence": "low",
        }],
        "provenance": {
            "author": "Jacob Warren and GrizzlyRay LLC",
            "created": date.today().isoformat(),
            "previous_version": None,
            "signatures": [],
        },
        "license": "CC-BY-4.0",
        "notes": _FALLBACK_NOTE,
    }
    folder = out_dir / "cards"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{row['refdes']}.yaml"
    text = yaml.safe_dump(card, sort_keys=False, allow_unicode=True, default_flow_style=False, width=4096)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return path


def _instances(text):
    names = []
    depth = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("+") or line.startswith(";"):
            continue
        token = line.split()[0]
        low = token.lower()
        if low == ".subckt":
            depth += 1
            continue
        if low == ".ends":
            if depth:
                depth -= 1
            continue
        if token.startswith("."):
            continue
        if depth:
            continue
        names.append(token)
    return names
