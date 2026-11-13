#!/usr/bin/env python3
"""Sample an OpenComponentCards v0.2 card into plain SPICE numbers (Apache-2.0).

Every random value comes from random.Random(seed). The include file holds
plain numbers in the card's unit. It does not call simulator functions such
as agauss, gauss, unif, mc, or flat.

Lot scope is drawn once per run and shared by every instance. Device scope
and total scope are drawn once per instance. Lot and device combine as in
docs/lot-device-spread.md. A distribution's truncate is part of that entry.
Published limits and final_limits apply to the combined value, by drawing
again, not by clamping a lot or device entry on its own.

Dependence curves are not evaluated. Offsets apply to the nominal value.
"""
import math
import random
import re
import statistics
from pathlib import Path

import yaml

_STD = statistics.NormalDist()
_MAX_TRIES = 10000
_SCOPES = ("total", "lot", "device")


class ExportError(ValueError):
    """The card cannot be sampled or written as a SPICE include file."""


def load_card(path):
    """Read a card and require nominal, unit, limits when present, and distributions."""
    file = Path(path)
    if not file.is_file():
        raise ExportError(f"not found: {path}")
    raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ExportError(f"{path} is not a card object")
    parameters = raw.get("parameters")
    if not isinstance(parameters, list) or not parameters:
        raise ExportError("card has no parameters")
    seen = set()
    for param in parameters:
        if not isinstance(param, dict):
            raise ExportError("a parameter is not an object")
        name = param.get("name", "?")
        if name in seen:
            raise ExportError(f"duplicate parameter name {name!r}")
        seen.add(name)
        nominal = param.get("nominal")
        if isinstance(nominal, bool) or not isinstance(nominal, (int, float)):
            raise ExportError(f"{name}: nominal must be a number")
        if not isinstance(param.get("unit"), str) or not param["unit"]:
            raise ExportError(f"{name}: unit is missing")
        dists = param.get("distributions")
        if not isinstance(dists, list) or not dists:
            raise ExportError(f"{name}: distributions are missing")
        if "limits" in param and not isinstance(param["limits"], dict):
            raise ExportError(f"{name}: limits must be an object")
    if not isinstance(raw.get("id"), str) or not raw["id"]:
        raise ExportError("card id is missing")
    return raw


def param_name(refdes, param):
    """SPICE parameter name. The p_ prefix keeps it distinct from an element name."""
    name = f"p_{_token(refdes)}_{_token(param)}"
    if name.lower() == str(refdes).lower():
        raise ExportError(f"{name} collides with element {refdes}")
    return name


def sample(card, n_runs, seed, instances):
    """Return one record per run. Each record has a value per parameter per instance."""
    if isinstance(n_runs, bool) or not isinstance(n_runs, int) or n_runs < 1:
        raise ExportError("n_runs must be a positive int")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ExportError("seed must be an int")
    refdes = _refdes(instances)
    if not isinstance(card, dict):
        raise ExportError("card must be an object")
    card_id = card.get("id")
    if not isinstance(card_id, str) or not card_id:
        raise ExportError("card id is missing")
    parameters = card.get("parameters")
    if not isinstance(parameters, list) or not parameters:
        raise ExportError("card has no parameters")
    scopes = {param["name"]: _scopes(param) for param in parameters}
    _unique_names(refdes, parameters)
    correlation = _correlation(card, [param["name"] for param in parameters])
    order = [param["name"] for param in parameters]
    units = {param["name"]: param["unit"] for param in parameters}
    rng = random.Random(seed)
    runs = []
    for number in range(1, n_runs + 1):
        runs.append({
            "card_id": card_id,
            "seed": seed,
            "run": number,
            "order": order,
            "units": units,
            "instances": _one_run(rng, parameters, scopes, refdes, correlation),
        })
    return runs


def write_params(run_values):
    """One .param include file for a single run. Instances come first, then card order."""
    order = run_values["order"]
    units = run_values["units"]
    lines = [
        "* OpenComponentCards SPICE export. Plain numbers from a seeded Python RNG.",
        f"* card id: {run_values['card_id']}",
        f"* seed: {run_values['seed']}",
        f"* run: {run_values['run']}",
        "* units: " + ", ".join(f"{name} {units[name]}" for name in order),
    ]
    for inst in run_values["instances"]:
        for name in order:
            lines.append(f".param {param_name(inst['refdes'], name)}={_format(inst['values'][name])}")
    return "\n".join(lines) + "\n"


