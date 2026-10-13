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

- Not manufacturer data. The example spreads are assumptions, mostly datasheet limits treated as 3 sigma.
- Not a new model format. Cards point at existing model files by hash.
- Not a finished standard. Fields will change based on feedback.
- Not proof a model is correct. A signature shows who published a card and that it has not changed.

## Repository layout

```
schema/card.schema.json     JSON Schema (draft 2020-12) for v0.1 cards
cards/examples/*.yaml       Three example cards: resistor, ceramic capacitor, power MOSFET
tools/validate.py           Validator: schema plus extra consistency checks
```

## Quick start

```bash
pip install -r requirements.txt
python3 tools/validate.py --schema schema/card.schema.json cards/examples/*.yaml
```

The validator checks the schema plus rules a schema cannot express: distribution parameters per type, `applies_to` semantics, correlation matrices (symmetric and positive semidefinite), SPDX license ids, units, quoted ISO dates, references, and nominal-vs-mean consistency.

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
- the default when a distribution's shape is unknown (uniform, or limit as 3 sigma)
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
