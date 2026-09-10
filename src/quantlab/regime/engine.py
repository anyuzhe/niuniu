from dataclasses import asdict

import polars as pl

from quantlab.domain import MarketState, Timeframe
from quantlab.factors.engine import compute_factor
from quantlab.factors.registry import FactorRegistry
from quantlab.regime.config import RegimeConfig, RegimeFilter


class RuleBasedRegimeEngine:
    version = "1.1.0"

    def __init__(self, config: RegimeConfig = RegimeConfig()):
        self.config = config

    def frame(self, factors: pl.DataFrame) -> pl.DataFrame:
        """Input: wide, current-bar efficiency/volatility and information keys."""
        required = {"symbol", "datetime", "available_at", "timeframe", "efficiency", "volatility"}
        if required - set(factors.columns):
            raise ValueError("Missing regime input fields")
        if any(factors[key].null_count() for key in required - {"efficiency", "volatility"}):
            raise ValueError("Null regime information key")
        if factors.select(pl.struct("symbol", "datetime").is_duplicated().any()).item():
            raise ValueError("Duplicate regime key")
        if factors["timeframe"].n_unique() != 1:
            raise ValueError("Classify one timeframe at a time")
        frame = factors.sort("symbol", "datetime")
        if frame.filter((pl.col("available_at") < pl.col("datetime")) |
                        (pl.col("available_at").diff().over("symbol") < pl.duration())).height:
            raise ValueError("Invalid regime information time")
        if frame.filter((pl.col("efficiency").abs() > 1 + 1e-12) | (pl.col("volatility") < 0) |
                        ~pl.col("efficiency").is_finite() | ~pl.col("volatility").is_finite()).height:
            raise ValueError("Invalid regime factor values")
        c = self.config
        frame = frame.with_columns(pl.col("volatility").rolling_mean(c.baseline_window).shift(1).over("symbol").alias("volatility_baseline"))
        efficiency, volatility, baseline = pl.col("efficiency"), pl.col("volatility"), pl.col("volatility_baseline")
        liquidity=pl.lit('Unknown')
        if 'amihud' in frame.columns:
            frame=frame.with_columns(
                pl.col('amihud').rolling_quantile(1/3,window_size=c.baseline_window).shift(1).over('symbol').alias('_liq_low'),
                pl.col('amihud').rolling_quantile(2/3,window_size=c.baseline_window).shift(1).over('symbol').alias('_liq_high'))
            liquidity=(pl.when(pl.col('amihud').is_null()|pl.col('_liq_low').is_null()|pl.col('_liq_high').is_null()).then(pl.lit('Unknown'))
                .when(pl.col('amihud')<pl.col('_liq_low')).then(pl.lit('High'))
                .when(pl.col('amihud')>pl.col('_liq_high')).then(pl.lit('Low')).otherwise(pl.lit('Medium')))
        return frame.with_columns(
            pl.when(efficiency.is_null()).then(pl.lit("Unknown"))
            .when(efficiency >= c.direction_threshold).then(pl.lit("Bull"))
            .when(efficiency <= -c.direction_threshold).then(pl.lit("Bear"))
            .otherwise(pl.lit("Neutral")).alias("regime_direction"),
            pl.when(efficiency.is_null()).then(pl.lit("Unknown"))
            .when(efficiency.abs() >= c.trend_threshold).then(pl.lit("Trend"))
            .when(efficiency.abs() <= c.range_threshold).then(pl.lit("Range"))
            .otherwise(pl.lit("Transition")).alias("regime_structure"),
            pl.when(volatility.is_null() | baseline.is_null()).then(pl.lit("Unknown"))
            .when(volatility <= baseline * c.volatility_low).then(pl.lit("Low"))
            .when(volatility >= baseline * c.volatility_high).then(pl.lit("High"))
            .otherwise(pl.lit("Medium")).alias("regime_volatility"),
            liquidity.alias("regime_liquidity"),
        )

    def classify(self, factors: pl.DataFrame) -> list[MarketState]:
        return [MarketState(row["symbol"], Timeframe(row["timeframe"]), row["datetime"], row["available_at"],
            row["regime_direction"], row["regime_structure"], row["regime_volatility"], row["regime_liquidity"], self.version)
            for row in self.frame(factors).iter_rows(named=True)]


def compute_regime(bars: pl.DataFrame, registry: FactorRegistry, config: RegimeConfig) -> tuple[pl.DataFrame, dict]:
    frame = bars.select("symbol", "datetime", "available_at", "timeframe")
    inputs = []
    for factor_id, column in (("BASE.DIRECTIONAL_EFFICIENCY", "efficiency"), ("BASE.RETURN_VOLATILITY", "volatility")):
        factor = registry.get(factor_id, "1.0.0")
        parameters = factor.parameters({"lookback": config.lookback})
        values = compute_factor(factor, bars, parameters)
        # Baselines consume past bars only when already known at the current
        # bar; this baseline implementation requires immediate input factors.
        if values.filter(pl.col("available_at") != pl.col("datetime")).height:
            raise ValueError("Regime inputs must be available at bar close")
        frame = frame.join(values.select("symbol", "datetime", pl.col("value").alias(column)), on=["symbol", "datetime"], validate="1:1")
        inputs.append({"definition": asdict(factor.definition), "parameters": parameters, "code_hash": registry.code_hash(factor)})
    liquidity=bars.sort('symbol','datetime').with_columns(
        (pl.when(pl.col('turnover')>0).then(pl.col('close').pct_change().over('symbol').abs()/pl.col('turnover')).otherwise(None) if 'turnover' in bars.columns else pl.lit(None,dtype=pl.Float64)).alias('amihud'))
    frame=frame.join(liquidity.select('symbol','datetime','amihud'),on=['symbol','datetime'],validate='1:1')
    engine = RuleBasedRegimeEngine(config)
    return engine.frame(frame), {"version": '1.1.0', "config": asdict(config), "inputs": inputs,
        'liquidity_model':'Amihud abs(close_return)/turnover against lagged per-symbol terciles; OHLCV proxy, not spread/depth'}


def filter_mask(states: pl.DataFrame, selection: RegimeFilter) -> pl.DataFrame:
    conditions = [pl.col(f"regime_{key}") == value for key, value in asdict(selection).items() if value is not None]
    return states.select("symbol", "datetime", pl.all_horizontal(conditions).alias("regime_eligible"))
