# OpenComponentCards

**v0.1 draft, feedback wanted.**
By Jacob Warren and GrizzlyRay LLC.

> Researched and drafted by Jacob Warren with Grok and AI assistants; example values are assumptions, not manufacturer statistics.

## What it is

Electronic parts are never exactly their nominal value. A 10 kOhm resistor might be 9.95 kOhm, a 10 uF capacitor might act like 4 uF once voltage is applied. Engineers simulate circuits with model files (SPICE, IBIS, Touchstone, Verilog-A), but those files rarely say how much a part varies, where the numbers came from, or who published which version.

A **Component Card** is a small YAML file that sits next to an existing model file. It does not replace the model. It adds:

1. **How much the part varies:** probability distributions for key values, each with a stated basis and confidence.
2. **Where the numbers came from:** sources, method, and a maturity level (inspired by IBIS revision and quality levels).
3. **Who published it and which version it is:** author, date, a sha256 link to the previous version, and a Sigstore signature.

## What this is not

- Not manufacturer statistics. The example spreads in `cards/examples/` are assumptions, mostly datasheet limits treated as 3 sigma. The real-data cards in `cards/real/` use published datasheet limits.
- Not a new model format. Cards point at existing model files by hash.
- Not a finished standard. Fields will change based on feedback.
- Not proof a model is correct. A signature shows who published a card and that it hasn't changed.

## Repository layout

```
schema/card.schema.json     JSON Schema (draft 2020-12) for v0.1 cards
cards/examples/*.yaml       Three example cards: resistor, ceramic capacitor, power MOSFET
cards/real/*.yaml           Real-data cards built from datasheets by Drew Owens (Adom)
cards/real/families/*.yaml  Family cards: shared series data plus value-dependent rules
tools/validate.py           Validator: schema plus extra consistency checks
tools/resolve.py            Merges a family card and a part card into one resolved card
docs/conditions.md          Standard keys for conditions
docs/lot-device-spread.md   Lot vs device spread in the distributions list
docs/family-cards.md        Family cards and value-dependent rules
docs/migration-v0.1-to-v0.2.md  What changed since v0.1 and how to convert cards
```

## Quick start

```bash
pip install -r requirements.txt
python3 tools/validate.py --schema schema/card.schema.json cards/examples/*.yaml cards/real/*.yaml
```

The validator checks the schema plus rules a schema cannot express: distribution parameters per type, `applies_to` semantics, correlation matrices (symmetric and positive semidefinite), SPDX license ids, units, quoted ISO dates, references, nominal-vs-mean consistency, and published limits.

## Published Limits

Each parameter can carry an optional `limits` block with the published datasheet numbers, kept apart from the modeling choice in `distributions`:

```yaml
limits: { min: 9900, typ: 10000, max: 10100, source_ref: ds1 }
```

`min`, `typ`, and `max` are each optional numbers in the parameter's unit, but at least one is needed. You can add `conditions` if the limit's published at different conditions than the parameter. This way two people can model the same datasheet fact differently and still point at the same limit. The validator errors if `min <= typ <= max` doesn't hold, and warns if a value distribution's support or truncation goes past the limits. It's optional, so cards without it stay valid. Suggested by Drew Owens ([#1](https://github.com/GrizzlyRay/opencomponentcards/issues/1)).

## Standard Conditions

