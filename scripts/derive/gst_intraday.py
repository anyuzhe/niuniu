"""Convert the gst MySQL export (16 stocks) into intraday backtest data.

Source (read-only): ``<data-root>/staging/gst_export_20260925/`` --
``stock_contracts.csv`` (per stock-day JSON of ~3 s trade aggregates, 2019-05..2024-10)
and ``stock_pans.csv`` (per stock-day JSON of ~3 s level-1 five-level quote snapshots,
2019-05..2020-06).  Output under ``<data-root>/lake/silver/gst_intraday/``:

    ticks/part-NNNNN.parquet    every trade row, with ``flag`` (NULL = clean)
    quotes/part-NNNNN.parquet   every quote snapshot, with ``flag``
    _state/<table>.json         byte offset + part counter (resumable)
    gst_intraday.duckdb         tables + clean views + 1-minute bars + day quality

    python scripts/derive/gst_intraday.py convert --table ticks  --max-seconds 150
    python scripts/derive/gst_intraday.py convert --table quotes --max-seconds 150
    python scripts/derive/gst_intraday.py build
"""
from __future__ import annotations

import argparse
import csv
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

csv.field_size_limit(10 ** 9)
SOURCE = "staging/gst_export_20260925"
OUT = "lake/silver/gst_intraday"
FILES = {"ticks": "stock_contracts.csv", "quotes": "stock_pans.csv"}
SIDES = {"买盘": "B", "卖盘": "S", "中性盘": "N"}
ROWS_PER_PART = 1_500_000
QUOTE_ROWS_PER_PART = 400_000


def symbol(code: str) -> str:
    code = str(code).strip()
    return ("sh." if code.startswith(("6", "9")) else "bj." if code.startswith(("4", "8", "920")) else "sz.") + code


def unescape(value: str):
    if value == "\\N":
        return None
    return value[1:] if value.startswith("\\\\") else value


