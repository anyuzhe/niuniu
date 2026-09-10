"""Versioned OHLC order-block proxy; not evidence of institutional orders."""
import polars as pl
from dataclasses import asdict
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event,FactorType,Timeframe
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.factors.ict import ICTComponent
from quantlab.storage.codec import digest


class OrderBlockComponent(ComputedFactor):
    def __init__(self,component,direction):
        self.component=component;self.direction=direction;suffix='UP' if direction==1 else 'DOWN'
        self.definition=FactorDefinition('ICT.OB_'+component.upper()+'_'+suffix,'1.0.0','ICT OB '+component+' '+suffix,'zone',FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            '同根已确认 BOS 与 ATR 实体位移，选择此前最近反向实体 K 线全高低区间；后续首次接触、收盘越远端失效及按证券 K 线数超时。',
            'OHLC_OB_lifecycle_v1; no inferred institutional order flow',source_theory=('ICT','SMC'))
    def parameters(self,supplied):
        extras={'search_bars':10,'max_age_bars':100}
        p=ICTComponent('displacement',self.direction).parameters({k:v for k,v in supplied.items() if k not in extras})
        for key,default in extras.items():
            value=supplied.get(key,default)
            if type(value) is not int or not 1<=value<=100000:raise ValueError('OB search/age windows must be positive integers <=100000')
            p[key]=value
        return p
    def trace(self,bars,parameters):
        p=self.parameters(parameters);bars=ordered_bars(bars);direction=self.direction;suffix='UP' if direction==1 else 'DOWN'
        _,_,base_events=ICTComponent('displacement',direction).trace(bars,{k:v for k,v in p.items() if k not in ('search_bars','max_age_bars')})
        displacement={(e.symbol,e.available_at):e for e in base_events if e.factor_id=='ICT.DISPLACEMENT_'+suffix}
        breaks={(e.symbol,e.available_at):e for e in base_events if e.factor_id=='SMC.BOS_'+suffix}
        events=[]
        def emit(component,row,zone):
            fid='ICT.OB_'+component.upper()+'_'+suffix
            metadata={**zone,'parameters':p,'status':component}
            identity={'factor_id':fid,'zone_id':zone['zone_id'],'at':row['available_at']}
            events.append(Event(digest(identity),fid,row['symbol'],Timeframe(row['timeframe']),row['datetime'],row['available_at'],direction=direction,metadata=metadata))
        for _,group in bars.group_by('symbol',maintain_order=True):
            history=[];zones=[];used=set()
            for index,row in enumerate(group.iter_rows(named=True)):
                live=[]
                for zone in zones:
                    # Strict expiry first, then close invalidation, then first touch.
                    if index-zone['created_index']>p['max_age_bars']:emit('expired',row,zone);continue
                    invalid=row['close']<zone['lower'] if direction==1 else row['close']>zone['upper']
                    if invalid:emit('invalidated',row,zone);continue
                    if not zone['touched'] and row['low']<=zone['upper'] and row['high']>=zone['lower']:
                        zone={**zone,'touched':True};emit('touched',row,zone)
                    live.append(zone)
                zones=live;key=(row['symbol'],row['available_at'])
                if key in displacement and key in breaks:
                    anchor=next((r for r in reversed(history[-p['search_bars']:]) if direction*(r['close']-r['open'])<0),None)
                    if anchor and anchor['datetime'] not in used and (row['close']>anchor['high'] if direction==1 else row['close']<anchor['low']):
                        # Reject anchors whose distal edge was already broken by an intervening close.
                        intervening=[r for r in history if r['datetime']>anchor['datetime']]
                        if not any(r['close']<anchor['low'] if direction==1 else r['close']>anchor['high'] for r in intervening):
                            zone={'zone_id':digest({'symbol':row['symbol'],'timeframe':row['timeframe'],'anchor':anchor['datetime'],'created_at':row['available_at'],'direction':direction,'parameters':p}),
                                'anchor_at':anchor['datetime'],'lower':anchor['low'],'upper':anchor['high'],'created_at':row['available_at'],
                                'created_index':index,'touched':False,'bos_event_id':breaks[key].event_id,
                                'confirmation':{'bos':asdict(breaks[key]),'displacement':asdict(displacement[key])}}
                            zones.append(zone);used.add(anchor['datetime']);emit('created',row,zone)
                history.append(row);history=history[-p['search_bars']:]
        known={(e.symbol,e.available_at) for e in events if e.factor_id==self.definition.factor_id}
        values=bars.select('symbol','datetime','available_at').with_columns(pl.Series('value',[float((r['symbol'],r['available_at']) in known) for r in bars.iter_rows(named=True)]))
        return values,[],sorted(events,key=lambda e:(e.available_at,e.symbol,e.event_id))
    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]


def order_block_pack():
    return FactorPack('ICTOrderBlockPack','1.0.0',tuple(OrderBlockComponent(c,d) for d in (1,-1) for c in ('created','touched','invalidated','expired')),('ICTBasePack',))
