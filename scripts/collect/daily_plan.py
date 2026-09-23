"""Generate a read-only daily collection review packet; never collect data.

Phase 1 proposes an immutable reference snapshot if today's is absent. Run again
after separately approved reference collection to produce individual status, bar
and corporate-action plans. Each plan requires its own explicit apply approval.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import coverage, scan_gaps, status_incremental, corporate_actions_daily
from collect.baostock_reference_snapshot import build_plan as reference_plan
from collect.daily_common import sha256_file, write_json_atomic


def build_packet(day: date, output: Path, *, target_end: date | None = None) -> dict:
    snapshot = (coverage.LAKE / "provider=baostock" / "reference_snapshots" /
                f"snapshot={day.isoformat()}")
    packet = {"schema_version": 1, "kind": "daily_collection_review",
              "snapshot_date": day.isoformat(), "network_requests": 0,
              "authorization": "each apply requires separate review and exact plan SHA",
              "plans": {}}
    if not snapshot.exists():
        plan = reference_plan(day, snapshot)
        name = "reference.json"
        write_json_atomic(output / name, plan)
        packet["phase"] = "reference_required"
        packet["plans"]["reference"] = {"file": name,
                                          "plan_sha256": plan["plan_sha256"],
                                          "destination": str(snapshot)}
    else:
        manifest_path = snapshot / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("run_status") != "completed" or manifest.get("plan", {}).get("snapshot_date") != day.isoformat():
            raise ValueError(f"reference snapshot incomplete or wrong date: {snapshot}")
        # Recheck all seven files, not just the two used by daily planners.
        results = manifest.get("results", [])
        if len(results) != 7 or any(
                row.get("status") != "ok" or
                sha256_file(snapshot / row["file"]) != row.get("sha256")
                for row in results):
            raise ValueError("reference snapshot files do not match the completed manifest")
        from collect.daily_common import select_reference_file
        for name in ("stock_basic", "trade_calendar"):
            chosen, _ = select_reference_file(day, lake=coverage.LAKE,
                                              fallback=coverage.STOCK_BASIC, name=name)
            if chosen.parent != snapshot:
                raise ValueError(f"reference {name} selection mismatch")
        packet["phase"] = "sources_ready"
        packet["reference_manifest_sha256"] = sha256_file(manifest_path)
        calendar = coverage.TradingCalendar(snapshot / "trade_calendar.parquet")
        if target_end is None:
            if day > calendar.last:
                raise ValueError("today's reference calendar does not cover today")
            # Only current-date review uses the clock cutoff. Historical replay
            # must specify --target-end explicitly.
            if day != datetime.now(ZoneInfo("Asia/Shanghai")).date():
                raise ValueError("historical review needs explicit --target-end")
            target_end = coverage.default_target_end(calendar)
        if not calendar.is_trading_day(target_end):
            raise ValueError("target must be a verified trading day")
        packet["bar_target_end"] = target_end.isoformat()
        plan = status_incremental.build_plan(
            Path(status_incremental.DEFAULT_DEST), end=target_end, asof=day)
        write_json_atomic(output / "status.json", plan)
        packet["plans"]["status"] = {"file": "status.json", "plan_sha256": plan["plan_sha256"],
                                       "actions": len(plan["actions"]),
                                       "interior_gap_symbols": len(plan["interior_gaps"])}
        for dataset in ("baostock-daily", "baostock-min5"):
            plan = scan_gaps.build_plan(dataset, target_end=target_end)
            name = f"{dataset}.json"
            write_json_atomic(output / name, plan)
            packet["plans"][dataset] = {"file": name, "plan_sha256": plan["plan_sha256"],
                                          "actions": len(plan["actions"]),
                                          "universe": plan["universe"]["listed_symbols"]}
        for dataset, (root, _) in corporate_actions_daily.DATASETS.items():
            plan = corporate_actions_daily.build_plan(dataset, root, observed_on=day)
            name = f"{dataset}.json"
            write_json_atomic(output / name, plan)
            packet["plans"][dataset] = {"file": name, "plan_sha256": plan["plan_sha256"],
                                          "observations": len(plan["actions"]),
                                          "source_window": plan["source_window"]}
    write_json_atomic(output / "index.json", packet)
    return packet


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", type=date.fromisoformat,
                        default=datetime.now(ZoneInfo("Asia/Shanghai")).date())
    parser.add_argument("--target-end", type=date.fromisoformat)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    packet = build_packet(args.date, Path(args.out_dir), target_end=args.target_end)
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
