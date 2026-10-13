# Contributing to OpenComponentCards

Thanks for helping. This is a v0.1 draft, so feedback on the schema itself is as valuable as new cards.

## Ways to help

- **Review the schema:** open an issue describing what is wrong, missing, or unclear. Engineers in SPICE modeling, metrology, and supply-chain security are especially welcome.
- **Add or improve a card:** open a pull request with a YAML file under `cards/`.
- **Improve the tools:** validator, exporters, docs.

## Card rules

1. Run the validator before opening a pull request:
   `python3 tools/validate.py --schema schema/card.schema.json cards/**/*.yaml`
2. Every distribution needs a `basis` and a `confidence`. Say plainly when a value is an estimate.
3. Do not copy proprietary data you have no right to share. Cite sources with exact evidence (table, page, figure).
4. Quote dates (`created: "2026-10-13"`).
5. Changing a published card makes a new version: bump the version in `id` and set `previous_version` to the sha256 of the old file.
6. Mark example or placeholder data clearly.

## Licensing of contributions

By contributing, you agree that code and schema changes are licensed under Apache-2.0 and card data under CC-BY-4.0.

## Conduct

Be kind and specific. Critique ideas, not people.
