"""Collect one immutable Baostock reference snapshot into a new batch directory.

The script never overwrites a prior batch and never switches a product pointer.
Review prints a deterministic plan hash; real collection requires the exact hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

QUERIES = (
    ("trade_calendar", "query_trade_dates", None),
    ("stock_basic", "query_stock_basic", None),
    ("industry", "query_stock_industry", "snapshot"),
    ("all_stock", "query_all_stock", "snapshot_day"),
    ("sz50", "query_sz50_stocks", "snapshot_date"),
    ("hs300", "query_hs300_stocks", "snapshot_date"),
    ("zz500", "query_zz500_stocks", "snapshot_date"),
)


def canonical_digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_plan(snapshot_date: date, destination: Path) -> dict[str, Any]:
    calls = []
    for name, method, mode in QUERIES:
        if mode is None and name == "trade_calendar":
            params = {"start_date": "1990-12-19", "end_date": snapshot_date.isoformat()}
        elif mode is None:
            params = {}
        elif mode == "snapshot_day":
            params = {"day": snapshot_date.isoformat()}
        else:
            params = {"date": snapshot_date.isoformat()}
        calls.append({"name": name, "method": method, "params": params})
    plan = {"schema_version": 1, "kind": "baostock_reference_snapshot",
            "snapshot_date": snapshot_date.isoformat(),
            "destination": str(destination.resolve()), "calls": calls}
    plan["plan_sha256"] = canonical_digest(plan)
    return plan


def _worker(method: str, params: dict[str, str], connection) -> None:
    try:
        import baostock as bs
        login = bs.login()
        if login.error_code != "0":
            connection.send(("error", f"login {login.error_code}: {login.error_msg}"))
            return
        function = getattr(bs, method, None)
        if function is None:
            connection.send(("error", f"SDK lacks {method}"))
            return
        response = function(**params)
        if response.error_code != "0":
            connection.send(("error", f"query {response.error_code}: {response.error_msg}"))
            return
        fields = list(response.fields)
        rows = []
        while response.error_code == "0" and response.next():
            values = response.get_row_data()
            if len(values) != len(fields):
                raise ValueError("provider row width differs from fields")
            rows.append(values)
        if response.error_code != "0":
            raise RuntimeError(f"pagination {response.error_code}: {response.error_msg}")
        connection.send(("ok", {"fields": fields, "rows": rows}))
    except Exception as exc:
        connection.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        try:
            bs.logout()
        except Exception:
            pass
        connection.close()


def query_isolated(method: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_worker, args=(method, params, child), daemon=True)
    process.start()
    child.close()
    try:
        if not parent.poll(timeout):
            raise TimeoutError(f"{method} exceeded {timeout:.1f}s")
        status, payload = parent.recv()
        if status != "ok":
            raise RuntimeError(payload)
        return payload
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)


def write_atomic(frame, path: Path) -> dict[str, Any]:
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    import pandas as pd
    back = pd.read_parquet(tmp)
    if len(back) != len(frame) or list(back.columns) != list(frame.columns):
        tmp.unlink(missing_ok=True)
        raise ValueError(f"read-back mismatch: {path.name}")
    os.replace(tmp, path)
    raw = path.read_bytes()
    return {"file": path.name, "rows": len(frame),
            "columns": list(frame.columns), "sha256": hashlib.sha256(raw).hexdigest()}


def checkpoint(path: Path, manifest: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--dest", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve-sha256")
    parser.add_argument("--request-timeout", type=float, default=90.0)
    args = parser.parse_args(argv)

    destination = Path(args.dest)
    plan = build_plan(args.snapshot_date, destination)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.apply:
        print("review only: no provider login or write")
        return 0
    if args.approve_sha256 != plan["plan_sha256"]:
        print("REFUSED: approval hash does not match plan", file=sys.stderr)
        return 2
    if destination.exists():
        print(f"REFUSED: destination already exists: {destination}", file=sys.stderr)
        return 2
    destination.mkdir(parents=True)
    manifest: dict[str, Any] = {"plan": plan, "run_status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(), "results": []}
    manifest_path = destination / "manifest.json"
    checkpoint(manifest_path, manifest)
    import pandas as pd
    for index, call in enumerate(plan["calls"], 1):
        record = {**call, "status": "running"}
        try:
            payload = query_isolated(call["method"], call["params"], args.request_timeout)
            frame = pd.DataFrame(payload["rows"], columns=payload["fields"])
            record.update(status="ok", **write_atomic(frame, destination / f"{call['name']}.parquet"))
        except Exception as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        manifest["results"].append(record)
        checkpoint(manifest_path, manifest)
        print(f"[{index}/{len(plan['calls'])}] {call['name']} {record['status']}", flush=True)
    manifest["run_status"] = ("completed_with_errors" if
                              any(r["status"] == "failed" for r in manifest["results"])
                              else "completed")
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    checkpoint(manifest_path, manifest)
    return 1 if manifest["run_status"] == "completed_with_errors" else 0


if __name__ == "__main__":
    raise SystemExit(main())
