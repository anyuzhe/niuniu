"""Live whole-market breadth, one row per minute, from TDX level-1 quotes.

Called by the intraday recorder once a minute during the session.  One pass quotes every
A share (TDX batch of 80 codes, ~70 requests, ~3-5 s) and writes the same fields as
``market_intraday_breadth`` plus ``as_of`` (latest quote server time), ``captured_at``,
``latency_s`` and ``n_requested``/``n_quoted``:

    <data-root>/lake/silver/market_intraday_breadth/freq=live/date=YYYY-MM-DD.parquet

The previous close is the exchange's own (``last_close`` in the quote, already adjusted
for ex-rights), so no factor is needed.  Stocks with zero volume today (suspended or not
yet traded) are left out, as in the history.  ``time`` is the minute the pass started,
'HH:MM' (09:25 = after the opening auction).  research_only (TDX, personal research).
"""
from __future__ import annotations

import glob
import io
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.trading.price_limit_regime import limit_prices

TZ = ZoneInfo("Asia/Shanghai")
BATCH = 80
MARKET = {"sz": 0, "sh": 1, "bj": 2}
OUT = "lake/silver/market_intraday_breadth/freq=live"


def limit_pct(symbol: str, day: date, is_st: bool) -> float:
    board = symbol[3:6]
    if symbol.startswith("bj."):
        return 0.30
    if board in ("688", "689"):
        return 0.20
    if board in ("300", "301") and day >= date(2020, 8, 24):
        return 0.20
    if is_st and day < date(2026, 7, 6):
        return 0.05
    return 0.10


def free_days(symbol: str, day: date) -> int:
    board = symbol[3:6]
    if symbol.startswith("bj."):
        return 1
    if board in ("688", "689"):
        return 5
    if board in ("300", "301"):
        return 5 if day >= date(2020, 8, 24) else 1
    return 5 if day >= date(2023, 4, 10) else 1


def round_price(value: float) -> float:
    import math
    return math.floor(value * 100 + 0.5 + 1e-6) / 100


