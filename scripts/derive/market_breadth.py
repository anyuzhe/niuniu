"""Whole-market intraday breadth series (equal-weight return, advancers/decliners, limit counts).

    python scripts/derive/market_breadth.py build --source tdx_min1 [--from 2026-05-20] [--to 2026-09-24]

Source ``tdx_min1``: <data-root>/lake/bronze/provider=tdx/kline_min1 (A shares incl. BSE).
Output: <data-root>/lake/silver/market_intraday_breadth/freq=1m/year=YYYY/month=MM.parquet,
one row per (date, time); ``time`` is the bar END in 'HH:MM' ('09:31' includes the
opening call auction; no rows for the lunch break; '15:00' includes the closing auction).

Per stock and minute: ``price`` = that bar's close.  Previous close = the stock's last
close on its previous trading day, converted to today's price basis with the published
qfq factors (``qfq_published_f24``: prev_close_raw * factor_prev / factor_today); when a
factor is missing (BSE, or days after the qfq build) the raw close is used and counted in
``n_prev_close_raw``.  A stock enters a date's rows only if it trades that day (TDX has no
bars for suspended days) and has a previous close; stocks in their first 5 trading days
(no price limit) are counted in returns/up/down but never in limit counts.

Limit price: round_half_up(prev_close_adj * (1 ± pct), 2); pct = 30% BSE, 20% ChiNext
(300/301) and STAR (688/689), 5% main-board ST (Baostock ``isST``) before 2026-07-06
(SSE/SZSE raised main-board risk-warning stocks to 10% from 2026-07-06), else 10%.  A stock is
at limit-up when price >= limit_up, limit-down when price <= limit_down; ``touched_*``
uses the running intraday high/low up to that minute.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import paths  # noqa: E402

VERSION = "market-breadth-v2"
OUT = "lake/silver/market_intraday_breadth"


def _sql_inputs(con, root: Path, start: str, end: str) -> None:
    t = f"{root}/lake/bronze/provider=tdx/kline_min1/*.parquet"
    snap = sorted(glob.glob(f"{root}/lake/bronze/provider=baostock/reference_snapshots/snapshot=*/stock_basic.parquet"))[-1]
    # a view, not a table: each month's query reads only that month's rows (memory stays bounded)
    con.execute(f"""CREATE OR REPLACE VIEW bars AS
        SELECT code, date, substr(time, 9, 2) || ':' || substr(time, 11, 2) AS hhmm, time,
               open, high, low, close, amount
        FROM read_parquet('{t}') WHERE volume > 0 OR amount > 0""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE days AS
        SELECT code, date, arg_min(open, time) AS day_open, arg_max(close, time) AS day_close, sum(amount) AS day_amount
        FROM bars WHERE date BETWEEN DATE '{start}' - INTERVAL 20 DAY AND DATE '{end}' GROUP BY 1, 2""")
    # previous-day close: TDX days plus Baostock daily (covers the day before the TDX window)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE closes AS
        SELECT code, date, day_close AS close, day_amount AS amount FROM days
        UNION ALL
        SELECT b.code, b.date, b.close, b.amount
        FROM read_parquet('{root}/lake/bronze/provider=baostock/stock_kline_daily/*.parquet') b
        WHERE b.volume > 0 AND b.date >= DATE '{start}' - INTERVAL 20 DAY AND b.date <= DATE '{end}'
          AND NOT EXISTS (SELECT 1 FROM days d WHERE d.code = b.code AND d.date = b.date)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE prev AS
        SELECT code, date, lag(close) OVER w AS prev_close_raw, lag(date) OVER w AS prev_date,
               lag(amount) OVER w AS prev_amount, row_number() OVER w AS nth_trading_day
        FROM closes WINDOW w AS (PARTITION BY code ORDER BY date)""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE factors AS
        SELECT code, date, factor FROM read_parquet('{root}/lake/silver/qfq_kline_daily_v2/*.parquet')
        WHERE date >= DATE '{start}' - INTERVAL 20 DAY""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE st AS
        SELECT code, CAST(date AS DATE) AS date, isST = '1' AS is_st
        FROM read_parquet('{root}/lake/bronze/provider=baostock/daily_status_v2/*.parquet')
        WHERE CAST(date AS DATE) >= DATE '{start}' - INTERVAL 20 DAY""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ipo AS
        SELECT lower(code) AS code, CAST(NULLIF(ipoDate, '') AS DATE) AS ipo_date FROM read_parquet('{snap}')""")
    con.execute("""CREATE OR REPLACE TEMP TABLE cal AS
        SELECT date, row_number() OVER (ORDER BY date) AS idx FROM (SELECT DISTINCT date FROM closes)""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE stock_day AS
        SELECT d.code, d.date, d.day_open, p.prev_amount,
               CASE WHEN fp.factor IS NOT NULL AND ft.factor IS NOT NULL
                    THEN p.prev_close_raw * fp.factor / ft.factor ELSE p.prev_close_raw END AS prev_close,
               (fp.factor IS NULL OR ft.factor IS NULL) AS prev_raw,
               CASE WHEN d.code LIKE 'bj.%' THEN 0.30
                    WHEN substr(d.code, 4, 3) IN ('300', '301', '688', '689') THEN 0.20
                    WHEN coalesce(s.is_st, false) AND d.date < DATE '2026-07-06' THEN 0.05 ELSE 0.10 END AS pct,
               (i.ipo_date >= (SELECT min(date) FROM cal) AND c.idx - (SELECT min(idx) FROM cal WHERE cal.date >= i.ipo_date) < 5) AS no_limit
        FROM days d
        JOIN prev p USING (code, date)
        LEFT JOIN factors fp ON fp.code = d.code AND fp.date = p.prev_date
        LEFT JOIN factors ft ON ft.code = d.code AND ft.date = d.date
        LEFT JOIN st s ON s.code = d.code AND s.date = d.date
        LEFT JOIN ipo i ON i.code = d.code
        JOIN cal c ON c.date = d.date
        WHERE p.prev_close_raw > 0 AND d.date BETWEEN DATE '{start}' AND DATE '{end}'""")
    con.execute("""CREATE OR REPLACE TEMP TABLE stock_day2 AS
        SELECT *, floor(prev_close * (1 + pct) * 100 + 0.5 + 1e-6) / 100 AS limit_up,
                  floor(prev_close * (1 - pct) * 100 + 0.5 + 1e-6) / 100 AS limit_down FROM stock_day""")


