# Sampling cards into SPICE

`tools/spice_export.py` reads a netlist and one or more component cards and writes plain SPICE numbers. Every random draw comes from `random.Random` seeded by `--seed`. The deck holds numbers in the card's unit. It does not call `agauss`, `gauss`, `unif`, `mc`, or `flat`.

A bound value in the netlist is a placeholder `{p_<refdes>_<param>}`, for example `{p_r1_resistance}`. Lot scope is drawn once per run and shared by every instance. Device scope and total scope are drawn once per instance. Lot and device combine as in [docs/lot-device-spread.md](lot-device-spread.md). Truncation belongs to the distribution entry it is written on. Published `limits` and `final_limits` apply to the combined value: a sample outside them is rejected and drawn again. The tool does not clamp. Dependence curves are not evaluated. An empirical distribution that names `samples_uri` is refused, because the sample file is not fetched.

With `--sim ngspice`, the default, the tool writes one `.cir` and one `.param` per run, then starts `ngspice -b` from an argument list. `shell` is false. With `--sim ltspice`, the tool writes one `ltspice.cir` and does not start a simulator. LTspice decks are written but not yet tested in LTspice.

`--allow-adom` and `--allow-fallback` are not flags of this tool. They belong to `tools/board_mc.py`, where both default off. This exporter samples only the cards passed with `--bind`. It does not contact Adom, and it does not build a fallback card.

Decks are written under `out/`. That directory is gitignored, so a generated deck is not committed.

## Command line

```bash
python3 tools/spice_export.py --netlist PATH --bind REFDES=CARD --runs N --seed N [--jobs N] [--sim ngspice|ltspice] [--spec NAME=lo:hi] [--out PATH] [--timeout SECONDS]
```

Pass `-h` or `--help` to print these flags and exit.

| Flag | Meaning |
|---|---|
| `-h`, `--help` | Print the flags and exit. |
| `--netlist` | Required. Netlist path. `{p_<refdes>_<param>}` marks a bound value. |
| `--bind` | `REFDES=path/to/card.yaml`. Repeatable. At least one is required. |
| `--runs` | Required. A positive integer. |
| `--seed` | Required. Integer seed for every card's RNG. |
| `--jobs` | ngspice workers. Default 1. A positive integer. Accepted for LTspice and not used there. |
| `--sim` | `ngspice` or `ltspice`. Default `ngspice`. |
| `--spec` | `NAME=lo:hi` yield limit. Repeatable. `NAME` is a meas name from the netlist, and `lo` is less than `hi`. |
| `--out` | Directory inside `out/`. Default `out/spice/<netlist stem>`. |
| `--timeout` | Seconds for each ngspice run. Default 60. Finite and greater than zero. |

The flags above are the ones `argparse` registers, including `-h` and `--help`.

`--out` must be a directory inside `out/`. `out/` itself is outside the rule and is refused. A relative path is resolved from the current directory, so `out/../cards/somewhere` is refused before a deck is written. An existing path that is not a directory is an input error.

A missing required flag, a bad value, a missing `--bind`, a missing netlist, a bad card, a binding mismatch, or `ngspice` missing from `PATH` when `--sim` is `ngspice` is an input error. The error line goes to stderr. A binding mismatch names both lists: netlist parameters with no binding, and bound parameters not used in the netlist. An empty list is written as `(none)`.

| Exit | Meaning |
|---|---|
| 0 | Every ngspice run is ok, or an LTspice deck was written. |
| 1 | One or more ngspice runs failed. `results.csv` and `summary.txt` are still written. |
| 2 | Input problem. No deck is written. |

## Measurements

ngspice-47 cannot parse `vdb()` or `vm()` on a `.meas` card. The same request works as a `meas` command inside `.control`. A leading dot is optional, so a `.meas` card and a control-mode `meas` command are both recorded. The RC fixture finds the -3 dB point with:

```
.control
ac dec 100 0.1 100
meas ac f3db WHEN vdb(out)=-3.0103
.endc
```

`WHEN v(out)=0.5` lands on that cutoff only for this unity-gain low-pass. A `.meas` card reads `v(out)` as the real part. On that circuit the real part is 0.5 at the same frequency where the magnitude is `1/sqrt(2)`.

## Output

Each ngspice run writes `run_NNNN.cir`, `run_NNNN.param`, and `run_NNNN.log`. The shared files are `results.csv` and `summary.txt`. The `.cir` includes its `.param` file before the netlist. Each `.param` line is a plain number. The header records the seed and the 1-based run.

`results.csv` has one row per run. The columns are `run`, `seed`, the sampled parameters, the meas names, and `status`. `summary.txt` gives count, failed, min, max, mean, and the sample standard deviation for each meas. A `--spec` adds a yield line. A failed run counts as outside the spec.

ngspice is invoked as `ngspice -b -o run_NNNN.log run_NNNN.cir` with the deck directory as the working directory. A timeout is recorded on that run and the other runs continue.

## LTspice

`--sim ltspice` writes `ltspice.cir`, `results.csv`, and `summary.txt`, then exits 0. The deck uses `.step param run` and a `.param` table of plain numbers for each bound name. The opening comment says the deck is untested in LTspice. The simulator is not started. LTspice decks are written but not yet tested in LTspice. The summary begins with `LTspice was not run.` and the meas counts stay at zero. Each csv row has status `written`.

## Safe defaults

On `tools/board_mc.py`, `--allow-adom` and `--allow-fallback` are off unless the flag is present. This exporter has neither switch. It samples the `--bind` cards only. Decks stay in `out/` and are not committed.
