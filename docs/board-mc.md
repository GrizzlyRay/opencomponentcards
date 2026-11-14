# Resolving a board and running Monte Carlo

`tools/board_mc.py` reads a BOM and a KiCad SPICE netlist, finds a card for each refdes, rewrites matched passive values to `{p_<refdes>_<param>}`, and runs ngspice through `tools/spice_export.py`.

The BOM is a CSV. Required columns are `refdes`, `mpn`, `manufacturer`, and `value`. Optional columns are `tolerance` and `adom_slug`. One cell may hold `R1-R4` or `R1,R2`. A bad range or a duplicate refdes, compared without regard to case, names its line and the command exits 2.

Each row is resolved in this order:

1. A card already in `cards/`. The MPN matches without regard to case, and spaces and dashes are ignored. When the row names a manufacturer, the card manufacturer has to match the same way.
2. An Adom draft, and only when `--allow-adom` is set and the row has `adom_slug`. The draft is written under the board directory in `out/`.
3. A tolerance card, and only when `--allow-fallback` is set, the row has a value and a tolerance, and the refdes is a resistor, capacitor, or inductor. The spread is uniform over the value plus or minus the tolerance. Maturity is `0.1`, confidence is low, the license is `CC-BY-4.0`, and the author is Jacob Warren and GrizzlyRay LLC. The note is `fallback from BOM tolerance, not from a datasheet`. The file is `<out>/cards/<refdes>.yaml`.
4. Otherwise the row is unresolved.

`--allow-adom` and `--allow-fallback` default off. An Adom slug or a tolerance-only row is then unresolved. Calling `resolve()` from Python still defaults both arguments on, so a direct caller keeps the earlier order. The command line passes both as false.

Netlist matching compares BOM refdes to element instance names whose first letter is `R`, `C`, `L`, `D`, `Q`, or `M`. The comparison ignores case. Comments, dot cards, names inside a `.subckt` body, and lines inside a `.control` block are not board parts. A control-mode `meas` command starts with `M` and is not counted as a MOSFET.

Binding rewrites a matched resistor, capacitor, or inductor value to `{p_<refdes>_<param>}` from `spice_export.param_name`. The parameter is the card's only primary name among `resistance`, `capacitance`, and `inductance`. The card file is read. Zero primaries, or more than one, leave the element as written and record the reason. `.subckt` bodies, models, and unmatched elements stay as written.

Unresolved parts, or a refdes present on only one side, exit 2. The message lists the unresolved rows, `bom_not_in_netlist`, and `netlist_not_in_bom` before any simulation. With the defaults, that exit writes no deck and no fallback card. A resistor, capacitor, or inductor that resolved to a card but could not be bound also exits 2 before ngspice starts.

Sampling, the ngspice workers, `results.csv`, and `summary.txt` are the SPICE exporter's. `board_report.md` lists each part, how it was found, and a warning for every fallback card and every Adom draft.

ngspice-47 cannot parse `vdb()` or `vm()` on a `.meas` card. Use a `meas` command inside `.control`. The RC fixture uses `meas ac f3db WHEN vdb(out)=-3.0103`. See [docs/spice-export.md](spice-export.md).

This command runs ngspice only. LTspice decks are written by `tools/spice_export.py` with `--sim ltspice`, and those decks are not yet tested in LTspice.

## Command line

```bash
python3 tools/board_mc.py --bom PATH --netlist PATH --runs N --seed N [--jobs N] [--spec NAME=lo:hi] [--allow-adom] [--allow-fallback] [--out PATH]
```

Pass `-h` or `--help` to print these flags and exit.

| Flag | Meaning |
|---|---|
| `-h`, `--help` | Print the flags and exit. |
| `--bom` | Required. BOM csv path. |
| `--netlist` | Required. KiCad SPICE netlist path. |
| `--runs` | Required. A positive integer. |
| `--seed` | Required. Integer seed for every card's RNG. |
| `--jobs` | ngspice workers. Default 1. A positive integer. |
| `--spec` | `NAME=lo:hi` yield limit. Repeatable. `NAME` is a meas name from the netlist, and `lo` is less than `hi`. |
| `--allow-adom` | Import `adom_slug` rows. Off unless this flag is set. |
| `--allow-fallback` | Build a tolerance card when no local card matches. Off unless this flag is set. |
| `--out` | Directory inside `out/`. Default `out/board/<bom stem>`. |

The flags above are the ones `argparse` registers, including `-h` and `--help`. Each ngspice run is limited to 60 seconds.

`--out` must be a directory inside `out/`. `out/` itself is refused. A relative path is resolved from the current directory, so `out/../cards/somewhere` is refused. An existing path that is not a directory is an input error.

| Exit | Meaning |
|---|---|
| 0 | Every run is ok. |
| 1 | One or more ngspice runs failed. `results.csv`, `summary.txt`, and `board_report.md` are still written. The failure line goes to stderr. |
| 2 | Input problem. Covers a bad flag, a missing file, a bad BOM, `--out` outside `out/`, unresolved parts, a netlist mismatch, a passive that could not be bound, or `ngspice` missing from `PATH`. The error line goes to stderr. |

With `--allow-adom` or `--allow-fallback`, resolution can write a draft or a fallback card before a mismatch exits 2. The ngspice run still does not start.

## Measurements

ngspice-47 `.meas` cannot parse `vdb` or `vm`. `vdb()` and `vm()` are accepted on the `meas` command inside `.control`, which is why the fixture measures `vdb(out)` there. A `.meas` card that reads `v(out)` sees the real part, so `WHEN v(out)=0.5` is the cutoff only for the unity-gain low-pass in the fixture.

## LTspice

`board_mc.py` does not write an LTspice deck. `tools/spice_export.py --sim ltspice` does. That deck is written and is not yet tested in LTspice. The opening comment in `ltspice.cir` says so, and the exporter does not start LTspice.

## Safe defaults

`--allow-adom` and `--allow-fallback` are off unless you set them. A default run does not contact Adom and does not invent a tolerance card. Rows that would need either path are unresolved and the command exits 2 before simulation. Output that does get written stays under `out/` and is not committed.
