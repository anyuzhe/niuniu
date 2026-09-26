"""Baostock daily + 5-minute bars for A shares delisted since 2020 (survivorship fix).

The main bar datasets (``stock_kline_daily``, ``stock_kline_min5``) hold listed stocks
only.  Whole-market statistics over history need the stocks that were trading then
and have since been delisted.  This collector writes them to separate directories so
the listed-only datasets keep their contract:

    <data-root>/lake/bronze/provider=baostock/stock_kline_daily_delisted/<sh_600087>.parquet
        date, code, open, high, low, close, preclose, volume, amount, adjustflag,
        tradestatus, isST, fetch_ts        (unadjusted; suspended days kept, tradestatus=0)
    <data-root>/lake/bronze/provider=baostock/stock_kline_min5_delisted/<sh_600087>.parquet
        same columns as stock_kline_min5

    python scripts/collect/bars_delisted.py plan [--since 2020-01-01]
    python scripts/collect/bars_delisted.py apply --plan PATH --approve SHA

``apply`` is resumable (state file per plan) and paces requests >= 1 s on one login.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import paths  # noqa: E402
from collect.bars_incremental import REQUEST_FIELDS, BaostockSession  # noqa: E402
from collect.daily_common import select_stock_basic  # noqa: E402

BASE = "lake/bronze/provider=baostock"
MIN5_FLOOR = "2020-01-02"
DIRS = {"baostock-daily-ext": "stock_kline_daily_delisted", "baostock-min5": "stock_kline_min5_delisted"}


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def plan(root: Path, since: str) -> tuple[Path, str]:
    import pandas as pd
    from datetime import date
    basic_path, _ = select_stock_basic(date.today(), lake=root / "lake/bronze", fallback=None)
    basic = pd.read_parquet(basic_path)
    sel = basic[(basic["type"].astype(str) == "1") & (basic["status"].astype(str) == "0")
                & (basic["outDate"].astype(str) >= since)]
    targets = []
    for row in sel.sort_values("code").itertuples(index=False):
        code, ipo, out = str(row.code), str(row.ipoDate), str(row.outDate)
        start = max(ipo, "2019-12-01")
        targets.append({"symbol": code, "name": str(row.code_name), "ipo": ipo, "out": out,
                        "daily": [start, out], "min5": [max(ipo, MIN5_FLOOR), out] if out >= MIN5_FLOOR else None})
    body = {"kind": "baostock_delisted_bars", "since": since, "data_root": str(root),
            "stock_basic": str(basic_path), "created_at": datetime.now(timezone.utc).isoformat(), "targets": targets}
    data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode()
    sha = hashlib.sha256(data).hexdigest()
    path = root / BASE / "_plans" / f"delisted-bars-{sha[:12]}.json"
    _atomic(path, data)
    return path, sha


def _frame(rows, dataset):
    import pandas as pd
    cols = REQUEST_FIELDS[dataset].split(",")
    frame = pd.DataFrame(rows, columns=cols)
    for c in ("open", "high", "low", "close", "amount") + (("preclose",) if "preclose" in cols else ()):
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0).astype("int64")
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["fetch_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if dataset == "baostock-min5":
        frame = frame[frame["volume"] > 0]       # match stock_kline_min5 (no blank bars)
    return frame


def apply(plan_path: Path, approve: str, *, max_seconds: float, pace: float = 1.0, log=print) -> dict:
    data = plan_path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != approve:
        raise SystemExit(f"plan SHA mismatch: {sha}")
    body = json.loads(data)
    root = Path(body["data_root"])
    state_path = root / BASE / "_state" / f"delisted-bars-{sha[:12]}.json"
    state = json.loads(state_path.read_text()) if state_path.is_file() else {"done": {}, "failed": {}}
    start = time.monotonic()
    for dataset in DIRS:
        key_name = "daily" if dataset == "baostock-daily-ext" else "min5"
        todo = [t for t in body["targets"] if t[key_name] and f"{dataset}/{t['symbol']}" not in state["done"]]
        if not todo:
            continue
        log(f"{dataset}: {len(todo)} to fetch")
        session = BaostockSession(dataset, 90.0)
        try:
            for i, t in enumerate(todo, 1):
                if time.monotonic() - start > max_seconds:
                    break
                key = f"{dataset}/{t['symbol']}"
                t0 = time.monotonic()
                try:
                    rows = session(t["symbol"], *t[key_name])
                    frame = _frame(rows, dataset)
                    out = root / BASE / DIRS[dataset] / (t["symbol"].replace(".", "_", 1) + ".parquet")
                    if len(frame):
                        buf = io.BytesIO()
                        frame.to_parquet(buf, index=False)
                        _atomic(out, buf.getvalue())
                    state["done"][key] = {"rows": int(len(frame)), "status": "ok" if len(frame) else "empty"}
                    state["failed"].pop(key, None)
                except Exception as error:
                    state["failed"][key] = f"{type(error).__name__}: {error}"[:200]
                    try:
                        session.reset()
                    except Exception:
                        pass
                if i % 20 == 0:
                    _atomic(state_path, json.dumps(state, ensure_ascii=False).encode())
                    log(f"{dataset} {i}/{len(todo)} {time.monotonic() - start:.0f}s")
                time.sleep(max(0.0, pace - (time.monotonic() - t0)))
        finally:
            session.close()
    _atomic(state_path, json.dumps(state, ensure_ascii=False).encode())
    total = sum(1 for t in body["targets"] for k in ("daily", "min5") if t[k])
    summary = {"plan_sha": sha, "targets": len(body["targets"]), "requests": total, "done": len(state["done"]),
               "failed": state["failed"], "elapsed_s": round(time.monotonic() - start, 1)}
    _atomic(root / BASE / "_receipts" / f"delisted-bars-{sha[:12]}-{datetime.now():%Y%m%dT%H%M%S}.json",
            json.dumps(summary, ensure_ascii=False, indent=1).encode())
    log(json.dumps({k: (len(v) if k == "failed" else v) for k, v in summary.items()}, ensure_ascii=False))
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--since", default="2020-01-01")
    a = sub.add_parser("apply")
    a.add_argument("--plan", required=True)
    a.add_argument("--approve", required=True)
    a.add_argument("--max-seconds", type=float, default=6 * 3600)
    args = parser.parse_args(argv)
    if args.command == "plan":
        path, sha = plan(paths.DATA_ROOT, args.since)
        print(json.dumps({"plan": str(path), "sha256": sha, "targets": len(json.loads(path.read_text())["targets"])}))
        return 0
    summary = apply(Path(args.plan), args.approve, max_seconds=args.max_seconds, log=lambda m: print(m, flush=True))
    return 0 if not summary["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
