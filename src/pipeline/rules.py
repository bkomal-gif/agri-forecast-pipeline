"""Stage 3 - Decision logic: turn forecast numbers into farmer advisories.

Rules are *declarative* (config/rules.yaml), not code. The field research team
can change a threshold, add a rule or retire one through a reviewed config
change, without an engineer touching the pipeline. Every advisory carries the
id of the rule that produced it, so any message can be traced back to the exact
threshold and forecast values behind it.

Rule scopes
- any_day : fires on the EARLIEST day within the horizon where all conditions hold
- horizon : conditions are aggregates (sum/max/min) over the whole horizon
"""
from __future__ import annotations

import math
import operator
from datetime import date

from .models import Advisory, DailyForecast

OPS = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt,
    ">=": operator.ge, "==": operator.eq,
}
AGGS = {"sum": sum, "max": max, "min": min}


def _day_view(days: list[DailyForecast], i: int) -> dict:
    """Values for day i plus derived look-ahead fields."""
    d = days[i]
    view = {
        "tmax_c": d.tmax_c, "tmin_c": d.tmin_c, "precip_mm": d.precip_mm,
        "precip_prob_pct": d.precip_prob_pct, "wind_max_kmh": d.wind_max_kmh,
    }
    # Look-ahead: spraying is wasted if rain arrives within ~24 h.
    nxt = days[i + 1] if i + 1 < len(days) and (days[i + 1].date - d.date).days == 1 else None
    view["precip_next_day_mm"] = nxt.precip_mm if nxt else None
    return view


def _check(value, op: str, threshold) -> bool:
    # Unknown values never satisfy a condition: we do not advise on missing data.
    return value is not None and OPS[op](value, threshold)


def evaluate(days: list[DailyForecast], run_date: date, rules_cfg: dict) -> list[Advisory]:
    horizon = rules_cfg["horizon_days"]
    window = [d for d in days if 0 <= (d.date - run_date).days < horizon]
    fired: list[Advisory] = []

    for rule in rules_cfg["rules"]:
        scope = rule.get("scope", "any_day")
        if scope == "any_day":
            for i, d in enumerate(window):
                view = _day_view(window, i)
                if all(_check(view.get(c["field"]), c["op"], c["value"]) for c in rule["when"]):
                    fired.append(Advisory(
                        code=rule["advisory"], severity=rule["severity"],
                        priority=rule["priority"], day_offset=(d.date - run_date).days,
                        date=d.date, params=_round(view), rule_id=rule["id"]))
                    break
        elif scope == "horizon":
            if len(window) < horizon:
                continue  # an aggregate over a partial horizon would be misleading
            ok, params = True, {"horizon": horizon}
            for c in rule["when"]:
                vals = [getattr(d, c["field"]) for d in window]
                if any(v is None for v in vals):
                    ok = False
                    break
                agg = AGGS[c["agg"]](vals)
                params[f"{c['agg']}_{c['field']}"] = agg
                ok = ok and _check(agg, c["op"], c["value"])
            if ok:
                fired.append(Advisory(
                    code=rule["advisory"], severity=rule["severity"], priority=rule["priority"],
                    day_offset=None, date=None, params=_round(params), rule_id=rule["id"]))
        else:
            raise ValueError(f"rule {rule['id']}: unknown scope '{scope}'")

    return sorted(_apply_suppression(fired, rules_cfg),
                  key=lambda a: (a.priority, a.day_offset if a.day_offset is not None else 99))


def _apply_suppression(fired: list[Advisory], rules_cfg: dict) -> list[Advisory]:
    """A stronger advisory silences weaker or contradictory ones - but only from
    its own day onward.

    Why the day check matters: if heavy rain arrives tomorrow and very heavy rain
    the day after, a naive 'very heavy suppresses heavy' rule would hide the fact
    that rain STARTS tomorrow - exactly the lead time farmers need. So a weaker
    advisory is suppressed only if it falls on or after the stronger one's day.
    Horizon-wide advisories (day_offset None) are suppressed whenever the
    stronger advisory fires at all.
    """
    by_code = {r["advisory"]: r for r in rules_cfg["rules"]}
    keep = []
    for weak in fired:
        silenced = False
        for strong in fired:
            if weak.code not in by_code[strong.code].get("suppresses", []):
                continue
            if (weak.day_offset is None or strong.day_offset is None
                    or weak.day_offset >= strong.day_offset):
                silenced = True
                break
        if not silenced:
            keep.append(weak)
    return keep


def _round(params: dict) -> dict:
    # Half-up rounding for display. Python's round() is banker's rounding, which
    # would print 64.5 mm (the IMD 'heavy' threshold) as "64 mm" - confusing next
    # to a heavy-rain alert. Thresholds are always checked on unrounded values.
    return {k: (math.floor(v + 0.5) if isinstance(v, float) else v) for k, v in params.items()}
