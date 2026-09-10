import polars as pl

from quantlab.domain import FactorType, Timeframe
from quantlab.events.breakout import BreakoutHighEngine
from quantlab.events.failed_breakout import FailedBreakoutEngine
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.builtin import lookback_parameters
from quantlab.factors.registry import FactorPack
from quantlab.structure.pivots import ConfirmedPivotEngine


class PivotHighConfirmed(ComputedFactor):
    definition = FactorDefinition(
        "STRUCT.PIVOT_HIGH_CONFIRMED", "1.0.0", "严格高点确认", "structure", FactorType.BOOLEAN,
        ("high", "low", "close"), tuple(Timeframe),
        "高点严格高于左右窗口；仅在右窗口结束时触发，发生时刻另存于 Structure",
        "high[t-right] > max(left highs) AND high[t-right] > max(right highs)",
        available_at_rule="confirmation bar availability; never backdate to pivot",
    )

    def parameters(self, supplied):
        if set(supplied) - {"left", "right"}:
            raise ValueError("PivotHighConfirmed accepts only left and right")
        params = {"left": supplied.get("left", 2), "right": supplied.get("right", 2)}
        ConfirmedPivotEngine(**params)
        return params

    def compute(self, bars, parameters):
        frame = ConfirmedPivotEngine(**parameters).flags(bars)
        return frame.select("symbol", "datetime", "available_at",
            pl.when(pl.col("ready")).then(pl.col("pivot_high")).otherwise(None).alias("value"))


class BreakoutHigh(ComputedFactor):
    definition = FactorDefinition(
        "EVT.BREAKOUT_HIGH", "1.0.0", "前高收盘突破", "breakout", FactorType.BOOLEAN,
        ("high", "close"), tuple(Timeframe),
        "每根收盘严格高于前 N 根最高价即触发；允许连续触发，不含当前高价",
        "close[t] > max(high[t-N:t-1])",
    )

    def parameters(self, supplied):
        return lookback_parameters(supplied)

    def compute(self, bars, parameters):
        return BreakoutHighEngine(**parameters).flags(bars).select(
            "symbol", "datetime", "available_at", pl.col("breakout_high").alias("value"))


class FailedBreakoutHigh(ComputedFactor):
    side = 'high'
    definition = FactorDefinition('EVT.FAILED_BREAKOUT_HIGH','1.0.0','前高突破失败','failed_breakout',FactorType.BOOLEAN,
        ('high','low','close'),tuple(Timeframe),
        '本根最高价严格越过此前 N 根最高价，收盘回到此前完整区间（含边界）；允许同根双侧事件',
        'high[t] > prior_high AND prior_low <= close[t] <= prior_high')

    def parameters(self, supplied):
        return lookback_parameters(supplied)

    def compute(self, bars, parameters):
        return FailedBreakoutEngine(**parameters).flags(bars).select('symbol','datetime','available_at',
            pl.col(f'failed_{self.side}').alias('value'))


class FailedBreakoutLow(FailedBreakoutHigh):
    side = 'low'
    definition = FactorDefinition('EVT.FAILED_BREAKOUT_LOW','1.0.0','前低突破失败','failed_breakout',FactorType.BOOLEAN,
        ('high','low','close'),tuple(Timeframe),
        '本根最低价严格越过此前 N 根最低价，收盘回到此前完整区间（含边界）；允许同根双侧事件',
        'low[t] < prior_low AND prior_low <= close[t] <= prior_high')


def technical_pack() -> FactorPack:
    return FactorPack("TechnicalBasePack", "1.1.0", (PivotHighConfirmed(), BreakoutHigh(), FailedBreakoutHigh(), FailedBreakoutLow()), ("BaseQuantPack",))
