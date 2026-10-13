import pytest

from conftest import RUN_DATE, make_days
from pipeline.rules import evaluate


def codes(days, rules_cfg):
    return [a.code for a in evaluate(days, RUN_DATE, rules_cfg)]


@pytest.mark.parametrize("mm,expected", [
    (64.4, "moderate_rain"),      # IMD: moderate tops out at 64.4
    (64.5, "heavy_rain"),         # IMD: heavy starts at 64.5
    (115.5, "heavy_rain"),
    (115.6, "very_heavy_rain"),
])
def test_imd_rainfall_boundaries(rules_cfg, mm, expected):
    days = make_days(d1={"precip_mm": mm, "precip_prob_pct": 90})
    assert codes(days, rules_cfg)[0] == expected


def test_display_rounding_is_half_up(rules_cfg):
    adv = evaluate(make_days(d1={"precip_mm": 64.5}), RUN_DATE, rules_cfg)[0]
    assert adv.params["precip_mm"] == 65   # banker's rounding would show 64


def test_earlier_weaker_alert_survives_later_stronger_one(rules_cfg):
    # Regression: heavy rain tomorrow must not be hidden by very heavy rain later.
    days = make_days(d1={"precip_mm": 78.0}, d2={"precip_mm": 132.0})
    advs = evaluate(days, RUN_DATE, rules_cfg)
    assert [(a.code, a.day_offset) for a in advs] == [("very_heavy_rain", 2), ("heavy_rain", 1)]


def test_same_day_stronger_alert_suppresses_weaker(rules_cfg):
    c = codes(make_days(d0={"tmax_c": 46.0}), rules_cfg)
    assert "heat_wave" in c and "heat" not in c


def test_no_spray_advice_on_heat_wave_day(rules_cfg):
    fair = {f"d{i}": {"precip_mm": 0, "precip_prob_pct": 5} for i in range(7)}
    fair["d0"] = {**fair["d0"], "tmax_c": 45.5}
    advs = evaluate(make_days(**fair), RUN_DATE, rules_cfg)
    spray = [a for a in advs if a.code == "spray_window"]
    assert spray and spray[0].day_offset != 0


def test_no_spray_advice_when_rain_follows(rules_cfg):
    days = make_days(d0={"precip_mm": 0, "precip_prob_pct": 5}, d1={"precip_mm": 20.0},
                     d2={"precip_mm": 20.0})
    assert "spray_window" not in codes(days, rules_cfg)


def test_missing_values_never_trigger_advice(rules_cfg):
    days = make_days(d0={"tmax_c": None}, d1={"tmax_c": None}, d2={"tmax_c": None})
    assert not any(c.startswith("heat") or c == "dry_spell" for c in codes(days, rules_cfg))


def test_dry_spell_needs_full_horizon(rules_cfg):
    dry = {f"d{i}": {"precip_mm": 0, "precip_prob_pct": 5, "tmax_c": 34} for i in range(7)}
    assert "dry_spell" in codes(make_days(**dry), rules_cfg)
    assert "dry_spell" not in codes(make_days(n=2, **dry), rules_cfg)