`conditions` and `limits.conditions` share a small vocabulary of standard keys with the unit in the name, like `temperature_c`, `frequency_hz`, `ac_vrms`, `dc_bias_v`, and a free-text `preconditioning`. Other keys still work, but the validator warns and suggests the closest standard key. See [docs/conditions.md](docs/conditions.md) for the full list. Suggested by Drew Owens ([#3](https://github.com/GrizzlyRay/opencomponentcards/issues/3)).

## Real-Data Cards

`cards/real/` holds the first cards built from real datasheet data: a Royalohm 4.7 Ohm 0603 resistor and a Samsung 4.7 uF X5R 0805 capacitor. Every value is a published limit with its datasheet page. Both were converted to the v0.2 `distributions` list (structure only, values unchanged) and pass the validator. `cards/real/families/royalohm-0603waf.yaml` is a family card for the whole 0603WAF series, built only from Drew's data, and the Royalohm part card now links to it.

A huge thank you to **Drew Owens** at [Adom](https://wiki.adom.inc), who built both cards from Adom wiki component pages within hours of v0.1 going out, and wrote up notes for v0.2. His write-up is [here](https://wiki.adom.inc/drew2/community-open-component-cards), and his suggestions are tracked in the [v0.2 issues](https://github.com/GrizzlyRay/opencomponentcards/issues?q=label%3Av0.2). The cards are CC-BY-4.0, so please credit Drew Owens and Adom when you reuse them.

## Verifying a Card

Every card in `cards/` is signed by this repo's GitHub Actions workflow using Sigstore keyless signing. The signature bundle sits next to the card as `<card>.sigstore.json`. Nobody holds a private key; the signer is the workflow's GitHub identity.

Install [cosign](https://docs.sigstore.dev/cosign/system_config/installation/), then run:

```sh
cosign verify-blob cards/examples/example_resistor.yaml \
  --bundle cards/examples/example_resistor.yaml.sigstore.json \
  --certificate-identity "https://github.com/GrizzlyRay/opencomponentcards/.github/workflows/sign.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
```

Or use the helper: `tools/verify.sh cards/examples/example_resistor.yaml`

`Verified OK` means this exact card was published by the GrizzlyRay/opencomponentcards workflow and hasn't changed since. It doesn't mean the numbers are right. That's what the card's sources and maturity level are for.

## Feedback wanted

Open an issue, especially on:
- the default when a distribution's shape is unknown (Drew's real cards use uniform over the published limit, and that's the leading answer for v0.2)
- exporting cards to SPICE Monte Carlo syntax (agauss, mc, DEV/LOT)
- binding card values into vendor subcircuit models
- mapping to CycloneDX or SPDX
- who should sign cards and how to trust signers

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Related work

CycloneDX and SPDX 3.0, IBIS and the IBIS Quality Specification, CMC compact models, GUM (JCGM 100/101), IEC 61360 / ECLASS, IPC-1752 / IPC-2581, Modelica, HPM Component Registry, JITX Open Components Database, open PDKs (SKY130, GF180MCU, IHP SG13G2), UQSpice, and datasheet2spice.

## License

- Schema, code, and tools: [Apache-2.0](LICENSE)
- Card data (`cards/`): [CC-BY-4.0](LICENSE-DATA)

## Changelog

**v0.2 (in progress).** The schema version stays 0.1 until all seven v0.2 issues are done. v0.2 has one breaking change so far; see [docs/migration-v0.1-to-v0.2.md](docs/migration-v0.1-to-v0.2.md).

- Added an optional `limits` field for published datasheet limits (#1, suggested by Drew Owens).
- Added a standard vocabulary for `conditions` keys, with units in the key name. Non-standard keys still pass but get a warning with the closest match (#3, suggested by Drew Owens). See [docs/conditions.md](docs/conditions.md).
- Made `model_binding.transform` machine-readable, with `offset`, `scale`, `replace`, and `affine` types plus an optional `note`. Plain string transforms still pass but get a warning (#6, suggested by Drew Owens). See [docs/model-binding.md](docs/model-binding.md).
- Added a `derived` source kind with a `derived_from` list, so a card can record a chain like "wiki page X cites datasheet p.3". The validator checks that the refs exist, that there's no cycle, and warns when a derived source doesn't trace back to a datasheet, measurement, or standard (#4, suggested by Drew Owens). See [docs/derived-sources.md](docs/derived-sources.md).
- **Breaking:** replaced the single `distribution` with a `distributions` list. Each entry has a `scope` of `total`, `lot`, or `device`: either one `total`, or lot and/or device with no total, mirroring SPICE Monte Carlo `LOT` and `DEV`. v0.1 cards with `distribution` now fail with a pointer to the migration guide, and every card in the repo was converted (#5, suggested by Drew Owens). See [docs/lot-device-spread.md](docs/lot-device-spread.md) and [docs/migration-v0.1-to-v0.2.md](docs/migration-v0.1-to-v0.2.md).
- Added family cards. A `card_type: family` card holds what a whole series shares, plus `rules` with `when` conditions on selectors like resistance, so the Royalohm 0603WAF TCR bracket (+/-200 ppm/K for 1 to 10 Ohm, +/-100 ppm/K above 10 Ohm) lives in one place. Part cards can link to a family with an optional `family` reference and override any field. `tools/resolve.py` merges the two, and the validator checks the link, the sha256, overlapping rules, and the resolved card. The design follows prior art from JEDEC JEP30 Family objects and JITX's parametric component families (#2, suggested by Drew Owens). See [docs/family-cards.md](docs/family-cards.md).
