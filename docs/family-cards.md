# Family cards

One datasheet often covers a whole series. The Royalohm 0603WAF datasheet covers every value in the series, and some specs depend on the value: TCR is +/-200 ppm/K for 1 to 10 Ohm and +/-100 ppm/K above 10 Ohm. With one card per part number, that bracket gets copied hundreds of times. A family card holds it once.

Suggested by Drew Owens (Adom) in his [v0.2 notes](https://wiki.adom.inc/drew2/community-open-component-cards) (#2).

## How it works

There are two kinds of card:

- A **part card** is what we've had all along: one manufacturer part number. It can now add an optional `family` reference.
- A **family card** (`card_type: family`) holds what the series shares, plus `rules` for the parts that depend on a value.

A part card that links to a family gets the family's data, then its own fields win. Resolving goes in this order:

1. Start from the family's `parameters`.
2. Apply every rule whose `when` matches the part's selector values.
3. Apply the part card's own fields on top.

## A family card

```yaml
card_version: "0.1"
card_type: family
id: occ:family/royalohm-0603waf@0.1.0
family:
  manufacturer: "Royalohm (UNI-ROYAL)"
  series: "0603WAF"
  category: resistor
  package: "0603"
  selectors:
    - name: resistance
      unit: Ohm
parameters:
  - name: tcr
    unit: ppm/K
    nominal: 0
    source_refs: [ds1]
rules:
  - id: tcr-1-to-10-ohm
    when: { resistance: { min: 1, max: 10 } }
    set:
      tcr:
        distributions:
          - { scope: total, type: uniform, applies_to: value, kind: epistemic,
              params: { min: -200, max: 200 }, basis: "...", confidence: low }
  - id: tcr-above-10-ohm
    when: { resistance: { gt: 10 } }
    set:
      tcr:
        distributions: [ ... +/-100 ppm/K ... ]
not_published:
  - "TCR below 1 Ohm: ..."
```

The full card is [`cards/real/families/royalohm-0603waf.yaml`](../cards/real/families/royalohm-0603waf.yaml).

- **`selectors`** are what rules can test. A numeric selector has a `unit`. A categorical selector, like a package, lists its `values`.
- **Family `parameters`** can leave out `nominal`, `distributions`, or `source_refs` when a rule or the part supplies them.
- **`rules`** each have an `id`, a `when`, and a `set`. In `when`, numeric ranges use `min` and `max` (inclusive) or `gt` and `lt` (exclusive), and categorical selectors use `in: [...]`. A rule matches when every condition matches. `set` maps a parameter name to the fields it replaces.
- **`not_published`** lists what the sources don't say for the whole series. If a fact isn't in the data, it goes here instead of being guessed.

## A part card that links to a family

```yaml
id: occ:resistor/royalohm-0603waf470kt5e@0.1.0
family:
  id: occ:family/royalohm-0603waf@0.1.0
  sha256: "5a9f964d..."
  select: { resistance: 4.7 }
```

- `id` must match a family card under `cards/` exactly, version included.
- `sha256` is optional. If it's set, it must be the sha256 of the family card file, so an edited family can't quietly change a part. If you edit a family, update the hash in the parts that pin it.
- `select` gives the part's selector values. If a numeric selector is missing, the part's parameter with the same name supplies its `nominal`.
- A part can leave out `manufacturer`, `category`, and `package`. They come from the family.

Parameters merge by name, field by field. Sources merge by `ref`, and the part's version wins.

## Resolving

```
python3 tools/resolve.py cards/real/royalohm-0603waf470kt5e.yaml
python3 tools/resolve.py --family cards/real/families/royalohm-0603waf.yaml --select resistance=1000
```

The first prints the resolved part card. The second shows what the family alone says at one point, which is handy for checking rules.

## What the validator checks

For a family card:

- The schema, including the rule shapes.
- Every `when` key is a declared selector, and uses `in` only for categorical selectors.
- Ranges aren't empty, and rule ids are unique.
- Every `set` targets a real family parameter.
- Two rules that set the same parameter can't overlap. `min: 10` in one rule and `gt: 10` in another is fine. `max: 10` and `min: 10` isn't, since both match 10 Ohm.
- Each rule, applied to the family, gives valid parameters.

For a part card with a `family` reference:

- The family exists and its sha256 matches.
- `select` uses only the family's selectors.
- After resolving, every parameter is complete. If no rule covers the part's value (for example 0.5 Ohm in the 0603WAF family), the part card has to give that parameter itself.
- The resolved card passes every normal check.

## Prior art

Prior art research found that most part data systems are built around single part numbers, with a series as a grouping. Two designs were closest to what we needed, and this one borrows from both:

- **JEDEC JEP30 (PartModel Guidelines)** has explicit Family objects. Part records reference a family by ID, so shared data isn't copied. Our `family.id` reference works the same way. See [JEP30](https://www.jedec.org/category/technology-focus-area/jep30).
- **JITX's open-components-database** keeps one file per component family, with parametric rules (value, case size, tolerance) that produce the exact part. Our `rules` with `when` conditions follow that idea, kept declarative so any tool can read them. See [open-components-database](https://github.com/JITx-Inc/open-components-database).

Octopart and Nexar link parts to a flat PartSeries, which groups parts but doesn't carry value-dependent specs.
