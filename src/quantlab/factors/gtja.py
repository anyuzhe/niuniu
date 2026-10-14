"""GTJA 191 (国泰君安 191) factor pack: the vendored aurumq-rl polars implementations behind the repo's factor interface.

Provenance, licence and the list of factors that are NOT offered (and why) are in ``gtja191/PROVENANCE.md``.
Inputs are the requested price basis, exactly like the Alpha packs: VWAP = turnover / volume x adj_factor,
``amount`` = turnover, ``returns`` = close / previous close - 1 per symbol. Cross-sectional operators (RANK etc.)
use the symbols supplied in this call, at the same close, before any research-universe filtering.
"""
import inspect
import re
from functools import lru_cache
import polars as pl
from quantlab.domain import FactorType, Timeframe
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack

_BENCHMARK = ('needs a real benchmark index (upstream substitutes the cross-section mean of the supplied symbols, '
              'which changes with the universe)')
UNSUPPORTED = {
    'gtja_030': 'stub upstream: Fama-French exposures are not available (upstream returns all-NaN)',
    'gtja_033': 'needs market cap, which the bar data does not carry',
    'gtja_062': 'needs market cap, which the bar data does not carry',
    'gtja_075': _BENCHMARK, 'gtja_149': _BENCHMARK, 'gtja_181': _BENCHMARK, 'gtja_182': _BENCHMARK,
    'gtja_143': 'recursive SELF definition: the value depends on how much history is loaded',
}
_CORE = ('open', 'high', 'low', 'close', 'volume')


@lru_cache(maxsize=1)
def _registry():
    from quantlab.factors.gtja191 import REGISTRY
    return REGISTRY


def _needed(entry):
    """Columns a factor reads: every quoted column name in its source plus the ones its docstring declares."""
    impl = getattr(entry.impl, '__wrapped__', entry.impl)
    source = inspect.getsource(impl)
    names = set(re.findall(r'col\(\s*"(\w+)"', source)) | set(re.findall(r'\[\s*"(\w+)"\s*\]', source))
    match = re.search(r'Required panel columns:(.*?)\n\s*\n', impl.__doc__ or '', re.S)
    if match:
        names |= set(re.findall(r'`+(\w+)`+', match.group(1)))
    return names & {'open', 'high', 'low', 'close', 'volume', 'vwap', 'amount', 'returns', 'cap'}


class GtjaFormula(ComputedFactor):
    def __init__(self, key, entry):
        self.key, self.entry = key, entry
        need = _needed(entry) or set(_CORE)
        columns = sorted(need & set(_CORE))
        if need & {'vwap', 'amount'}:
            columns += ['turnover']
        if 'vwap' in need:
            columns += ['adj_factor']
        self.need = need
        flag = {0: '', 1: '（上游标注：论文公式有已知勘误，保守实现）'}.get(entry.quality_flag, '')
        self.definition = FactorDefinition(
            f'GTJA191.{key.upper()}', '1.0.0', f'国泰君安191 · {key}', 'quant', FactorType.SCALAR,
            tuple(dict.fromkeys(columns)), (Timeframe.DAILY,),
            f'{entry.description}{flag}。移植自 aurumq-rl（MIT），按来源实现，未与论文逐条独立复核。截面运算基于本次传入股票；'
            'VWAP 按成交额/成交量×复权因子；输出 ±1e6 截断，非有限结果置空。',
            f'aurumq-rl gtja191/{key}', tags=('gtja191', f'quality_{entry.quality_flag}'), source_theory=('GTJA191',),
            available_at_rule='same-close observed inputs; synchronous cross section')

    def parameters(self, supplied):
        if supplied:
            raise ValueError('Frozen GTJA191 formula accepts no parameters')
        return {}

    def compute(self, bars, parameters):
        self.parameters(parameters)
        if bars.filter(pl.col('available_at') != pl.col('datetime')).height:
            raise ValueError('GTJA191 cross sections require inputs available at bar close')
        data = bars.sort('symbol', 'datetime')
        if self.need & {'vwap', 'amount'} and data.filter((pl.col('volume') < 0) | pl.col('turnover').is_null()).height:
            raise ValueError('GTJA191 amount/vwap need non-null turnover and non-negative volume')
        if 'vwap' in self.need and data.filter((pl.col('adj_factor') <= 0) | ~pl.col('adj_factor').is_finite() | pl.col('adj_factor').is_null()).height:
            raise ValueError('VWAP needs valid price adjustment factors')
        panel = data.select(pl.col('symbol').alias('stock_code'), pl.col('datetime').alias('trade_date'),
                            *[pl.col(c) for c in _CORE if c in data.columns],
                            *([pl.col('turnover').alias('amount')] if 'amount' in self.need else []),
                            *([pl.when(pl.col('volume') > 0).then(pl.col('turnover') / pl.col('volume') * pl.col('adj_factor')).otherwise(None).alias('vwap')] if 'vwap' in self.need else []))
        if 'returns' in self.need:
            panel = panel.with_columns((pl.col('close') / pl.col('close').shift(1).over('stock_code') - 1.0).alias('returns'))
        values = self.entry.impl(panel).cast(pl.Float64)
        computed = pl.DataFrame({'symbol': data['symbol'], 'datetime': data['datetime'],
                                 'value': pl.Series(values).to_list()}, schema={'symbol': pl.Utf8, 'datetime': data.schema['datetime'], 'value': pl.Float64})
        computed = computed.with_columns(pl.when(pl.col('value').is_finite()).then(pl.col('value')).otherwise(None).alias('value'))
        return bars.select('symbol', 'datetime', 'available_at').join(computed, on=['symbol', 'datetime'], validate='1:1')


def gtja_pack():
    registry = _registry()
    return FactorPack('GTJA191Pack', '1.0.0', tuple(GtjaFormula(key, entry) for key, entry in sorted(registry.items()) if key not in UNSUPPORTED))
