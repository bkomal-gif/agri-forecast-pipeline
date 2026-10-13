import json
import os
import sqlite3

import pytest

from conftest import ROOT, RUN_DATE
from pipeline.run import run


@pytest.mark.parametrize("region,channels,status", [
    ("up_pilot", {"sms", "whatsapp", "voice", "llm"}, "ok"),       # 1 of 5 held back = 20%
    # Second geography, config-only. 1 of 4 held back = 25% > 20% threshold,
    # so the run must be flagged 'degraded' (exit code 2) for the ops team.
    ("bihar_pilot", {"sms", "voice"}, "degraded"),
])
def test_region_runs_end_to_end(tmp_path, region, channels, status):
    res = run(ROOT / "config" / "regions" / f"{region}.yaml", "synthetic", RUN_DATE,
              tmp_path / "out", ROOT / "config" / "rules.yaml",
              ROOT / "config" / "templates.yaml", tmp_path / "audit.sqlite")
    assert res["status"] == status, res
    assert res["locations_blocked"]                 # the injected bad record was held back
    out = tmp_path / "out" / res["run_id"]
    assert {p.stem for p in out.glob("*.jsonl")} == channels
    assert (out / "run_report.md").exists()
    for f in out.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            p = json.loads(line)
            assert p["location_id"] not in res["locations_blocked"]

    db = sqlite3.connect(tmp_path / "audit.sqlite")
    assert db.execute("select status from runs").fetchone()[0] == status
    assert db.execute("select count(*) from messages").fetchone()[0] == res["messages"]
    assert db.execute("select count(*) from qc_issues where level='error'").fetchone()[0] >= 1


def test_failed_fetch_is_reported_not_crashed(tmp_path, monkeypatch):
    import pipeline.ingest as ingest

    def boom(*a, **k):
        raise RuntimeError("upstream down")
    monkeypatch.setattr(ingest.SyntheticSource, "fetch", boom)
    res = run(ROOT / "config" / "regions" / "up_pilot.yaml", "synthetic", RUN_DATE,
              tmp_path / "out", ROOT / "config" / "rules.yaml",
              ROOT / "config" / "templates.yaml", tmp_path / "audit.sqlite")
    assert res["status"] == "failed" and "upstream down" in res["error"]


@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 to hit Open-Meteo")
def test_live_open_meteo(tmp_path):
    from datetime import datetime
    from pipeline.channels import IST
    res = run(ROOT / "config" / "regions" / "up_pilot.yaml", "open-meteo",
              datetime.now(IST).date(), tmp_path / "out", ROOT / "config" / "rules.yaml",
              ROOT / "config" / "templates.yaml", tmp_path / "audit.sqlite")
    assert res["status"] in ("ok", "degraded"), res
