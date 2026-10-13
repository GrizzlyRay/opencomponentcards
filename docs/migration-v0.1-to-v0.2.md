# Migrating from v0.1 to v0.2

v0.2 was released on 2026-10-13. Cards now use `card_version: "0.2"`, and the schema only accepts `"0.2"`, so change that line in every card along with the steps below. There are two breaking changes: the `distributions` list and the signature file layout. Everything else is an optional addition.

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

## Breaking Change: Signature Files Moved to `<card>.sigs/` (#7)

Card contents don't change, but signature files do. A card's bundle used to be `<card>.sigstore.json`. Now each card has a folder with one bundle per signer:

```
<card>.sigs/<signer-id>.sigstore.json
```

Every bundle in this repo was moved to `<card>.sigs/grizzlyray-sign-workflow.sigstore.json`, so the signatures are still valid. If you keep your own copy of cards, move them the same way:

```sh
for b in $(find cards -name '*.sigstore.json' -not -path '*.sigs/*'); do
  c="${b%.sigstore.json}"; mkdir -p "$c.sigs"; git mv "$b" "$c.sigs/grizzlyray-sign-workflow.sigstore.json"
done
```

Scripts that call `cosign verify-blob --bundle <card>.sigstore.json` need the new path, or use `tools/verify.sh`. See [signer-trust.md](signer-trust.md).

## Other v0.2 Changes (Not Breaking)

These are all optional additions, so a v0.1 card only needs the change above.

- **`limits`** (#1): published datasheet min, typ, and max, kept apart from the modeling choice. See the README.
- **Standard `conditions` keys** (#3): unit-in-name keys like `temperature_c` and `dc_bias_v`. Other keys still pass with a warning. `bias_v` stays as an accepted alias. See [conditions.md](conditions.md).
- **Structured `model_binding.transform`** (#6): `offset`, `scale`, `replace`, or `affine`. Plain-text transforms still pass with a warning. See [model-binding.md](model-binding.md).
- **`derived` source kind** (#4): a `derived_from` chain from a wiki page or tool back to a datasheet. See [derived-sources.md](derived-sources.md).
- **Family cards** (#2): a new `card_type: family` card holds what a series shares plus value-dependent `rules`, and a part card can point at it with an optional `family: {id, sha256, select}`. Cards without `family` work exactly as before. If you edit a family card, update the `sha256` in the part cards that pin it. See [family-cards.md](family-cards.md).
- **Signer trust policy** (#7): `trust/signers.yaml` lists who's trusted to sign cards and at what level. Cards don't change. `tools/verify.sh` takes card paths the same way but now checks the policy, and accepts `--min-level` and `--strict`. Multiple signatures per card are covered above. See [signer-trust.md](signer-trust.md).

All suggested by Drew Owens (Adom).
