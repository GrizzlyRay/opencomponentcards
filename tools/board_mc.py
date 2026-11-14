#!/usr/bin/env python3
"""Match a board BOM to component cards and run a Monte Carlo (Apache-2.0).

read_bom expands refdes ranges. resolve prefers a local card, then a caller
supplied importer, then a tolerance fallback written under out/. The caller
passes the importer, which is what keeps a test from touching the network.
match_netlist compares those refdes to element names in a KiCad SPICE netlist.
bind_netlist rewrites a matched resistor, capacitor, or inductor value to
{p_<refdes>_<param>} from the card's primary value parameter.

The command line turns adom import and fallback cards off unless the matching
flag is set. It then samples and runs ngspice through spice_export. Decks
hold plain numbers from a seeded Python RNG. ngspice is started with an
argument list.
"""
import argparse
import csv
import re
import shutil
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import spice_export as sx
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
_PRIMARY_NAMES = ("resistance", "capacitance", "inductance")
_ADOM_DRAFT = "Adom draft, not a measured card"
_TIMEOUT = 60


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


def resolve(bom_rows, cards_dir, out_dir, importer=None, *, allow_adom=True, allow_fallback=True):
    """Find a card for each refdes. Local, then importer, then tolerance fallback.

    out_dir is the board directory inside out/, such as out/board/<name>.
    Fallback cards are written to out_dir/cards/. The importer, when given,
    is called as importer(slug, out_dir) and must return the draft path.
    allow_adom and allow_fallback default to on so a direct caller keeps the
    previous order. The command line turns both off unless its flags are set.
    """
    given = Path(out_dir)
    _inside_out(given)
    index = _card_index(cards_dir)
    return [
        _resolve_row(row, index, given, importer, allow_adom, allow_fallback)
        for row in bom_rows
    ]


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


def bind_netlist(netlist_text, resolved):
    """Rewrite matched R, C, and L values to {p_<refdes>_<param>}.

    The parameter is the card's only primary value parameter: resistance,
    capacitance, or inductance. The card is read. A refdes letter does not
    choose the parameter. Zero or several of those names leave the element
    as written. .subckt bodies, models, and unmatched elements stay as written.

    Returns netlist, bound, and left_alone. A bound item has refdes, param,
    placeholder, path, and reason. A left_alone item has refdes and reason.
    """
    if not isinstance(netlist_text, str):
        raise InputError("netlist text must be a string")
    by_key = {}
    order = []
    for item in resolved:
        refdes = item.get("refdes") if isinstance(item, dict) else None
        if not isinstance(refdes, str) or not refdes:
            raise InputError("resolved item is missing refdes")
        key = refdes.casefold()
        if key in by_key:
            raise InputError(f"duplicate refdes {refdes}")
        by_key[key] = item
        order.append(key)

    bound = []
    left = []
    seen = set()
    out = []
    subckt = 0
    control = 0
    for raw in netlist_text.splitlines(keepends=True):
        body, ending = _split_ending(raw)
        stripped = body.strip()
        word = stripped.split(None, 1)[0] if stripped else ""
        low = word.lower()
        copy = body
        if subckt == 0 and control == 0 and stripped and not _skipped_line(stripped) and not word.startswith("."):
            spans = _token_spans(body)
            token = body[spans[0][0]:spans[0][1]] if spans else ""
            key = token.casefold()
            if key in by_key:
                seen.add(key)
                copy, record, did_bind = _bind_element(body, spans, by_key[key])
                if did_bind:
                    bound.append(record)
                else:
                    left.append(record)
            elif token[:1].upper() in _BOARD_PREFIXES:
                left.append({"refdes": token, "reason": "not in the resolved list"})
        if low == ".subckt":
            subckt += 1
        elif low == ".ends" and subckt:
            subckt -= 1
        elif low == ".control":
            control += 1
        elif low == ".endc" and control:
            control -= 1
        out.append(copy + ending)
    for key in order:
        if key in seen:
            continue
        item = by_key[key]
        if item.get("path"):
            reason = "not found as a top-level element"
        else:
            reason = item.get("reason") or "not found as a top-level element"
        left.append({"refdes": item["refdes"], "reason": reason})
    return {"netlist": "".join(out), "bound": bound, "left_alone": left}


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


