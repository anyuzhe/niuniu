"""Limit-board tape: level-1 books of the stocks near or at the daily limit, every 3 seconds.

Runs as a thread inside the intraday recorder (``scripts/collect/sector_intraday_recorder.py``).  The
list of stocks is dynamic and only grows during the day:

* seeded before the open from the previous session's daily bars: stocks that closed at the limit or
  up at least 70 % of their limit rate (7 % for 10 cm, 14 % for 20 cm, 21 % for 30 cm);
* every minute the recorder's whole-market pass (``LiveBreadth.record``) hands over its quotes and any
  stock up (or down) at least 70 % of its limit rate, or whose day high (low) touched the limit price,
  joins the list;
* a restart during the day rebuilds the list from the files already written.

Each sample asks TDX for the list only (80 codes per request), so a pass takes about 0.1-0.5 s.  Rows
are buffered and written once a minute:

    <data-root>/lake/bronze/provider=tdx/limit_board_tape/date=YYYY-MM-DD/HHMM.parquet
    <data-root>/lake/bronze/provider=tdx/limit_board_tape/_receipts/YYYY-MM-DD.json

One row per stock per sample.  Prices in yuan, volumes in shares (TDX quotes them in lots of 100;
multiplied here), amounts in yuan.  ``captured_at`` is the Beijing time the pass started (milliseconds);
``servertime`` is TDX's own stamp for that stock, kept as text.  09:15-09:30 is sampled every 5 s with
``phase = auction`` and only raw quote fields (what TDX returns there is decoded after looking at real
days); from 09:30 every 3 s with ``phase = continuous``.  A day without a file was not recorded and
cannot be filled in afterwards.  research_only (TDX, personal research).
"""
from __future__ import annotations

import glob
import io
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.data.market_breadth_live import BATCH, MARKET
from quantlab.trading.price_limit_regime import limit_prices

TZ = ZoneInfo("Asia/Shanghai")
OUT = "lake/bronze/provider=tdx/limit_board_tape"
DATASET_ID = "limit_board_tape"
VERSION = "limit-board-tape-v1"
ENTER_RATIO = 0.7          # share of the limit rate that puts a stock on the list
INTERVAL = 3.0             # seconds between samples from 09:30
AUCTION_INTERVAL = 5.0     # seconds between samples 09:15-09:30
MAX_WATCH = 1200           # a pass over more stocks than this would no longer fit in the interval
PREFIX = {0: "sz.", 1: "sh.", 2: "bj."}


def window(clock: str) -> str:
    """'HH:MM:SS' -> before | auction | continuous | lunch | after."""
    if clock < "09:15:00":
        return "before"
    if clock < "09:30:00":
        return "auction"
    if clock <= "11:30:30":
        return "continuous"
    if clock < "13:00:00":
        return "lunch"
    if clock <= "15:00:30":
        return "continuous"
    return "after"


def qualify(quote: dict, rate: float) -> list[tuple[str, str]]:
    """(side, reason) pairs for which this quote puts the stock on the list: touched the limit, or moved
    at least ENTER_RATIO of the limit rate."""
    price, pre = float(quote.get("price") or 0), float(quote.get("last_close") or 0)
    if price <= 0 or pre <= 0:
        return []
    try:
        up, down = limit_prices(pre, rate)
    except ValueError:
        return []
    high, low = float(quote.get("high") or 0), float(quote.get("low") or 0)
    move = price / pre - 1
    out = []
    if high >= up - 1e-6:
        out.append(("up", "触板"))
    elif move >= ENTER_RATIO * rate - 1e-9:
        out.append(("up", "涨幅"))
    if 0 < low <= down + 1e-6:
        out.append(("down", "触板"))
    elif move <= -ENTER_RATIO * rate + 1e-9:
        out.append(("down", "涨幅"))
    return out