BREADTH_SQL = """
WITH x AS (
  SELECT b.date, b.hhmm, b.code, b.close AS price, s.prev_close, s.day_open, s.prev_amount, s.prev_raw, s.no_limit,
         s.limit_up, s.limit_down,
         max(b.high) OVER w AS run_high, min(b.low) OVER w AS run_low
  FROM bars b JOIN stock_day2 s USING (code, date)
  WHERE b.date BETWEEN DATE '{start}' AND DATE '{end}'
  WINDOW w AS (PARTITION BY b.code, b.date ORDER BY b.time ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))
SELECT date, hhmm AS time,
       count(*) AS n_stocks,
       avg(price / prev_close - 1) AS ew_ret_prev_close,
       avg(price / day_open - 1) AS ew_ret_open,
       sum((price / prev_close - 1) * prev_amount) / nullif(sum(prev_amount) FILTER (WHERE prev_amount > 0), 0) AS amt_w_ret_prev_close,
       median(price / prev_close - 1) AS median_ret_prev_close,
       count(*) FILTER (WHERE price > prev_close + 1e-9) AS up_count,
       count(*) FILTER (WHERE price < prev_close - 1e-9) AS down_count,
       count(*) FILTER (WHERE abs(price - prev_close) <= 1e-9) AS flat_count,
       count(*) FILTER (WHERE NOT no_limit AND price >= limit_up - 1e-6) AS limit_up_count,
       count(*) FILTER (WHERE NOT no_limit AND price <= limit_down + 1e-6) AS limit_down_count,
       count(*) FILTER (WHERE NOT no_limit AND run_high >= limit_up - 1e-6) AS touched_limit_up_count,
       count(*) FILTER (WHERE NOT no_limit AND run_low <= limit_down + 1e-6) AS touched_limit_down_count,
       count(*) FILTER (WHERE no_limit) AS n_no_limit,
       count(*) FILTER (WHERE prev_raw) AS n_prev_close_raw
FROM x GROUP BY 1, 2 ORDER BY 1, 2"""


