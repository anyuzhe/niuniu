"""1-minute (and index 5-minute) bars from the Tongdaxin (TDX) quote servers via pytdx.

TDX servers keep a rolling window: about 21,840 bars per security and period, i.e.
the latest ~91 trading days of 1-minute bars and ~455 trading days of 5-minute bars
(measured 2026-09-25).  Every trading day the oldest day falls out, so the backfill
should run once as early as possible and the daily mode keeps the history growing.

Outputs (one parquet per security, same layout as the Baostock bars):

    <data-root>/lake/bronze/provider=tdx/kline_min1/<sh_600000>.parquet        A shares incl. BSE
    <data-root>/lake/bronze/provider=tdx/index_kline_min1/<sh_000001>.parquet  main indices
    <data-root>/lake/bronze/provider=tdx/index_kline_min5/<sh_000001>.parquet

columns ``date, time('YYYYMMDDHHMMSSsss', bar end), code, open, high, low, close,
volume(shares), amount(yuan, float32 precision on the wire), fetch_ts, provider``;
index files also carry ``up_count, down_count`` (the exchange's advancing/declining
issues at that minute).  The first bar of a day (09:31 / 09:35) includes the opening
call auction, exactly as Baostock's.  Personal research use only (research_only).

    python scripts/collect/tdx_minute.py plan --mode backfill            # prints plan path + SHA
    python scripts/collect/tdx_minute.py apply --plan <path> --approve <sha> [--max-seconds N]

``apply`` is resumable: a per-plan state file records finished securities; rerunning
the same approved plan continues where it stopped.  It refuses to run on a trading
day between 09:10 and 15:10 Beijing time, because the page offsets move while bars
are being added.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT / "src"))
from collect import paths  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
HOSTS = [("180.153.18.170", 7709), ("58.34.106.207", 7709), ("116.205.183.150", 7709), ("116.205.171.132", 7709)]
PAGE = 800
PACE = 0.3                       # seconds between requests on one connection
WORKERS = 4                      # parallel connections, each starting on its own host
INDICES = {"sh.000001": "上证指数", "sh.000300": "沪深300", "sh.000905": "中证500",
           "sh.000852": "中证1000", "sz.399001": "深证成指", "sz.399006": "创业板指"}
MARKET = {"sz": 0, "sh": 1, "bj": 2}
CATEGORY = {"min1": 8, "min5": 0}
PYTDX_CANDIDATES = [ROOT / "artifacts/tdx-source-probe-20260918-013455/upstream/pytdx-1.72",
                    Path("/Volumes/Lexar/niuniu/artifacts/tdx-source-probe-20260918-013455/upstream/pytdx-1.72")]
BASE = "lake/bronze/provider=tdx"


def _load_pytdx():
    try:
        import pytdx  # noqa: F401
    except ImportError:
        extra = [Path(os.environ["TDX_PYTDX_PATH"])] if os.environ.get("TDX_PYTDX_PATH") else []
        for candidate in extra + PYTDX_CANDIDATES:
            if (candidate / "pytdx/hq.py").is_file():
                sys.path.insert(0, str(candidate))
                break
    from pytdx.hq import TdxHq_API
    from pytdx.parser.setup_commands import SetupCmd1, SetupCmd2

    class API(TdxHq_API):
        # pytdx 1.72's third setup command makes these servers reject bar requests
        def setup(self):
            SetupCmd1(self.client).call_api()
            SetupCmd2(self.client).call_api()
    return API


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def targets(data_root: Path) -> list[dict]:
    from quantlab.data.stock_intraday import universe
    out = [{"symbol": s, "kind": "stock", "period": "min1", "dir": "kline_min1"} for s in universe(data_root)]
    for s in INDICES:
        out.append({"symbol": s, "kind": "index", "period": "min1", "dir": "index_kline_min1"})
        out.append({"symbol": s, "kind": "index", "period": "min5", "dir": "index_kline_min5"})
    return out


def file_for(data_root: Path, target: dict) -> Path:
    return data_root / BASE / target["dir"] / (target["symbol"].replace(".", "_") + ".parquet")


def plan(data_root: Path, mode: str) -> tuple[Path, str]:
    body = {"kind": "tdx_minute", "mode": mode, "created_at": datetime.now(timezone.utc).isoformat(),
            "data_root": str(data_root), "hosts": HOSTS, "page": PAGE, "pace": PACE, "workers": WORKERS,
            "targets": targets(data_root)}
    data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode()
    sha = hashlib.sha256(data).hexdigest()
    path = data_root / BASE / "_plans" / f"tdx-minute-{mode}-{sha[:12]}.json"
    _atomic(path, data)
    return path, sha


def _in_session(now: datetime, data_root: Path) -> bool:
    if now.weekday() >= 5:
        return False
    hm = now.strftime("%H:%M")
    return "09:10" <= hm <= "15:10"


def _to_rows(bars: list, target: dict, fetch_ts: str) -> list[dict]:
    rows = []
    for b in bars:
        dt = b["datetime"]                                   # 'YYYY-MM-DD HH:MM', bar end
        row = {"date": dt[:10], "time": dt[:4] + dt[5:7] + dt[8:10] + dt[11:13] + dt[14:16] + "00000",
               "code": target["symbol"], "open": float(b["open"]), "high": float(b["high"]),
               "low": float(b["low"]), "close": float(b["close"]), "volume": int(round(float(b["vol"]))),
               "amount": float(b["amount"]), "fetch_ts": fetch_ts, "provider": "tdx"}
        if target["kind"] == "index":
            row["up_count"] = int(b.get("up_count") or 0)
            row["down_count"] = int(b.get("down_count") or 0)
        rows.append(row)
    return rows


class Worker:
    def __init__(self, API, host_index: int, sleep=time.sleep):
        self.API, self.host_index, self.sleep = API, host_index, sleep
        self.api = None
        self.requests = 0

    def _connect(self):
        host, port = HOSTS[self.host_index % len(HOSTS)]
        self.api = self.API(raise_exception=True)
        if not self.api.connect(host, port, time_out=8):
            raise ConnectionError(f"connect {host}:{port} failed")

    def page(self, target: dict, offset: int) -> list:
        market, code = MARKET[target["symbol"][:2]], target["symbol"][3:]
        category = CATEGORY[target["period"]]
        last_error = None
        for attempt in range(4):
            try:
                if self.api is None:
                    self._connect()
                self.sleep(PACE)
                self.requests += 1
                fn = self.api.get_index_bars if target["kind"] == "index" else self.api.get_security_bars
                return fn(category, market, code, offset, PAGE) or []
            except Exception as error:               # reconnect to the next host and retry
                last_error = error
                try:
                    self.api.disconnect()
                except Exception:
                    pass
                self.api = None
                self.host_index += 1
                self.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"{type(last_error).__name__}: {last_error}")

    def close(self):
        if self.api is not None:
            try:
                self.api.disconnect()
            except Exception:
                pass


def fetch(worker: Worker, target: dict, existing_last: str | None) -> list:
    """Pages backwards from the newest bar; stops at an empty/short page or once the
    page reaches bars already stored (daily mode)."""
    bars, offset = [], 0
    while True:
        page = worker.page(target, offset)
        bars = page + bars
        if len(page) < PAGE:
            break
        if existing_last and page[0]["datetime"][:10] <= existing_last:
            break
        offset += PAGE
        if offset > 30000:
            break
    return bars


def _merge_write(path: Path, rows: list[dict]) -> dict:
    import pandas as pd
    new = pd.DataFrame(rows)
    if new.empty and not path.is_file():
        return {"rows": 0}
    if path.is_file():
        old = pd.read_parquet(path)
        old["date"] = old["date"].astype(str)
        frame = pd.concat([old, new], ignore_index=True)
    else:
        frame = new
    frame = frame.drop_duplicates(["date", "time"], keep="last").sort_values(["date", "time"]).reset_index(drop=True)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    _atomic(path, buffer.getvalue())
    return {"rows": int(len(frame)), "first": str(frame["date"].iloc[0]), "last": str(frame["date"].iloc[-1]),
            "added": int(len(new))}


def _last_date(path: Path) -> str | None:
    if not path.is_file():
        return None
    import pyarrow.parquet as pq
    table = pq.read_table(path, columns=["date"])
    return str(max(table.column("date").to_pylist())) if table.num_rows else None


def apply(plan_path: Path, approve: str, *, max_seconds: float, API=None, now_fn=None, log=print) -> dict:
    data = plan_path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != approve:
        raise SystemExit(f"plan SHA mismatch: {sha}")
    body = json.loads(data)
    data_root = Path(body["data_root"])
    now = (now_fn or (lambda: datetime.now(TZ)))()
    if _in_session(now, data_root):
        raise SystemExit("交易时段（09:10–15:10）不运行：分页位置会随新K线移动")
    API = API or _load_pytdx()
    state_path = data_root / BASE / "_state" / f"tdx-minute-{sha[:12]}.json"
    state = json.loads(state_path.read_text()) if state_path.is_file() else {"plan_sha": sha, "done": {}}
    todo = [t for t in body["targets"] if f'{t["dir"]}/{t["symbol"]}' not in state["done"]]
    log(f"plan {sha[:12]} mode={body['mode']} targets={len(body['targets'])} remaining={len(todo)}")
    lock = threading.Lock()
    start = time.monotonic()
    fetch_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    failures = {"consecutive": 0, "halt": None}

    def work(index: int):
        worker = Worker(API, index)
        try:
            while True:
                with lock:
                    if not todo or failures["halt"] or time.monotonic() - start > max_seconds:
                        return
                    target = todo.pop(0)
                key = f'{target["dir"]}/{target["symbol"]}'
                path = file_for(data_root, target)
                existing = _last_date(path) if body["mode"] == "daily" else None
                try:
                    bars = fetch(worker, target, existing)
                    result = _merge_write(path, _to_rows(bars, target, fetch_ts))
                    result["status"] = "ok" if bars else "empty"
                    with lock:
                        failures["consecutive"] = 0
                except Exception as error:
                    result = {"status": "failed", "error": str(error)[:200]}
                    with lock:
                        failures["consecutive"] += 1
                        if failures["consecutive"] >= 30:
                            failures["halt"] = "连续 30 只失败，停止（可能被限制或断网）"
                with lock:
                    if result["status"] != "failed":
                        state["done"][key] = result
                    else:
                        failed = state.setdefault("failed", {})
                        result["retries"] = failed.get(key, {}).get("retries", 0) + 1
                        failed[key] = result
                        if result["retries"] <= 1:
                            todo.append(target)       # one more try at the end of the queue
                    finished = len(state["done"])
                    if finished % 50 == 0:
                        _atomic(state_path, json.dumps(state, ensure_ascii=False).encode())
                        log(f"{finished}/{len(body['targets'])} done, {time.monotonic() - start:.0f}s")
        finally:
            worker.close()

    threads = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(body["workers"])]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic(state_path, json.dumps(state, ensure_ascii=False).encode())
    summary = {"plan_sha": sha, "mode": body["mode"], "targets": len(body["targets"]), "done": len(state["done"]),
               "failed": sorted(k for k in state.get("failed", {}) if k not in state["done"]),
               "remaining": len(body["targets"]) - len(state["done"]), "halt": failures["halt"],
               "elapsed_s": round(time.monotonic() - start, 1)}
    receipt = data_root / BASE / "_receipts" / f"tdx-minute-{sha[:12]}-{datetime.now(TZ):%Y%m%dT%H%M%S}.json"
    _atomic(receipt, json.dumps(summary, ensure_ascii=False, indent=1).encode())
    log(json.dumps({**{k: v for k, v in summary.items() if k != "failed"}, "failed": len(summary["failed"])},
                   ensure_ascii=False))
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--mode", choices=("backfill", "daily"), required=True)
    a = sub.add_parser("apply")
    a.add_argument("--plan", required=True)
    a.add_argument("--approve", required=True)
    a.add_argument("--max-seconds", type=float, default=36 * 3600)
    args = parser.parse_args(argv)
    if args.command == "plan":
        path, sha = plan(paths.DATA_ROOT, args.mode)
        print(json.dumps({"plan": str(path), "sha256": sha}, ensure_ascii=False))
        return 0
    summary = apply(Path(args.plan), args.approve, max_seconds=args.max_seconds, log=lambda m: print(m, flush=True))
    return 0 if not summary["halt"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
