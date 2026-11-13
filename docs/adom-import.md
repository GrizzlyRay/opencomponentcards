# Importing an Adom wiki page

`tools/adom_import.py` reads one Adom wiki `page.json` and writes an OpenComponentCards v0.2 draft. It copies published min and max limits into a uniform distribution. It does not download the datasheet, and it does not store a datasheet hash.

The field mapping comes from Drew Owens at Adom. His notes are at <https://wiki.adom.inc/drew2/community-open-component-cards>.

A draft is a starting point. `card_version` stays `"0.2"`. The card id ends in `@0.1.0`, which is the first revision of that imported card, not a schema bump. Drafts are written under `out/`. That directory is gitignored, so generated cards are never committed. Do not commit a saved `page.json` either.

## Command line

```bash
python3 tools/adom_import.py <slug|url> [--from-file PATH] [--out PATH] [--kinds a,b] [--category X] [--manufacturer X] [--date YYYY-MM-DD] [--report]
```

The target may be a bare slug, `owner/slug`, `https://wiki.adom.inc/<owner>/<slug>`, or a `/blob/...` URL. The fetch URL is always `https://wiki.adom.inc/blob/component/<slug>/page.json`. Redirects are followed, the timeout is 20 seconds, and the User-Agent names opencomponentcards. On a 404 the tool prints the wiki's JSON hint.

`--from-file` reads a local `page.json` and does not use the network. `--out` defaults to `out/adom/<slug>.yaml`. Any path outside `out/` is refused before the page is read. `--kinds` can only narrow the import kinds below. Naming a skipped kind is an error. `--category` and `--manufacturer` replace the page values. `--date` is the card's `created` field, as `YYYY-MM-DD` (the default is today). `--report` prints one line per row: the parameter name, or `skipped` plus the reason.

After a card is written, the tool runs the same checks as `tools/validate.py` and prints `PASS` or the errors.

| Exit | Meaning |
|---|---|
| 0 | The card was written and is valid. |
| 1 | The card was written, but validation failed. |
| 2 | Input problem. Nothing was written. Covers a missing page, no rows, no usable rows, a missing manufacturer, a missing license, a bad `--out`, or a bad `--kinds`. |

```bash
python3 tools/adom_import.py 2n7002 --report
python3 tools/adom_import.py synthetic-mosfet --from-file tests/fixtures/adom/synthetic-mosfet.json --out out/adom/synthetic-mosfet.yaml --date 2026-11-13 --report
```

The second command uses a hand-written fixture. It is not a page from wiki.adom.inc.

## Field mapping

| Adom page | Card |
|---|---|
| `title` | `part.description` |
| `component.manufacturer` | `part.manufacturer`, and the manufacturer piece of the id |
| `component.mpn` | `part.mpn` in its original case. The id uses the lowercase token. |
| `component.package` | `part.package`, when the page has one |
| `component.category` | `part.category`, through the table below |
| `component.datasheet` | `sources` entry `ds1`, kind `datasheet`, with the URI copied and no sha256 |
| `owner` and `slug` | `sources` entry `wiki1`, kind `derived`, `derived_from: [ds1]`, URI `https://wiki.adom.inc/<owner>/<slug>` |
| `license` | `license`, copied unchanged |
| `version` and `updated_at` | `notes` |
| row `symbol` | parameter `name` |
| row `min` and `max` | `limits` and the uniform `params`, after the unit scale |
| row `conditions` | parameter `conditions`, when a standard key can be read |
| row `source_page` | `ds1` evidence, as `p.N` for each distinct page on a usable row |

The id shape is `occ:<category>/<manufacturer-slug>-<mpn-lower>@0.1.0`. The manufacturer slug is lowercase, with each run of non-alphanumeric characters turned into one hyphen.

| Adom category | OCC category |
|---|---|
| Resistor or Resistors | `resistor` |
| Capacitor or Capacitors | `capacitor` |
| Inductor or Inductors | `inductor` |
| Diode or Diodes | `diode` |
| anything else, including Transistor | `other`, and a warning is printed and added to `notes` |

Matching ignores case. `--category` is stored as given and does not warn. An empty manufacturer is an error unless `--manufacturer` is set. A missing or blank license is an error. The tool never invents a license.

`model_files` is empty. `derivation.kind` is `data`. `validation.maturity` is `"0.1"`, with no simulators and no comparisons. `provenance.created` is `--date`. `previous_version` is null and `signatures` is empty. The author line names Jacob Warren and GrizzlyRay LLC and the wiki page the rows came from.

`wiki1.evidence` is the fixed string `metadata.characteristics.rows`. `ds1.evidence` is the sorted page list, such as `p.2` or `p.1, p.2`. If no usable row has an integer `source_page`, the evidence is `datasheet`. Neither source gets a sha256. The datasheet file is not downloaded.

