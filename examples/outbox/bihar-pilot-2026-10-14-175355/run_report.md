# Run report: bihar-pilot-2026-10-14-175355

- Source: `synthetic`  |  Run date: 2026-10-14  |  Status: **degraded**
- Locations messaged: 3 / 4  |  Payloads: 6
- Stage latency (ms): ingest 0.7, qc 0.1, rules_and_compose 0.4, render_channels 0.5, write_outbox 0.7

## Quality-control issues

| Location | Date | Check | Level | Detail |
|---|---|---|---|---|
| br-muzaffarpur | 2026-10-15 | range | error | precip_mm=-999.0 outside [0, 500] |
| br-muzaffarpur | 2026-10-17 | missing | warning | tmax_c is null |

**Held back (no message sent):** br-muzaffarpur

## Advisories by location

### Patna (hi)
- [critical] परसों बहुत भारी बारिश (132 मिमी) की संभावना। छिड़काव या खाद न डालें। खेत से पानी निकालें और कटी फसल को सुरक्षित रखें।  _(rule `rain.very_heavy.imd`)_
- [high] कल भारी बारिश (78 मिमी) की संभावना। छिड़काव और खाद डालना टालें। खेत की नालियाँ खुली रखें।  _(rule `rain.heavy.imd`)_
- SMS: UCS-2, 2 segment(s), headline text, 0 advisory(ies) dropped to fit

### Purnia (en)
- [critical] Today: heat wave (max 45°C). Avoid field work 12-4 pm. Give animals shade and water.  _(rule `heat.heatwave.imd_absolute`)_
- SMS: GSM-7, 1 segment(s), full text, 0 advisory(ies) dropped to fit

### Gaya (hi)
- [high] परसों तेज़ हवा (44 किमी/घंटा)। छिड़काव न करें। ऊँची और बेल वाली फसलों को सहारा दें।  _(rule `wind.strong`)_
- [medium] परसों मध्यम बारिश (24 मिमी) की संभावना। सिंचाई न करें।  _(rule `rain.moderate.imd`)_
- SMS: UCS-2, 2 segment(s), headline text, 0 advisory(ies) dropped to fit
