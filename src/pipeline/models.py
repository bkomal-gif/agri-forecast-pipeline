"""Core data contracts shared by every pipeline stage.

Every stage consumes and produces these types, so a new forecast source or a new
dissemination channel only has to speak this vocabulary - nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date


@dataclass(frozen=True)
class Location:
    """A delivery unit (district, block, village cluster) defined in region config."""
    id: str
    name: str
    lat: float
    lon: float
    language: str = "en"
    names: dict[str, str] = field(default_factory=dict)  # localized display names

    def display_name(self, language: str) -> str:
        return self.names.get(language, self.name)


@dataclass(frozen=True)
class DailyForecast:
    """One forecast day at one location, in canonical units.

    Units: temperatures in degC, precipitation in mm/day, probability in %,
    wind speed in km/h (daily max at 10 m).
    """
    location_id: str
    date: date
    tmax_c: float | None
    tmin_c: float | None
    precip_mm: float | None
    precip_prob_pct: float | None
    wind_max_kmh: float | None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d


@dataclass(frozen=True)
class Advisory:
    """A triggered rule: what to tell the farmer, how urgently, and why."""
    code: str
    severity: str          # info | medium | high | critical
    priority: int          # lower number = more important
    day_offset: int | None  # 0 = run day; None = applies to whole horizon
    date: date | None
    params: dict           # values rendered into the template (precip, tmax, ...)
    rule_id: str           # which rule fired - kept for audit trail


@dataclass
class QCIssue:
    location_id: str
    date: str | None
    check: str
    level: str   # "error" blocks messaging for the location, "warning" does not
    detail: str