def _token(text):
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").lower()
    if not cleaned:
        raise ExportError(f"no SPICE-safe characters in {text!r}")
    if cleaned[0].isdigit():
        cleaned = "n" + cleaned
    return cleaned


def _refdes(instances):
    if isinstance(instances, (str, bytes)) or not isinstance(instances, (list, tuple)) or not instances:
        raise ExportError("instances must be a non-empty list of refdes")
    if any(not isinstance(item, str) or not item for item in instances):
        raise ExportError("instances must be refdes strings")
    return list(instances)


def _unique_names(refdes, parameters):
    names = [param_name(ref, param["name"]) for ref in refdes for param in parameters]
    if len(names) != len(set(names)):
        raise ExportError("SPICE parameter names are not unique")


def _scopes(param):
    name = param["name"]
    found = {}
    dists = param.get("distributions")
    if not isinstance(dists, list) or not dists:
        raise ExportError(f"{name}: distributions are missing")
    for dist in dists:
        if not isinstance(dist, dict):
            raise ExportError(f"{name}: distribution must be an object")
        scope = dist.get("scope")
        if scope not in _SCOPES:
            raise ExportError(f"{name}: scope {scope!r} is not total, lot, or device")
        if scope in found:
            raise ExportError(f"{name}: duplicate scope {scope}")
        found[scope] = dist
    if "total" in found and ({"lot", "device"} & set(found)):
        raise ExportError(f"{name}: total cannot be combined with lot or device")
    return found


def _correlation(card, names):
    corr = card.get("correlation")
    if not corr:
        return None
    listed = corr.get("parameters")
    matrix = corr.get("matrix")
    if not isinstance(listed, list) or not isinstance(matrix, list):
        raise ExportError("correlation needs parameters and a matrix")
    width = len(listed)
    if len(matrix) != width or any(not isinstance(row, list) or len(row) != width for row in matrix):
        raise ExportError("correlation matrix size does not match its parameters")
    known = set(names)
    for name in listed:
        if name not in known:
            raise ExportError(f"correlation: unknown parameter {name!r}")
    return {"parameters": list(listed), "matrix": matrix}


def _one_run(rng, parameters, scopes, refdes, correlation):
    lot_entries = [(param["name"], scopes[param["name"]]["lot"]) for param in parameters if "lot" in scopes[param["name"]]]
    inst_entries = []
    for param in parameters:
        found = scopes[param["name"]]
        if "total" in found:
            inst_entries.append((param["name"], found["total"]))
        elif "device" in found:
            inst_entries.append((param["name"], found["device"]))
    for _lot_try in range(_MAX_TRIES):
        lot = _draw_entries(rng, lot_entries, correlation)
        placed = []
        for ref in refdes:
            one = _one_instance(rng, parameters, scopes, ref, lot, inst_entries, correlation)
            if one is None:
                placed = None
                break
            placed.append(one)
        if placed is not None:
            return placed
    raise ExportError("published limits rejected too many samples")


def _one_instance(rng, parameters, scopes, refdes, lot, inst_entries, correlation):
    for _try in range(_MAX_TRIES):
        per = _draw_entries(rng, inst_entries, correlation)
        values = {}
        draws = {}
        ok = True
        for param in parameters:
            name = param["name"]
            found = scopes[name]
            raw = {}
            if "lot" in found:
                raw["lot"] = lot[name]
            if "device" in found:
                raw["device"] = per[name]
            if "total" in found:
                raw["total"] = per[name]
            value = _combine(name, param["nominal"], found, raw)
            if not _acceptable(name, param["nominal"], value, param):
                ok = False
                break
            values[name] = value
            draws[name] = raw
        if ok:
            return {"refdes": refdes, "values": values, "draws": draws}
    return None


def _draw_entries(rng, entries, correlation):
    by = {name: dist for name, dist in entries}
    drawn = {}
    if correlation and len(by) >= 2:
        listed = correlation["parameters"]
        group = [name for name in listed if name in by]
        if len(group) >= 2:
            indexes = [listed.index(name) for name in group]
            matrix = correlation["matrix"]
            sub = [[matrix[i][j] for j in indexes] for i in indexes]
            factor = _cholesky(sub)
            latent = [_STD.inv_cdf(_open_unit(rng)) for _ in group]
            for row, name in enumerate(group):
                mixed = sum(factor[row][col] * latent[col] for col in range(row + 1))
                drawn[name] = _ppf(name, by[name], _unit_from_normal(mixed))
    for name, dist in entries:
        if name not in drawn:
            drawn[name] = _ppf(name, dist, _open_unit(rng))
    return drawn


