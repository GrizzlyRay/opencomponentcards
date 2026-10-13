# Real-Data Cards

These are the first OpenComponentCards built from real datasheet data, not assumptions.

Both cards were built by **Drew Owens** at **Adom** ([wiki.adom.inc](https://wiki.adom.inc)) from Adom wiki component pages, and they're used here with his permission. Every value is a published datasheet limit with its page number, and each card links the mirrored datasheet PDF by sha256. See Drew's page for the full write-up and his v0.2 notes: [Community: Open Component Cards](https://wiki.adom.inc/drew2/community-open-component-cards).

| Card | Part | Source page |
|---|---|---|
| `royalohm-0603waf470kt5e.yaml` | Royalohm 0603WAF470KT5E, 4.7 Ohm 1% 0603 resistor | [adom/0603waf470kt5e](https://wiki.adom.inc/adom/0603waf470kt5e) |
| `samsung-cl21a475kaqnnng.yaml` | Samsung CL21A475KAQNNNG, 4.7 uF 10% X5R 25 V 0805 MLCC | [adom/cl21a475kaqnnng](https://wiki.adom.inc/adom/cl21a475kaqnnng) |

The datasheets don't publish distribution shapes, so each spread is a uniform over the published limit.

Both cards were converted from Drew's original v0.1 cards to the v0.2 `distributions` list. Only the structure changed; every value, basis, and attribution is the same. See [docs/migration-v0.1-to-v0.2.md](../../docs/migration-v0.1-to-v0.2.md).

License: CC-BY-4.0. Please credit Drew Owens and Adom (wiki.adom.inc) when you reuse these cards.

Thanks, Drew!
