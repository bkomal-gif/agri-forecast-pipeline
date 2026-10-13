"""Stage 1 - Ingest: fetch raw forecast data and normalize it to DailyForecast.

Design: every source returns the *raw* payload (kept for the audit trail) plus a
parsed list of DailyForecast objects. Swapping Open-Meteo for IMD, NCMRWF or a
partner's gridded product means writing one new class with a `fetch` method;
QC, rules, templating and channels are untouched.
"""
from __future__ import annotations

import json
import math
import random
import time
from datetime import date, timedelta
from typing import Protocol

from .models import DailyForecast, Location

DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
]

# Maps source variable names onto the canonical DailyForecast fields.
FIELD_MAP = {
    "temperature_2m_max": "tmax_c",
    "temperature_2m_min": "tmin_c",
    "precipitation_sum": "precip_mm",
    "precipitation_probability_max": "precip_prob_pct",
    "wind_speed_10m_max": "wind_max_kmh",
}


class ForecastSource(Protocol):
    name: str

    def fetch(self, locations: list[Location], run_date: date, days: int) -> list[dict]:
        """Return one raw payload per location, in the same order as `locations`."""
        ...


def parse_open_meteo(payloads: list[dict], locations: list[Location]) -> list[DailyForecast]:
    """Parse Open-Meteo-shaped daily payloads into canonical records.

    Missing values are kept as None (not dropped) so QC can report them explicitly.
    """
    if len(payloads) != len(locations):
        raise ValueError(f"expected {len(locations)} payloads, got {len(payloads)}")
    records: list[DailyForecast] = []
    for loc, payload in zip(locations, payloads):
        daily = payload.get("daily") or {}
        times = daily.get("time") or []
        for i, t in enumerate(times):
            values = {}
            for src, dst in FIELD_MAP.items():
                series = daily.get(src) or []
                values[dst] = series[i] if i < len(series) else None
            records.append(DailyForecast(location_id=loc.id, date=date.fromisoformat(t), **values))
    return records


class OpenMeteoSource:
    """Live global NWP forecast via the Open-Meteo API (no key needed).

    Note: Open-Meteo's free tier is for non-commercial use. A production deployment
    would swap in IMD / NCMRWF feeds behind the same interface.
    """
    name = "open-meteo"
    URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, timeout_s: float = 20, retries: int = 3, backoff_s: float = 2.0):
        self.timeout_s = timeout_s
        self.retries = retries
        self.backoff_s = backoff_s

    def fetch(self, locations: list[Location], run_date: date, days: int) -> list[dict]:
        import requests  # imported lazily so offline runs and tests don't need network libs

        params = {
            # One batched request for all locations: one round-trip instead of N.
            "latitude": ",".join(f"{l.lat:.4f}" for l in locations),
            "longitude": ",".join(f"{l.lon:.4f}" for l in locations),
            "daily": ",".join(DAILY_VARS),
            "timezone": "Asia/Kolkata",
            "forecast_days": days,
            "wind_speed_unit": "kmh",
        }
        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = requests.get(self.URL, params=params, timeout=self.timeout_s)
                resp.raise_for_status()
                data = resp.json()
                # The API returns an object for one location, a list for several.
                return data if isinstance(data, list) else [data]
            except Exception as err:  # network, HTTP or JSON errors
                last_err = err
                if attempt < self.retries:
                    time.sleep(self.backoff_s * 2 ** (attempt - 1))
        raise RuntimeError(f"Open-Meteo fetch failed after {self.retries} attempts: {last_err}")


class SyntheticSource:
    """Deterministic, physically plausible forecasts in the exact Open-Meteo shape.

    Used for offline demos and tests. It injects scripted events (a heavy-rain
    spell, a heat spike, a windy day) so every rule path is exercised, plus an
    optional corrupted record so the QC stage has something real to catch.
    """
    name = "synthetic"

    def __init__(self, seed: int = 42, inject_bad_record: bool = True):
        self.seed = seed
        self.inject_bad_record = inject_bad_record

    def fetch(self, locations: list[Location], run_date: date, days: int) -> list[dict]:
        payloads = []
        for idx, loc in enumerate(locations):
            rng = random.Random(f"{self.seed}-{loc.id}-{run_date.isoformat()}")
            daily = {"time": [], **{v: [] for v in DAILY_VARS}}
            # Gentle north-south gradient so locations differ realistically.
            base_tmax = 33.0 - 0.6 * (loc.lat - 25.0)
            for d in range(days):
                day = run_date + timedelta(days=d)
                tmax = base_tmax + 1.5 * math.sin(d / 2) + rng.uniform(-1, 1)
                tmin = tmax - rng.uniform(9, 12)
                precip = max(0.0, rng.gauss(1.0, 2.0))
                prob = min(100.0, precip * 12 + rng.uniform(0, 15))
                wind = rng.uniform(6, 14)
                scenario = idx % 4
                if scenario == 0 and d in (1, 2):      # heavy -> very heavy spell
                    precip = 78.0 if d == 1 else 132.0
                    prob, wind = 90.0, 28.0
                elif scenario == 1 and d == 0:          # pre-monsoon style heat spike
                    tmax, tmin = 45.4, 31.0
                elif scenario == 2 and d == 2:          # moderate rain + squally wind
                    precip, prob, wind = 24.0, 70.0, 44.0
                # scenario 3: fair weather -> spray window / dry spell advisories
                daily["time"].append(day.isoformat())
                daily["temperature_2m_max"].append(round(tmax, 1))
                daily["temperature_2m_min"].append(round(tmin, 1))
                daily["precipitation_sum"].append(round(precip, 1))
                daily["precipitation_probability_max"].append(round(prob))
                daily["wind_speed_10m_max"].append(round(wind, 1))
            payloads.append({"latitude": loc.lat, "longitude": loc.lon, "daily": daily})

        if self.inject_bad_record and len(payloads) > 1:
            # Simulate a sensor/decoding glitch in the last location: impossible
            # value on day 1 and a missing value on day 3.
            bad = payloads[-1]["daily"]
            bad["precipitation_sum"][1] = -999.0
            if days > 3:
                bad["temperature_2m_max"][3] = None
        return payloads


def get_source(name: str, **kwargs) -> ForecastSource:
    sources = {"open-meteo": OpenMeteoSource, "synthetic": SyntheticSource}
    if name not in sources:
        raise ValueError(f"unknown source '{name}'. choose from {sorted(sources)}")
    return sources[name](**kwargs)


def dump_raw(payloads: list[dict]) -> str:
    return json.dumps(payloads, ensure_ascii=False)
