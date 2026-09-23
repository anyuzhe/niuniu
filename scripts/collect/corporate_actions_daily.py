"""Plan and explicitly approve repeat observations of listed corporate actions.

THS/CNINFO re-query full supplier histories; Baostock re-queries a bounded
report-year window and preserves earlier raw rows. Existing files are only
replaced after byte-exact backup. Nothing is published to a product catalog.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import coverage, universe
from collect.baostock_dividend import DividendSession
from collect.cninfo_allotment import make_fetcher as cninfo_fetcher
from collect.daily_common import (atomic_parquet, backup_verified, canonical_digest,
                                  empty_marker, logical_frame_digest, observed_state,
                                  run_lock, select_stock_basic, sha256_file, symbol_file, validate_observed_state,
                                  write_empty_marker, write_json_atomic)
from collect.ths_dividend import make_fetcher as ths_fetcher

ROOT = coverage.LAKE
DATASETS = {
    "ths-dividend": (ROOT / "provider=ths" / "corporate_actions_dividend_v2", "stocks-listed"),
    "cninfo-allotment": (ROOT / "provider=cninfo" / "corporate_actions_allotment_v2", "tdx-rights-listed"),
    "baostock-dividend": (ROOT / "provider=baostock" / "corporate_actions_dividend_v2", "stocks-listed"),
}


def build_plan(dataset: str, root: Path, *, observed_on: date,
               lookback_years: int = 3, codes: list[str] | None = None) -> dict:
    if dataset not in DATASETS:
        raise ValueError(f"unsupported dataset: {dataset}")
    if lookback_years < 1 or lookback_years > 60:
        raise ValueError("lookback_years must be 1..60")
    stock_path, manifest_sha = select_stock_basic(
        observed_on, lake=coverage.LAKE, fallback=coverage.STOCK_BASIC)
    listed = coverage.listed_a_shares(stock_path)
    if codes is None:
        rights = set(universe.resolve("tdx-rights")) if dataset == "cninfo-allotment" else set(listed)
        codes = sorted(rights & set(listed))
    if len(codes) != len(set(codes)) or not codes:
        raise ValueError("universe must be nonempty and unique")
    if set(codes) - set(listed):
        raise ValueError("universe includes non-listed securities")
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"baseline dataset not found: {root}")
    actions = [{"code": code, **observed_state(root, code)} for code in sorted(codes)]
    start_year = (observed_on.year - lookback_years + 1) if dataset == "baostock-dividend" else None
    plan = {"schema_version": 1, "kind": "corporate_actions_daily",
            "dataset": dataset, "root": str(root), "observed_on": observed_on.isoformat(),
            "universe_preset": DATASETS[dataset][1], "universe_count": len(codes),
            "stock_basic_path": str(stock_path.resolve()),
            "stock_basic_sha256": sha256_file(stock_path),
            "reference_manifest_sha256": manifest_sha,
            "source_window": {"report_year_start": start_year,
                              "report_year_end": observed_on.year} if start_year else "full_supplier_history",
            "actions": actions}
    plan["plan_sha256"] = canonical_digest(plan)
    return plan


def validate_plan(plan: dict, *, allow_changed: set[str] = frozenset()) -> list[dict]:
    if (plan.get("kind") != "corporate_actions_daily" or
            canonical_digest(plan) != plan.get("plan_sha256") or
            plan.get("dataset") not in DATASETS):
        raise ValueError("invalid company-action plan")
    dataset = plan["dataset"]
    # Always rederive the universe and bind the newest approved reference bytes.
    stock_path, _ = select_stock_basic(date.fromisoformat(plan["observed_on"]),
                                       lake=coverage.LAKE, fallback=coverage.STOCK_BASIC)
    listed = coverage.listed_a_shares(stock_path)
    rights = set(universe.resolve("tdx-rights")) if dataset == "cninfo-allotment" else set(listed)
    codes = sorted(rights & set(listed))
    source_window = plan["source_window"]
    lookback = (plan["source_window"]["report_year_end"] -
                plan["source_window"]["report_year_start"] + 1
                if isinstance(source_window, dict) else 3)
    rebuilt = build_plan(dataset, Path(plan["root"]),
                         observed_on=date.fromisoformat(plan["observed_on"]),
                         lookback_years=lookback, codes=codes)
    # A resumed batch may have changed its own completed symbols; all other
    # plan and universe inputs must still match exactly.
    for name in ("schema_version", "kind", "dataset", "root", "observed_on",
                 "universe_preset", "universe_count", "stock_basic_path",
                 "stock_basic_sha256", "reference_manifest_sha256", "source_window"):
        if rebuilt[name] != plan[name]:
            raise ValueError(f"stale company-action plan: {name}")
    if [x["code"] for x in rebuilt["actions"]] != [x["code"] for x in plan["actions"]]:
        raise ValueError("company-action universe changed")
    for action in plan["actions"]:
        if action["code"] not in allow_changed:
            validate_observed_state(Path(plan["root"]), action)
    return plan["actions"]


def _fetcher(plan: dict, timeout: float):
    dataset = plan["dataset"]
    if dataset == "ths-dividend":
        return ths_fetcher(), None
    if dataset == "cninfo-allotment":
        return cninfo_fetcher(), None
    listed = coverage.listed_a_shares(Path(plan["stock_basic_path"]))
    start = plan["source_window"]["report_year_start"]
    years = {action["code"]: max(start, listed[action["code"]].year)
             for action in plan["actions"]}
    session = DividendSession(years, plan["source_window"]["report_year_end"], timeout)
    return session, session.close


def _invoke(fetch, code: str, timeout: float):
    # The Baostock session already has a killable worker; web scrapers use
    # per-request signal timeout (POSIX main-thread CLI only).
    if isinstance(fetch, DividendSession):
        return fetch(code)
    import signal
    if not hasattr(signal, "SIGALRM"):
        raise RuntimeError("web scraper hard timeout unsupported on this platform")
    def expired(_signum, _frame):
        raise TimeoutError(f"supplier request exceeded {timeout}s for {code}")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        return fetch(code)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _merge_baostock(old, incoming, start_year: int):
    import pandas as pd
    if old is None:
        return incoming
    if "report_year_requested" not in old.columns or "report_year_requested" not in incoming.columns:
        raise ValueError("Baostock report year missing")
    older = old[pd.to_numeric(old["report_year_requested"], errors="raise") < start_year]
    current = old[pd.to_numeric(old["report_year_requested"], errors="raise") >= start_year]
    if len(current) and incoming.empty:
        raise ValueError("supplier returned empty recent window with existing events")
    if set(old.columns) != set(incoming.columns):
        raise ValueError("Baostock dividend schema changed")
    return pd.concat([older, incoming[list(old.columns)]], ignore_index=True)


def apply_one(plan: dict, action: dict, fetch, *, timeout: float, backup_root: Path) -> dict:
    import pandas as pd
    root = Path(plan["root"])
    code = action["code"]
    validate_observed_state(root, action)
    frame = _invoke(fetch, code, timeout)
    observed_at = datetime.now(timezone.utc).isoformat()
    if frame is None:
        raise ValueError("supplier returned None, not a verified empty result")
    supplier_rows = len(frame)
    supplier_digest = logical_frame_digest(frame)
    evidence = dict(getattr(frame, "attrs", {}))
    if len(frame) and ("code" not in frame.columns or set(frame["code"]) != {code}):
        raise ValueError("supplier code mismatch")
    # Recheck after the network call; a concurrent writer must never be overwritten.
    validate_observed_state(root, action)
    path = symbol_file(root, code)
    marker = empty_marker(root, code)
    old = pd.read_parquet(path) if path.is_file() else None
    if plan["dataset"] == "baostock-dividend":
        frame = _merge_baostock(old, frame, plan["source_window"]["report_year_start"])
    elif old is not None and frame.empty:
        raise ValueError("supplier returned empty history despite existing events")
    entry = {"code": code, "status": "unchanged", "observed_at": observed_at,
             "supplier_rows": supplier_rows, "supplier_logical_sha256": supplier_digest}
    if evidence:
        entry["supplier_evidence"] = evidence
    if frame.empty:
        if marker.exists():
            entry["empty_marker_sha256"] = action["empty_marker_sha256"]
            return entry
        entry["empty_marker"] = write_empty_marker(root, code, plan["dataset"],
                                                   plan["observed_on"], evidence)
        entry["status"] = "empty"
        return entry
    digest = logical_frame_digest(frame)
    entry["logical_sha256"] = digest
    if old is not None and logical_frame_digest(old) == digest:
        entry["sha256_after"] = action["parquet_sha256"]
        return entry
    # Preserve original source bytes before replacing anything. Empty markers
    # are backed up too; no deletion is performed until new parquet read-back.
    if old is not None:
        entry["backup"] = backup_verified(path, backup_root / path.name,
                                          action["parquet_sha256"])
    if marker.exists():
        entry["marker_backup"] = backup_verified(
            marker, backup_root / "_empty" / marker.name,
            action["empty_marker_sha256"])
    entry["sha256_after"] = atomic_parquet(frame, path)
    if marker.exists():
        marker.unlink()
    entry["status"] = "updated" if old is not None else "new"
    entry["rows_after"] = len(frame)
    return entry


def apply(plan: dict, *, timeout: float = 120, throttle: float = 1,
          retries: int = 2, resume_run: bool = False, fetch_factory=_fetcher) -> dict:
    with run_lock(Path(plan["root"]), f"{plan['dataset']}-daily"):
        return _apply_unlocked(plan, timeout=timeout, throttle=throttle,
                               retries=retries, resume_run=resume_run,
                               fetch_factory=fetch_factory)


def _apply_unlocked(plan: dict, *, timeout: float, throttle: float,
                    retries: int, resume_run: bool, fetch_factory) -> dict:
    if timeout <= 0 or retries < 1 or throttle < 0:
        raise ValueError("invalid runtime limits")
    root = Path(plan["root"])
    receipt_path = root / "_receipts" / f"daily-{plan['dataset']}-{plan['plan_sha256'][:16]}.json"
    completed: dict[str, dict] = {}
    if receipt_path.exists():
        if not resume_run:
            raise FileExistsError(f"run receipt exists: {receipt_path}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("plan_sha256") != plan.get("plan_sha256") or receipt.get("run_status") == "finished":
            raise ValueError("cannot resume unrelated or completed run")
        completed = {row["code"]: row for row in receipt["results"] if row["status"] != "failed"}
        for code, row in completed.items():
            actual = observed_state(root, code)
            if row["status"] in ("new", "updated", "unchanged") and row.get("sha256_after"):
                valid = actual["parquet_sha256"] == row["sha256_after"] and not actual["empty_marker_sha256"]
            elif row["status"] in ("empty", "unchanged"):
                expected = row.get("empty_marker", {}).get("sha256") or row.get("empty_marker_sha256")
                valid = bool(expected) and actual["empty_marker_sha256"] == expected and not actual["parquet_sha256"]
            else:
                valid = False
            if not valid:
                raise ValueError(f"completed output changed: {code}")
    else:
        receipt = {"plan_sha256": plan["plan_sha256"], "dataset": plan["dataset"],
                   "run_status": "running", "results": []}
    actions = validate_plan(plan, allow_changed=set(completed))
    if not receipt_path.exists():
        write_json_atomic(receipt_path, receipt)
    backup_root = coverage.DATA_ROOT / "backups" / f"corporate-daily-{plan['plan_sha256'][:16]}"
    fetch, close = (None, None)
    try:
        if any(x["code"] not in completed for x in actions):
            fetch, close = fetch_factory(plan, timeout)
        for action in actions:
            if action["code"] in completed:
                continue
            row = None
            for attempt in range(1, retries + 1):
                try:
                    row = apply_one(plan, action, fetch, timeout=timeout, backup_root=backup_root)
                    row["attempts"] = attempt
                    break
                except Exception as exc:
                    if attempt == retries:
                        row = {"code": action["code"], "status": "failed",
                               "attempts": attempt, "error": f"{type(exc).__name__}: {exc}"}
            receipt["results"] = [x for x in receipt["results"] if x["code"] != action["code"]]
            receipt["results"].append(row)
            write_json_atomic(receipt_path, receipt)
            time.sleep(throttle)
    finally:
        if close:
            close()
    receipt["run_status"] = ("finished_with_errors" if any(x["status"] == "failed" for x in receipt["results"])
                             else "finished")
    write_json_atomic(receipt_path, receipt)
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", choices=sorted(DATASETS), required=True)
    parser.add_argument("--dest")
    parser.add_argument("--observed-on", type=date.fromisoformat)
    parser.add_argument("--lookback-years", type=int, default=3)
    parser.add_argument("--plan-output")
    parser.add_argument("--plan")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve-sha256")
    parser.add_argument("--resume-run", action="store_true")
    parser.add_argument("--request-timeout", type=float, default=120)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--throttle", type=float, default=1)
    args = parser.parse_args(argv)
    root = Path(args.dest or DATASETS[args.dataset][0])
    if not args.apply:
        target = args.observed_on or datetime.now(ZoneInfo("Asia/Shanghai")).date()
        plan = build_plan(args.dataset, root, observed_on=target,
                          lookback_years=args.lookback_years)
        print(json.dumps({"dataset": args.dataset, "symbols": len(plan["actions"]),
                          "source_window": plan["source_window"],
                          "plan_sha256": plan["plan_sha256"]}, ensure_ascii=False))
        if args.plan_output:
            write_json_atomic(Path(args.plan_output), plan)
        return 0
    if not args.plan or not args.approve_sha256:
        raise PermissionError("apply requires --plan and --approve-sha256")
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if (args.approve_sha256 != plan.get("plan_sha256") or args.dataset != plan.get("dataset")
            or root.resolve() != Path(plan["root"])):
        raise PermissionError("approved plan scope or SHA mismatch")
    receipt = apply(plan, timeout=args.request_timeout, throttle=args.throttle,
                    retries=args.retries, resume_run=args.resume_run)
    counts = {state: sum(r["status"] == state for r in receipt["results"])
              for state in ("unchanged", "updated", "new", "empty", "failed")}
    print(json.dumps({"run_status": receipt["run_status"], **counts}, ensure_ascii=False))
    return int(receipt["run_status"] != "finished")


if __name__ == "__main__":
    raise SystemExit(main())