def _combine(name, nominal, found, raw):
    if "total" in found:
        return _apply_one(name, nominal, found["total"].get("applies_to"), raw["total"])
    present = [scope for scope in ("lot", "device") if scope in found]
    applies = {found[scope].get("applies_to") for scope in present}
    if applies == {"relative_offset"}:
        value = nominal
        for scope in present:
            value = value * (1.0 + raw[scope])
        return value
    if applies == {"additive_offset"}:
        value = nominal
        for scope in present:
            value = value + raw[scope]
        return value
    shown = ", ".join(sorted(str(item) for item in applies))
    raise ExportError(
        f"{name}: cannot combine applies_to {shown}; lot and device must both be relative_offset or both additive_offset"
    )


def _apply_one(name, nominal, applies, draw):
    if applies == "value":
        return draw
    if applies == "additive_offset":
        return nominal + draw
    if applies == "relative_offset":
        return nominal * (1.0 + draw)
    raise ExportError(f"{name}: cannot sample applies_to {applies!r}")


def _acceptable(name, nominal, value, param):
    limits = param.get("limits") or {}
    if limits:
        if "min" in limits and value < limits["min"]:
            return False
        if "max" in limits and value > limits["max"]:
            return False
    final = param.get("final_limits")
    if not final:
        return True
    if "min" not in final or "max" not in final:
        raise ExportError(f"{name}: final_limits need min and max")
    checked = value
    if final.get("relative_to_nominal"):
        if nominal == 0:
            raise ExportError(f"{name}: final_limits are relative to a nominal of 0")
        checked = value / nominal
    return final["min"] <= checked <= final["max"]


def _ppf(name, dist, unit):
    """Quantile at unit in (0, 1), after this entry's own truncate."""
    kind = dist.get("type")
    params = dist.get("params")
    if not isinstance(params, dict):
        raise ExportError(f"{name}: distribution params are missing")
    truncate = dist.get("truncate") or {}
    if not isinstance(truncate, dict):
        raise ExportError(f"{name}: truncate must be an object")
    if kind == "uniform":
        return _uniform_ppf(name, params, truncate, unit)
    if kind == "normal":
        return _normal_ppf(name, params, truncate, unit)
    if kind == "lognormal":
        return _lognormal_ppf(name, params, truncate, unit)
    if kind == "triangular":
        return _triangular_ppf(name, params, truncate, unit)
    if kind == "empirical":
        return _empirical_ppf(name, params, truncate, unit)
    raise ExportError(f"{name}: cannot sample distribution type {kind!r}")


def _uniform_ppf(name, params, truncate, unit):
    if "min" not in params or "max" not in params:
        raise ExportError(f"{name}: uniform needs min and max")
    low, high = params["min"], params["max"]
    if "min" in truncate:
        low = max(low, truncate["min"])
    if "max" in truncate:
        high = min(high, truncate["max"])
    if not low < high:
        raise ExportError(f"{name}: uniform truncate leaves no support")
    return low + unit * (high - low)


def _normal_ms(name, params):
    if "mean" not in params:
        raise ExportError(f"{name}: normal needs a mean")
    mean = params["mean"]
    if "sigma" in params and "sigma_pct" in params:
        raise ExportError(f"{name}: normal has both sigma and sigma_pct")
    if "sigma" in params:
        sigma = params["sigma"]
    elif "sigma_pct" in params:
        if mean == 0:
            raise ExportError(f"{name}: normal sigma_pct needs a non-zero mean")
        sigma = abs(mean) * params["sigma_pct"] / 100.0
    else:
        raise ExportError(f"{name}: normal needs sigma or sigma_pct")
    if isinstance(sigma, bool) or not isinstance(sigma, (int, float)) or sigma <= 0:
        raise ExportError(f"{name}: normal sigma must be > 0")
    return float(mean), float(sigma)


def _normal_ppf(name, params, truncate, unit):
    mean, sigma = _normal_ms(name, params)
    law = statistics.NormalDist(mean, sigma)
    left = law.cdf(truncate["min"]) if "min" in truncate else 0.0
    right = law.cdf(truncate["max"]) if "max" in truncate else 1.0
    if not left < right:
        raise ExportError(f"{name}: normal truncate leaves no support")
    return law.inv_cdf(left + unit * (right - left))