class LimitBoardTape:
    def __init__(self, data_root: Path, breadth, *, interval: float = INTERVAL, now_fn=None, wait=None):
        """``breadth`` is the recorder's LiveBreadth: it supplies the TDX client class and hosts, the
        trading day, the limit rule per stock and the trading calendar.  The tape keeps its own TDX
        connection because pytdx clients are not thread-safe."""
        self.data_root = Path(data_root)
        self.breadth = breadth
        self.interval = interval
        self.today = breadth.today
        self.now_fn = now_fn or (lambda: datetime.now(TZ))
        self.wait = wait or (lambda stop, seconds: stop.wait(seconds))
        self.api = None
        self.host_index = 1                      # the breadth pass starts at host 0
        self.lock = threading.Lock()
        self.watch: dict[tuple[str, str], dict] = {}
        self.dropped: set[str] = set()
        self.buffer: list[dict] = []
        self._rates: dict[str, float | None] = {}
        self._limits: dict[str, tuple[float, float] | None] = {}
        self.dir = self.data_root / OUT / f"date={self.today.isoformat()}"
        self.receipt_path = self.data_root / OUT / "_receipts" / f"{self.today.isoformat()}.json"
        self.receipt = {"date": self.today.isoformat(), "version": VERSION, "interval_s": interval,
                        "auction_interval_s": AUCTION_INTERVAL, "ok": 0, "failed": 0, "overruns": 0,
                        "rows": 0, "list_max": 0, "list_now": 0, "dropped": 0, "max_pass_s": 0.0,
                        "first_captured_at": None, "last_captured_at": None, "last_error": None,
                        "entered": {}, "seed": None, "restarts": 0}
        if self.receipt_path.is_file():          # a restart during the day keeps the counts
            try:
                self.receipt.update(json.loads(self.receipt_path.read_text()))
                self.receipt["restarts"] = self.receipt.get("restarts", 0) + 1
            except ValueError:
                pass

    # ------------------------------------------------------------------ the list
    def rate(self, symbol: str):
        if symbol not in self._rates:
            try:
                self._rates[symbol] = self.breadth._rule(symbol)
            except Exception:
                self._rates[symbol] = None
        return self._rates[symbol]

    def _add(self, symbol: str, side: str, reason: str, at: datetime) -> bool:
        key = (symbol, side)
        if key in self.watch:
            return False
        if len(self.watch) >= MAX_WATCH:
            self.dropped.add(symbol)
            self.receipt["dropped"] = len(self.dropped)
            return False
        self.watch[key] = {"symbol": symbol, "side": side, "reason": reason,
                           "entered_at": at.isoformat(timespec="seconds")}
        counts = self.receipt["entered"]
        counts[reason] = counts.get(reason, 0) + 1
        self.receipt["list_now"] = len(self.watch)
        self.receipt["list_max"] = max(self.receipt["list_max"], len(self.watch))
        return True

    def update_from_quotes(self, captured_at: datetime, quotes: list[dict]) -> int:
        """Called with the whole-market quotes of each minute pass; returns how many stocks joined."""
        added = 0
        with self.lock:
            for q in quotes:
                symbol = PREFIX.get(q.get("market"), "?") + str(q.get("code"))
                rate = self.rate(symbol)
                if rate is None:
                    continue
                for side, reason in qualify(q, rate):
                    added += self._add(symbol, side, reason, captured_at)
        return added

    def seed(self) -> dict:
        """Stocks that closed the previous session at the limit or up at least ENTER_RATIO of the rate,
        from the daily bars (unadjusted closes: an ex-rights day only ever looks lower)."""
        import duckdb
        pattern = f"{self.data_root}/lake/bronze/provider=baostock/stock_kline_daily/*.parquet"
        today = self.today.isoformat()
        rows = duckdb.connect().execute(
            "SELECT code, date, close, rn FROM (SELECT code, date, close, "
            "row_number() OVER (PARTITION BY code ORDER BY date DESC) AS rn "
            f"FROM read_parquet('{pattern}') WHERE date < DATE '{today}') WHERE rn <= 2 ORDER BY code, rn").fetchall()
        previous = max((d for d in self.breadth.calendar if d < today), default=None)
        latest: dict[str, list] = {}
        for code, day, close, rn in rows:
            latest.setdefault(str(code), []).append((str(day), float(close)))
        newest = max((v[0][0] for v in latest.values()), default=None)
        info = {"bars_through": newest, "previous_session": previous, "limit_up": 0, "big_move": 0, "note": None}
        if newest is None or (previous and newest < previous):
            info["note"] = f"日K只到 {newest}，上一个交易日是 {previous}，种子名单可能不全"
        at = self.now_fn()
        with self.lock:
            for symbol, pair in latest.items():
                if len(pair) < 2 or pair[0][0] != newest or pair[1][1] <= 0:
                    continue
                rate = self.rate(symbol)
                if rate is None:
                    continue
                close, pre = pair[0][1], pair[1][1]
                try:
                    up, _ = limit_prices(pre, rate)
                except ValueError:
                    continue
                if close >= up - 1e-6:
                    info["limit_up"] += self._add(symbol, "up", "昨日涨停", at)
                elif close / pre - 1 >= ENTER_RATIO * rate - 1e-9:
                    info["big_move"] += self._add(symbol, "up", "昨日涨幅", at)
        self.receipt["seed"] = info
        return info

    def restore(self) -> int:
        """Rebuild the list from today's files after a restart; returns how many entries came back."""
        files = sorted(glob.glob(str(self.dir / "*.parquet")))
        if not files:
            return 0
        import pandas as pd
        frame = pd.concat([pd.read_parquet(f, columns=["symbol", "side", "enter_reason", "entered_at"])
                           for f in files], ignore_index=True).drop_duplicates(["symbol", "side"])
        with self.lock:
            for symbol, side, reason, entered in frame.itertuples(index=False):
                if (symbol, side) not in self.watch:
                    self.watch[(symbol, side)] = {"symbol": symbol, "side": side, "reason": reason,
                                                  "entered_at": entered}
            self.receipt["list_now"] = len(self.watch)
            self.receipt["list_max"] = max(self.receipt["list_max"], len(self.watch))
        return len(frame)

    # ------------------------------------------------------------------ sampling
    def _connect(self):
        host, port = self.breadth.hosts[self.host_index % len(self.breadth.hosts)]
        self.api = self.breadth.API(raise_exception=True)
        if not self.api.connect(host, port, time_out=5):
            raise ConnectionError(f"connect {host}:{port} failed")

    def _fetch(self, symbols: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(symbols), BATCH):
            chunk = [(MARKET[s[:2]], s[3:]) for s in symbols[i:i + BATCH]]
            for attempt in range(3):
                try:
                    if self.api is None:
                        self._connect()
                    out += self.api.get_security_quotes(chunk) or []
                    break
                except Exception:
                    self.close()
                    self.host_index += 1
                    if attempt == 2:
                        raise
        return out

    def _limit_prices(self, symbol: str, pre: float):
        if symbol not in self._limits:
            rate = self.rate(symbol)
            try:
                self._limits[symbol] = limit_prices(pre, rate) if rate and pre > 0 else None
            except ValueError:
                self._limits[symbol] = None
        return self._limits[symbol]

    def sample(self, captured_at: datetime, phase: str) -> int:
        """One pass over the list; the rows go to the buffer.  Returns the number of rows."""
        with self.lock:
            entries = list(self.watch.values())
        if not entries:
            return 0
        started = time.monotonic()
        quotes = self._fetch(sorted({e["symbol"] for e in entries}))
        capture_s = round(time.monotonic() - started, 2)
        by_code = {(q.get("market"), str(q.get("code"))): q for q in quotes}
        stamp = captured_at.isoformat(timespec="milliseconds")
        rows = []
        for e in entries:
            symbol = e["symbol"]
            q = by_code.get((MARKET[symbol[:2]], symbol[3:]))
            if not q:
                continue
            pre = float(q.get("last_close") or 0)
            limits = self._limit_prices(symbol, pre)
            row = {"captured_at": stamp, "servertime": str(q.get("servertime")), "symbol": symbol,
                   "side": e["side"], "phase": phase, "price": q.get("price"), "last_close": q.get("last_close"),
                   "open": q.get("open"), "high": q.get("high"), "low": q.get("low"),
                   "volume": float(q.get("vol") or 0) * 100, "amount": q.get("amount"),
                   "cur_volume": float(q.get("cur_vol") or 0) * 100,
                   "outer_volume": float(q.get("b_vol") or 0) * 100,     # 外盘: traded at the ask (active buying)
                   "inner_volume": float(q.get("s_vol") or 0) * 100}     # 内盘: traded at the bid (active selling)
            for side in ("bid", "ask"):
                for level in range(1, 6):
                    row[f"{side}{level}"] = q.get(f"{side}{level}")
            for side in ("bid", "ask"):
                for level in range(1, 6):
                    row[f"{side}_vol{level}"] = float(q.get(f"{side}_vol{level}") or 0) * 100
            # What TDX puts in the unnamed fields during the auction is decoded after looking at real days,
            # so those rows keep them as they came.
            extra = ({k: v for k, v in q.items() if k.startswith(("reversed_bytes", "active"))}
                     if phase == "auction" else None)
            row.update(limit_up_price=limits[0] if limits else None, limit_down_price=limits[1] if limits else None,
                       enter_reason=e["reason"], entered_at=e["entered_at"], capture_s=capture_s,
                       raw_extra=json.dumps(extra, default=str) if extra else "",
                       provider="tdx", _minute=captured_at.strftime("%H%M"))
            rows.append(row)
        with self.lock:
            self.buffer += rows
        receipt = self.receipt
        receipt["first_captured_at"] = receipt["first_captured_at"] or stamp
        receipt["last_captured_at"] = stamp
        receipt["max_pass_s"] = max(receipt["max_pass_s"], capture_s)
        return len(rows)

    # ------------------------------------------------------------------ files
    def flush(self, before: str | None = None) -> int:
        """Write buffered rows to ``date=D/HHMM.parquet``; with ``before`` ('HHMM') only earlier minutes."""
        import pandas as pd
        with self.lock:
            take = [r for r in self.buffer if before is None or r["_minute"] < before]
            self.buffer = [r for r in self.buffer if not (before is None or r["_minute"] < before)]
        written = 0
        by_minute: dict[str, list[dict]] = {}
        for r in take:
            by_minute.setdefault(r["_minute"], []).append(r)
        for minute, rows in sorted(by_minute.items()):
            path = self.dir / f"{minute}.parquet"
            try:
                frame = pd.DataFrame([{k: v for k, v in r.items() if k != "_minute"} for r in rows])
                if path.is_file():               # a restart inside the same minute
                    old = pd.read_parquet(path)
                    frame = pd.concat([old, frame], ignore_index=True).drop_duplicates(["captured_at", "symbol", "side"])
                path.parent.mkdir(parents=True, exist_ok=True)
                buf = io.BytesIO()
                frame.to_parquet(buf, index=False)
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_bytes(buf.getvalue())
                os.replace(tmp, path)
                written += len(rows)
            except Exception as error:           # keep the rows for the next flush
                with self.lock:
                    self.buffer += rows
                self.receipt["last_error"] = f"写文件失败 {type(error).__name__}: {error}"[:300]
        self.receipt["rows"] += written
        if take:
            self.save_receipt()
        return written

    def save_receipt(self) -> None:
        try:
            self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.receipt_path.with_name(self.receipt_path.name + ".tmp")
            tmp.write_text(json.dumps(self.receipt, ensure_ascii=False, indent=1) + "\n")
            os.replace(tmp, self.receipt_path)
        except OSError as error:                 # the next flush tries again; the tape keeps running
            self.receipt["last_error"] = f"写回执失败 {type(error).__name__}: {error}"[:300]

    def close(self) -> None:
        if self.api is not None:
            try:
                self.api.disconnect()
            except Exception:
                pass
            self.api = None

    # ------------------------------------------------------------------ loop
    def run(self, stop: threading.Event) -> None:
        from quantlab.data.day_seals import is_sealed
        if is_sealed(self.data_root, DATASET_ID, self.today.isoformat()):
            return
        try:
            self.restore()
        except Exception as error:
            self.receipt["last_error"] = f"恢复名单失败 {type(error).__name__}: {error}"[:300]
        try:
            self.seed()
        except Exception as error:
            self.receipt["seed"] = {"error": f"{type(error).__name__}: {error}"[:300]}
        self.save_receipt()
        try:
            while not stop.is_set():
                now = self.now_fn()
                phase = window(now.strftime("%H:%M:%S"))
                if phase == "after":
                    break
                if phase in ("before", "lunch"):
                    self.flush()
                    self.wait(stop, 5.0)
                    continue
                started = time.monotonic()
                try:
                    self.sample(now, phase)
                    self.receipt["ok"] += 1
                except Exception as error:
                    self.receipt["failed"] += 1
                    self.receipt["last_error"] = f"{type(error).__name__}: {error}"[:300]
                self.flush(before=now.strftime("%H%M"))
                interval = AUCTION_INTERVAL if phase == "auction" else self.interval
                spent = time.monotonic() - started
                if spent > interval:
                    self.receipt["overruns"] += 1
                self.wait(stop, max(0.2, interval - spent))
        finally:
            self.flush()
            self.save_receipt()
            self.close()


__all__ = ["LimitBoardTape", "qualify", "window", "OUT", "DATASET_ID"]
