"""Frozen vn.py formula packs; no dataset training or upstream future labels."""
import ast
import json
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
import polars as pl
from quantlab.domain import FactorType,Timeframe
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.registry import FactorPack

@lru_cache(maxsize=1)
def formulas():
    return json.loads(Path(__file__).with_name('alpha_expressions.json').read_text())['packs']

class AlphaFormula(ComputedFactor):
    def __init__(self,pack,name,expression):
        self.pack=pack;self.name=name;self.expression=expression
        fields=tuple(sorted({n.id for n in ast.walk(ast.parse(expression)) if isinstance(n,ast.Name)} & {'open','high','low','close','volume','vwap'}))
        required=tuple(v for v in fields if v!='vwap')+(('volume','turnover','adj_factor') if 'vwap' in fields else ())
        self.definition=FactorDefinition(f'{pack.upper()}.{name.upper()}','1.0.0',f'{pack} · {name}',
            'quant',FactorType.SCALAR,tuple(dict.fromkeys(required)),tuple(Timeframe),
            '固定 vn.py 4.4.0 公式；不训练模型、不使用上游未来标签。截面排名基于本次传入股票；VWAP 按成交额/成交量×复权因子。非有限结果置空。',
            expression,source_theory=(pack,),available_at_rule='same-close observed inputs; synchronous cross section')
    def parameters(self,supplied):
        if supplied:raise ValueError('Frozen Alpha formula accepts no parameters')
        return {}
    def compute(self,bars,parameters):
        self.parameters(parameters)
        if version('vnpy')!='4.4.0':raise ValueError('Alpha formula adapter requires vnpy==4.4.0')
        from vnpy.alpha.dataset.utility import calculate_by_expression
        if bars.filter(pl.col('available_at')!=pl.col('datetime')).height:
            raise ValueError('Alpha cross sections require inputs available at bar close')
        data=bars.sort('symbol','datetime')
        if 'vwap' in self.expression:
            if data.filter((pl.col('adj_factor')<=0)|~pl.col('adj_factor').is_finite()|pl.col('adj_factor').is_null()).height:
                raise ValueError('VWAP needs valid price adjustment factors')
            data=data.with_columns(pl.when(pl.col('volume')>0).then(pl.col('turnover')/pl.col('volume')*pl.col('adj_factor')).otherwise(None).alias('vwap'))
        data=data.rename({'symbol':'vt_symbol'}).select('datetime','vt_symbol',*[c for c in ('open','high','low','close','volume','vwap') if c in data.columns])
        # expression is loaded only from our versioned package, never user text.
        computed=calculate_by_expression(data,self.expression)
        value=next(c for c in computed.columns if c not in ('datetime','vt_symbol'))
        computed=computed.select(pl.col('vt_symbol').alias('symbol'),'datetime',
            pl.when(pl.col(value).cast(pl.Float64).is_finite()).then(pl.col(value).cast(pl.Float64)).otherwise(None).alias('value'))
        return bars.select('symbol','datetime','available_at').join(computed,on=['symbol','datetime'],validate='1:1')

def alpha_packs():
    return tuple(FactorPack(name+'Pack','1.0.0',tuple(AlphaFormula(name,key,expr) for key,expr in entries.items())) for name,entries in formulas().items())