## Units

Printed units are looked up in a closed table. Two lookalike characters are folded first: Greek mu `μ` (U+03BC) becomes micro `µ` (U+00B5), and ohm `Ω` (U+2126) becomes `Ω` (U+03A9). The match is then exact and case sensitive. `ms` is milliseconds. `mS` is millisiemens and is not an OCC unit. There is no prefix math, so `kV`, `uA`, `KΩ`, and the word `Ohm` are unknown.

The scale converts the printed number into the OCC unit. `°C` and `℃` become `degC` with scale 1. They are not shifted to kelvin. `ppm/°C` and `ppm/℃` become `ppm/K` with scale 1.

| Printed | OCC unit | Scale |
|---|---|---|
| `V` | `V` | 1 |
| `mV` | `V` | 0.001 |
| `µV` | `V` | 0.000001 |
| `A` | `A` | 1 |
| `mA` | `A` | 0.001 |
| `µA` | `A` | 0.000001 |
| `nA` | `A` | 0.000000001 |
| `pA` | `A` | 0.000000000001 |
| `Ω` | `Ohm` | 1 |
| `kΩ` | `Ohm` | 1000 |
| `MΩ` | `Ohm` | 1000000 |
| `mΩ` | `Ohm` | 0.001 |
| `F` | `F` | 1 |
| `µF` | `F` | 0.000001 |
| `nF` | `F` | 0.000000001 |
| `pF` | `F` | 0.000000000001 |
| `H` | `H` | 1 |
| `mH` | `H` | 0.001 |
| `µH` | `H` | 0.000001 |
| `nH` | `H` | 0.000000001 |
| `W` | `W` | 1 |
| `mW` | `W` | 0.001 |
| `s` | `s` | 1 |
| `ms` | `s` | 0.001 |
| `µs` | `s` | 0.000001 |
| `ns` | `s` | 0.000000001 |
| `Hz` | `Hz` | 1 |
| `kHz` | `Hz` | 1000 |
| `MHz` | `Hz` | 1000000 |
| `°C`, `℃` | `degC` | 1 |
| `%` | `1` | 0.01 |
| `ppm/°C`, `ppm/℃` | `ppm/K` | 1 |

`S`, `mS`, `°C/W`, and `ppm/V` are unknown. An unknown unit is skipped, not guessed.

## Kinds

Imported kinds:

- `electrical`
- `tolerance`
- `temperature_coefficient`
- `voltage_coefficient`
- `timing`

Skipped kinds, even when `--kinds` asks for them:

- `absolute_maximum`
- `recommended_operating`
- `thermal`

Any other kind is unknown and is skipped. `--kinds` may list a subset of the imported kinds. It may not list a skipped kind, and it may not list an unknown kind.

A row is usable only when its kind is imported and requested, its unit is in the table, and both min and max are numbers with min less than max after scaling. The first matching reason wins:

1. `skipped kind`
2. `unknown kind`
3. `kind not requested`
4. `unknown unit`
5. `one-sided limits`
6. `min not less than max`

A typ-only row, or a row with only a max, is one-sided and is skipped.

## Rules

- The spread is uniform over the published limits. Each parameter gets one distribution: `scope` total, `type` uniform, `applies_to` value, `confidence` low. `kind` is `population`, except `temperature_coefficient` and `voltage_coefficient`, which are `epistemic`.
- The distribution `params` are the scaled min and max. `limits` repeats those numbers and cites `wiki1`. Parameters cite `wiki1` only.
- For every unit except percent, `nominal` is the midpoint of the scaled limits. A percent row is a spread around the part value, so its unit is `1` and its nominal is 0.
- Plus or minus x is stored as min -x and max +x. Plus or minus 1 percent is min -1 and max 1, which scales to limits -0.01 and 0.01.
- Maturity is `"0.1"`.
- The license is copied from the page. A page with no license is an input error.
- No datasheet hash is written. The datasheet is not downloaded.
- A row is keyed by name, symbol, kind, and conditions. The unit is not part of the key, so the same spec in `µA` and `nA` stays two rows and is not merged.
- Parameter names come from the symbol of each usable row, in order. `VGS(th)` becomes `vgs_th`. A second usable row with the same symbol gets `_2`, then `_3`. Skipped rows do not take a name.
- Condition text is read only for `temperature_c`, `frequency_hz`, `vgs_v`, `vds_v`, `vds_eq_vgs`, and `id_a`. The left-hand side must be `T`, `f`, `VGS`, `VDS`, or `ID`. `VDS = VGS` sets `vds_eq_vgs` and does not invent a voltage. A range, a conflicting repeat, or plain prose is left out. If nothing parses, the parameter has no `conditions` key.
- The basis quotes the row name, symbol, kind, conditions, and datasheet page, and says the shape was not published.
- Drafts live in `out/` and are never committed.
