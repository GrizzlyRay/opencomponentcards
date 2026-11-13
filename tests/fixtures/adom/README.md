# Synthetic Adom page fixtures

Every file here is synthetic. The values are invented. The JSON is shaped like an Adom wiki `page.json`: `owner`, `slug`, `license`, `component`, and spec rows under `metadata.characteristics.rows`. Importer tests can load these files with no network.

Real Adom pages must not be committed here. Pages from wiki.adom.inc are someone else's content, under that wiki's license, and they change. Keep any downloaded page out of git.

`owner` and `slug` on every file start with `synthetic-`. Each file has `_note` set to `synthetic test fixture, invented values, not from wiki.adom.inc`.

## synthetic-mosfet.json

Example Semi transistor page. License `CC-BY-SA-4.0`. Category `Transistor`.

- Two `RDS(on)` rows share name, symbol, and kind. Only `conditions` differs (`VGS = 4.5V, ID = 5A` and `VGS = 10V, ID = 10A`). The unit is `Ω` (U+03A9 GREEK CAPITAL LETTER OMEGA).
- `IDSS` is stored twice, in `µA` (U+00B5 MICRO SIGN) and in `nA`.
- `IGSS` is in `μA` (U+03BC GREEK SMALL LETTER MU), a different code point from the micro sign on `IDSS`.
- `RG` is in `Ω` (U+2126 OHM SIGN), a different code point from the omega on `RDS(on)`.
- `gFS` is in `mS`, and `RθJA` is in `°C/W` (U+00B0 DEGREE SIGN). Neither unit is in the card unit list.
- `VDSS` is max-only (`min` and `typ` null). `Coss` is typ-only (`min` and `max` null). The `IDSS` rows are max-only as well.
- Kinds include `absolute_maximum` (`VDSS`), `recommended_operating` (`VGS`), and `thermal` (`RθJA`).
- `VSW` has `min` greater than `max`.
- `VGS(th)` has `min` and `max`. Its conditions are `VDS = VGS, ID = 250µA`, with U+00B5 in `µA`.

## synthetic-passive.json

Resistor page. License `CC-BY-SA-4.0`. Category `Resistor`.

- Tolerance row in `%`, `min` -1, `max` 1.
- `temperature_coefficient` row in `ppm/℃` (U+2103 DEGREE CELSIUS), `min` -100, `max` 100.
- Resistance row in `kΩ` (U+03A9).
- Capacitance row in `nF`.
- A `voltage_coefficient` row.
- A `timing` row in `ns`.

## synthetic-no-manufacturer.json

Same page shape, with `component.manufacturer` set to `""`.

## synthetic-no-rows.json

Component identity is present. There is no `metadata.characteristics` object.

## synthetic-no-license.json

Same JSON as `synthetic-passive.json` with the `license` field removed and no other change. The slug stays `synthetic-passive` so the missing field is the only difference.
