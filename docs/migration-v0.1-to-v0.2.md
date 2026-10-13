# Migrating from v0.1 to v0.2

v0.2 is still in progress. The schema version stays `"0.1"` until all seven v0.2 issues are done, so cards keep `card_version: "0.1"` for now. This page lists what's changed so far.

## Breaking change: `distribution` is now a `distributions` list (#5)

Each parameter now has a `distributions` list instead of a single `distribution`. Every entry needs a `scope`:

- `total`: the whole spread. Use exactly one `total` entry and nothing else.
- `lot` and/or `device`: lot-to-lot and device-to-device spread, mirroring SPICE Monte Carlo `LOT` and `DEV`. No `total` is allowed next to them.

The `spread_components` list and the `informational` flag from the first draft of #5 are gone. A v0.1 card with `distribution` fails with:

```
v0.1 'distribution' replaced by 'distributions' list; see docs/migration-v0.1-to-v0.2.md
```

### How to convert a card

Rename `distribution:` to `distributions:`, turn it into a one-item list, and add `scope: total`. Nothing else changes.

Before (v0.1):

```yaml
    distribution:
      type: uniform
      applies_to: value
      kind: population
      params: { min: 4.653, max: 4.747 }
      basis: "Datasheet +/-1% tolerance (p.3). Shape not published; uniform over the limit."
      confidence: low
```

After (v0.2):

```yaml
    distributions:
      - scope: total
        type: uniform
        applies_to: value
        kind: population
        params: { min: 4.653, max: 4.747 }
        basis: "Datasheet +/-1% tolerance (p.3). Shape not published; uniform over the limit."
        confidence: low
```

If you want to split a spread into lot and device, replace the `total` entry with the two entries. See [lot-device-spread.md](lot-device-spread.md).

All cards in this repo were converted this way, including Drew Owens' two cards in `cards/real/`. Only the structure changed. Each of his cards has a comment noting the conversion from his [original v0.1 card](https://wiki.adom.inc/drew2/community-open-component-cards). The cards are re-signed when the change merges.

## Other v0.2 changes so far (not breaking)

These are all optional additions, so a v0.1 card only needs the change above.

- **`limits`** (#1): published datasheet min, typ, and max, kept apart from the modeling choice. See the README.
- **Standard `conditions` keys** (#3): unit-in-name keys like `temperature_c` and `dc_bias_v`. Other keys still pass with a warning. `bias_v` stays as an accepted alias. See [conditions.md](conditions.md).
- **Structured `model_binding.transform`** (#6): `offset`, `scale`, `replace`, or `affine`. Plain-text transforms still pass with a warning. See [model-binding.md](model-binding.md).
- **`derived` source kind** (#4): a `derived_from` chain from a wiki page or tool back to a datasheet. See [derived-sources.md](derived-sources.md).

All suggested by Drew Owens (Adom).
