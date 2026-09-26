"""Record one-minute THS sector-board snapshots during the trading session.

Runs as one long process on the Mac (the launcher ``.command`` starts it before the
open); only one recorder runs at a time (``catalog/jobs/sector_recorder.lock``).  At 09:25,
10:00, 11:30, 14:00, 14:57 and 15:00 it also writes a whole-market stock snapshot
(``stock_intraday_snapshot``), 30 s after the slot and only until the slot's deadline in
``stock_intraday.SNAPSHOT_DEADLINES``; a slot that could not be taken in time is receipted as
``missed``, never taken later under its label.  The day's board-constituents snapshot
(``sector_constituents.py``) that feeds ``constituent_count`` is refreshed in bounded slices
before the open, over lunch and in the spare seconds of each minute, so it never holds up the
samples.  Every ``--interval`` seconds between 09:15 and 15:01 Beijing time it asks the
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
LOCK = "catalog/jobs/sector_recorder.lock"
STOCK_SNAPSHOTS = "lake/bronze/provider=fuyao/stock_intraday_snapshot"


def hold_single_instance(data_root: Path):
    """Open handle holding the recorder lock, or ``None`` when another recorder holds it.

    Two recorders would each keep the day's receipt in memory and overwrite each other's."""
    path = data_root / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        import fcntl
    except ImportError:
        return handle
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _at(today: str, hhmm: str) -> float:
    return datetime.strptime(f"{today} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ).timestamp()


def slot_actions(now: datetime, today: str, done: set, missed: set) -> tuple[list[str], list[str]]:
    """(slots to capture now, slots whose window closed without a snapshot)."""
    from quantlab.data.stock_intraday import SNAPSHOT_DEADLINES, SNAPSHOT_TIMES
    capture, lapsed = [], []
    for slot in SNAPSHOT_TIMES:
        if slot in done or slot in missed:
            continue
        if now.timestamp() >= _at(today, SNAPSHOT_DEADLINES[slot]):
            lapsed.append(slot)
        elif now.timestamp() >= _at(today, slot) + 30:
            capture.append(slot)
    return capture, lapsed


class ConstituentsRefresh:
    """The day's board-constituents snapshot in bounded slices, so it never holds up the samples."""
    PASSES = 5  # full passes over the board list with failures before giving up for the day

    def __init__(self, data_root: Path, run=None):
        self.data_root = data_root
        self.run = run
        self.done = False
        self.passes = 0

    def step(self, budget: float) -> None:
        if self.done or budget < 5:
            return
        try:
            if self.run is None:
                from collect.sector_constituents import run
                self.run = run
            result = self.run(self.data_root, max_seconds=budget)
        except Exception as error:
            self.passes += 1
            self.done = self.passes >= self.PASSES
            print(f"成分快照失败（盘中板块照常记录，constituent_count 沿用上一天）：{error}", flush=True)
            return
        print(json.dumps({k: v for k, v in result.items() if k != "empty_boards"}, ensure_ascii=False), flush=True)
        if result.get("complete") or result.get("status") == "already_complete":
            self.done = True
        elif not result.get("timed_out"):
            self.passes += 1
            self.done = self.passes >= self.PASSES


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


def _stock_receipt(data_root: Path, today: str, entry: dict) -> None:
    receipt_path = data_root / STOCK_SNAPSHOTS / "_receipts" / f"{today}.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {"date": today, "samples": []}
    receipt["samples"].append(entry)
    _atomic(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=1) + "\n").encode())
    print(json.dumps({k: v for k, v in entry.items() if k != "meta"}, ensure_ascii=False), flush=True)


def mark_missed(data_root: Path, slot: str) -> dict:
    from quantlab.data.stock_intraday import SNAPSHOT_DEADLINES
    now = datetime.now(TZ)
    entry = {"sampled_at": now.isoformat(), "slot": slot, "status": "missed",
             "reason": f"{SNAPSHOT_DEADLINES[slot]} 前没有取到（记录器没在运行或取数失败），过后不再以这个时点补取"}
    _stock_receipt(data_root, now.date().isoformat(), entry)
    return entry


