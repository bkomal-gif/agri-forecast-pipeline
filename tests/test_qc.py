from dataclasses import replace

from conftest import RUN_DATE, make_days
from pipeline.models import Location
from pipeline.qc import run_qc

LOC = [Location("t-1", "T", 25, 82)]


def qc(days, rules_cfg):
    return run_qc(days, LOC, RUN_DATE, 7, rules_cfg["horizon_days"], rules_cfg["bounds"])


def test_clean_data_passes(rules_cfg):
    r = qc(make_days(), rules_cfg)
    assert not r.issues and "t-1" in r.clean


def test_impossible_value_inside_horizon_blocks_location(rules_cfg):
    r = qc(make_days(d1={"precip_mm": -999.0}), rules_cfg)
    assert "t-1" in r.blocked and r.errors[0].check == "range"


def test_missing_value_outside_horizon_is_only_a_warning(rules_cfg):
    r = qc(make_days(d5={"tmax_c": None}), rules_cfg)
    assert "t-1" not in r.blocked
    assert [i.level for i in r.issues] == ["warning"]
    assert len(r.clean["t-1"]) == 6   # the bad day is dropped, the rest kept


def test_tmin_above_tmax_is_caught(rules_cfg):
    r = qc(make_days(d0={"tmin_c": 35.0}), rules_cfg)
    assert r.errors[0].check == "consistency"


def test_stale_feed_is_caught(rules_cfg):
    days = [replace(d, date=d.date.replace(day=d.date.day - 1)) for d in make_days()]
    r = qc(days, rules_cfg)
    assert any(i.check == "freshness" for i in r.errors)


def test_incomplete_feed_is_caught(rules_cfg):
    r = qc(make_days(n=4), rules_cfg)
    assert any(i.check == "completeness" for i in r.errors)
