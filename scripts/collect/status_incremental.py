"""Review and approval-bound incremental Baostock daily status/ST collection.

Only absent symbols and missing tail trading days are fetched. Interior gaps are
reported separately and never filled automatically. No bars/catalog are changed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import coverage
from collect.baostock_daily_status import DEFAULT_DEST, REQUIRED, StatusSession
from collect.daily_common import (atomic_parquet, backup_verified, canonical_digest,
                                  observed_state, run_lock, select_reference_file,
                                  select_stock_basic, sha256_file, symbol_file,
                                  validate_observed_state, write_json_atomic)


def build_plan(root: Path, *, end: date | None = None,
               calendar_path: Path | None = None,
               stock_path: Path | None = None,
               asof: date | None = None) -> dict:
    import pandas as pd
    calendar_asof = asof or end or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    auto_calendar = calendar_path is None
    calendar_manifest_sha = None
    if calendar_path is None:
        calendar_path, calendar_manifest_sha = select_reference_file(
            calendar_asof, lake=coverage.LAKE, fallback=coverage.CALENDAR,
            name="trade_calendar")
    calendar = coverage.TradingCalendar(calendar_path)
    if end is None and calendar_asof > calendar.last:
        raise ValueError(f"reference calendar stale after {calendar.last}; collect a new snapshot before planning")
    target = end or coverage.default_target_end(calendar)
    if not calendar.is_trading_day(target):
        raise ValueError("target must be an archived trading day")
    auto_stock = stock_path is None
    manifest_sha = None
    if stock_path is None:
        stock_path, manifest_sha = select_stock_basic(
            target, lake=coverage.LAKE, fallback=coverage.STOCK_BASIC)
    listed = coverage.listed_a_shares(stock_path)
    actions = []
    interior_gaps = []
    for code, ipo in listed.items():
        path = symbol_file(root, code)
        state = observed_state(root, code)
        if state["empty_marker_sha256"]:
            raise ValueError(f"status dataset cannot contain empty marker: {code}")
        if path.exists():
            frame = pd.read_parquet(path, columns=["date", "code", "tradestatus", "isST"])
            if frame.empty or frame["code"].isna().any() or set(frame["code"]) != {code}:
                raise ValueError(f"invalid existing status file: {code}")
            days = {date.fromisoformat(str(x)[:10]) for x in frame["date"]}
            if len(days) != len(frame):
                raise ValueError(f"duplicate status date: {code}")
            last = max(days)
            missing = [day.isoformat() for day in calendar.between(min(days), last)
                       if day not in days]
            if missing:
                interior_gaps.append({"code": code, "missing_dates": missing})
            start = calendar.first_on_or_after(last + timedelta(days=1))
        else:
            last = None
            start = calendar.first_on_or_after(max(ipo, calendar.first))
        if start is None or start > target:
            continue
        actions.append({"code": code, "start": start.isoformat(),
                        "end": target.isoformat(), "previous_last": last.isoformat() if last else None,
                        **state})
    plan = {"schema_version": 1, "kind": "baostock_status_incremental",
            "root": str(root.resolve()), "target_end": target.isoformat(),
            "calendar_path": str(calendar_path.resolve()),
            "calendar_sha256": sha256_file(calendar_path),
            "calendar_selection_auto": auto_calendar,
            "calendar_asof": calendar_asof.isoformat(),
            "calendar_manifest_sha256": calendar_manifest_sha,
            "stock_path": str(stock_path.resolve()), "stock_sha256": sha256_file(stock_path),
            "stock_selection_auto": auto_stock, "reference_manifest_sha256": manifest_sha,
            "universe_count": len(listed), "interior_gaps": interior_gaps,
            "actions": actions}
    plan["plan_sha256"] = canonical_digest(plan)
    return plan


def validate_plan(plan: dict, *, completed: set[str] = frozenset()) -> list[dict]:
    if plan.get("kind") != "baostock_status_incremental" or canonical_digest(plan) != plan.get("plan_sha256"):
        raise ValueError("invalid status plan identity")
    root = Path(plan["root"])
    if not root.is_dir():
        raise ValueError("status dataset missing")
    rebuilt = build_plan(root, end=date.fromisoformat(plan["target_end"]),
                         calendar_path=None if plan["calendar_selection_auto"] else Path(plan["calendar_path"]),
                         stock_path=None if plan["stock_selection_auto"] else Path(plan["stock_path"]),
                         asof=date.fromisoformat(plan["calendar_asof"]))
    for key in ("schema_version", "kind", "root", "target_end", "calendar_path",
                "calendar_sha256", "calendar_selection_auto", "calendar_asof",
                "calendar_manifest_sha256", "stock_path", "stock_sha256", "stock_selection_auto",
                "reference_manifest_sha256", "universe_count"):
        if rebuilt[key] != plan[key]:
            raise ValueError(f"status plan stale: {key}")
    pending = [x for x in plan["actions"] if x["code"] not in completed]
    if pending != rebuilt["actions"] or rebuilt["interior_gaps"] != plan["interior_gaps"]:
        raise ValueError("status plan actions or interior evidence changed")
    for action in pending:
        validate_observed_state(root, action)
    return plan["actions"]


def merge_status(root: Path, action: dict, frame, calendar) -> tuple[object, int]:
    import pandas as pd
    code = action["code"]
    if list(frame.columns) != REQUIRED + ["fetch_ts"]:
        raise ValueError(f"unexpected provider schema: {code}")
    days = [date.fromisoformat(str(x)[:10]) for x in frame["date"]]
    expected = set(calendar.between(date.fromisoformat(action["start"]),
                                    date.fromisoformat(action["end"])))
    if len(days) != len(set(days)) or set(days) != expected:
        raise ValueError(f"provider status trading-day coverage differs: {code}")
    if set(frame["code"]) != {code} or not frame["tradestatus"].isin(["0", "1"]).all() or not frame["isST"].isin(["0", "1"]).all():
        raise ValueError(f"invalid status values: {code}")
    path = symbol_file(root, code)
    if not path.exists():
        return frame, 0
    old = pd.read_parquet(path)
    if list(old.columns) != list(frame.columns):
        raise ValueError(f"status schema changed: {code}")
    if any(date.fromisoformat(str(x)[:10]) >= min(days) for x in old["date"]):
        raise ValueError(f"provider response overlaps existing status: {code}")
    return pd.concat([old, frame], ignore_index=True), len(old)


def apply(plan: dict, *, timeout: float = 120, throttle: float = .5,
          resume_run: bool = False, session_factory=StatusSession) -> dict:
    with run_lock(Path(plan["root"]), "baostock-status-daily"):
        return _apply_unlocked(plan, timeout=timeout, throttle=throttle,
                               resume_run=resume_run, session_factory=session_factory)


def _apply_unlocked(plan: dict, *, timeout: float, throttle: float,
                    resume_run: bool, session_factory) -> dict:
    if timeout <= 0 or throttle < 0:
        raise ValueError("invalid runtime limits")
    root = Path(plan["root"])
    receipts = root / "_receipts" / f"status-incremental-{plan['plan_sha256'][:16]}.json"
    completed = set()
    if receipts.exists():
        if not resume_run:
            raise FileExistsError(f"run already exists: {receipts}")
        result = json.loads(receipts.read_text(encoding="utf-8"))
        if result.get("plan_sha256") != plan.get("plan_sha256") or result.get("run_status") == "finished":
            raise ValueError("cannot resume unrelated or completed run")
        for row in result["results"]:
            if row["status"] == "ok":
                code = row["code"]
                if observed_state(root, code)["parquet_sha256"] != row["sha256_after"]:
                    raise ValueError(f"completed status output changed: {code}")
                completed.add(code)
    else:
        result = {"plan_sha256": plan["plan_sha256"], "run_status": "running", "results": []}
    actions = validate_plan(plan, completed=completed)  # before supplier login
    backup_root = coverage.DATA_ROOT / "backups" / f"status-incremental-{plan['plan_sha256'][:16]}"
    calendar = coverage.TradingCalendar(Path(plan["calendar_path"]))
    if not receipts.exists():
        write_json_atomic(receipts, result)
    if not actions:
        result["run_status"] = "finished"
        write_json_atomic(receipts, result)
        return result
    session = session_factory({x["code"]: date.fromisoformat(x["start"]) for x in actions},
                              date.fromisoformat(plan["target_end"]), timeout)
    try:
        for action in actions:
            code = action["code"]
            row = {"code": code, "start": action["start"], "end": action["end"]}
            try:
                validate_observed_state(root, action)
                frame = session(code)
                merged, previous_rows = merge_status(root, action, frame, calendar)
                validate_observed_state(root, action)
                path = symbol_file(root, code)
                if action["parquet_sha256"]:
                    row["backup"] = backup_verified(path, backup_root / path.name,
                                                    action["parquet_sha256"])
                row.update(status="ok", old_rows=previous_rows, added_rows=len(frame),
                           sha256_after=atomic_parquet(merged, path))
            except Exception as exc:
                row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                reset = getattr(session, "_start", None)
                if getattr(session, "connection", None) is None and callable(reset):
                    reset()
            result["results"] = [x for x in result["results"] if x["code"] != code]
            result["results"].append(row)
            write_json_atomic(receipts, result)
            time.sleep(throttle)
    finally:
        session.close()
    result["run_status"] = "finished_with_errors" if any(x["status"] == "failed" for x in result["results"]) else "finished"
    write_json_atomic(receipts, result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", default=DEFAULT_DEST)
    parser.add_argument("--target-end", type=date.fromisoformat)
    parser.add_argument("--plan-output")
    parser.add_argument("--plan")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume-run", action="store_true")
    parser.add_argument("--approve-sha256")
    parser.add_argument("--request-timeout", type=float, default=120)
    parser.add_argument("--throttle", type=float, default=.5)
    args = parser.parse_args(argv)
    if not args.apply:
        plan = build_plan(Path(args.dest), end=args.target_end)
        print(json.dumps({"actions": len(plan["actions"]),
                          "interior_gap_symbols": len(plan["interior_gaps"]),
                          "plan_sha256": plan["plan_sha256"]}, ensure_ascii=False))
        if args.plan_output:
            write_json_atomic(Path(args.plan_output), plan)
        return 0
    if not args.plan or not args.approve_sha256:
        raise PermissionError("apply requires --plan and --approve-sha256")
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if args.approve_sha256 != plan.get("plan_sha256") or Path(args.dest).resolve() != Path(plan["root"]):
        raise PermissionError("approved plan SHA or destination mismatch")
    result = apply(plan, timeout=args.request_timeout, throttle=args.throttle,
                   resume_run=args.resume_run)
    print(json.dumps({"run_status": result["run_status"], "results": len(result["results"])}, ensure_ascii=False))
    return 1 if result["run_status"] != "finished" else 0


if __name__ == "__main__":
    raise SystemExit(main())
