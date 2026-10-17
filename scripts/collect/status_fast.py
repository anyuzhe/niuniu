"""Fast daily status update: tradestatus from the day's own bar, isST carried forward.

Asking Baostock about all ~5,200 symbols for one new day takes 1.5-2 h. Two facts make that
unnecessary: the trading flag equals ``volume > 0`` of the day's daily bar already on disk (0 mismatches
over 208,409 stock-days, last 40 days), and ``isST`` flips on only a handful of symbols per week.
So the day's row is derived locally, and only the symbols where that could be wrong are asked from
Baostock one by one: ST on the previous day, no bar today, or (when the day's ``all_stock`` snapshot is
complete) the name disagrees with the carried flag (name contains ST or 退).

Flow: ``plan`` -> ``apply --approve-sha256`` (like status_incremental.py), ``reconcile-plan`` ->
``reconcile-apply`` weekly. Symbols with no status file or with a lagging history are not touched;
status_incremental.py fills those. Every derived row is listed in
``_receipts/status-fast-provenance-<day>.json`` (derived vs asked) so ``reconcile`` can re-read exactly
those rows from Baostock and fix any difference. Derived rows are appended without a per-file backup
(one appended row, undo = drop it, provenance names every file); rows asked from Baostock are backed up.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import coverage
from collect.baostock_daily_status import DEFAULT_DEST, REQUIRED, StatusSession
from collect.daily_common import (atomic_parquet, backup_verified, canonical_digest, observed_state,
                                  run_lock, sha256_file, symbol_file, validate_observed_state,
                                  write_json_atomic)
from collect.paths import bronze
from collect.status_incremental import merge_status

RAW_DIR = bronze("baostock", "stock_kline_daily")
MIN_BARS = 4000  # fewer bars than this on the day = the day's bars are not in yet
NAME_MARKS = ("ST", "退")
RECONCILE_KEEP = 12  # provenance files looked at by one reconcile


class _OneDay:
    def __init__(self, day: date):
        self.day = day

    def between(self, start: date, end: date) -> list[date]:
        return [self.day] if start <= self.day <= end else []


class _Days:
    def __init__(self, days: list[date]):
        self.days = sorted(days)

    def between(self, start: date, end: date) -> list[date]:
        return [d for d in self.days if start <= d <= end]


def code_of(path: Path) -> str:
    return path.stem.replace("_", ".", 1)


def name_flag(name: str) -> bool:
    return any(mark in name for mark in NAME_MARKS)


def day_names(day: date, lake: Path | None = None) -> tuple[dict[str, bool] | None, dict | None]:
    """Names from the day's reference snapshot, only when that snapshot is complete."""
    import pandas as pd
    snap = (lake or coverage.LAKE) / "provider=baostock" / "reference_snapshots" / f"snapshot={day.isoformat()}"
    try:
        manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    entry = [x for x in manifest.get("results", []) if x.get("name") == "all_stock"]
    path = snap / "all_stock.parquet"
    if manifest.get("run_status") != "completed" or len(entry) != 1 or entry[0].get("status") != "ok" or not path.is_file():
        return None, None
    frame = pd.read_parquet(path, columns=["code", "code_name"])
    frame = frame[frame["code"].notna()]
    if frame.empty:
        return None, None
    flags = {str(c): name_flag("" if n is None or n != n else str(n)) for c, n in zip(frame["code"], frame["code_name"])}
    return flags, {"path": str(path), "sha256": sha256_file(path), "count": len(flags)}


def _bar_volume(raw_dir: Path, code: str, day: date):
    import pyarrow.parquet as pq
    path = raw_dir / (code.replace(".", "_", 1) + ".parquet")
    if not path.is_file():
        return None
    table = pq.read_table(path, columns=["date", "volume"], filters=[("date", "==", day)])
    if table.num_rows != 1:
        return None
    value = table.column("volume")[0].as_py()
    return None if value is None else int(value)


