"""Lagged provider ratios; causal transforms are not historical PIT certification."""
import polars as pl
from quantlab.domain import FactorType, Timeframe
from quantlab.factors.base import ExpressionFactor, FactorDefinition
from quantlab.factors.registry import FactorPack

SERIES = {
    'PE_TTM': ('bs_pe_ttm', '滞后滚动市盈率', 'valuation'),
    'PB_MRQ': ('bs_pb_mrq', '滞后市净率', 'valuation'),
    'PS_TTM': ('bs_ps_ttm', '滞后滚动市销率', 'valuation'),
    'PCF_NCF_TTM': ('bs_pcf_ncf_ttm', '滞后滚动市现率', 'valuation'),
    'TURN_PCT': ('bs_turn_pct', '滞后换手率（百分数）', 'liquidity'),
}


class BaostockRatio(ExpressionFactor):
    def __init__(self, name):
        self.field, title, category = SERIES[name]
        self.definition = FactorDefinition(
            'BAO.'+name, '1.0.0', title, category, FactorType.SCALAR,
            (self.field,), (Timeframe.DAILY,),
            '来自已校验的不复权日线响应，至少滞后一根实际日线；空值与负值保留。'
            '不认证首次公布时间、历史修订或严格PIT；不得解释为盈利结论。',
            f'shift({self.field}, lag_bars).over(symbol)',
            tags=('baostock', 'retrospective', 'explicit_information_lag'),
            available_at_rule='Next observed daily close or later; vendor first-publication time unverified',
        )

    def parameters(self, supplied):
        if not isinstance(supplied, dict) or set(supplied)-{'lag_bars'}:
            raise ValueError('仅支持 lag_bars 参数')
        lag = supplied.get('lag_bars', 1)
        if type(lag) is not int or not 1 <= lag <= 252:
            raise ValueError('Baostock因子必须滞后1–252根已观察日线，不能使用零滞后')
        return {'lag_bars': lag}

    def expression(self, parameters):
        return pl.col(self.field).shift(parameters['lag_bars']).over('symbol')


def baostock_pack():
    return FactorPack('BaostockDailyRatioPack', '1.0.0',
                      tuple(BaostockRatio(name) for name in SERIES))
