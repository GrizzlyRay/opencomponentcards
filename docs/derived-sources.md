# Derived sources

Sometimes a card's numbers don't come straight from a datasheet. They come from a page, database, or tool that itself cites the datasheet. `kind: datasheet` would hide that step, so v0.2 adds `kind: derived`.

A derived source lists the refs it took its data from in `derived_from`. Those upstream sources go in the same `sources` list, so the chain is explicit.

```yaml
sources:
  - ref: ds1
    kind: datasheet
    uri: "https://example.com/part-datasheet.pdf"
    evidence: "p.3 tolerance table"
    confidence: high
  - ref: wiki1
    kind: derived
    uri: "https://wiki.example.com/parts/part-123"
    derived_from: [ds1]
    evidence: "Specs section, each value cites ds1 p.3"
    confidence: high
```

Parameters can then cite `wiki1` (where the numbers were read) or `ds1`, or both.

## Rules

- `derived_from` is required when `kind` is `derived`.
- Every ref in `derived_from` must exist in `sources`. Unknown refs are errors.
- Chains can't loop. A cycle like `a -> b -> a` is an error.
- A derived source should trace back to a primary source: a `datasheet`, `measurement`, or `standard`. If it doesn't, the validator warns.
- Setting `derived_from` on a non-derived kind is allowed but gets a warning.

Cards that don't use `derived` are unchanged, so every v0.1 card still passes.