def build_plan(root: Path, day: date, *, raw_dir: Path = RAW_DIR, names: dict[str, bool] | None | str = "auto",
               names_info: dict | None = None, lake: Path | None = None) -> dict:
    import pandas as pd
    if isinstance(names, str):  # "auto"
        names, names_info = day_names(day, lake)
    state = {}
    for path in sorted(root.glob("*.parquet")):
        frame = pd.read_parquet(path, columns=["date", "tradestatus", "isST"])
        if frame.empty:
            raise ValueError(f"empty status file: {path.name}")
        i = frame["date"].astype(str).idxmax()
        state[code_of(path)] = (str(frame.at[i, "date"])[:10], str(frame.at[i, "isST"]))
    if not state:
        raise ValueError("status dataset has no files")
    previous_days = Counter(v[0] for v in state.values() if v[0] < day.isoformat())
    if not previous_days:
        raise ValueError(f"no status history before {day}")
    previous = previous_days.most_common(1)[0][0]
    actions, lagging, present = [], [], []
    bars = 0
    for code, (last, prev_st) in sorted(state.items()):
        if last == day.isoformat():
            present.append(code)
            continue
        if last != previous:
            lagging.append(code)
            continue
        volume = _bar_volume(raw_dir, code, day)
        bars += volume is not None
        reasons = []
        if prev_st == "1":
            reasons.append("st_yesterday")
        if volume is None:
            reasons.append("no_bar")
        if names is not None and code in names and names[code] != (prev_st == "1"):
            reasons.append("name_differs")
        action = {"code": code, "mode": "query" if reasons else "derive", "reasons": reasons,
                  **observed_state(root, code)}
        if not reasons:
            action.update(tradestatus="1" if volume > 0 else "0", isST=prev_st)
        actions.append(action)
    # codes whose status already has the day were derived from that day's bars (by this tool or by the slow path),
    # so they count as evidence the day is in; otherwise a rerun after a finished day would call it "not complete"
    if len(present) + bars < MIN_BARS:
        raise ValueError(f"only {len(present) + bars} daily bars on {day}; the day's bars are not complete yet")
    stems = {code_of(p) for p in raw_dir.glob("*.parquet")}
    plan = {"schema_version": 1, "kind": "baostock_status_fast", "root": str(root.resolve()),
            "raw_dir": str(raw_dir.resolve()), "day": day.isoformat(), "previous_day": previous,
            "names": names_info, "bars_on_day": bars, "derive": sum(a["mode"] == "derive" for a in actions),
            "query": sum(a["mode"] == "query" for a in actions), "already_present": len(present),
            "lagging": lagging, "no_status_file": sorted(stems - set(state)), "actions": actions}
    plan["plan_sha256"] = canonical_digest(plan)
    return plan


def _receipt_path(root: Path, sha: str, kind: str = "status-fast") -> Path:
    return root / "_receipts" / f"{kind}-{sha[:16]}.json"


def _validate(plan: dict, kind: str) -> list[dict]:
    if plan.get("kind") != kind or canonical_digest(plan) != plan.get("plan_sha256"):
        raise ValueError("invalid status plan identity")
    root = Path(plan["root"])
    if not root.is_dir():
        raise ValueError("status dataset missing")
    return plan["actions"]


def apply(plan: dict, *, timeout: float = 120, throttle: float = .5, resume_run: bool = False,
          session_factory=StatusSession) -> dict:
    root = Path(plan["root"])
    with run_lock(root, "baostock-status-daily"):
        return _apply_unlocked(plan, root, timeout, throttle, resume_run, session_factory)


def _already_applied(root: Path, action: dict, day: date) -> bool:
    import pandas as pd
    if action["mode"] != "derive":
        return False
    frame = pd.read_parquet(symbol_file(root, action["code"]), columns=["date", "tradestatus", "isST"])
    last = frame.iloc[frame["date"].astype(str).values.argmax()]
    return (str(last["date"])[:10] == day.isoformat() and last["tradestatus"] == action["tradestatus"]
            and last["isST"] == action["isST"])


