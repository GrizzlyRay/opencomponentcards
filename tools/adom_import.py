#!/usr/bin/env python3
"""Map Adom wiki characteristic rows into OpenComponentCards values (Apache-2.0).

Pure functions only. No network and no command-line interface.
Printed units become the closed OCC unit list, with a scale into that unit.
"""
import re

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
