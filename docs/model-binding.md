# Model binding

`model_binding` tells an exporter how a sampled card value changes a parameter in the referenced model file. Since v0.2 (in progress), `transform` is structured so a tool can apply it without a person reading the note. Suggested by Drew Owens (#6).

```yaml
model_binding:
  param: VTO                     # parameter name in the model file
  transform: { type: offset, reference: 1.8, param_unit: V }
  note: "Optional prose for humans."
```

Here `x` is the sampled card value, `P_file` is the value in the model file, and `P_new` is what the exporter writes.

| type | formula | required fields | optional fields |
| --- | --- | --- | --- |
| `offset` | `P_new = P_file + (x - reference)` | none | `reference` (defaults to `nominal`), `param_unit` |
| `scale` | `P_new = P_file * (x / reference)` | none | `reference` (defaults to `nominal`, can't be 0), `param_unit` |
| `replace` | `P_new = x` | none | `param_unit` |
| `affine` | `P_new = factor * x + offset` | `factor`, `offset` | `param_unit` |

## Validator checks

- Required fields for each type are present, and fields a type doesn't use are errors.
- For `offset` and `replace`, `param_unit` must match the card's `unit`. Use `affine` when the model needs a unit conversion (for example `factor: 1.0e-3` for mV to V). `scale` is a ratio, so any unit works.
- A missing `param_unit` on `offset` or `replace` warns and assumes the card unit.

## Backward compatibility

A plain string `transform` (the v0.1 form) still passes, but the validator warns and suggests the structured type. `note` is now optional.
