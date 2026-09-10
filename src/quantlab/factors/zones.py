from quantlab.domain import FactorType, Timeframe
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.zones.fvg import FVGZoneEngine


class FVGBullCreated(ComputedFactor):
    definition = FactorDefinition(
        "ZONE.FVG_BULL_CREATED", "1.0.0", "向上 FVG 创建", "price_zone", FactorType.BOOLEAN,
        ("high", "low"), tuple(Timeframe),
        "第三根低价严格高于第一根高价，第三根完成时创建区域", "low[t] > high[t-2]",
    )
    column = "bull_created"

    def parameters(self, supplied):
        if supplied:
            raise ValueError("Basic FVG factors have no parameters")
        return {}

    def compute(self, bars, parameters):
        return FVGZoneEngine().flags(bars).select("symbol", "datetime", "available_at",
            self.column).rename({self.column: "value"})


class FVGBearCreated(FVGBullCreated):
    definition = FactorDefinition(
        "ZONE.FVG_BEAR_CREATED", "1.0.0", "向下 FVG 创建", "price_zone", FactorType.BOOLEAN,
        ("high", "low"), tuple(Timeframe),
        "第三根高价严格低于第一根低价，第三根完成时创建区域", "high[t] < low[t-2]",
    )
    column = "bear_created"


class FVGActiveCount(FVGBullCreated):
    definition = FactorDefinition(
        "ZONE.FVG_ACTIVE_COUNT", "1.0.0", "活跃 FVG 数量", "price_zone", FactorType.SCALAR,
        ("high", "low"), tuple(Timeframe),
        "按当根可用信息统计两个方向尚未完全回补或跳空失效的区域数；仅限已加载历史",
        "count(active FVG zones after current bar updates and creation)",
    )

    def compute(self, bars, parameters):
        return FVGZoneEngine().analyze(bars).counts.rename({"active_count": "value"})


def zone_pack() -> FactorPack:
    return FactorPack("ZoneBasePack", "1.0.0", (FVGBullCreated(), FVGBearCreated(), FVGActiveCount()), ("BaseQuantPack",))
