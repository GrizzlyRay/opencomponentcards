# Lot vs device spread

Parts from one reel track each other. A card can say how much of a parameter's spread is lot-to-lot and how much is device-to-device, the same split SPICE Monte Carlo makes with `LOT` and `DEV` tolerances. Suggested by Drew Owens (#5).

## Fields

Each parameter has a `distributions` list. Every entry is a standard distribution block (`type`, `applies_to`, `kind`, `params`, `basis`, `confidence`) plus a `scope`:

- `scope: total`: all of the spread. If a parameter has a `total`, it's the only entry.
- `scope: lot`: lot-to-lot spread. One draw per lot, shared by every part in it.
- `scope: device`: device-to-device spread within one lot. One draw per part.

So a parameter has either exactly one `total`, or a `lot` and/or `device` entry with no `total`. There's no second copy of the spread to keep in sync.

A simple spread:

```yaml
distributions:
  - scope: total
    type: uniform
    applies_to: value
    kind: population
    params: { min: 4.653, max: 4.747 }
    basis: "Datasheet +/-1% tolerance (p.3)."
    confidence: low
```

A split spread (from `cards/examples/example_resistor.yaml`, EXAMPLE numbers):

```yaml
distributions:
  - scope: lot
    type: normal
    applies_to: relative_offset
    kind: population
    params: { mean: 0, sigma: 0.0029 }   # EXAMPLE: 0.29% lot-to-lot sigma
    basis: "EXAMPLE split, not measured."
    confidence: low
  - scope: device
    type: normal
    applies_to: relative_offset
    kind: population
    params: { mean: 0, sigma: 0.0017 }   # EXAMPLE: 0.17% device-to-device sigma
    basis: "EXAMPLE split, not measured."
    confidence: low
```

Together they give about sqrt(0.29^2 + 0.17^2) = 0.33% sigma, the same as the old 1% limit treated as 3 sigma.

## How sampling works

For each Monte Carlo run:

1. Draw the `lot` entry once per lot. Every part in that lot shares it.
2. Draw the `device` entry once per part.
3. Apply both to the nominal (or the dependence curve). With `relative_offset`, value = nominal * (1 + lot) * (1 + device). With `additive_offset`, value = nominal + lot + device.

If only one of the two is given, the other is treated as zero (the validator warns).

## Mapping to SPICE

| Card | SPICE (PSpice / LTspice style) |
| --- | --- |
| `scope: lot` | `LOT` tolerance on the model parameter |
| `scope: device` | `DEV` tolerance on the model parameter |
| `scope: total` | single tolerance, or `DEV` only |

For a normal entry with `sigma` given as a fraction, a 3-sigma tolerance is `LOT=3*sigma` (as a percent, `LOT=<3*sigma*100>%`), with `DEV` likewise. For example, the resistor example's lot sigma of 0.0029 maps to roughly `LOT=0.87%` and its device sigma of 0.0017 to roughly `DEV=0.51%`. Uniform entries map to the simulator's uniform `LOT`/`DEV` distribution. Check your simulator's docs for how it reads the tolerance (some treat it as a uniform limit by default).

## Correlation

The `correlation` matrix is applied at each scope separately: lot draws are correlated with lot draws, and device draws with device draws, using the same matrix. A parameter with only a `total` entry joins the device draw. The validator warns when a correlation mixes split and total-only parameters so you can check that's what you meant.

## Validator rules

- Error: every entry needs a `scope` of `total`, `lot`, or `device`.
- Error: the same scope appears twice on one parameter.
- Error: a `total` sits next to `lot` or `device`.
- Error: lot and device both use `applies_to: value` (they'd double count; use offsets).
- Error: the v0.1 `distribution`, `spread_components`, or `informational` fields. See [migration-v0.1-to-v0.2.md](migration-v0.1-to-v0.2.md).
- Warning: `scope: lot` or `device` with `kind: epistemic`. Scope describes part-to-part spread, which is a population idea.
- Warning: only one of lot or device is given.
- Published `limits` are checked against the `total` entry. For split parameters only the limit order and source are checked.
