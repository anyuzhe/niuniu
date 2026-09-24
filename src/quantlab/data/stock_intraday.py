"""Whole-market A-share snapshot at fixed intraday times (Fuyao, sample cross-checked).

Used by the intraday recorder at 09:25, 10:00, 11:30, 14:00, 14:57 and 15:00
Beijing time.  One call quotes every listed A share (Baostock reference list plus
the BSE stocks found in the latest board-constituents snapshot) through Fuyao in
batches of 300, then cross-checks a fixed-size random sample against Tencent's
batch quote.  Fields follow ``realtime_quote``; prices in yuan, volume in shares,
amount in yuan.
"""
from __future__ import annotations

import random
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.data.research_provider import DataProviderError
from quantlab.data.sector_intraday import niuniu_symbol

TZ = ZoneInfo("Asia/Shanghai")
SNAPSHOT_TIMES = ("09:25", "10:00", "11:30", "14:00", "14:57", "15:00")
BATCH = 300
SAMPLE = 200


def universe(data_root: Path) -> list[str]:
    import pandas as pd
    symbols: set[str] = set()
    base = data_root / "lake/bronze/provider=baostock/reference_snapshots"
    snaps = sorted(p for p in base.glob("snapshot=*") if (p / "stock_basic.parquet").is_file())
    if snaps:
        basic = pd.read_parquet(snaps[-1] / "stock_basic.parquet", columns=["code", "type", "status"])
        mask = (basic["type"].astype(str) == "1") & (basic["status"].astype(str) == "1")
        symbols |= {str(c).lower() for c in basic.loc[mask, "code"]}
    cons = sorted((data_root / "lake/bronze/provider=fuyao/sector_board_constituents").glob("date=*.parquet"))
    if cons:
        extra = pd.read_parquet(cons[-1], columns=["symbol"])["symbol"]
        symbols |= {s for s in extra if str(s).startswith("bj.")}
    if len(symbols) < 4000:
        raise DataProviderError("stock_intraday_snapshot", f"证券清单只有 {len(symbols)} 只，参考快照可能缺失")
    return sorted(symbols)


def _thscode(symbol: str) -> str:
    exchange, code = symbol.split(".")
    return code + "." + exchange.upper()


def capture(client, symbols: list[str], *, public_loader=None, sleep=time.sleep, rng=None) -> tuple[list[dict], dict]:
    rows, stamps, errors = [], [], 0
    for index in range(0, len(symbols), BATCH):
        chunk = [_thscode(s) for s in symbols[index:index + BATCH]]
        call = None
        for attempt in range(2):
            try:
                call = client.call("a-share", "get_a_share_prices_snapshot", {"thscodes": ",".join(chunk)})
                break
            except Exception:
                errors += 1
                if attempt == 0:
                    sleep(1.0)
        if call is None:
            raise DataProviderError("stock_intraday_snapshot", f"扶摇第 {index // BATCH + 1} 批请求失败两次")
        try:
            stamp = datetime.fromtimestamp(int(call.get("response_timestamp")) / 1000, TZ).isoformat()
        except (TypeError, ValueError):
            stamp = None
        stamps.append(stamp)
        for item in (call.get("data") or {}).get("item", []):
            symbol = niuniu_symbol(item.get("thscode"))
            if not symbol:
                continue
            last = item.get("last_price")
            volume = item.get("volume")
            rows.append({"symbol": symbol, "last": last, "change": item.get("price_change"),
                         "change_pct": item.get("price_change_ratio_pct"), "previous_close": item.get("prev_price"),
                         "open": item.get("open_price"), "high": item.get("high_price"), "low": item.get("low_price"),
                         "volume": volume, "amount": item.get("turnover"), "as_of": stamp,
                         "status": "no_trade_today" if not last or not volume else "trading"})
        sleep(0.3)
    meta = {"requested": len(symbols), "returned": len(rows), "fuyao_retries": errors,
            "as_of_min": min(s for s in stamps if s) if any(stamps) else None,
            "as_of_max": max(s for s in stamps if s) if any(stamps) else None}
    if public_loader is not None:
        rng = rng or random.Random(0)
        trading = [r for r in rows if r["status"] == "trading"]
        sample = rng.sample(trading, min(SAMPLE, len(trading)))
        try:
            quotes = public_loader([r["symbol"] for r in sample])
            checked = [r for r in sample if r["symbol"] in quotes]
            agree = [r for r in checked
                     if abs(float(quotes[r["symbol"]].get("last") or 0) - float(r["last"])) <= max(0.011, abs(float(r["last"])) * 0.0002)]
            meta["cross_check"] = {"source": "tencent", "sampled": len(sample), "checked": len(checked),
                                   "agree": len(agree),
                                   "disagree": [r["symbol"] for r in checked if r not in agree][:50]}
        except Exception as error:
            meta["cross_check"] = {"source": "tencent", "error": f"{type(error).__name__}: {error}"[:200]}
    return rows, meta


__all__ = ["SNAPSHOT_TIMES", "capture", "universe"]
