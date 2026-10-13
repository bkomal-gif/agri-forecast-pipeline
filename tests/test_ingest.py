import pytest

from conftest import RUN_DATE
from pipeline.ingest import SyntheticSource, parse_open_meteo
from pipeline.models import Location

LOCS = [Location("a", "A", 25.0, 82.0), Location("b", "B", 26.0, 81.0)]

# Shape copied from a real Open-Meteo daily response.
REAL_SHAPE = {
    "latitude": 25.0, "longitude": 82.0, "timezone": "Asia/Kolkata",
    "daily_units": {"precipitation_sum": "mm"},
    "daily": {
        "time": ["2026-10-14", "2026-10-15"],
        "temperature_2m_max": [32.1, 31.4], "temperature_2m_min": [21.0, None],
        "precipitation_sum": [0.0, 12.3], "precipitation_probability_max": [5, 62],
        "wind_speed_10m_max": [9.4, 14.0],
    },
}


def test_parse_keeps_nulls_for_qc():
    recs = parse_open_meteo([REAL_SHAPE], LOCS[:1])
    assert len(recs) == 2
    assert recs[1].precip_mm == 12.3 and recs[1].tmin_c is None


def test_parse_rejects_payload_location_mismatch():
    with pytest.raises(ValueError):
        parse_open_meteo([REAL_SHAPE], LOCS)


def test_synthetic_is_deterministic_and_api_shaped():
    a = SyntheticSource().fetch(LOCS, RUN_DATE, 7)
    b = SyntheticSource().fetch(LOCS, RUN_DATE, 7)
    assert a == b
    recs = parse_open_meteo(a, LOCS)
    assert len(recs) == 14 and recs[0].date == RUN_DATE