def _apply_unlocked(plan, root, timeout, throttle, resume_run, session_factory) -> dict:
    actions = _validate(plan, "baostock_status_fast")
    day = date.fromisoformat(plan["day"])
    receipt = _receipt_path(root, plan["plan_sha256"])
    done: set[str] = set()
    if receipt.exists():
        if not resume_run:
            raise FileExistsError(f"run already exists: {receipt}")
        result = json.loads(receipt.read_text(encoding="utf-8"))
        if result.get("plan_sha256") != plan["plan_sha256"] or result.get("run_status") == "finished":
            raise ValueError("cannot resume unrelated or completed run")
        for row in result["results"]:
            if row["status"] == "ok":
                if observed_state(root, row["code"])["parquet_sha256"] != row["sha256_after"]:
                    raise ValueError(f"completed status output changed: {row['code']}")
                done.add(row["code"])
    else:
        result = {"plan_sha256": plan["plan_sha256"], "day": plan["day"], "run_status": "running", "results": []}
        write_json_atomic(receipt, result)
    pending = []
    for action in actions:
        if action["code"] in done:
            continue
        try:
            validate_observed_state(root, action)
        except ValueError:
            # a crash between checkpoints leaves files written but not yet in the receipt: accept
            # them only if the stored last row is exactly what this plan derives
            if not (resume_run and _already_applied(root, action, day)):
                raise
            result["results"] = [x for x in result["results"] if x["code"] != action["code"]] + [
                {"code": action["code"], "mode": action["mode"], "status": "ok", "resumed": True,
                 "sha256_after": observed_state(root, action["code"])["parquet_sha256"]}]
            continue
        pending.append(action)
    backup_root = coverage.DATA_ROOT / "backups" / f"status-fast-{plan['plan_sha256'][:16]}"
    calendar = _OneDay(day)
    session = None

    def write(action: dict, frame) -> dict:
        merged, old_rows = merge_status(root, {"code": action["code"], "start": day.isoformat(),
                                               "end": day.isoformat()}, frame, calendar)
        path = symbol_file(root, action["code"])
        row = {"old_rows": old_rows}
        if action["mode"] == "query":
            row["backup"] = backup_verified(path, backup_root / path.name, action["parquet_sha256"])
        row["sha256_after"] = atomic_parquet(merged, path)
        return row

    try:
        for action in pending:
            code = action["code"]
            row = {"code": code, "mode": action["mode"]}
            try:
                if action["mode"] == "derive":
                    import pandas as pd
                    frame = pd.DataFrame([[day.isoformat(), code, action["tradestatus"], action["isST"],
                                           datetime.now().astimezone().isoformat()]],
                                         columns=REQUIRED + ["fetch_ts"])
                else:
                    if session is None:
                        session = session_factory({a["code"]: day for a in pending if a["mode"] == "query"},
                                                  day, timeout)
                    frame = session(code)
                row.update(status="ok", **write(action, frame))
            except Exception as exc:
                row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                reset = getattr(session, "_start", None)
                if session is not None and getattr(session, "connection", None) is None and callable(reset):
                    reset()
            result["results"] = [x for x in result["results"] if x["code"] != code] + [row]
            if action["mode"] == "query":
                write_json_atomic(receipt, result)
                time.sleep(throttle)
            elif len(result["results"]) % 500 == 0:
                write_json_atomic(receipt, result)
    finally:
        if session is not None:
            session.close()
    result["run_status"] = ("finished_with_errors" if any(x["status"] == "failed" for x in result["results"])
                            else "finished")
    write_json_atomic(receipt, result)
    ok = {x["code"]: x["mode"] for x in result["results"] if x["status"] == "ok"}
    write_json_atomic(root / "_receipts" / f"status-fast-provenance-{plan['day']}.json", {
        "day": plan["day"], "plan_sha256": plan["plan_sha256"], "reconciled": False,
        "derived": sorted(c for c, m in ok.items() if m == "derive"),
        "asked": sorted(c for c, m in ok.items() if m == "query"),
        "names": plan.get("names"), "failed": sorted(x["code"] for x in result["results"] if x["status"] == "failed")})
    return result


# ---------------------------------------------------------------- weekly reconcile

def _open_provenance(root: Path) -> list[dict]:
    files = sorted((root / "_receipts").glob("status-fast-provenance-*.json"))
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    return [r for r in rows if not r.get("reconciled")][-RECONCILE_KEEP:]


def build_reconcile_plan(root: Path) -> dict:
    """Re-read every derived row of the open days from Baostock, one request per symbol."""
    open_days = _open_provenance(root)
    if not open_days:
        raise ValueError("nothing to reconcile")
    per_code: dict[str, list[str]] = {}
    for row in open_days:
        for code in row["derived"]:
            per_code.setdefault(code, []).append(row["day"])
    actions = [{"code": code, "days": sorted(days), **observed_state(root, code)}
               for code, days in sorted(per_code.items())]
    plan = {"schema_version": 1, "kind": "baostock_status_reconcile", "root": str(root.resolve()),
            "days": [r["day"] for r in open_days], "actions": actions}
    plan["plan_sha256"] = canonical_digest(plan)
    return plan


