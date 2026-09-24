"""Record one-minute THS sector-board snapshots during the trading session.

Runs as one long process on the Mac (the launcher ``.command`` starts it before the
open).  It first refreshes the day's board-constituents snapshot
(``sector_constituents.py``, a few minutes) that feeds ``constituent_count``.  Every ``--interval`` seconds between 09:15 and 15:01 Beijing time it asks the
DATA provider ``SectorIntradayProvider.board_snapshot`` for concept + industry
boards and appends the rows to one Parquet file per minute:

    <data-root>/lake/bronze/provider=fuyao/sector_board_intraday/date=YYYY-MM-DD/HHMMSS.parquet

plus ``_receipts/<date>.json`` (one entry per sample: ok / failed, row count, SHA-256).
Failures are recorded and never written as empty data.  Exits on a non-trading day
and after the close.  No approval SHA: the recorder only reads a live source the
user asked to record (2026-09-24) and writes new files, never rewrites old ones.

    python scripts/collect/sector_intraday_recorder.py            # today, 60 s
    python scripts/collect/sector_intraday_recorder.py --once     # one sample now (test)
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
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from collect import paths  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
START, END = "09:15", "15:01"


def _atomic(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return hashlib.sha256(data).hexdigest()


def sample(provider, target: Path) -> dict:
    import pandas as pd
    now = datetime.now(TZ)
    entry = {"sampled_at": now.isoformat()}
    try:
        value = provider.board_snapshot(["concept", "industry"])
        frame = pd.DataFrame(value["boards"])
        frame["market_status"] = value["market_status"]
        frame["snapshot_as_of"] = value["as_of"]
        frame["stale"] = bool(value.get("stale"))
        buf = io.BytesIO()
        frame.to_parquet(buf, index=False)
        name = now.strftime("%H%M%S") + ".parquet"
        entry.update(status="ok", file=name, rows=len(frame), completeness=value["completeness"],
                     market_status=value["market_status"], as_of=value["as_of"], stale=bool(value.get("stale")),
                     sha256=_atomic(target / name, buf.getvalue()))
    except Exception as error:  # recorded, never written as data
        entry.update(status="failed", error=f"{type(error).__name__}: {error}"[:300])
    return entry


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=str(paths.DATA_ROOT))
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    from quantlab.data.sector_intraday import SectorIntradayProvider
    provider = SectorIntradayProvider(data_root=args.data_root, min_interval_boards=min(10.0, args.interval))
    today = datetime.now(TZ).date().isoformat()
    base = Path(args.data_root) / "lake/bronze/provider=fuyao/sector_board_intraday"
    target = base / f"date={today}"
    receipt_path = base / "_receipts" / f"{today}.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {"date": today, "samples": []}

    def record(entry):
        receipt["samples"].append(entry)
        _atomic(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=1) + "\n").encode())
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    if args.once:
        record(sample(provider, target))
        return 0
    try:
        if not provider._trading_day("sector_board_intraday", today):
            print(f"{today} 不是交易日，退出。")
            return 0
    except Exception as error:
        print(f"交易日历读取失败：{error}")
        return 1
    # Daily constituents snapshot (for constituent_count); a few minutes, resumable.
    try:
        from collect.sector_constituents import run as snapshot_constituents
        for _ in range(5):
            result = snapshot_constituents(Path(args.data_root), max_seconds=600)
            print(json.dumps({k: v for k, v in result.items() if k != "empty_boards"}, ensure_ascii=False), flush=True)
            if result.get("complete") or result.get("status") == "already_complete":
                break
    except Exception as error:
        print(f"成分快照失败（盘中板块照常记录，constituent_count 沿用上一天）：{error}", flush=True)
    while True:
        hm = datetime.now(TZ).strftime("%H:%M")
        if hm >= END:
            print("已收盘，记录结束。", flush=True)
            return 0
        if hm < START or "11:31" <= hm < "12:59":
            time.sleep(15)
            continue
        started = time.monotonic()
        record(sample(provider, target))
        time.sleep(max(1.0, args.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    sys.exit(main())
