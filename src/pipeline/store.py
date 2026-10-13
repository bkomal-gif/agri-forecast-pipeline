"""Audit trail in SQLite.

Answers the questions that come up after any complaint or field visit:
"What did farmers in district X receive on date Y, from which forecast values,
via which rule - and was anything held back?" SQLite keeps the demo
dependency-free; the schema maps one-to-one onto Postgres/BigQuery.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, region TEXT, run_date TEXT, source TEXT,
    started_at TEXT, status TEXT, stage_ms TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS raw_payloads (
    run_id TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS forecasts (
    run_id TEXT, location_id TEXT, date TEXT, tmax_c REAL, tmin_c REAL,
    precip_mm REAL, precip_prob_pct REAL, wind_max_kmh REAL
);
CREATE TABLE IF NOT EXISTS qc_issues (
    run_id TEXT, location_id TEXT, date TEXT, check_name TEXT, level TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT, run_id TEXT, channel TEXT, location_id TEXT, language TEXT,
    advisory_codes TEXT, rule_ids TEXT, expires_at TEXT, content TEXT,
    PRIMARY KEY (message_id, run_id)
);
"""


class AuditStore:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)

    def record_run(self, run_id, region, run_date, source, started_at, status, stage_ms, summary):
        self.conn.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?)",
            (run_id, region, run_date, source, started_at, status,
             json.dumps(stage_ms), json.dumps(summary)))

    def record_raw(self, run_id, payload_json: str):
        self.conn.execute("INSERT INTO raw_payloads VALUES (?,?)", (run_id, payload_json))

    def record_forecasts(self, run_id, records):
        self.conn.executemany(
            "INSERT INTO forecasts VALUES (?,?,?,?,?,?,?,?)",
            [(run_id, r.location_id, r.date.isoformat(), r.tmax_c, r.tmin_c,
              r.precip_mm, r.precip_prob_pct, r.wind_max_kmh) for r in records])

    def record_issues(self, run_id, issues):
        self.conn.executemany(
            "INSERT INTO qc_issues VALUES (?,?,?,?,?,?)",
            [(run_id, i.location_id, i.date, i.check, i.level, i.detail) for i in issues])

    def record_messages(self, payloads):
        self.conn.executemany(
            "INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
            [(p["message_id"], p["run_id"], p["channel"], p["location_id"], p["language"],
              json.dumps(p["advisory_codes"]), json.dumps(p["rule_ids"]), p["expires_at"],
              json.dumps(p["content"], ensure_ascii=False)) for p in payloads])

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()