def reconcile_apply(plan: dict, *, timeout: float = 120, throttle: float = .5, session_factory=StatusSession) -> dict:
    import pandas as pd
    root = Path(plan["root"])
    with run_lock(root, "baostock-status-daily"):
        actions = _validate(plan, "baostock_status_reconcile")
        receipt = _receipt_path(root, plan["plan_sha256"], "status-reconcile")
        if receipt.exists():
            raise FileExistsError(f"run already exists: {receipt}")
        for action in actions:
            validate_observed_state(root, action)
        backup_root = coverage.DATA_ROOT / "backups" / f"status-reconcile-{plan['plan_sha256'][:16]}"
        first = min(date.fromisoformat(d) for d in plan["days"])
        last = max(date.fromisoformat(d) for d in plan["days"])
        session = session_factory({a["code"]: first for a in actions}, last, timeout)
        result = {"plan_sha256": plan["plan_sha256"], "run_status": "running", "checked": 0, "changed": [], "failed": []}
        write_json_atomic(receipt, result)
        try:
            for action in actions:
                code = action["code"]
                try:
                    truth = session(code)
                    want = set(action["days"])
                    truth = truth[truth["date"].astype(str).str[:10].isin(want)]
                    if set(truth["date"].astype(str).str[:10]) != want:
                        raise ValueError(f"provider lacks days for {code}")
                    path = symbol_file(root, code)
                    old = pd.read_parquet(path)
                    key = old["date"].astype(str).str[:10]
                    stored = old[key.isin(want)].set_index(key[key.isin(want)])[["tradestatus", "isST"]]
                    asked = truth.assign(d=truth["date"].astype(str).str[:10]).set_index("d")[["tradestatus", "isST"]]
                    diff = sorted(d for d in want if tuple(stored.loc[d]) != tuple(asked.loc[d]))
                    if diff:
                        fixed = old.copy()
                        for d in diff:
                            mask = key == d
                            fixed.loc[mask, "tradestatus"] = asked.loc[d, "tradestatus"]
                            fixed.loc[mask, "isST"] = asked.loc[d, "isST"]
                            fixed.loc[mask, "fetch_ts"] = datetime.now().astimezone().isoformat()
                        backup_verified(path, backup_root / path.name, action["parquet_sha256"])
                        atomic_parquet(fixed, path)
                        result["changed"].append({"code": code, "days": diff,
                                                  "stored": {d: list(stored.loc[d]) for d in diff},
                                                  "baostock": {d: list(asked.loc[d]) for d in diff}})
                except Exception as exc:
                    result["failed"].append({"code": code, "error": f"{type(exc).__name__}: {exc}"})
                    reset = getattr(session, "_start", None)
                    if getattr(session, "connection", None) is None and callable(reset):
                        reset()
                result["checked"] += 1
                if result["checked"] % 200 == 0:
                    write_json_atomic(receipt, result)
                time.sleep(throttle)
        finally:
            session.close()
        result["run_status"] = "finished_with_errors" if result["failed"] else "finished"
        write_json_atomic(receipt, result)
        if not result["failed"]:
            for p in (root / "_receipts").glob("status-fast-provenance-*.json"):
                row = json.loads(p.read_text(encoding="utf-8"))
                if row["day"] in plan["days"] and not row.get("reconciled"):
                    row.update(reconciled=True, reconciled_by=plan["plan_sha256"])
                    write_json_atomic(p, row)
        return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("plan", "apply", "reconcile-plan", "reconcile-apply"))
    parser.add_argument("--dest", default=DEFAULT_DEST)
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--plan-output")
    parser.add_argument("--plan")
    parser.add_argument("--approve-sha256")
    parser.add_argument("--resume-run", action="store_true")
    parser.add_argument("--request-timeout", type=float, default=120)
    parser.add_argument("--throttle", type=float, default=.5)
    args = parser.parse_args(argv)
    root = Path(args.dest)
    if args.command in ("plan", "reconcile-plan"):
        if args.command == "plan":
            if args.day is None:
                parser.error("plan needs --day")
            plan = build_plan(root, args.day)
            summary = {k: plan[k] for k in ("day", "previous_day", "bars_on_day", "derive", "query", "already_present")}
            summary.update(lagging=len(plan["lagging"]), no_status_file=len(plan["no_status_file"]),
                           names=bool(plan["names"]))
        else:
            plan = build_reconcile_plan(root)
            summary = {"days": plan["days"], "symbols": len(plan["actions"])}
        summary["plan_sha256"] = plan["plan_sha256"]
        print(json.dumps(summary, ensure_ascii=False))
        if args.plan_output:
            write_json_atomic(Path(args.plan_output), plan)
        return 0
    if not args.plan or not args.approve_sha256:
        raise PermissionError("apply requires --plan and --approve-sha256")
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if args.approve_sha256 != plan.get("plan_sha256") or root.resolve() != Path(plan["root"]):
        raise PermissionError("approved plan SHA or destination mismatch")
    if args.command == "apply":
        result = apply(plan, timeout=args.request_timeout, throttle=args.throttle, resume_run=args.resume_run)
        print(json.dumps({"run_status": result["run_status"], "results": len(result["results"]),
                          "failed": sum(x["status"] == "failed" for x in result["results"])}, ensure_ascii=False))
    else:
        result = reconcile_apply(plan, timeout=args.request_timeout, throttle=args.throttle)
        print(json.dumps({"run_status": result["run_status"], "checked": result["checked"],
                          "changed": len(result["changed"]), "failed": len(result["failed"])}, ensure_ascii=False))
    return 0 if result["run_status"] == "finished" else 1


if __name__ == "__main__":
    raise SystemExit(main())
