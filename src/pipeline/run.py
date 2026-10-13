"""Orchestrator: ingest -> QC -> rules -> compose -> channel payloads -> outbox + audit.

Usage
    python -m pipeline.run --region config/regions/up_pilot.yaml --source synthetic
    python -m pipeline.run --region config/regions/up_pilot.yaml --source open-meteo

Exit codes (so a scheduler can alert on them)
    0 ok | 1 failed (e.g. forecast fetch failed) | 2 degraded (too many locations held by QC)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from .channels import build_adapters
from .ingest import dump_raw, get_source, parse_open_meteo
from .messages import compose
from .models import Location
from .qc import run_qc
from .rules import evaluate
from .store import AuditStore

ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_locations(region_cfg: dict) -> list[Location]:
    locs = [Location(id=l["id"], name=l["name"], lat=l["lat"], lon=l["lon"],
                     language=l.get("language", region_cfg.get("default_language", "en")),
                     names=l.get("names", {}))
            for l in region_cfg["locations"]]
    ids = [l.id for l in locs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate location ids in region config")
    return locs


class StageTimer:
    def __init__(self):
        self.ms: dict[str, float] = {}

    def __call__(self, name):
        timer = self

        class _T:
            def __enter__(self):
                self.t0 = time.perf_counter()

            def __exit__(self, *exc):
                timer.ms[name] = round((time.perf_counter() - self.t0) * 1000, 1)
        return _T()


def run(region_path: Path, source_name: str, run_date: date, out_dir: Path,
        rules_path: Path, templates_path: Path, db_path: Path) -> dict:
    region_cfg = load_yaml(region_path)
    rules_cfg = load_yaml(rules_path)
    templates = load_yaml(templates_path)
    locations = load_locations(region_cfg)
    loc_by_id = {l.id: l for l in locations}
    adapters = build_adapters(region_cfg["channels"])
    days = region_cfg.get("forecast_days", 7)

    started = datetime.now(timezone.utc)
    run_id = f"{region_cfg['region_id']}-{run_date.isoformat()}-{started.strftime('%H%M%S')}"
    timer = StageTimer()
    store = AuditStore(db_path)
    summary: dict = {"locations": len(locations)}
    status = "ok"

    try:
        source = get_source(source_name)
        with timer("ingest"):
            raw = source.fetch(locations, run_date, days)
            records = parse_open_meteo(raw, locations)
        store.record_raw(run_id, dump_raw(raw))
        store.record_forecasts(run_id, records)

        with timer("qc"):
            qc = run_qc(records, locations, run_date, days, rules_cfg["horizon_days"],
                        rules_cfg["bounds"])
        store.record_issues(run_id, qc.issues)

        payloads, composed_all, warnings = [], [], []
        with timer("rules_and_compose"):
            for loc_id, fc in qc.clean.items():
                loc = loc_by_id[loc_id]
                advs = evaluate(fc, run_date, rules_cfg)
                msg = compose(loc, advs, run_date, templates)
                warnings += [f"{loc_id}: {w}" for w in msg.warnings]
                composed_all.append((loc, fc, msg))

        with timer("render_channels"):
            for loc, fc, msg in composed_all:
                for ad in adapters:
                    payloads.append(ad.render(msg, run_id=run_id, run_date=run_date,
                                              location=loc, forecast=fc, source=source.name))

        with timer("write_outbox"):
            run_out = out_dir / run_id
            run_out.mkdir(parents=True, exist_ok=True)
            for ad in adapters:
                with open(run_out / f"{ad.name}.jsonl", "w", encoding="utf-8") as f:
                    for p in payloads:
                        if p["channel"] == ad.name:
                            f.write(json.dumps(p, ensure_ascii=False) + "\n")
            store.record_messages(payloads)

        blocked_frac = len(qc.blocked) / len(locations)
        if blocked_frac > rules_cfg.get("max_blocked_fraction", 0.2):
            status = "degraded"
        summary.update({
            "messages": len(payloads),
            "locations_messaged": len(qc.clean),
            "locations_blocked": sorted(qc.blocked),
            "qc_errors": len(qc.errors),
            "qc_warnings": len(qc.issues) - len(qc.errors),
            "template_warnings": warnings,
            "sms_over_budget": [p["location_id"] for p in payloads
                                if p["channel"] == "sms" and p["content"]["over_budget"]],
        })
        write_report(run_out / "run_report.md", run_id, source.name, run_date, status,
                     timer.ms, summary, qc, composed_all, payloads)
        summary["outbox"] = str(run_out)
    except Exception as err:
        status = "failed"
        summary["error"] = f"{type(err).__name__}: {err}"
    finally:
        summary["total_ms"] = round(sum(timer.ms.values()), 1)
        store.record_run(run_id, region_cfg["region_id"], run_date.isoformat(), source_name,
                         started.isoformat(), status, timer.ms, summary)
        store.commit()
        store.close()

    return {"run_id": run_id, "status": status, "stage_ms": timer.ms, **summary}


def write_report(path, run_id, source, run_date, status, stage_ms, summary, qc,
                 composed_all, payloads):
    """Human-readable run report for program and research teams."""
    L = [f"# Run report: {run_id}", "",
         f"- Source: `{source}`  |  Run date: {run_date}  |  Status: **{status}**",
         f"- Locations messaged: {summary['locations_messaged']} / {summary['locations']}  |  "
         f"Payloads: {summary['messages']}",
         f"- Stage latency (ms): " + ", ".join(f"{k} {v}" for k, v in stage_ms.items()), ""]
    if qc.issues:
        L += ["## Quality-control issues", "", "| Location | Date | Check | Level | Detail |",
              "|---|---|---|---|---|"]
        L += [f"| {i.location_id} | {i.date or '-'} | {i.check} | {i.level} | {i.detail} |"
              for i in qc.issues]
        if qc.blocked:
            L += ["", f"**Held back (no message sent):** {', '.join(sorted(qc.blocked))}"]
        L.append("")
    L += ["## Advisories by location", ""]
    for loc, _, msg in composed_all:
        L.append(f"### {loc.name} ({msg.language})")
        for a, line in zip(msg.advisories, msg.lines):
            L.append(f"- [{a.severity}] {line}  _(rule `{a.rule_id}`)_")
        if not msg.advisories:
            L.append(f"- {msg.lines[0]}")
        sms = next((p for p in payloads if p["channel"] == "sms"
                    and p["location_id"] == loc.id), None)
        if sms:
            c = sms["content"]
            L.append(f"- SMS: {c['encoding']}, {c['segments']} segment(s), {c['mode']} text, "
                     f"{c['dropped_advisories']} advisory(ies) dropped to fit")
        L.append("")
    Path(path).write_text("\n".join(L), encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Forecast-to-farmer-message pipeline")
    p.add_argument("--region", required=True, type=Path)
    p.add_argument("--source", default="synthetic", choices=["synthetic", "open-meteo"])
    p.add_argument("--run-date", type=date.fromisoformat,
                   help="YYYY-MM-DD (default: today in IST)")
    p.add_argument("--out", type=Path, default=ROOT / "outbox")
    p.add_argument("--rules", type=Path, default=ROOT / "config" / "rules.yaml")
    p.add_argument("--templates", type=Path, default=ROOT / "config" / "templates.yaml")
    p.add_argument("--db", type=Path, default=ROOT / "data" / "audit.sqlite")
    a = p.parse_args(argv)

    from .channels import IST
    run_date = a.run_date or datetime.now(IST).date()
    result = run(a.region, a.source, run_date, a.out, a.rules, a.templates, a.db)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return {"ok": 0, "failed": 1, "degraded": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
