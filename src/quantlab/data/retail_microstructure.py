"""Research-only retail microstructure proxies from the TDX trade archive.

No network access, no writes to the data lake, and no upgrade from the TDX
personal-research qualification. Provider trade volume is only certified as
lots_provider; therefore notional values below are scale proxies, not RMB.
"""
from dataclasses import dataclass
from datetime import date
from math import ceil

import duckdb
import polars as pl

from quantlab.data.tdx_lake import QUALIFICATION, TdxLake


@dataclass(frozen=True)
class RetailMicrostructureConfig:
    small_order_quantile: float = 0.20
    min_qualified_days: int = 120
    min_symbols_per_day: int = 3000
    relative_full_market_ratio: float = 0.90

    def __post_init__(self):
        if type(self.small_order_quantile) not in (int, float) or not 0 < self.small_order_quantile < .5:
            raise ValueError("small_order_quantile must be in (0, .5)")
        if type(self.min_qualified_days) is not int or self.min_qualified_days < 20:
            raise ValueError("min_qualified_days must be an integer >= 20")
        if type(self.min_symbols_per_day) is not int or self.min_symbols_per_day < 3:
            raise ValueError("min_symbols_per_day must be an integer >= 3")
        if type(self.relative_full_market_ratio) not in (int, float) or not .5 <= self.relative_full_market_ratio <= 1:
            raise ValueError("relative_full_market_ratio must be in [.5, 1]")


