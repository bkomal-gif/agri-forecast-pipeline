# Run report: up-pilot-2026-10-14-175355

- Source: `synthetic`  |  Run date: 2026-10-14  |  Status: **ok**
- Locations messaged: 4 / 5  |  Payloads: 16
- Stage latency (ms): ingest 0.6, qc 0.2, rules_and_compose 0.4, render_channels 1.5, write_outbox 1.4

## Quality-control issues

| Location | Date | Check | Level | Detail |
|---|---|---|---|---|
| up-bahraich | 2026-10-15 | range | error | precip_mm=-999.0 outside [0, 500] |
| up-bahraich | 2026-10-17 | missing | warning | tmax_c is null |

**Held back (no message sent):** up-bahraich

## Advisories by location

### Varanasi (hi)
- [critical] परसों बहुत भारी बारिश (132 मिमी) की संभावना। छिड़काव या खाद न डालें। खेत से पानी निकालें और कटी फसल को सुरक्षित रखें।  _(rule `rain.very_heavy.imd`)_
- [high] कल भारी बारिश (78 मिमी) की संभावना। छिड़काव और खाद डालना टालें। खेत की नालियाँ खुली रखें।  _(rule `rain.heavy.imd`)_
- SMS: UCS-2, 2 segment(s), headline text, 0 advisory(ies) dropped to fit

### Lucknow (hi)
- [critical] आज लू (अधिकतम 45°C)। दोपहर 12 से 4 बजे तक खेत में काम न करें। पशुओं को छाया और पानी दें।  _(rule `heat.heatwave.imd_absolute`)_
- [info] अगले 3 दिन बारिश की संभावना नहीं। मिट्टी सूखी हो तो सिंचाई करें।  _(rule `dry.no_rain_horizon`)_
- [info] कल छिड़काव के लिए मौसम अच्छा है।  _(rule `ops.spray_window`)_
- SMS: UCS-2, 2 segment(s), headline text, 0 advisory(ies) dropped to fit

### Gorakhpur (hi)
- [high] परसों तेज़ हवा (44 किमी/घंटा)। छिड़काव न करें। ऊँची और बेल वाली फसलों को सहारा दें।  _(rule `wind.strong`)_
- [medium] परसों मध्यम बारिश (24 मिमी) की संभावना। सिंचाई न करें।  _(rule `rain.moderate.imd`)_
- [info] आज छिड़काव के लिए मौसम अच्छा है।  _(rule `ops.spray_window`)_
- SMS: UCS-2, 3 segment(s), full text, 0 advisory(ies) dropped to fit

### Jhansi (hi)
- अगले 3 दिन मौसम से कोई खतरा नहीं। खेती का काम सामान्य रूप से करें।
- SMS: UCS-2, 2 segment(s), full text, 0 advisory(ies) dropped to fit
