"""Frozen Retail Crowding V1 price/volume factors.

The V1 contract intentionally uses only close, volume and turnover (transaction
amount) available at the daily bar close. Attention and trade-side features are
reserved for later versions and are never imputed here.
"""
import polars as pl

from quantlab.domain import FactorType, Timeframe
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack

WINDOW = 20
MOMENTUM_BARS = 5


def _prior_z(column: str, window: int = WINDOW) -> pl.Expr:
    """Current value versus the *prior* complete window, population std."""
    value = pl.col(column)
    prior = value.shift(1).over("symbol")
    mean = prior.rolling_mean(window_size=window, min_samples=window).over("symbol")
    std = prior.rolling_std(window_size=window, min_samples=window, ddof=0).over("symbol")
    return pl.when(std > 1e-12).then((value - mean) / std).otherwise(None)


class VolumeShock20(ComputedFactor):
    definition = FactorDefinition(
        "RETAIL.VOLUME_SHOCK_20", "1.0.0", "成交量异常度20", "behavior",
        FactorType.SCALAR, ("volume",), (Timeframe.DAILY,),
        "当日成交量相对之前20个交易日成交量的时序Z分数；基准窗口不含当日，零方差输出null。",
        "(volume_t-mean(volume[t-20:t-1]))/std_pop(volume[t-20:t-1])",
        causal=True, lookahead_risk="low",
        tags=("retail_crowding", "volume", "shock"),
        available_at_rule="daily bar close after 20 prior bars",
    )

    def parameters(self, supplied):
        if supplied:
            raise ValueError("RETAIL.VOLUME_SHOCK_20 has no parameters")
        return {}

    def compute(self, bars, parameters):
        self.parameters(parameters)
        return bars.select("symbol", "datetime", "available_at", _prior_z("volume").alias("value"))


class AmountShock20(ComputedFactor):
    definition = FactorDefinition(
        "RETAIL.AMOUNT_SHOCK_20", "1.0.0", "成交额异常度20", "behavior",
        FactorType.SCALAR, ("turnover",), (Timeframe.DAILY,),
        "当日成交额相对之前20个交易日成交额的时序Z分数；turnover字段在MQC日线合同中表示成交额而非换手率；零方差输出null。",
        "(amount_t-mean(amount[t-20:t-1]))/std_pop(amount[t-20:t-1])",
        causal=True, lookahead_risk="low",
        tags=("retail_crowding", "amount", "shock"),
        available_at_rule="daily bar close after 20 prior bars",
    )

    def parameters(self, supplied):
        if supplied:
            raise ValueError("RETAIL.AMOUNT_SHOCK_20 has no parameters")
        return {}

    def compute(self, bars, parameters):
        self.parameters(parameters)
        return bars.select("symbol", "datetime", "available_at", _prior_z("turnover").alias("value"))


class RetailCrowdingV1(ComputedFactor):
    definition = FactorDefinition(
        "RETAIL.CROWDING_V1", "1.0.0", "散户拥挤V1", "behavior",
        FactorType.SCALAR, ("close", "volume", "turnover"), (Timeframe.DAILY,),
        "MOM5异常度、成交量异常度、成交额异常度的等权平均；每个异常度都只使用之前20个交易日作为基准，不含当日。",
        "(z_prev20(close_t/close_t-5-1)+z_prev20(volume_t)+z_prev20(amount_t))/3",
        causal=True, lookahead_risk="low",
        tags=("retail_crowding", "behavior", "price_volume"),
        available_at_rule="daily bar close after 25 prior bars",
    )

    def parameters(self, supplied):
        if supplied:
            raise ValueError("RETAIL.CROWDING_V1 has no parameters")
        return {}

    def compute(self, bars, parameters):
        self.parameters(parameters)
        frame = bars.with_columns(
            (pl.col("close") / pl.col("close").shift(MOMENTUM_BARS).over("symbol") - 1).alias("_mom5")
        )
        frame = frame.with_columns(
            _prior_z("_mom5").alias("_z_mom5"),
            _prior_z("volume").alias("_z_volume"),
            _prior_z("turnover").alias("_z_amount"),
        )
        ready = pl.all_horizontal(
            pl.col("_z_mom5").is_not_null(),
            pl.col("_z_volume").is_not_null(),
            pl.col("_z_amount").is_not_null(),
        )
        return frame.select(
            "symbol", "datetime", "available_at",
            pl.when(ready).then(
                (pl.col("_z_mom5") + pl.col("_z_volume") + pl.col("_z_amount")) / 3.0
            ).otherwise(None).alias("value"),
        )


def retail_crowding_pack() -> FactorPack:
    return FactorPack(
        "RetailCrowdingPack", "1.0.0",
        (VolumeShock20(), AmountShock20(), RetailCrowdingV1()),
        ("BaseQuantPack",),
    )