def _resolve_row(row, index, out_dir, importer, allow_adom, allow_fallback):
    refdes = row["refdes"]
    local = _local_card(row, index)
    if local is not None:
        return {"refdes": refdes, "found": "local", "path": local, "reason": f"mpn matches {local.name}"}
    slug = (row.get("adom_slug") or "").strip()
    if slug:
        if not allow_adom:
            return {
                "refdes": refdes,
                "found": "unresolved",
                "path": None,
                "reason": "adom import is off; pass --allow-adom",
            }
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
        if not allow_fallback:
            return {
                "refdes": refdes,
                "found": "unresolved",
                "path": None,
                "reason": "fallback is off; pass --allow-fallback",
            }
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
    """Top-level element names. .subckt bodies and .control blocks are not elements.

    A control-mode meas command starts with M. Counting it would report a
    MOSFET that is not on the board.
    """
    names = []
    subckt = 0
    control = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("+") or line.startswith(";"):
            continue
        token = line.split()[0]
        low = token.lower()
        if low == ".subckt":
            subckt += 1
            continue
        if low == ".ends":
            if subckt:
                subckt -= 1
            continue
        if low == ".control":
            control += 1
            continue
        if low == ".endc":
            if control:
                control -= 1
            continue
        if token.startswith("."):
            continue
        if subckt or control:
            continue
        names.append(token)
    return names


def _skipped_line(stripped):
    return stripped.startswith("*") or stripped.startswith("+") or stripped.startswith(";")


def _split_ending(raw):
    if raw.endswith("\r\n"):
        return raw[:-2], "\r\n"
    if raw.endswith("\n") or raw.endswith("\r"):
        return raw[:-1], raw[-1]
    return raw, ""


def _token_spans(line):
    spans = []
    index = 0
    size = len(line)
    while index < size:
        while index < size and line[index].isspace():
            index += 1
        if index >= size:
            break
        start = index
        while index < size and not line[index].isspace():
            index += 1
        spans.append((start, index))
    return spans


def _bind_element(body, spans, item):
    refdes = item["refdes"]
    path = item.get("path")
    if not path:
        return body, {"refdes": refdes, "reason": item.get("reason") or "unresolved"}, False
    token = body[spans[0][0]:spans[0][1]] if spans else ""
    if token[:1].upper() not in ("R", "C", "L"):
        return body, {"refdes": refdes, "reason": "not a resistor, capacitor, or inductor line"}, False
    if len(spans) < 4:
        return body, {"refdes": refdes, "reason": "no value token on the element line"}, False
    try:
        card = sx.load_card(path)
    except sx.ExportError as exc:
        return body, {"refdes": refdes, "reason": f"no clear primary value parameter ({exc})"}, False
    primaries = [
        param.get("name")
        for param in card.get("parameters") or []
        if isinstance(param, dict) and param.get("name") in _PRIMARY_NAMES
    ]
    if len(primaries) != 1:
        listed = ", ".join(primaries) if primaries else "none"
        return body, {"refdes": refdes, "reason": f"no clear primary value parameter ({listed})"}, False
    param = primaries[0]
    try:
        placeholder = sx.param_name(refdes, param)
    except sx.ExportError as exc:
        return body, {"refdes": refdes, "reason": str(exc)}, False
    start, end = spans[3]
    rewritten = body[:start] + "{" + placeholder + "}" + body[end:]
    return rewritten, {
        "refdes": refdes,
        "param": param,
        "placeholder": placeholder,
        "path": Path(path),
        "reason": f"primary value parameter {param}",
    }, True