class TdxRetailMicrostructure:
    """Read-only daily feature builder over tdx_trades_compacted."""

    def __init__(self, data_root, config=None):
        self.lake = TdxLake(data_root)
        self.config = config or RetailMicrostructureConfig()
        if not self.lake.catalog.is_file():
            raise ValueError("TDX catalog is unavailable")

    def _connect(self):
        return duckdb.connect(str(self.lake.catalog), read_only=True)

    @staticmethod
    def _where(start=None, end=None, symbols=()):
        clauses, params = [], []
        if start is not None:
            if type(start) is not date:
                raise ValueError("start must be date")
            clauses.append("date>=?")
            params.append(start)
        if end is not None:
            if type(end) is not date:
                raise ValueError("end must be date")
            clauses.append("date<=?")
            params.append(end)
        if start is not None and end is not None and start > end:
            raise ValueError("start after end")
        symbols = tuple(symbols)
        if len(symbols) != len(set(symbols)):
            raise ValueError("duplicate symbols")
        if symbols:
            clauses.append("code IN (" + ",".join("?" for _ in symbols) + ")")
            params.extend(symbols)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def coverage(self, start=None, end=None):
        where, params = self._where(start, end)
        sql = (
            "SELECT date,count(*) AS n_rows,count(DISTINCT code) AS raw_symbols,"
            "count(DISTINCT CASE WHEN json_extract_string(record_json,'$.side') IN ('buy','sell') "
            "AND price>0 AND volume>0 THEN code END) AS feature_symbols,"
            "sum(CASE WHEN volume_unit!='lots_provider' THEN 1 ELSE 0 END) AS bad_units,"
            "sum(CASE WHEN qualification!=? THEN 1 ELSE 0 END) AS bad_qualification "
            "FROM tdx_trades_compacted" + where + " GROUP BY date ORDER BY date"
        )
        with self._connect() as con:
            try:
                rows = con.execute(sql, [QUALIFICATION, *params]).fetchall()
            except duckdb.CatalogException as exc:
                raise ValueError("tdx_trades_compacted is unavailable") from exc
        if any(row[4] for row in rows):
            raise ValueError("Unexpected TDX trade volume unit")
        if any(row[5] for row in rows):
            raise ValueError("Unexpected TDX trade qualification")
        max_feature_symbols = max((row[3] for row in rows), default=0)
        threshold = (
            max(self.config.min_symbols_per_day, ceil(max_feature_symbols * self.config.relative_full_market_ratio))
            if max_feature_symbols else self.config.min_symbols_per_day
        )
        by_day = [
            {
                "date": row[0].isoformat(),
                "rows": row[1],
                "raw_symbols": row[2],
                "feature_symbols": row[3],
                "qualified": row[3] >= threshold,
            }
            for row in rows
        ]
        qualified = [row for row in by_day if row["qualified"]]
        ready = len(qualified) >= self.config.min_qualified_days
        return {
            "format": "niuniu-retail-microstructure-coverage-v1",
            "qualification": QUALIFICATION,
            "volume_unit": "lots_provider",
            "available_days": len(by_day),
            "max_raw_symbols": max((row[2] for row in rows), default=0),
            "max_feature_symbols": max_feature_symbols,
            "qualified_symbol_threshold": threshold,
            "qualified_days": len(qualified),
            "min_qualified_days": self.config.min_qualified_days,
            "status": "READY_FOR_INFERENCE" if ready else "INSUFFICIENT_COVERAGE",
            "inference_ready": ready,
            "by_day": by_day,
            "scope": "Cross-section completeness proxy only; does not certify PIT completeness or vendor history completeness.",
        }

    def require_inference_ready(self, start=None, end=None):
        result = self.coverage(start, end)
        if not result["inference_ready"]:
            raise ValueError(
                f"INSUFFICIENT_COVERAGE: {result['qualified_days']}/{result['min_qualified_days']} qualified days"
            )
        return result

    def daily_features(self, start=None, end=None, symbols=()):
        where, params = self._where(start, end, symbols)
        q = float(self.config.small_order_quantile)
        sql = f"""
        WITH raw AS (
          SELECT date,code,price,volume,volume_unit,qualification,
                 json_extract_string(record_json,'$.side') AS side,
                 try_cast(json_extract(record_json,'$.order_count') AS DOUBLE) AS order_count
          FROM tdx_trades_compacted{where}
        ), counts AS (
          SELECT date,code,count(*) AS rows_total,
                 sum(CASE WHEN side IN ('buy','sell') THEN 1 ELSE 0 END) AS rows_directional_side,
                 sum(CASE WHEN side NOT IN ('buy','sell') OR side IS NULL THEN 1 ELSE 0 END) AS rows_non_directional,
                 sum(CASE WHEN volume IS NULL OR volume<=0 THEN 1 ELSE 0 END) AS rows_nonpositive_volume
          FROM raw GROUP BY date,code
        ), valid AS (
          SELECT date,code,side,price,volume,order_count,price*volume AS notional_proxy,
                 CASE WHEN order_count>0 THEN volume/order_count END AS avg_lots_per_order
          FROM raw
          WHERE side IN ('buy','sell') AND price>0 AND volume>0
            AND volume_unit='lots_provider' AND qualification='{QUALIFICATION}'
        ), directional AS (
          SELECT date,code,count(*) AS valid_directional_rows,
                 sum(CASE WHEN side='buy' THEN notional_proxy ELSE 0 END) AS buy_notional_proxy,
                 sum(CASE WHEN side='sell' THEN notional_proxy ELSE 0 END) AS sell_notional_proxy,
                 sum(CASE WHEN side='buy' THEN volume ELSE 0 END) AS buy_volume_lots,
                 sum(CASE WHEN side='sell' THEN volume ELSE 0 END) AS sell_volume_lots
          FROM valid GROUP BY date,code
        ), thresholds AS (
          SELECT date,code,quantile_cont(avg_lots_per_order,{q}) AS small_order_threshold
          FROM valid WHERE avg_lots_per_order IS NOT NULL GROUP BY date,code
        ), small AS (
          SELECT v.date,v.code,count(*) AS small_order_rows,
                 sum(notional_proxy) AS small_order_notional_proxy,
                 sum(CASE WHEN side='buy' THEN notional_proxy ELSE 0 END) AS small_buy_notional_proxy,
                 sum(CASE WHEN side='sell' THEN notional_proxy ELSE 0 END) AS small_sell_notional_proxy
          FROM valid v JOIN thresholds t USING(date,code)
          WHERE v.avg_lots_per_order<=t.small_order_threshold
          GROUP BY v.date,v.code
        )
        SELECT c.date,c.code,c.rows_total,c.rows_directional_side,c.rows_non_directional,c.rows_nonpositive_volume,
               d.valid_directional_rows,s.small_order_rows,t.small_order_threshold,
               d.buy_notional_proxy,d.sell_notional_proxy,d.buy_volume_lots,d.sell_volume_lots,
               CASE WHEN d.buy_notional_proxy+d.sell_notional_proxy>0 THEN
                    (d.buy_notional_proxy-d.sell_notional_proxy)/(d.buy_notional_proxy+d.sell_notional_proxy) END AS buy_imbalance_proxy,
               CASE WHEN d.buy_volume_lots+d.sell_volume_lots>0 THEN
                    (d.buy_volume_lots-d.sell_volume_lots)/(d.buy_volume_lots+d.sell_volume_lots) END AS volume_imbalance,
               CASE WHEN d.buy_notional_proxy+d.sell_notional_proxy>0 AND s.small_order_notional_proxy IS NOT NULL THEN
                    s.small_order_notional_proxy/(d.buy_notional_proxy+d.sell_notional_proxy) END AS small_order_notional_share,
               CASE WHEN s.small_buy_notional_proxy+s.small_sell_notional_proxy>0 THEN
                    (s.small_buy_notional_proxy-s.small_sell_notional_proxy)/(s.small_buy_notional_proxy+s.small_sell_notional_proxy) END AS small_order_buy_imbalance
        FROM counts c
        JOIN directional d USING(date,code)
        LEFT JOIN thresholds t USING(date,code)
        LEFT JOIN small s USING(date,code)
        ORDER BY c.date,c.code
        """
        with self._connect() as con:
            try:
                frame = con.execute(sql, params).pl()
            except duckdb.CatalogException as exc:
                raise ValueError("tdx_trades_compacted is unavailable") from exc
        return frame.with_columns(
            pl.lit("provider_lot_price_units_not_RMB").alias("notional_proxy_unit"),
            pl.lit(QUALIFICATION).alias("qualification"),
        )