def fnum(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def in_session(t: str) -> bool:
    return "09:15:00" <= t <= "15:01:00"


def records(path: Path, offset: int):
    """Yield (row, next_offset) from ``offset``; quote parity finds record ends."""
    with path.open("rb") as handle:
        handle.seek(offset)
        if offset == 0:
            handle.readline()
        buf, quotes = [], 0
        while True:
            line = handle.readline()
            if not line:
                return
            buf.append(line)
            quotes += line.count(b'"')
            if quotes % 2:
                continue
            row = next(csv.reader(io.StringIO(b"".join(buf).decode("utf-8"))))
            buf, quotes = [], 0
            yield row, handle.tell()


TICK_COLS = ["symbol", "name", "date", "seq", "time", "price", "change_price", "change_pct", "volume", "amount",
             "side", "side_raw", "flag", "source_id"]
QUOTE_COLS = (["symbol", "name", "date", "seq", "time", "last", "open", "high", "low", "cum_volume", "cum_amount"]
              + [f"{side}{i}_{kind}" for side in ("bid", "ask") for i in range(1, 6) for kind in ("px", "vol")]
              + ["item_date", "flag", "source_id"])


def tick_rows(row, out):
    source_id, code, name, day, payload = int(row[0]), row[2], row[3], row[4], unescape(row[5])
    items = json.loads(payload) if payload else []
    sym = symbol(code)
    previous = None
    for seq, item in enumerate(items):
        t = str(item.get("time") or "")
        price = fnum(item.get("price"))
        lots = fnum(item.get("deal_lot"))
        amount = fnum(item.get("deal_amount"))
        raw = item.get("status")
        side = SIDES.get(raw)
        key = (t, price, lots, amount)
        if price is None or price <= 0:
            flag = "no_price"
        elif side is None:
            flag = "bad_status"          # e.g. "/th>": a scraped HTML fragment row, duplicates its neighbour
        elif not in_session(t):
            flag = "out_of_session"
        elif key == previous:
            flag = "duplicate"
        else:
            flag = None
        previous = key
        change = item.get("change_price")
        out["symbol"].append(sym); out["name"].append(name); out["date"].append(day); out["seq"].append(seq)
        out["time"].append(t); out["price"].append(price)
        out["change_price"].append(0.0 if change == "--" else fnum(change))
        out["change_pct"].append(fnum(item.get("change_ratio")))
        out["volume"].append(int(lots * 100) if lots is not None else None)
        out["amount"].append(amount); out["side"].append(side); out["side_raw"].append(raw)
        out["flag"].append(flag); out["source_id"].append(source_id)
    return len(items)


def quote_rows(row, out):
    source_id, code, name, day, payload = int(row[0]), row[2], row[3], row[4], unescape(row[5])
    items = json.loads(payload) if payload else []
    sym = symbol(code)
    previous_time = None
    for seq, item in enumerate(items):
        t = str(item.get("time") or "")
        item_date = str(item.get("date") or "")
        last = fnum(item.get("now"))
        if item_date != day:
            flag = "item_date_differs"
        elif not in_session(t):
            flag = "out_of_session"
        elif t == previous_time:
            flag = "duplicate_time"
        elif last is None or last <= 0:
            flag = "no_price"
        else:
            flag = None
        previous_time = t
        deal = item.get("deal") or [None, None]
        out["symbol"].append(sym); out["name"].append(name); out["date"].append(day); out["seq"].append(seq)
        out["time"].append(t)
        for key, source in (("last", "now"), ("open", "open"), ("high", "high"), ("low", "low")):
            value = fnum(item.get(source))
            out[key].append(value if value and value > 0 else None)
        out["cum_volume"].append(fnum(deal[0])); out["cum_amount"].append(fnum(deal[1]))
        for side, prefix in (("bid", "buy"), ("ask", "sell")):
            for i in range(1, 6):
                px, vol = (item.get(f"{prefix}{i}") or [None, None])[:2]
                px = fnum(px)
                out[f"{side}{i}_px"].append(px if px and px > 0 else None)
                out[f"{side}{i}_vol"].append(fnum(vol))
        out["item_date"].append(item_date); out["flag"].append(flag); out["source_id"].append(source_id)
    return len(items)


def _write_part(out: dict, cols, target: Path) -> str:
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.table({c: out[c] for c in cols})
    table = table.set_column(table.schema.get_field_index("date"), "date",
                             table.column("date").cast(pa.string()).cast(pa.date32()))
    tmp = target.with_name(target.name + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, target)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def convert(data_root: Path, table: str, max_seconds: float) -> dict:
    source = data_root / SOURCE / FILES[table]
    out_dir = data_root / OUT / table
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = data_root / OUT / "_state" / f"{table}.json"
    state = (json.loads(state_path.read_text()) if state_path.is_file()
             else {"table": table, "source": str(source.relative_to(data_root)), "source_bytes": source.stat().st_size,
                   "offset": 0, "records": 0, "rows": 0, "parts": [], "complete": False})
    if state["complete"]:
        return state
    if state["source_bytes"] != source.stat().st_size:
        raise RuntimeError("source file size changed since the conversion started")
    cols = TICK_COLS if table == "ticks" else QUOTE_COLS
    builder = tick_rows if table == "ticks" else quote_rows
    started = time.monotonic()
    out = {c: [] for c in cols}
    pending_offset = state["offset"]
    pending_records = 0

    def flush():
        nonlocal out, pending_records
        if not out["symbol"]:
            return
        name = f"part-{len(state['parts']):05d}.parquet"
        sha = _write_part(out, cols, out_dir / name)
        state["parts"].append({"file": name, "rows": len(out["symbol"]), "sha256": sha,
                               "records": pending_records, "end_offset": pending_offset})
        state["rows"] += len(out["symbol"])
        state["records"] += pending_records
        state["offset"] = pending_offset
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_path.with_name(state_path.name + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        os.replace(tmp, state_path)
        out = {c: [] for c in cols}
        pending_records = 0

    exhausted = True
    for row, next_offset in records(source, state["offset"]):
        if len(row) != 10:
            raise RuntimeError(f"record with {len(row)} columns at offset {pending_offset}")
        if unescape(row[9]) is None:           # deleted_at is NULL
            builder(row, out)
        pending_records += 1
        pending_offset = next_offset
        if len(out["symbol"]) >= (ROWS_PER_PART if table == "ticks" else QUOTE_ROWS_PER_PART):
            flush()
        if time.monotonic() - started > max_seconds:
            exhausted = False
            break
    flush()
    if exhausted:
        state["complete"] = True
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    return {k: v for k, v in state.items() if k != "parts"} | {"parts": len(state["parts"])}


BUILD_SQL = """
CREATE OR REPLACE TABLE ticks_all AS SELECT * FROM read_parquet('{root}/ticks/part-*.parquet');
CREATE OR REPLACE TABLE quotes_all AS SELECT * FROM read_parquet('{root}/quotes/part-*.parquet');
CREATE OR REPLACE TABLE trading_days AS SELECT CAST(calendar_date AS DATE) AS date
    FROM read_parquet('{calendar}') WHERE CAST(is_trading_day AS VARCHAR) IN ('1','1.0','True','true');

-- one row per (symbol, date, source): coverage and cross-checks
CREATE OR REPLACE TABLE stock_days AS
WITH t AS (
  SELECT symbol, date, count(*) AS rows_all, count(*) FILTER (WHERE flag IS NULL) AS rows_clean,
         count(DISTINCT source_id) AS source_records,
         min(time) FILTER (WHERE flag IS NULL) AS first_time, max(time) FILTER (WHERE flag IS NULL) AS last_time,
         arg_max(price, seq) FILTER (WHERE flag IS NULL) AS close,
         sum(volume) FILTER (WHERE flag IS NULL) AS volume, sum(amount) FILTER (WHERE flag IS NULL) AS amount,
         median(price / (1 + change_pct / 100)) FILTER (WHERE flag IS NULL AND change_pct > -99) AS prev_close
  FROM ticks_all GROUP BY 1, 2),
q AS (
  SELECT symbol, date, count(*) AS quote_rows_all, count(*) FILTER (WHERE flag IS NULL) AS quote_rows_clean,
         max(cum_volume) FILTER (WHERE flag IS NULL) AS quote_cum_volume,
         min(time) FILTER (WHERE flag IS NULL) AS quote_first_time, max(time) FILTER (WHERE flag IS NULL) AS quote_last_time,
         arg_max(last, seq) FILTER (WHERE flag IS NULL) AS quote_last
  FROM quotes_all GROUP BY 1, 2)
SELECT coalesce(t.symbol, q.symbol) AS symbol, coalesce(t.date, q.date) AS date,
       t.rows_all, t.rows_clean, t.source_records, t.first_time, t.last_time, t.close, t.volume, t.amount, t.prev_close,
       q.quote_rows_all, q.quote_rows_clean, q.quote_cum_volume, q.quote_last, q.quote_first_time, q.quote_last_time,
       (coalesce(t.date, q.date) IN (SELECT date FROM trading_days)) AS is_trading_day
FROM t FULL JOIN q ON t.symbol = q.symbol AND t.date = q.date;

CREATE OR REPLACE VIEW ticks AS
  SELECT a.* EXCLUDE (flag, side_raw, source_id),
         CAST(a.date AS TIMESTAMP) + CAST(a.time AS INTERVAL) AS ts
  FROM ticks_all a JOIN stock_days d USING (symbol, date)
  WHERE a.flag IS NULL AND d.usable_ticks;
CREATE OR REPLACE VIEW quotes AS
  SELECT a.* EXCLUDE (flag, item_date, source_id),
         CAST(a.date AS TIMESTAMP) + CAST(a.time AS INTERVAL) AS ts
  FROM quotes_all a JOIN stock_days d USING (symbol, date)
  WHERE a.flag IS NULL AND d.usable_quotes;
"""


def build(data_root: Path, *, log=print, reload: bool = False) -> dict:
    import duckdb
    root = data_root / OUT
    for table in FILES:
        state = json.loads((root / "_state" / f"{table}.json").read_text())
        if not state.get("complete"):
            raise RuntimeError(f"{table} conversion is not complete")
    snaps = sorted((data_root / "lake/bronze/provider=baostock/reference_snapshots").glob("snapshot=*"))
    calendar = snaps[-1] / "trade_calendar.parquet"
    db_path = root / "gst_intraday.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("SET preserve_insertion_order=false")
    have = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    for statement in BUILD_SQL.format(root=root, calendar=calendar).split(";\n"):
        statement = statement.strip()
        if not statement or statement.startswith("CREATE OR REPLACE VIEW"):
            continue                    # views need stock_days quality columns first
        table = statement.split()[4] if statement.startswith("CREATE OR REPLACE TABLE") else None
        if table in ("ticks_all", "quotes_all") and table in have and not reload:
            continue                    # 79M source rows are loaded once; derived tables are rebuilt
        con.execute(statement)
    log("基础表完成")
    # cross-check against DATA's Baostock raw daily bars
    daily_dir = data_root / "lake/bronze/provider=baostock/stock_kline_daily"
    symbols = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM stock_days ORDER BY 1").fetchall()]
    files = [str(daily_dir / (s.replace(".", "_", 1) + ".parquet")) for s in symbols]
    con.execute(f"""CREATE OR REPLACE TABLE daily_ref AS
        SELECT code AS symbol, CAST(date AS DATE) AS date, CAST(close AS DOUBLE) AS close,
               CAST(volume AS DOUBLE) AS volume, CAST(amount AS DOUBLE) AS amount
        FROM read_parquet({files!r}, union_by_name=true)""")
    con.execute("""CREATE OR REPLACE TABLE stock_days AS
        SELECT s.*, r.close AS ref_close, r.volume AS ref_volume, r.amount AS ref_amount,
               CASE WHEN s.close IS NULL OR r.close IS NULL THEN NULL ELSE abs(s.close - r.close) END AS close_diff,
               CASE WHEN r.volume > 0 THEN s.volume / r.volume END AS volume_ratio,
               CASE WHEN r.volume > 0 THEN s.quote_cum_volume / r.volume END AS quote_volume_ratio,
               coalesce(s.is_trading_day AND r.close IS NOT NULL AND r.volume > 0 AND s.rows_clean >= 50
                AND abs(s.close - r.close) <= 0.011 AND s.volume / r.volume BETWEEN 0.97 AND 1.03
                AND s.first_time <= '09:31:00' AND s.last_time >= '14:56:00', false) AS usable_ticks,
               coalesce(s.is_trading_day AND r.close IS NOT NULL AND r.volume > 0 AND s.quote_rows_clean >= 50
                AND s.quote_cum_volume / r.volume BETWEEN 0.98 AND 1.02
                AND s.quote_first_time <= '09:31:00' AND s.quote_last_time >= '14:56:00', false) AS usable_quotes,
               CASE WHEN NOT s.is_trading_day THEN '非交易日'
                    WHEN r.close IS NULL OR r.volume = 0 THEN '停牌或无日线参考'
                    WHEN s.rows_clean IS NULL THEN NULL
                    WHEN s.first_time > '09:31:00' OR s.last_time < '14:56:00' THEN '成交记录没覆盖全天'
                    WHEN abs(s.close - r.close) > 0.011 THEN '收盘价与日线不符'
                    WHEN s.volume / r.volume NOT BETWEEN 0.97 AND 1.03 THEN '成交量与日线相差超过3%'
                    WHEN s.rows_clean < 50 THEN '成交记录过少' END AS tick_reject_reason,
               CASE WHEN s.quote_rows_clean IS NULL THEN NULL
                    WHEN NOT s.is_trading_day THEN '非交易日'
                    WHEN r.close IS NULL OR r.volume = 0 THEN '停牌或无日线参考'
                    WHEN s.quote_first_time > '09:31:00' OR s.quote_last_time < '14:56:00' THEN '盘口快照没覆盖全天'
                    WHEN s.quote_cum_volume / r.volume NOT BETWEEN 0.98 AND 1.02 THEN '累计成交量与日线相差超过2%'
                    WHEN s.quote_rows_clean < 50 THEN '盘口快照过少' END AS quote_reject_reason
        FROM stock_days s LEFT JOIN daily_ref r USING (symbol, date)""")
    for statement in BUILD_SQL.format(root=root, calendar=calendar).split(";\n"):
        statement = statement.strip()
        if statement.startswith("CREATE OR REPLACE VIEW"):
            con.execute(statement)
    con.execute("""CREATE OR REPLACE TABLE bars_1m AS
        SELECT symbol, date,
               CASE WHEN time < '09:30:00' THEN '09:25' WHEN time >= '15:00:00' THEN '15:00'
                    WHEN time <= '09:31:00' THEN '09:31'
                    WHEN time >= '11:30:00' AND time < '13:00:00' THEN '11:30'
                    WHEN time >= '13:00:00' AND time <= '13:01:00' THEN '13:01'
                    ELSE strftime(CAST(date AS TIMESTAMP) + CAST(time AS INTERVAL) + INTERVAL 59 SECOND
                                  - INTERVAL (second(CAST(time AS TIME)) ) SECOND, '%H:%M') END AS minute,
               arg_min(price, seq) AS open, max(price) AS high, min(price) AS low, arg_max(price, seq) AS close,
               sum(volume) AS volume, sum(amount) AS amount, sum(amount) / nullif(sum(volume), 0) AS vwap,
               count(*) AS ticks,
               sum(volume) FILTER (WHERE side = 'B') AS buy_volume, sum(volume) FILTER (WHERE side = 'S') AS sell_volume
        FROM ticks GROUP BY 1, 2, 3""")
    con.execute("""CREATE OR REPLACE TABLE stocks AS
        SELECT symbol, any_value(name) AS name,
               count(*) FILTER (WHERE usable_ticks) AS tick_days, min(date) FILTER (WHERE usable_ticks) AS tick_from,
               max(date) FILTER (WHERE usable_ticks) AS tick_to,
               count(*) FILTER (WHERE usable_quotes) AS quote_days, min(date) FILTER (WHERE usable_quotes) AS quote_from,
               max(date) FILTER (WHERE usable_quotes) AS quote_to,
               count(*) FILTER (WHERE rows_clean IS NOT NULL AND NOT usable_ticks) AS rejected_tick_days,
               count(*) FILTER (WHERE quote_rows_clean IS NOT NULL AND NOT usable_quotes) AS rejected_quote_days
        FROM stock_days LEFT JOIN (SELECT symbol, any_value(name) AS name FROM ticks_all GROUP BY 1) USING (symbol)
        GROUP BY symbol ORDER BY symbol""")
    summary = {
        "stocks": con.execute("SELECT * FROM stocks").fetchdf().to_dict(orient="records"),
        "ticks_all": con.execute("SELECT count(*) FROM ticks_all").fetchone()[0],
        "ticks_clean": con.execute("SELECT count(*) FROM ticks").fetchone()[0],
        "quotes_all": con.execute("SELECT count(*) FROM quotes_all").fetchone()[0],
        "quotes_clean": con.execute("SELECT count(*) FROM quotes").fetchone()[0],
        "bars_1m": con.execute("SELECT count(*) FROM bars_1m").fetchone()[0],
        "flags_ticks": dict(con.execute("SELECT coalesce(flag,'clean'), count(*) FROM ticks_all GROUP BY 1").fetchall()),
        "flags_quotes": dict(con.execute("SELECT coalesce(flag,'clean'), count(*) FROM quotes_all GROUP BY 1").fetchall()),
        "day_rejections": con.execute("""SELECT
              count(*) FILTER (WHERE NOT is_trading_day) AS not_trading_day,
              count(*) FILTER (WHERE is_trading_day AND ref_close IS NULL) AS no_reference,
              count(*) FILTER (WHERE rows_clean IS NOT NULL AND NOT usable_ticks) AS ticks_rejected,
              count(*) FILTER (WHERE quote_rows_clean IS NOT NULL AND NOT usable_quotes) AS quotes_rejected
            FROM stock_days""").fetchdf().to_dict(orient="records")[0],
        "tick_reject_reasons": dict(con.execute("SELECT tick_reject_reason, count(*) FROM stock_days WHERE tick_reject_reason IS NOT NULL GROUP BY 1").fetchall()),
        "quote_reject_reasons": dict(con.execute("SELECT quote_reject_reason, count(*) FROM stock_days WHERE quote_reject_reason IS NOT NULL GROUP BY 1").fetchall()),
    }
    con.execute("CREATE OR REPLACE TABLE build_info AS SELECT ? AS built_at, ? AS summary_json",
                [datetime.now(timezone.utc).isoformat(), json.dumps(summary, ensure_ascii=False, default=str)])
    con.execute("CHECKPOINT")
    con.close()
    (root / "build_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=str(paths.DATA_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--table", choices=sorted(FILES), required=True)
    c.add_argument("--max-seconds", type=float, default=1e9)
    sub.add_parser("build")
    args = parser.parse_args(argv)
    root = Path(args.data_root)
    if args.command == "convert":
        print(json.dumps(convert(root, args.table, args.max_seconds), ensure_ascii=False))
    else:
        summary = build(root)
        print(json.dumps({k: v for k, v in summary.items() if k != "stocks"}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