class LiveBreadth:
    def __init__(self, data_root: Path, *, API=None, hosts=None, sleep=time.sleep, today: date | None = None):
        import pandas as pd
        self.data_root = Path(data_root)
        self.sleep = sleep
        self.today = today or datetime.now(TZ).date()
        if API is None:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
            from collect.tdx_minute import HOSTS, _load_pytdx
            API = _load_pytdx()
            hosts = hosts or HOSTS
            from pytdx.parser.get_security_quotes import GetSecurityQuotesCmd
            original = GetSecurityQuotesCmd._format_time
            if not getattr(original, "_niuniu_safe", False):
                def safe(self, stamp, _orig=original):   # pytdx fails on the off-hours zero timestamp
                    return _orig(self, stamp) if len(str(stamp)) >= 6 else str(stamp)
                safe._niuniu_safe = True
                GetSecurityQuotesCmd._format_time = safe
        self.API, self.hosts = API, list(hosts or [])
        self.host_index = 0
        self.api = None
        from quantlab.data.stock_intraday import universe
        self.symbols = universe(self.data_root)
        # ST flags, IPO dates and trading calendar from the latest reference data
        st_glob = f"{self.data_root}/lake/bronze/provider=baostock/daily_status_v2/*.parquet"
        self.st: set[str] = set()
        try:
            import duckdb
            rows = duckdb.connect().execute(
                f"SELECT code FROM (SELECT code, arg_max(isST, date) AS st FROM read_parquet('{st_glob}') GROUP BY 1) "
                "WHERE st = '1'").fetchall()
            self.st = {r[0] for r in rows}
        except Exception:
            pass
        snaps = sorted(glob.glob(f"{self.data_root}/lake/bronze/provider=baostock/reference_snapshots/snapshot=*/"))
        self.ipo, self.calendar = {}, []
        if snaps:
            basic = pd.read_parquet(Path(snaps[-1]) / "stock_basic.parquet", columns=["code", "ipoDate"])
            self.ipo = {str(c).lower(): str(d) for c, d in zip(basic["code"], basic["ipoDate"]) if str(d) not in ("", "nan")}
            cal = pd.read_parquet(Path(snaps[-1]) / "trade_calendar.parquet")
            self.calendar = sorted(str(d) for d, t in zip(cal["calendar_date"], cal["is_trading_day"]) if str(t) == "1")

    def _rule(self, symbol: str):
        """Limit rate from ``price_limit_regime`` (shared with the rest of niuniu); None = no/unknown limit."""
        from quantlab.trading.price_limit_regime import NORMAL, limit_rule
        ipo = self.ipo.get(symbol)
        since = None
        if ipo:
            today = self.today.isoformat()
            since = sum(1 for d in self.calendar if ipo <= d <= today) or None
        try:
            result = limit_rule(symbol, self.today, is_st=symbol in self.st,
                                listing_date=date.fromisoformat(ipo) if ipo else None, sessions_since_listing=since)
        except ValueError:
            return None
        return result["rate"] if result.get("status") == NORMAL else None

    def _no_limit(self, symbol: str) -> bool:
        ipo = self.ipo.get(symbol)
        if not ipo or ipo < (self.today - timedelta(days=20)).isoformat():
            return False
        today = self.today.isoformat()
        n = sum(1 for d in self.calendar if ipo <= d <= today) or 1
        return n <= free_days(symbol, self.today)

    def _connect(self):
        host, port = self.hosts[self.host_index % len(self.hosts)]
        self.api = self.API(raise_exception=True)
        if not self.api.connect(host, port, time_out=5):
            raise ConnectionError(f"connect {host}:{port} failed")

    def quotes(self) -> list[dict]:
        out = []
        for i in range(0, len(self.symbols), BATCH):
            chunk = [(MARKET[s[:2]], s[3:]) for s in self.symbols[i:i + BATCH]]
            for attempt in range(3):
                try:
                    if self.api is None:
                        self._connect()
                    out += self.api.get_security_quotes(chunk) or []
                    break
                except Exception:
                    try:
                        self.api.disconnect()
                    except Exception:
                        pass
                    self.api, self.host_index = None, self.host_index + 1
                    if attempt == 2:
                        raise
            self.sleep(0.05)
        return out

    def compute(self, quotes: list[dict], captured_at: datetime) -> dict:
        prefix = {0: "sz.", 1: "sh.", 2: "bj."}
        rets, rets_open, n = [], [], 0
        up = down = flat = lu = ld = tlu = tld = no_lim = 0
        stamps = []
        for q in quotes:
            symbol = prefix.get(q.get("market"), "?") + str(q.get("code"))
            price, pre, opn = float(q.get("price") or 0), float(q.get("last_close") or 0), float(q.get("open") or 0)
            if price <= 0 or pre <= 0 or not q.get("vol"):
                continue
            n += 1
            stamps.append(str(q.get("servertime") or ""))
            rets.append(price / pre - 1)
            if opn > 0:
                rets_open.append(price / opn - 1)
            up += price > pre + 1e-9
            down += price < pre - 1e-9
            flat += abs(price - pre) <= 1e-9
            rule = self._rule(symbol)
            if rule is None:
                no_lim += 1
                continue
            hi, lo = limit_prices(pre, rule)
            lu += price >= hi - 1e-6
            ld += price <= lo + 1e-6
            tlu += float(q.get("high") or 0) >= hi - 1e-6
            tld += 0 < float(q.get("low") or 0) <= lo + 1e-6
        import statistics
        as_of = max(stamps) if stamps else None
        latency = None
        if as_of and len(as_of) >= 8:
            h, m, s = as_of[:8].split(":")
            server = captured_at.replace(hour=int(h), minute=int(m), second=int(float(s)), microsecond=0)
            latency = round((captured_at - server).total_seconds(), 1)
        return {"date": self.today, "time": captured_at.strftime("%H:%M"), "n_stocks": n,
                "ew_ret_prev_close": sum(rets) / n if n else None,
                "ew_ret_open": sum(rets_open) / len(rets_open) if rets_open else None,
                "median_ret_prev_close": statistics.median(rets) if rets else None,
                "up_count": int(up), "down_count": int(down), "flat_count": int(flat),
                "limit_up_count": int(lu), "limit_down_count": int(ld),
                "touched_limit_up_count": int(tlu), "touched_limit_down_count": int(tld), "n_no_limit": no_lim,
                "n_requested": len(self.symbols), "n_quoted": len(quotes), "as_of": as_of,
                "captured_at": captured_at.isoformat(timespec="seconds"), "latency_s": latency,
                "source": "tdx_quotes", "version": "market-breadth-live-v1"}

    def record(self) -> dict:
        import pandas as pd
        started = datetime.now(TZ)
        row = self.compute(self.quotes(), started)
        row["capture_s"] = round((datetime.now(TZ) - started).total_seconds(), 1)
        path = self.data_root / OUT / f"date={self.today.isoformat()}.parquet"
        frame = pd.DataFrame([row])
        if path.is_file():
            old = pd.read_parquet(path)
            frame = pd.concat([old[old["time"] != row["time"]], frame], ignore_index=True).sort_values("time")
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        frame.to_parquet(buf, index=False)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(buf.getvalue())
        os.replace(tmp, path)
        return row

    def close(self):
        if self.api is not None:
            try:
                self.api.disconnect()
            except Exception:
                pass
            self.api = None


__all__ = ["LiveBreadth", "limit_pct", "free_days"]
