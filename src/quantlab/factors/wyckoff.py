"""Frozen prior-range OHLC variant, not discretionary accumulation phases."""
import math
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event, FactorType, Timeframe
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.storage.codec import digest


class WyckoffComponent(ComputedFactor):
    def __init__(self, component):
        self.component = component
        self.definition = FactorDefinition('WYCKOFF.'+component.upper(), '1.0.0',
            'Wyckoff '+component, 'event', FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'), tuple(Timeframe),
            '冻结前区间的 OHLC 变体：扫出收回后，缩量且不破极值的 Test，再收盘突破冻结区间；不同 K 线确认。',
            'prior range -> excursion/reclaim -> lower-volume test -> close break', source_theory=('Wyckoff',))

    def parameters(self, supplied):
        defaults = {'lookback':20, 'max_width':.15, 'max_bars':40, 'test_fraction':.25}
        if set(supplied)-set(defaults): raise ValueError('Unknown Wyckoff parameter')
        p = {**defaults, **supplied}
        for k in ('lookback','max_bars'):
            if type(p[k]) is not int or p[k]<2: raise ValueError('Wyckoff windows must be integers >= 2')
        for k in ('max_width','test_fraction'):
            if type(p[k]) not in (float,int) or not math.isfinite(p[k]) or not 0<p[k]<=1:
                raise ValueError('Wyckoff fractions must be in (0,1]')
        return p

    def trace(self, bars, parameters):
        p=self.parameters(parameters); bars=ordered_bars(bars); output=[]; events=[]
        for _, group in bars.group_by('symbol',maintain_order=True):
            rows=group.to_dicts(); active=None
            for i,row in enumerate(rows):
                flags=set(); metadata={}
                if i>=p['lookback']:
                    prior=rows[i-p['lookback']:i]; lo=min(r['low'] for r in prior); hi=max(r['high'] for r in prior)
                    compact=hi>lo and (hi-lo)/lo<=p['max_width']
                    if compact: flags.add('range')
                    if active is not None:
                        a=active; direction=a['direction']; width=a['high']-a['low']
                        invalid=(row['low']<a['extreme'] if direction==1 else row['high']>a['extreme'])
                        if i-a['index']>p['max_bars'] or invalid:
                            flags.add('invalidated'); metadata=dict(a); active=None
                        elif not a['tested']:
                            test=(row['low']<=a['low']+width*p['test_fraction'] and row['close']>=a['low']) if direction==1 else \
                                (row['high']>=a['high']-width*p['test_fraction'] and row['close']<=a['high'])
                            if test and row['volume']<a['volume']:
                                flags.add('test_up' if direction==1 else 'test_down'); a['tested']=True; metadata=dict(a)
                        elif (row['close']>a['high'] if direction==1 else row['close']<a['low']):
                            flags.add('sos' if direction==1 else 'sow'); metadata=dict(a); active=None
                    elif compact:
                        spring=row['low']<lo and lo<=row['close']<=hi
                        upthrust=row['high']>hi and lo<=row['close']<=hi
                        # An outside bar has ambiguous direction; do not infer its path.
                        if spring != upthrust:
                            direction=1 if spring else -1
                            active={'direction':direction,'low':lo,'high':hi,'extreme':row['low'] if spring else row['high'],
                                'volume':row['volume'],'index':i,'tested':False,'origin_at':row['available_at']}
                            metadata=dict(active); flags.add('spring' if spring else 'upthrust')
                    for flag in sorted(flags):
                        identity={'factor':'WYCKOFF.'+flag.upper(),'symbol':row['symbol'],'at':row['available_at'],
                            'timeframe':row['timeframe'],'parameters':p,'version':'1.0.0'}
                        events.append(Event(digest(identity),identity['factor'],row['symbol'],Timeframe(row['timeframe']),
                            row['datetime'],row['available_at'],direction=metadata.get('direction',0),metadata={**metadata,'parameters':p}))
                output.append({k:row[k] for k in ('symbol','datetime','available_at')} | {'value':None if i<p['lookback'] else float(self.component in flags)})
        return pl.DataFrame(output).with_columns(pl.col('value').cast(pl.Float64)), [], events

    def compute(self,bars,parameters): return self.trace(bars,parameters)[0]


def wyckoff_pack():
    return FactorPack('WyckoffBasePack','1.0.0',tuple(WyckoffComponent(c) for c in
        ('range','spring','upthrust','test_up','test_down','sos','sow')))