def stock_snapshot(data_root: Path, client, label: str, public_loader=None, due: float | None = None) -> dict:
    """One whole-market snapshot written to stock_intraday_snapshot/date=D/<HHMM>.parquet."""
    import pandas as pd
    from quantlab.data.stock_intraday import capture, universe
    now = datetime.now(TZ)
    today = now.date().isoformat()
    base = data_root / STOCK_SNAPSHOTS
    entry = {"sampled_at": now.isoformat(), "slot": label}
    if due is not None:
        entry.update(due_at=datetime.fromtimestamp(due, TZ).isoformat(), delay_seconds=round(now.timestamp() - due, 1))
    try:
        rows, meta = capture(client, universe(data_root), public_loader=public_loader)
        frame = pd.DataFrame(rows)
        frame["slot"] = label
        buf = io.BytesIO()
        frame.to_parquet(buf, index=False)
        name = label.replace(":", "") + ".parquet"
        entry.update(status="ok", file=name, rows=len(frame), meta=meta,
                     sha256=_atomic(base / f"date={today}" / name, buf.getvalue()))
    except Exception as error:
        entry.update(status="failed", error=f"{type(error).__name__}: {error}"[:300])
    _stock_receipt(data_root, today, entry)
    return entry


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=str(paths.DATA_ROOT))
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--stock-snapshot-now", action="store_true", help="立即做一次全市场个股快照（测试用）")
    args = parser.parse_args(argv)
    data_root = Path(args.data_root)
    lock = hold_single_instance(data_root)
    if lock is None:
        print("另一个盘中记录器正在运行，本次退出（两个记录器会互相覆盖回执）。", flush=True)
        return 1
    from quantlab.data.day_seals import is_sealed
    from quantlab.data.sector_intraday import SectorIntradayProvider
    from quantlab.data.stock_intraday import SNAPSHOT_TIMES
    provider = SectorIntradayProvider(data_root=args.data_root, min_interval_boards=min(10.0, args.interval))
    try:
        from quantlab.trading.public_web_market_snapshot import _http, _tencent
        public_loader = lambda symbols: _tencent(symbols, _http)[0]  # noqa: E731
    except Exception:
        public_loader = None
    today = datetime.now(TZ).date().isoformat()
    if is_sealed(data_root, "sector_board_intraday", today) or is_sealed(data_root, "stock_intraday_snapshot", today):
        print(f"{today} 的盘中记录已封存，只读，不再写入。")
        return 1
    base = data_root / "lake/bronze/provider=fuyao/sector_board_intraday"
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
    if args.stock_snapshot_now:
        stock_snapshot(data_root, provider.client, datetime.now(TZ).strftime("%H:%M"), public_loader)
        return 0
    try:
        if not provider._trading_day("sector_board_intraday", today):
            print(f"{today} 不是交易日，退出。")
            return 0
    except Exception as error:
        print(f"交易日历读取失败：{error}")
        return 1
    live = None
    try:
        from quantlab.data.market_breadth_live import LiveBreadth
        live = LiveBreadth(data_root)
    except Exception as error:
        print(f"全市场情绪（实时）初始化失败，本日不记录：{error}", flush=True)
    live_receipt = data_root / "lake/silver/market_intraday_breadth/freq=live/_receipts" / f"{today}.json"
    live_log = {"date": today, "ok": 0, "failed": 0, "last_error": None}

    def record_live():
        try:
            row = live.record()
            live_log["ok"] += 1
            live_log["last"] = {k: row[k] for k in ("time", "n_stocks", "up_count", "down_count", "capture_s", "latency_s")}
        except Exception as error:
            live_log["failed"] += 1
            live_log["last_error"] = f"{type(error).__name__}: {error}"[:300]
            print(f"全市场情绪（实时）失败：{live_log['last_error']}", flush=True)
        _atomic(live_receipt, (json.dumps(live_log, ensure_ascii=False, indent=1) + "\n").encode())

    refresh = ConstituentsRefresh(data_root)
    done_slots, missed_slots = set(), set()
    snap_receipt = data_root / STOCK_SNAPSHOTS / "_receipts" / f"{today}.json"
    if snap_receipt.is_file():
        samples = json.loads(snap_receipt.read_text()).get("samples", [])
        done_slots = {s["slot"] for s in samples if s.get("status") == "ok"}
        missed_slots = {s["slot"] for s in samples if s.get("status") == "missed"}
    while True:
        now = datetime.now(TZ)
        hm = now.strftime("%H:%M")
        capture, lapsed = slot_actions(now, today, done_slots, missed_slots)
        for slot in lapsed:
            mark_missed(data_root, slot)
            missed_slots.add(slot)
        for slot in capture:
            if stock_snapshot(data_root, provider.client, slot, public_loader,
                              due=_at(today, slot) + 30).get("status") == "ok":
                done_slots.add(slot)
        if hm >= END and all(slot in done_slots or slot in missed_slots for slot in SNAPSHOT_TIMES):
            print("已收盘，记录结束。", flush=True)
            return 0
        if hm >= "15:25":
            print("已收盘，记录结束（部分时点快照未成功，见回执）。", flush=True)
            return 0
        if hm < START or "11:31" <= hm < "12:59" or hm >= END:
            if hm < END:  # use the wait for the constituents snapshot, ending a minute before sampling resumes
                resume = _at(today, START if hm < START else "12:59")
                refresh.step(min(600.0, resume - time.time() - 60))
            time.sleep(15)
            continue
        started = time.monotonic()
        if live is not None and ("09:25" <= hm <= "11:30" or "13:00" <= hm <= "15:00"):
            record_live()
        record(sample(provider, target))
        refresh.step(args.interval - (time.monotonic() - started) - 10)
        time.sleep(max(1.0, args.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    sys.exit(main())