def _lognormal_ppf(name, params, truncate, unit):
    if "mu" not in params or "sigma" not in params:
        raise ExportError(f"{name}: lognormal needs mu and sigma")
    mu, sigma = params["mu"], params["sigma"]
    if isinstance(sigma, bool) or not isinstance(sigma, (int, float)) or sigma <= 0:
        raise ExportError(f"{name}: lognormal sigma must be > 0")

    def cdf(point):
        if point <= 0:
            return 0.0
        return _STD.cdf((math.log(point) - mu) / sigma)

    left = cdf(truncate["min"]) if "min" in truncate else 0.0
    right = cdf(truncate["max"]) if "max" in truncate else 1.0
    if not left < right:
        raise ExportError(f"{name}: lognormal truncate leaves no support")
    return math.exp(mu + sigma * _STD.inv_cdf(left + unit * (right - left)))


def _triangular_ppf(name, params, truncate, unit):
    for key in ("min", "mode", "max"):
        if key not in params:
            raise ExportError(f"{name}: triangular needs min, mode, and max")
    low, mode, high = params["min"], params["mode"], params["max"]
    if not low <= mode <= high or not low < high:
        raise ExportError(f"{name}: triangular needs min <= mode <= max and min < max")
    left_x = max(truncate.get("min", low), low)
    right_x = min(truncate.get("max", high), high)
    left = _triangular_cdf(left_x, low, mode, high)
    right = _triangular_cdf(right_x, low, mode, high)
    if not left < right:
        raise ExportError(f"{name}: triangular truncate leaves no support")
    return _triangular_raw(left + unit * (right - left), low, mode, high)


def _triangular_cdf(point, low, mode, high):
    if point <= low:
        return 0.0
    if point >= high:
        return 1.0
    span = high - low
    if point < mode:
        return (point - low) ** 2 / (span * (mode - low))
    if mode == high:
        return 1.0
    return 1.0 - (high - point) ** 2 / (span * (high - mode))


def _triangular_raw(unit, low, mode, high):
    span = high - low
    if mode > low and unit < (mode - low) / span:
        return low + math.sqrt(unit * span * (mode - low))
    if mode == high:
        return high
    return high - math.sqrt((1.0 - unit) * span * (high - mode))


def _empirical_ppf(name, params, truncate, unit):
    if "samples_uri" in params:
        raise ExportError(f"{name}: cannot sample empirical distribution from samples_uri; the sample file is not fetched")
    bins = params.get("bins")
    if not isinstance(bins, list) or not bins:
        raise ExportError(f"{name}: empirical needs bins")
    kept = []
    full = 0.0
    for item in bins:
        if not isinstance(item, dict):
            raise ExportError(f"{name}: empirical bin must be an object")
        value, prob = item.get("value"), item.get("probability")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ExportError(f"{name}: empirical bin value must be a number")
        if isinstance(prob, bool) or not isinstance(prob, (int, float)) or prob < 0:
            raise ExportError(f"{name}: empirical bin probability must be >= 0")
        full += prob
        if "min" in truncate and value < truncate["min"]:
            continue
        if "max" in truncate and value > truncate["max"]:
            continue
        kept.append((float(value), float(prob)))
    if abs(full - 1.0) > 1e-6:
        raise ExportError(f"{name}: empirical bin probabilities must sum to 1")
    total = sum(prob for _, prob in kept)
    if not kept or total <= 0:
        raise ExportError(f"{name}: empirical truncate leaves no support")
    ordered = sorted(kept, key=lambda item: item[0])
    cum = 0.0
    target = unit * total
    for value, prob in ordered:
        cum += prob
        if target <= cum:
            return value
    return ordered[-1][0]


def _cholesky(matrix):
    width = len(matrix)
    factor = [[0.0] * width for _ in range(width)]
    for row in range(width):
        for col in range(row + 1):
            total = matrix[row][col] - sum(factor[row][k] * factor[col][k] for k in range(col))
            if row == col:
                if total < -1e-8:
                    raise ExportError("correlation matrix is not positive semidefinite")
                factor[row][col] = math.sqrt(max(total, 0.0))
            elif factor[col][col] == 0.0:
                factor[row][col] = 0.0
            else:
                factor[row][col] = total / factor[col][col]
    return factor


def _open_unit(rng):
    """A uniform draw in (0, 1), never the endpoints."""
    return (rng.getrandbits(53) + 0.5) / float(1 << 53)


def _unit_from_normal(point):
    unit = _STD.cdf(point)
    tiny = 0.5 / float(1 << 53)
    if unit < tiny:
        return tiny
    if unit > 1.0 - tiny:
        return 1.0 - tiny
    return unit


def _format(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ExportError(f"cannot write non-finite value {value!r}")
    if value == 0:
        return "0"
    return repr(float(value))
