from typing import Any, Mapping

import polars as pl

from quantlab.domain import FactorType, Timeframe
from quantlab.factors.base import ComputedFactor, ExpressionFactor, FactorDefinition
from quantlab.factors.registry import FactorPack


def lookback_parameters(supplied: Mapping[str, Any]) -> dict[str, Any]:
    if set(supplied) - {"lookback"}:
        raise ValueError("Only lookback is supported")
    value = supplied.get("lookback", 20)
    if type(value) is not int or value < 1:
        raise ValueError("lookback must be a positive integer")
    return {"lookback": value}


class Momentum(ExpressionFactor):
    definition = FactorDefinition(
        "BASE.MOMENTUM", "1.0.0", "区间动量", "momentum", FactorType.SCALAR,
        ("close",), tuple(Timeframe),
        "当前收盘相对 N 根之前收盘的变化率", "close / shift(close, N) - 1",
    )

    def parameters(self, supplied):
        return lookback_parameters(supplied)

    def expression(self, parameters):
        return pl.col("close") / pl.col("close").shift(parameters["lookback"]).over("symbol") - 1


class CloseLocation(ComputedFactor):
    definition = FactorDefinition(
        "BASE.CLOSE_LOCATION", "1.0.0", "收盘区间位置", "structure", FactorType.SCALAR,
        ("high", "low", "close"), tuple(Timeframe),
        "收盘在当根高低区间的位置；零振幅取 0.5", "(close - low) / (high - low)",
    )

    def parameters(self, supplied):
        if supplied:
            raise ValueError("CloseLocation has no parameters")
        return {}

    def compute(self, bars, parameters):
        span = pl.col("high") - pl.col("low")
        return bars.select(
            "symbol", "datetime", "available_at",
            pl.when(span == 0).then(0.5).otherwise((pl.col("close") - pl.col("low")) / span).alias("value"),
        )


class ATR(ComputedFactor):
    definition = FactorDefinition(
        "BASE.ATR", "1.0.0", "平均真实波幅（简单平均）", "volatility", FactorType.SCALAR,
        ("high", "low", "close"), tuple(Timeframe),
        "最近 N 根真实波幅的简单平均；首根缺少前收盘，记为 null",
        "SMA(max(high-low, abs(high-prev_close), abs(low-prev_close)), N)",
    )

    def parameters(self, supplied):
        return lookback_parameters(supplied)

    def compute(self, bars, parameters):
        previous = pl.col("close").shift(1).over("symbol")
        frame = bars.with_columns(pl.when(previous.is_not_null()).then(pl.max_horizontal(
            pl.col("high") - pl.col("low"), (pl.col("high") - previous).abs(),
            (pl.col("low") - previous).abs(),
        )).alias("true_range"))
        return frame.select("symbol", "datetime", "available_at",
            pl.col("true_range").rolling_mean(parameters["lookback"]).over("symbol").alias("value"))


class ReturnVolatility(ComputedFactor):
    definition = FactorDefinition(
        "BASE.RETURN_VOLATILITY", "1.0.0", "收益波动率", "volatility", FactorType.SCALAR,
        ("close",), tuple(Timeframe),
        "最近 N 个简单收益率的样本标准差，不年化；N 至少为 2",
        "std(close / prev_close - 1, N, ddof=1)",
    )

    def parameters(self, supplied):
        parameters = lookback_parameters(supplied)
        if parameters["lookback"] < 2:
            raise ValueError("ReturnVolatility lookback must be >= 2")
        return parameters

    def compute(self, bars, parameters):
        frame = bars.with_columns((pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("return"))
        return frame.select("symbol", "datetime", "available_at",
            pl.col("return").rolling_std(parameters["lookback"], ddof=1).over("symbol").alias("value"))


class DirectionalEfficiency(ComputedFactor):
    definition = FactorDefinition(
        "BASE.DIRECTIONAL_EFFICIENCY", "1.0.0", "有符号方向效率", "trend", FactorType.SCALAR,
        ("close",), tuple(Timeframe),
        "N 根净价格变化除以逐根绝对变化之和，范围 [-1,1]；完整窗口无变化取 0",
        "(close-shift(close,N)) / sum(abs(diff(close)), N)",
    )

    def parameters(self, supplied):
        return lookback_parameters(supplied)

    def compute(self, bars, parameters):
        n = parameters["lookback"]
        frame = bars.with_columns(pl.col("close").diff().abs().over("symbol").alias("step"))
        distance = pl.col("step").rolling_sum(n).over("symbol")
        change = pl.col("close") - pl.col("close").shift(n).over("symbol")
        return frame.select("symbol", "datetime", "available_at",
            pl.when(distance == 0).then(0.0).otherwise(change / distance).alias("value"))


def base_quant_pack() -> FactorPack:
    return FactorPack("BaseQuantPack", "1.1.0", (
        Momentum(), CloseLocation(), ATR(), ReturnVolatility(), DirectionalEfficiency(),
    ))
