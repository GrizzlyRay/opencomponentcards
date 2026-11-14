---
name: opencomponentcards
user-invocable: true
description: >-
  Use when the user wants to import an OpenComponentCards card, turn cards
  into plain SPICE numbers, or run a board Monte Carlo from a local clone.
  Triggers include import a component card, export spice parameters, bind a
  BOM, and sweep a board.
---

# OpenComponentCards for Adom

This skill runs the OpenComponentCards tools in a local clone of https://github.com/GrizzlyRay/opencomponentcards. It does not publish a wiki page.

Author: Jacob Warren and GrizzlyRay LLC. Where this skill mentions Adom, the credit is an engineer at Adom.

## Checkout

Work in the clone. Run every tool with `.venv/bin/python`. System python3 does not provide PyYAML. Do not install packages and do not fetch dependencies. If `.venv/bin/python` is missing, say so and stop.

```
.venv/bin/python tools/adom_import.py --help
.venv/bin/python tools/spice_export.py --help
.venv/bin/python tools/board_mc.py --help
```

## Safe defaults

- Do not pass `--allow-adom` or `--allow-fallback` unless the user asks. Without those flags, a row that needs an Adom draft or a tolerance fallback stays unresolved.
- An unresolved part, or a netlist mismatch, is an exit 2. The tool prints the full list before any simulation.
- Every `--out` path stays under `out/`. That directory is gitignored. A path outside it is refused.
- Never commit a real Adom page.json, and never commit a drafted card.
- Do not download a datasheet and do not add a datasheet hash. Drafts stay in `out/`.
- Do not run `adom-wiki pkg publish`, `adom-wiki repo push`, or `adom-wiki auth`.

## Import a card

`tools/adom_import.py` reads one component page and writes one card.

```
.venv/bin/python tools/adom_import.py TARGET \
  [--from-file PATH] \
  [--out PATH] \
  [--kinds a,b] \
  [--category NAME] \
  [--manufacturer NAME] \
  [--date YYYY-MM-DD] \
  [--report]
```

`TARGET` is a slug, a `https://wiki.adom.inc/<owner>/<slug>` URL, or a `/blob/...` URL. Prefer `--from-file` with a page the user already has, so the tool does not fetch. `--out` defaults to `out/adom/<slug>.yaml` and must stay inside `out/`. `--kinds` is a comma-separated list that can only narrow the import kinds. A skipped kind is an error. `--category` and `--manufacturer` override the page. `--date` is the card created date, `YYYY-MM-DD`, and the default is today. `--report` prints each row's parameter name or skip reason.

Exit 0 when the written card is valid. Exit 1 when a card was written but is invalid. Exit 2 on an input problem. Leave the draft in `out/`.

## Export SPICE

`tools/spice_export.py` samples bound cards into plain numbers. Python draws every random value from `--seed`. Do not put `agauss`, `gauss`, `unif`, `mc`, or `flat` in a deck.

```
.venv/bin/python tools/spice_export.py \
  --netlist PATH \
  --bind REFDES=path/to/card.yaml \
  --runs N \
  --seed S \
  [--jobs N] \
  [--sim ngspice|ltspice] \
  [--spec NAME=lo:hi] \
  [--out out/spice/NAME] \
  [--timeout SECONDS]
```

`--netlist`, `--runs`, and `--seed` are required. Repeat `--bind` once per refdes. The netlist marks a value with `{p_<refdes>_<param>}`. Before any run, every placeholder must be bound and every bound name must be used. A mismatch is an exit 2 and names both lists.

`--jobs` defaults to 1. `--sim` defaults to `ngspice`. `ltspice` writes one table deck and does not run LTspice. Repeat `--spec` as `NAME=lo:hi`. `--out` defaults to `out/spice/<netlist stem>` and must stay inside `out/`. `--timeout` is the number of seconds for each ngspice run and defaults to 60.

Exit 0 when every ngspice run is ok, or when an LTspice deck was written. Exit 1 when some ngspice runs failed. Exit 2 on an input problem.

## Board Monte Carlo

`tools/board_mc.py` matches a BOM to cards, rewrites resistor, capacitor, and inductor values, and runs ngspice through the SPICE exporter.

```
.venv/bin/python tools/board_mc.py \
  --bom PATH \
  --netlist PATH \
  --runs N \
  --seed S \
  [--jobs N] \
  [--spec NAME=lo:hi] \
  [--allow-adom] \
  [--allow-fallback] \
  [--out out/board/NAME]
```

`--bom`, `--netlist`, `--runs`, and `--seed` are required. `--jobs` defaults to 1. Repeat `--spec` as `NAME=lo:hi`. `--out` defaults to `out/board/<bom stem>` and must stay inside `out/`.

Leave `--allow-adom` and `--allow-fallback` off unless the user asks. There is no `--cards` flag. Local cards come from the clone's `cards/` directory. A resolved resistor, capacitor, or inductor is rewritten to `{p_<refdes>_<param>}` using that card's only primary value parameter: resistance, capacitance, or inductance. The card is read. A letter on the refdes does not choose the parameter.

Any unresolved part, or a BOM refdes missing from the netlist, or a board part in the netlist missing from the BOM, is an exit 2 with both lists before any simulation. A clean run writes `results.csv`, `summary.txt`, and `board_report.md` under `--out`. The report names each part, how its card was found, and a warning for every fallback or Adom draft.

Exit 0 when every run is ok. Exit 1 when some runs failed. Exit 2 on an input problem.
