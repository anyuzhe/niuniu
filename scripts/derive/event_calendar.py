"""Calendar of market events from 2019, derived from exchange rules and the trading calendar.

    python scripts/derive/event_calendar.py

Writes <data-root>/lake/silver/event_calendar/event_calendar.parquet, one row per (date, event):
``date, event, detail, rule, source`` where ``source`` is ``rule`` (computed, not checked against an
announcement).  Events:

* ``index_futures_expiry``  CFFEX IF/IH/IC/IM: third Friday of the month, next trading day if closed
  (IM from 2022-07-22).
* ``etf_options_expiry``    SSE/SZSE ETF options: fourth Wednesday of the month, next trading day if
  closed (300ETF options from 2019-12-23; 500ETF / ChiNext ETF options from 2022-09-19).
* ``index_rebalance_effective``  CSI 300/500/1000, SSE 50, STAR 50, ChiNext index: semi-annual review
  effective the trading day after the second Friday of June and December.  Announcement dates are not
  included (they are published on the index providers' websites about two weeks earlier).
* ``pre_holiday`` / ``post_holiday``  last trading day before / first after a closure that removes at
  least one weekday.
* ``month_end`` / ``quarter_end``  last trading day of the month / quarter.
"""
from __future__ import annotations

import glob
import io
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import paths  # noqa: E402

START = date(2019, 1, 1)


def load_calendar(root: Path) -> list[date]:
    import pandas as pd
    snap = sorted(glob.glob(f"{root}/lake/bronze/provider=baostock/reference_snapshots/snapshot=*/trade_calendar.parquet"))[-1]
    cal = pd.read_parquet(snap)
    return sorted(date.fromisoformat(str(d)) for d, t in zip(cal["calendar_date"], cal["is_trading_day"]) if str(t) == "1")


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def build(days: list[date]) -> list[dict]:
    trading = set(days)
    last = days[-1]

    def on_or_after(d):
        while d not in trading and d <= last:
            d += timedelta(days=1)
        return d if d in trading else None

    rows = []
    for y in range(START.year, last.year + 1):
        for m in range(1, 13):
            fut = on_or_after(nth_weekday(y, m, 4, 3))
            if fut and fut >= START:
                rows.append({"date": fut, "event": "index_futures_expiry",
                             "detail": "IF/IH/IC" + ("/IM" if fut >= date(2022, 7, 22) else ""),
                             "rule": "第三个周五，遇休市顺延"})
            opt = on_or_after(nth_weekday(y, m, 2, 4))
            if opt and opt >= START:
                names = ["50ETF"] + (["300ETF"] if opt >= date(2019, 12, 23) else []) + \
                        (["500ETF", "创业板ETF"] if opt >= date(2022, 9, 19) else [])
                rows.append({"date": opt, "event": "etf_options_expiry", "detail": "/".join(names),
                             "rule": "第四个周三，遇休市顺延"})
            if m in (6, 12):
                eff = on_or_after(nth_weekday(y, m, 4, 2) + timedelta(days=1))
                if eff:
                    rows.append({"date": eff, "event": "index_rebalance_effective",
                                 "detail": "沪深300/中证500/中证1000/上证50/科创50/创业板指 定期调样",
                                 "rule": "6月、12月第二个周五的下一交易日"})
    for i, d in enumerate(days):
        if d < START:
            continue
        nxt = days[i + 1] if i + 1 < len(days) else None
        prv = days[i - 1] if i > 0 else None
        if nxt and any((d + timedelta(days=k)).weekday() < 5 for k in range(1, (nxt - d).days)):
            rows.append({"date": d, "event": "pre_holiday", "detail": f"下一交易日 {nxt}", "rule": "其后休市且少了至少一个工作日"})
        if prv and any((prv + timedelta(days=k)).weekday() < 5 for k in range(1, (d - prv).days)):
            rows.append({"date": d, "event": "post_holiday", "detail": f"上一交易日 {prv}", "rule": "此前休市且少了至少一个工作日"})
        if nxt is None or nxt.month != d.month:
            if nxt is not None or d.month != (d + timedelta(days=1)).month:
                rows.append({"date": d, "event": "month_end", "detail": None, "rule": "当月最后一个交易日"})
                if d.month in (3, 6, 9, 12):
                    rows.append({"date": d, "event": "quarter_end", "detail": None, "rule": "当季最后一个交易日"})
    for r in rows:
        r["source"] = "rule"
    return sorted(rows, key=lambda r: (r["date"], r["event"]))


def main() -> int:
    import pandas as pd
    root = paths.DATA_ROOT
    frame = pd.DataFrame(build(load_calendar(root)))
    out = root / "lake/silver/event_calendar/event_calendar.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_bytes(buf.getvalue())
    os.replace(tmp, out)
    print(frame.groupby("event").size().to_dict(), frame["date"].min(), frame["date"].max())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