def _comment_unused(netlist, binds):
    """Comment-list card parameters that are not already a {p_...} placeholder.

    spice_export requires every bound name to appear in the netlist. A comment
    is enough, and it keeps the extra parameter out of the signal path.
    """
    missing = []
    for refdes, card in binds:
        for param in card.get("parameters") or []:
            name = param.get("name") if isinstance(param, dict) else None
            if not isinstance(name, str) or not name:
                continue
            token = "{" + sx.param_name(refdes, name) + "}"
            if token not in netlist:
                missing.append(token)
    if not missing:
        return netlist
    block = "* Other bound card parameters, not in the signal path:\n"
    block += "".join(f"* {token}\n" for token in missing)
    lines = netlist.splitlines(keepends=True)
    end_at = None
    depth = 0
    for index, raw in enumerate(lines):
        body, _ending = _split_ending(raw)
        stripped = body.strip()
        if not stripped or _skipped_line(stripped):
            continue
        word = stripped.split(None, 1)[0].lower()
        if word == ".subckt":
            depth += 1
        elif word == ".ends" and depth:
            depth -= 1
        elif depth == 0 and word == ".end":
            end_at = index
    if end_at is None:
        if netlist.endswith("\n") or not netlist:
            return netlist + block
        return netlist + "\n" + block
    lines.insert(end_at, block)
    return "".join(lines)


def _board_out(given, bom_path, netlist_path):
    if given is None:
        stem = Path(bom_path).stem or Path(netlist_path).stem or "board"
        path = _OUT / "board" / stem
    else:
        raw = Path(given)
        path = raw if raw.is_absolute() else Path.cwd() / raw
    return _inside_out(path)


