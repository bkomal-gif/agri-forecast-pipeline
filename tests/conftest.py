import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pipeline.models import DailyForecast, Location  # noqa: E402

RUN_DATE = date(2026, 10, 14)


@pytest.fixture
def rules_cfg():
    return yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def templates():
    return yaml.safe_load((ROOT / "config" / "templates.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def loc():
    return Location(id="t-1", name="Testpur", lat=25.0, lon=82.0, language="en")


def make_days(n=7, **overrides_by_day):
    """Benign weather for n days; override with d<i>={field: value}."""
    days = []
    for i in range(n):
        vals = dict(tmax_c=31.0, tmin_c=20.0, precip_mm=5.0, precip_prob_pct=40.0,
                    wind_max_kmh=10.0)
        vals.update(overrides_by_day.get(f"d{i}", {}))
        days.append(DailyForecast("t-1", RUN_DATE + timedelta(days=i), **vals))
    return days
