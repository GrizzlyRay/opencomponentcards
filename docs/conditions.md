# Standard conditions keys

`conditions` (on a parameter) and `limits.conditions` record the test conditions a value or limit was published at. A shared set of keys lets tools compare cards from different authors. Units are part of the key name, so values are plain numbers.

| Key | Type | Meaning |
|---|---|---|
| `temperature_c` | number | Ambient or case temperature, degC |
| `temperature_min_c` | number | Low end of a temperature range, degC |
| `temperature_max_c` | number | High end of a temperature range, degC |
| `reference_span_c` | [number, number] | Temperature span a coefficient is defined over, degC |
| `frequency_hz` | number | Measurement frequency, Hz |
| `ac_vrms` | number | AC test signal level, Vrms |
| `dc_bias_v` | number | DC bias voltage across the part, V |
| `bias_v` | number | Accepted alias for `dc_bias_v`, kept so v0.1 cards stay clean. Prefer `dc_bias_v` in new cards. |
| `vgs_v` | number | Gate-source voltage, V |
| `vds_v` | number | Drain-source voltage, V |
| `vds_eq_vgs` | boolean | Drain tied to gate (VDS = VGS), as in threshold tests |
| `id_a` | number | Drain current, A |
| `humidity_pct` | number | Relative humidity, % (0 to 100) |
| `duration_h` | number | Test or stress duration, hours |
| `preconditioning` | string | Free text, e.g. "150 C for 1 h, then 24 h rest (p.2)" |

## Example

```yaml
conditions: { frequency_hz: 1000, ac_vrms: 1.0, dc_bias_v: 0, preconditioning: "150 C for 1 h, then 24 h rest" }
```

## Other keys

Other keys are still allowed, so older cards keep passing. The validator prints a warning for each non-standard key and suggests the closest standard one, e.g. `temp_c` gets "did you mean 'temperature_c'?". If you need a key that isn't here, open an issue so it can be added.

The list came from the keys Drew Owens (Adom) used in the first real-data cards (#3).