def build(root: Path, source: str, start: str, end: str, log=print) -> dict:
    import duckdb
    if source != "tdx_min1":
        raise SystemExit("only --source tdx_min1 is implemented")
    t0 = time.monotonic()
    con = duckdb.connect()
    con.execute(f"SET threads = {int(os.environ.get('BREADTH_THREADS', '4'))}")
    con.execute(f"SET memory_limit = '{os.environ.get('BREADTH_MEMORY', '4GB')}'")
    con.execute(f"SET temp_directory = '{root / OUT / '_tmp'}'")
    con.execute("SET preserve_insertion_order = false")
    _sql_inputs(con, root, start, end)
    log(f"inputs ready {time.monotonic() - t0:.0f}s")
    # TDX keeps a rolling window per security; only publish days where (almost) every
    # trading stock has bars, otherwise early days would be computed from a subset.
    con.execute(f"""CREATE OR REPLACE TEMP TABLE coverage AS
        WITH ref AS (SELECT date, count(*) AS n_ref FROM read_parquet('{root}/lake/bronze/provider=baostock/stock_kline_daily/*.parquet')
                     WHERE volume > 0 AND date BETWEEN DATE '{start}' AND DATE '{end}' GROUP BY 1),
             got AS (SELECT date, count(*) FILTER (WHERE code NOT LIKE 'bj.%') AS n_got FROM days GROUP BY 1)
        SELECT date, n_ref, n_got FROM ref JOIN got USING (date)""")
    full = con.execute("SELECT min(date) FROM coverage WHERE n_got >= n_ref").fetchone()[0]
    if full is None:
        raise SystemExit("no day with full coverage")
    if str(full) > start:
        log(f"first fully covered day {full}; earlier days skipped")
        start = str(full)
    months = [r[0] for r in con.execute(
        f"SELECT DISTINCT strftime(date, '%Y-%m') FROM days WHERE date BETWEEN DATE '{start}' AND DATE '{end}' ORDER BY 1").fetchall()]
    out_base = root / OUT / "freq=1m"
    written = []
    for ym in months:
        y, m = ym.split("-")
        first, last = con.execute(
            f"SELECT min(date), max(date) FROM days WHERE strftime(date, '%Y-%m') = '{ym}' "
            f"AND date BETWEEN DATE '{start}' AND DATE '{end}'").fetchone()
        target = out_base / f"year={y}" / f"month={m}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        con.execute(f"""COPY (SELECT *, '{source}' AS source, '{VERSION}' AS version
                        FROM ({BREADTH_SQL.format(start=first, end=last)})) TO '{tmp}' (FORMAT parquet)""")
        os.replace(tmp, target)
        rows = con.execute(f"SELECT count(*), count(DISTINCT date) FROM '{target}'").fetchone()
        written.append({"file": str(target.relative_to(root)), "rows": rows[0], "days": rows[1]})
        log(f"{ym}: {rows[0]} rows, {rows[1]} days, {time.monotonic() - t0:.0f}s")
    receipt = {"version": VERSION, "source": source, "from": start, "to": end, "built_at": datetime.now(timezone.utc).isoformat(),
               "files": written, "elapsed_s": round(time.monotonic() - t0, 1)}
    path = out_base / "_receipts" / f"build-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=1))
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source", default="tdx_min1")
    b.add_argument("--from", dest="start", default="2019-01-01")
    b.add_argument("--to", dest="end", default="2099-12-31")
    args = parser.parse_args(argv)
    receipt = build(paths.DATA_ROOT, args.source, args.start, args.end, log=lambda m: print(m, flush=True))
    print(json.dumps({k: v for k, v in receipt.items() if k != "files"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
