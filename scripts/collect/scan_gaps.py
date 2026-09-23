"""Build a deterministic, read-only gap plan for baostock bars.

The plan includes listed A-shares only. It reports both missing symbols (``full``)
and trailing date gaps (``tail``), but never fetches data. The plan hash is the
unit a user may later approve for ``bars_incremental.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import coverage as cov  # noqa: E402
from collect.daily_common import select_reference_file, select_stock_basic  # noqa: E402

DATASETS = {
    "baostock-daily": {
        "dir": cov.LAKE / "provider=baostock" / "stock_kline_daily",
        "vendor_floor": None,
        "description": "baostock daily bars",
    },
    "baostock-min5": {
        "dir": cov.LAKE / "provider=baostock" / "stock_kline_min5",
        "vendor_floor": cov.VENDOR_FLOOR["baostock-min5"],
        "description": "baostock 5-minute bars",
    },
}


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_digest(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("plan_sha256", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _existing_coverage(root: Path) -> dict[str, dict[str, Any]]:
    """Aggregate existing parquet files once; no per-symbol reads."""
    files = sorted(root.glob("*.parquet"))
    if not files:
        return {}
    import duckdb
    con = duckdb.connect()
    try:
        rows = con.execute(
            "with bars as ("
            " select regexp_extract(filename, '([^/]+)\\.parquet$', 1) as sym,"
            " date, max(date) over (partition by regexp_extract(filename, '([^/]+)\\.parquet$', 1)) as max_date"
            " from read_parquet(?, filename=true)"
            ") select sym, count(*), min(date), max(date), count(distinct date),"
            " sum(case when date=max_date then 1 else 0 end)"
            " from bars group by sym order by sym",
            [str(root / "*.parquet")],
        ).fetchall()
    finally:
        con.close()
    result: dict[str, dict[str, Any]] = {}
    for stem, n_rows, min_day, max_day, n_days, last_day_rows in rows:
        code = stem.replace("_", ".", 1)
        result[code] = {
            "present": True,
            "rows": int(n_rows),
            "min_date": cov.to_date(min_day) if min_day else None,
            "max_date": cov.to_date(max_day) if max_day else None,
            "n_days": int(n_days),
            "last_day_rows": int(last_day_rows),
            "days": set(),
        }
    return result


def build_plan(dataset: str, *, target_end: date,
               calendar_path: Path | None = None,
               stock_basic_path: Path | None = None,
               dataset_dir: Path | None = None,
               only_symbols: set[str] | None = None,
               action_limit: int | None = None) -> dict[str, Any]:
    """Return a deterministic report and bounded collection plan."""
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset}")
    spec = DATASETS[dataset]
    root = Path(dataset_dir or spec["dir"])
    if not root.is_dir():
        raise FileNotFoundError(f"dataset directory does not exist: {root}")
    auto_calendar = calendar_path is None
    auto_stock = stock_basic_path is None
    calendar_manifest_sha = stock_manifest_sha = None
    if auto_calendar:
        calendar_path, calendar_manifest_sha = select_reference_file(
            target_end, lake=cov.LAKE, fallback=cov.CALENDAR, name="trade_calendar")
    if auto_stock:
        stock_basic_path, stock_manifest_sha = select_stock_basic(
            target_end, lake=cov.LAKE, fallback=cov.STOCK_BASIC)
    calendar = cov.TradingCalendar(Path(calendar_path))
    if target_end > calendar.last:
        raise ValueError(f"reference calendar ends {calendar.last}; target {target_end} is unverified")
    end = calendar.latest_on_or_before(target_end)
    if end is None:
        raise ValueError(f"target {target_end} predates calendar")
    listed = cov.listed_a_shares(Path(stock_basic_path))
    if only_symbols is not None:
        listed = {code: ipo for code, ipo in listed.items() if code in only_symbols}
    existing = _existing_coverage(root)

    counts = {key: 0 for key in
              ("full", "tail", "refresh_last", "up_to_date", "ahead", "not_yet_listed",
               "suspended_tail")}
    all_actions: list[dict[str, Any]] = []
    status_evidence: list[dict[str, Any]] = []
    status_root = root.parent / "daily_status_v2"
    known_vendor_limits = 0
    for code, ipo_date in listed.items():
        path = root / cov.symbol_filename(code)
        current = existing.get(code, {
            "present": False, "rows": 0, "min_date": None,
            "max_date": None, "n_days": 0, "last_day_rows": 0, "days": set(),
        })
        gap = cov.compute_gap(
            current, calendar, target_end=end, first_start=ipo_date,
            vendor_floor=spec["vendor_floor"],
        )
        # A 5-minute file can contain the target date but only a partial session.
        # Normal A-share sessions have 48 five-minute bars; refresh that final day
        # rather than falsely classifying the symbol as current.
        if (dataset == "baostock-min5" and gap["action"] == "up_to_date" and
                current["last_day_rows"] < 48):
            gap = {**gap, "action": "refresh_last", "fetch_start": end,
                   "fetch_end": end, "n_trading_days": 1}
        # A trailing no-bar range is not retryable if the separately collected
        # supplier status covers every expected session and marks them all 0.
        if gap["action"] == "tail" and status_root.is_dir():
            status_path = status_root / cov.symbol_filename(code)
            if status_path.is_file():
                import pandas as pd
                status = pd.read_parquet(status_path, columns=["date", "code", "tradestatus"])
                expected = set(calendar.between(current["max_date"] + timedelta(days=1), end))
                rows = status[status["date"].astype(str).isin({d.isoformat() for d in expected})]
                if (expected and len(rows) == len(expected) and
                        set(rows["code"]) == {code} and
                        {cov.to_date(x) for x in rows["date"]} == expected and
                        set(rows["tradestatus"]) == {"0"}):
                    gap["action"] = "suspended_tail"
                    status_evidence.append({"symbol": code, "path": str(status_path.resolve()),
                                            "sha256": file_sha256(status_path),
                                            "sessions": len(expected)})
        counts[gap["action"]] += 1
        known_vendor_limits += int(gap["known_vendor_limit"])
        if gap["action"] not in {"full", "tail", "refresh_last"}:
            continue
        all_actions.append({
            "symbol": code,
            "action": gap["action"],
            "path": str(path),
            "existing_rows": current["rows"],
            "existing_max_date": (current["max_date"].isoformat()
                                  if current["max_date"] else None),
            "existing_last_day_rows": current["last_day_rows"],
            "sha256_before": file_sha256(path),
            "fetch_start": gap["fetch_start"].isoformat(),
            "fetch_end": gap["fetch_end"].isoformat(),
            "n_trading_days": gap["n_trading_days"],
            "known_vendor_limit_applied": gap["known_vendor_limit"],
        })

    all_actions.sort(key=lambda item: (item["fetch_start"], item["symbol"]))
    planned = all_actions[:action_limit] if action_limit is not None else all_actions
    listed_files = {cov.symbol_filename(code) for code in listed}
    excluded_files = sum(1 for path in root.glob("*.parquet")
                         if path.name not in listed_files)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "niuniu_bars_gap_plan",
        "dataset": dataset,
        "description": spec["description"],
        "dataset_dir": str(root.resolve()),
        "target_end": end.isoformat(),
        "calendar": {
            "path": str(Path(calendar_path).resolve()),
            "sha256": file_sha256(Path(calendar_path)),
            "first": calendar.first.isoformat(),
            "last": calendar.last.isoformat(),
            "auto_selected": auto_calendar,
            "reference_manifest_sha256": calendar_manifest_sha,
            "asof": target_end.isoformat(),
        },
        "universe": {
            "path": str(Path(stock_basic_path).resolve()),
            "sha256": file_sha256(Path(stock_basic_path)),
            "contract": "type=1 and status=1; delisted excluded",
            "listed_symbols": len(listed),
            "excluded_nonlisted_files": excluded_files,
            "auto_selected": auto_stock,
            "reference_manifest_sha256": stock_manifest_sha,
            "asof": target_end.isoformat(),
        },
        "vendor_floor": (spec["vendor_floor"].isoformat()
                         if spec["vendor_floor"] else None),
        "summary": {
            **counts,
            "actions_total": len(all_actions),
            "actions_in_plan": len(planned),
            "known_vendor_limits_applied": known_vendor_limits,
        },
        "status_evidence": status_evidence,
        "actions": planned,
    }
    payload["plan_sha256"] = canonical_digest(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", required=True, choices=sorted(DATASETS))
    parser.add_argument("--target-end", type=date.fromisoformat)
    parser.add_argument("--symbols", nargs="*", help="optional bounded symbol set")
    parser.add_argument("--limit", type=int,
                        help="include at most N actions in the approvable plan")
    parser.add_argument("--json", help="write the deterministic plan to this path")
    parser.add_argument("--show", type=int, default=10)
    args = parser.parse_args(argv)

    if args.target_end is None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        current_path, _ = select_reference_file(
            today, lake=cov.LAKE, fallback=cov.CALENDAR, name="trade_calendar")
        calendar = cov.TradingCalendar(current_path)
        if today > calendar.last:
            raise ValueError(f"reference calendar stale after {calendar.last}; collect today's snapshot first")
        target = cov.default_target_end(calendar)
    else:
        target = args.target_end
    plan = build_plan(
        args.dataset,
        target_end=target,
        only_symbols=set(args.symbols) if args.symbols else None,
        action_limit=args.limit,
    )
    summary = plan["summary"]
    print(f"dataset: {plan['dataset']}")
    print(f"target:  {plan['target_end']}")
    print(f"universe: {plan['universe']['listed_symbols']} listed A-shares; "
          f"{plan['universe']['excluded_nonlisted_files']} non-listed files ignored")
    print("status:   full={full} tail={tail} suspended-tail={suspended_tail} "
          "refresh-last={refresh_last} current={up_to_date} ahead={ahead} "
          "not-yet-listed={not_yet_listed}".
          format(**summary))
    print(f"plan:     {summary['actions_in_plan']} / {summary['actions_total']} actions")
    print(f"sha256:   {plan['plan_sha256']}")
    for action in plan["actions"][:args.show]:
        print("  {symbol} {action} {fetch_start}..{fetch_end} ({n_trading_days} days)".
              format(**action))
    if args.json:
        output = Path(args.json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        print(f"plan file: {output}")
    print("read-only scan: no network request and no data-lake write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
