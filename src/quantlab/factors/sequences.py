from datetime import timedelta
from copy import deepcopy
from quantlab.sequence.specification import normalize_steps, sequence_scopes

import polars as pl

from quantlab.domain import FactorType, Timeframe
from quantlab.events.breakout import BreakoutHighEngine
from quantlab.events.failed_breakout import FailedBreakoutEngine
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.builtin import lookback_parameters
from quantlab.factors.registry import FactorPack
from quantlab.sequence.engine import EventSelector, OrderedSequenceEngine, SequenceDefinition


class RepeatedBreakout(ComputedFactor):
    definition = FactorDefinition(
        "SEQ.REPEATED_BREAKOUT", "1.0.0", "限时两次前高突破", "sequence", FactorType.BOOLEAN,
        ("high", "close"), tuple(Timeframe),
        "两次前高突破在不同时刻发生，间隔严格小于 max_gap_seconds；不重叠配对，仅完成当根触发",
        "BreakoutHigh -> BreakoutHigh within elapsed-time window",
        available_at_rule="second breakout availability",
    )

    def parameters(self, supplied):
        if set(supplied) - {"lookback", "max_gap_seconds"}:
            raise ValueError("RepeatedBreakout accepts lookback and max_gap_seconds")
        params = lookback_parameters({"lookback": supplied.get("lookback", 20)})
        seconds = supplied.get("max_gap_seconds", 172800)
        if type(seconds) is not int or not 0 < seconds <= 31536000:
            raise ValueError("max_gap_seconds must be an integer in [1, 31536000]")
        return {**params, "max_gap_seconds": seconds}

    def trace(self, bars, parameters):
        params = self.parameters(parameters)
        detector = BreakoutHighEngine(params["lookback"])
        flags = detector.flags(bars)
        events = detector.detect(bars)
        selector = EventSelector("EVT.BREAKOUT_HIGH", direction=1)
        definition = SequenceDefinition(self.definition.factor_id, (selector, selector), timedelta(seconds=params["max_gap_seconds"]))
        matches = OrderedSequenceEngine(definition).advance(events, flags["available_at"].max())
        completed = {(m.symbol, m.available_at) for m in matches if m.status == "completed"}
        values = flags.select("symbol", "datetime", "available_at").with_columns(pl.Series("value", [
            None if row["level"] is None else float((row["symbol"], row["available_at"]) in completed)
            for row in flags.iter_rows(named=True)
        ], dtype=pl.Float64))
        return values, matches, events

    def compute(self, bars, parameters):
        return self.trace(bars, parameters)[0]


class FailedLowThenBreakout(ComputedFactor):
    definition = FactorDefinition('SEQ.FAILED_LOW_THEN_BREAKOUT','1.0.0','前低突破失败后向上确认','sequence',FactorType.BOOLEAN,
        ('high','low','close'),tuple(Timeframe),
        '前低突破失败后限时出现前高收盘突破；等待中前高突破失败优先取消，仅完成当根触发，不重叠配对',
        'FailedBreakoutLow -> BreakoutHigh; cancel on FailedBreakoutHigh',
        available_at_rule='completion breakout availability; never backdate to failed low')

    def parameters(self, supplied):
        return RepeatedBreakout().parameters(supplied)

    def trace(self, bars, parameters):
        params = self.parameters(parameters)
        detector = FailedBreakoutEngine(params['lookback'])
        flags = detector.flags(bars)
        if flags.select(pl.struct('symbol','available_at').is_duplicated().any()).item():
            raise ValueError('Sequence factor requires unique symbol/available_at keys')
        events = detector.detect(bars) + BreakoutHighEngine(params['lookback']).detect(bars)
        definition = SequenceDefinition(self.definition.factor_id,
            (EventSelector('EVT.FAILED_BREAKOUT_LOW',direction=1),EventSelector('EVT.BREAKOUT_HIGH',direction=1)),
            timedelta(seconds=params['max_gap_seconds']),
            invalidators=(EventSelector('EVT.FAILED_BREAKOUT_HIGH',direction=-1),))
        matches = OrderedSequenceEngine(definition).advance(events,flags['available_at'].max())
        completed = {(m.symbol,m.available_at) for m in matches if m.status=='completed'}
        values = flags.select('symbol','datetime','available_at').with_columns(pl.Series('value',[
            None if row['prior_high'] is None else float((row['symbol'],row['available_at']) in completed)
            for row in flags.iter_rows(named=True)],dtype=pl.Float64))
        return values, matches, events

    def analyze(self, bars, parameters):
        return self.trace(bars, parameters)[:2]

    def compute(self, bars, parameters):
        return self.analyze(bars,parameters)[0]


