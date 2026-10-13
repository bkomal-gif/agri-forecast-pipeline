"""Stage 2 - Quality control.

Principle: for time-sensitive farmer advice, a wrong message is worse than a late
one. If any day inside the advisory horizon fails an *error* check, that
location is held back (no message) and the issue is logged for the ops team.
Problems outside the horizon only raise warnings.

Checks
- completeness : every location has the expected number of days
- missing      : a required variable is null
- range        : value is physically implausible (bounds in rules config)
- consistency  : tmin > tmax
- freshness    : first forecast date is not the run date (stale feed)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .models import DailyForecast, Location, QCIssue

REQUIRED = ["tmax_c", "tmin_c", "precip_mm", "precip_prob_pct", "wind_max_kmh"]


@dataclass
class QCResult:
    clean: dict[str, list[DailyForecast]]       # location_id -> usable days, date-sorted
    blocked: set[str]                           # location_ids held back from messaging
    issues: list[QCIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[QCIssue]:
        return [i for i in self.issues if i.level == "error"]


def run_qc(records: list[DailyForecast], locations: list[Location], run_date: date,
           expected_days: int, horizon_days: int, bounds: dict) -> QCResult:
    by_loc: dict[str, list[DailyForecast]] = defaultdict(list)
    for r in records:
        by_loc[r.location_id].append(r)

    issues: list[QCIssue] = []
    clean: dict[str, list[DailyForecast]] = {}
    blocked: set[str] = set()

    for loc in locations:
        days = sorted(by_loc.get(loc.id, []), key=lambda r: r.date)
        loc_issues: list[QCIssue] = []

        if len(days) != expected_days:
            loc_issues.append(QCIssue(loc.id, None, "completeness", "error",
                                      f"expected {expected_days} days, got {len(days)}"))
        if days and days[0].date != run_date:
            loc_issues.append(QCIssue(loc.id, days[0].date.isoformat(), "freshness", "error",
                                      f"first forecast day {days[0].date} != run date {run_date}"))

        good_days = []
        for r in days:
            offset = (r.date - run_date).days
            in_horizon = 0 <= offset < horizon_days
            level = "error" if in_horizon else "warning"
            day_ok = True
            for var in REQUIRED:
                v = getattr(r, var)
                if v is None:
                    loc_issues.append(QCIssue(loc.id, r.date.isoformat(), "missing", level,
                                              f"{var} is null"))
                    day_ok = False
                    continue
                lo, hi = bounds[var]
                if not lo <= v <= hi:
                    loc_issues.append(QCIssue(loc.id, r.date.isoformat(), "range", level,
                                              f"{var}={v} outside [{lo}, {hi}]"))
                    day_ok = False
            if r.tmin_c is not None and r.tmax_c is not None and r.tmin_c > r.tmax_c:
                loc_issues.append(QCIssue(loc.id, r.date.isoformat(), "consistency", level,
                                          f"tmin {r.tmin_c} > tmax {r.tmax_c}"))
                day_ok = False
            if day_ok:
                good_days.append(r)

        issues.extend(loc_issues)
        if any(i.level == "error" for i in loc_issues):
            blocked.add(loc.id)
        else:
            clean[loc.id] = good_days

    return QCResult(clean=clean, blocked=blocked, issues=issues)