def _adom_importer(slug, out_dir):
    """Write one draft under out_dir. Called only when --allow-adom is set."""
    import adom_import

    try:
        page = adom_import.fetch_page(slug)
        card = adom_import.build_card(page, adom_import.Options(date=date.today().isoformat()))
    except adom_import.InputError as exc:
        raise InputError(str(exc)) from exc
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(slug)).strip("-") or "page"
    path = Path(out_dir) / "adom" / f"{safe}.yaml"
    _inside_out(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(adom_import.dump_card(card), encoding="utf-8")
    return path


def _problem_text(resolved, matched):
    lines = ["unresolved:"]
    unresolved = [item for item in resolved if item.get("found") == "unresolved" or not item.get("path")]
    if not unresolved:
        lines.append("  (none)")
    else:
        for item in unresolved:
            lines.append(f"  {item['refdes']}: {item.get('reason') or 'unresolved'}")
    bom_missing = matched["bom_not_in_netlist"]
    net_missing = matched["netlist_not_in_bom"]
    lines.append("bom_not_in_netlist: " + (", ".join(bom_missing) if bom_missing else "(none)"))
    lines.append("netlist_not_in_bom: " + (", ".join(net_missing) if net_missing else "(none)"))
    return "\n".join(lines)


def _board_report(resolved, summary):
    lines = ["# Board report", "", "## Parts", ""]
    warnings = []
    for item in resolved:
        path = item.get("path")
        lines.append(f"### {item['refdes']}")
        lines.append(f"- card: {path if path else '(none)'}")
        lines.append(f"- found: {item.get('found') or 'unresolved'}")
        lines.append(f"- reason: {item.get('reason') or ''}")
        lines.append("")
        if item.get("found") == "fallback":
            warnings.append(f"- {item['refdes']}: {_FALLBACK_NOTE}")
        elif item.get("found") == "adom":
            warnings.append(f"- {item['refdes']}: {_ADOM_DRAFT}")
    lines.append("## Warnings")
    lines.append("")
    if warnings:
        lines.extend(warnings)
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(summary.rstrip())
    lines.append("")
    return "\n".join(lines)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError(message)


def main(argv=None):
    """Resolve a BOM, bind the netlist, and run ngspice. Exit 0, 1, or 2."""
    parser = _Parser(prog="board_mc.py", description="Bind a board BOM to cards and run a Monte Carlo in ngspice.")
    parser.add_argument("--bom", required=True, help="BOM csv path")
    parser.add_argument("--netlist", required=True, help="KiCad SPICE netlist path")
    parser.add_argument("--runs", required=True, type=int, help="number of runs")
    parser.add_argument("--seed", required=True, type=int, help="seed for every card's RNG")
    parser.add_argument("--jobs", type=int, default=1, help="ngspice workers (default 1)")
    parser.add_argument("--spec", action="append", default=None, help="NAME=lo:hi yield limit (repeatable)")
    parser.add_argument("--allow-adom", action="store_true", help="import adom_slug rows")
    parser.add_argument("--allow-fallback", action="store_true", help="build a tolerance card when no card matches")
    parser.add_argument("--out", help="directory inside out/ (default out/board/<bom stem>)")
    try:
        return _run(parser.parse_args(argv))
    except (InputError, sx.ExportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run(args):
    if isinstance(args.runs, bool) or args.runs < 1:
        raise InputError("--runs must be a positive int")
    if isinstance(args.jobs, bool) or args.jobs < 1:
        raise InputError("--jobs must be a positive int")
    dest = _board_out(args.out, args.bom, args.netlist)
    if dest.exists() and not dest.is_dir():
        raise InputError(f"--out {args.out or dest} is not a directory")
    bom_path = Path(args.bom)
    net_path = Path(args.netlist)
    if not bom_path.is_file():
        raise InputError(f"not found: {args.bom}")
    if not net_path.is_file():
        raise InputError(f"not found: {args.netlist}")
    try:
        netlist = net_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"cannot read {args.netlist}: {exc}") from exc
    rows = read_bom(bom_path)
    cards_dir = Path(__file__).resolve().parent.parent / "cards"
    importer = _adom_importer if args.allow_adom else None
    resolved = resolve(
        rows,
        cards_dir,
        dest,
        importer,
        allow_adom=args.allow_adom,
        allow_fallback=args.allow_fallback,
    )
    matched = match_netlist(netlist, [row["refdes"] for row in rows])
    unresolved = [item for item in resolved if item.get("found") == "unresolved" or not item.get("path")]
    if unresolved or matched["bom_not_in_netlist"] or matched["netlist_not_in_bom"]:
        print("error: unresolved parts or netlist mismatch", file=sys.stderr)
        print(_problem_text(resolved, matched), file=sys.stderr)
        return 2
    bound = bind_netlist(netlist, resolved)
    stuck = []
    bound_keys = {item["refdes"].casefold() for item in bound["bound"]}
    for item in resolved:
        if item["refdes"].casefold() in bound_keys:
            continue
        if _passive(item["refdes"]) is not None:
            stuck.append(item)
    if stuck:
        print("error: could not bind every resistor, capacitor, and inductor", file=sys.stderr)
        reasons = {item["refdes"].casefold(): item.get("reason") for item in bound["left_alone"]}
        for item in stuck:
            print(f"  {item['refdes']}: {reasons.get(item['refdes'].casefold()) or item.get('reason')}", file=sys.stderr)
        return 2
    binds = [(item["refdes"], sx.load_card(item["path"])) for item in bound["bound"]]
    text = _comment_unused(bound["netlist"], binds)
    meas = sx.meas_names(text)
    specs = sx.parse_specs(args.spec or [], meas)
    binary = shutil.which("ngspice")
    if binary is None:
        raise InputError("ngspice not found on PATH")
    plan = sx.plan_export(text, binds, args.runs, args.seed)
    sx.write_decks(dest, sx.render_ngspice(plan, text))
    rows_out = sx.simulate_ngspice(dest, plan, meas, binary, args.jobs, _TIMEOUT)
    summary = sx.summary_text(rows_out, meas, specs, "ngspice")
    try:
        (dest / "results.csv").write_bytes(sx.results_csv(rows_out, plan["order"], meas).encode("utf-8"))
        (dest / "summary.txt").write_bytes(summary.encode("utf-8"))
        (dest / "board_report.md").write_text(_board_report(resolved, summary), encoding="utf-8")
    except OSError as exc:
        raise InputError(str(exc)) from exc
    failed = sum(row["status"] != "ok" for row in rows_out)
    if failed:
        print(f"failed {failed} of {len(rows_out)} {dest}", file=sys.stderr)
        return 1
    print(f"ok {len(rows_out)} runs {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