def sequence_pack() -> FactorPack:
    return FactorPack("SequenceBasePack", "1.2.0", (RepeatedBreakout(), FailedLowThenBreakout(), CustomOrderedSequence()), ("TechnicalBasePack",))


class CustomOrderedSequence(ComputedFactor):
    """Editable ordered sequence over existing confirmed breakout event detectors."""
    SOURCES = ('EVT.BREAKOUT_HIGH','EVT.FAILED_BREAKOUT_LOW','EVT.FAILED_BREAKOUT_HIGH')
    definition = FactorDefinition('SEQ.CUSTOM_ORDERED','1.0.0','自定义有序事件序列','sequence',FactorType.BOOLEAN,
        ('high','low','close'),tuple(Timeframe),
        '有序事件在不同时刻推进；每步间隔严格小于超时值；失效事件优先；不重叠配对，仅完成当根输出 1。',
        'Ordered confirmed events; invalidation before transition',available_at_rule='completion event availability')

    def parameters(self,supplied):
        if set(supplied)-{'lookback','max_gap_seconds','steps','invalidators','step_timeframes'}:raise ValueError('Unknown sequence parameters')
        base=RepeatedBreakout().parameters({k:v for k,v in supplied.items() if k in ('lookback','max_gap_seconds')})
        steps=supplied.get('steps',['EVT.FAILED_BREAKOUT_LOW','EVT.BREAKOUT_HIGH'])
        invalidators=supplied.get('invalidators',['EVT.FAILED_BREAKOUT_HIGH'])
        flat,optional=normalize_steps(steps,self.SOURCES)
        sequence_scopes(steps)
        for values in (invalidators,):
            if not isinstance(values,list) or any(not isinstance(v,str) or v not in self.SOURCES for v in values):raise ValueError('Sequence source must be a supported confirmed event')
        if len(invalidators)!=len(set(invalidators)):raise ValueError('Duplicate invalidator')
        if set(flat)&set(invalidators):raise ValueError('A step cannot also invalidate the sequence')
        timeframes=supplied.get('step_timeframes')
        if timeframes is not None:
            if not isinstance(timeframes,list) or len(timeframes)!=len(flat):raise ValueError('Explicit timeframe required for each expanded step')
            for value in timeframes:Timeframe(value)
        return {**base,'steps':deepcopy(steps),'invalidators':list(invalidators),**({'step_timeframes':list(timeframes)} if timeframes is not None else {})}

    def trace(self,bars,parameters):
        params=self.parameters(parameters);detector=FailedBreakoutEngine(params['lookback']);flags=detector.flags(bars)
        if flags.select(pl.struct('symbol','available_at').is_duplicated().any()).item():raise ValueError('Sequence requires unique symbol/available_at keys')
        events=detector.detect(bars)+BreakoutHighEngine(params['lookback']).detect(bars)
        step_timeframes=tuple(Timeframe(v) for v in params.get('step_timeframes',[]))
        if step_timeframes:
            from quantlab.multitimeframe.resample import resample_bars
            base_timeframe=Timeframe(bars['timeframe'][0])
            for timeframe in sorted(set(step_timeframes)-{base_timeframe},key=lambda t:t.minutes):
                if timeframe.minutes<base_timeframe.minutes:raise ValueError('Sequence cannot manufacture lower-timeframe data')
                higher=resample_bars(bars,timeframe,require_all=False)
                if higher.is_empty():continue
                events+=FailedBreakoutEngine(params['lookback']).detect(higher)+BreakoutHighEngine(params['lookback']).detect(higher)
        flat,optional=normalize_steps(params['steps'],self.SOURCES)
        definition=SequenceDefinition(self.definition.factor_id,tuple(EventSelector(v) for v in flat),
            timedelta(seconds=params['max_gap_seconds']),tuple(EventSelector(v) for v in params['invalidators']),optional_steps=optional,scopes=sequence_scopes(params['steps']),step_timeframes=step_timeframes)
        matches=OrderedSequenceEngine(definition).advance(events,flags['available_at'].max()) if flags.height else []
        completed={(m.symbol,m.available_at) for m in matches if m.status=='completed'}
        values=flags.select('symbol','datetime','available_at').with_columns(pl.Series('value',[
            None if r['prior_high'] is None else float((r['symbol'],r['available_at']) in completed)
            for r in flags.iter_rows(named=True)],dtype=pl.Float64))
        return values,matches,events

    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]
