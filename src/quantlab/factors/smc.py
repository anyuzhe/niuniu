import polars as pl
from quantlab.domain import FactorType, Timeframe
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.structure.breaks import ConfirmedSwingBreakEngine


class SwingBreakUp(ComputedFactor):
    side='up'
    definition=FactorDefinition('SMC.BOS_UP','1.0.0','已确认摆动高点向上突破','structure',FactorType.BOOLEAN,
        ('open','high','low','close','volume','turnover'),tuple(Timeframe),
        '严格左右拐点确认后，收盘首次从不高于该高点变为高于；每个拐点仅触发一次；等高不触发。此为明确规则的 SMC 基础变体。',
        'confirmed pivot high AND previous_close <= level < close',source_theory=('SMC',))
    def parameters(self,supplied):
        if set(supplied)-{'left','right'}:raise ValueError('Only left/right are supported')
        params={'left':supplied.get('left',2),'right':supplied.get('right',2)}
        ConfirmedSwingBreakEngine(**params)
        return params
    def compute(self,bars,parameters):
        values,_=ConfirmedSwingBreakEngine(**parameters).analyze(bars)
        return values.select('symbol','datetime','available_at',pl.col(self.side).alias('value'))


class SwingBreakDown(SwingBreakUp):
    side='down'
    definition=FactorDefinition('SMC.BOS_DOWN','1.0.0','已确认摆动低点向下突破','structure',FactorType.BOOLEAN,
        ('open','high','low','close','volume','turnover'),tuple(Timeframe),
        '严格左右拐点确认后，收盘首次从不低于该低点变为低于；每个拐点仅触发一次；等低不触发。',
        'confirmed pivot low AND previous_close >= level > close',source_theory=('SMC',))


def smc_pack():
    return FactorPack('SMCBasePack','1.0.0',(SwingBreakUp(),SwingBreakDown()),('TechnicalBasePack',))
