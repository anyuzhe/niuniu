"""Frozen-band EQH/EQL OHLC proxies with causal, resumable lifecycles."""
from copy import deepcopy
import math
import polars as pl
from quantlab.domain import Event, SequenceMatch, FactorType, Timeframe
from quantlab.data.validation import ordered_bars
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.storage.codec import digest

PROFILE='equal_extreme_pool_v1'
EVENTS=('created','strengthened','touched','swept','reclaimed','invalidated','expired')
COMPONENTS=(*EVENTS,'active_count','lower_price','upper_price')
DEFAULTS=dict(left=2,right=2,tolerance_bps=10.,absolute_tolerance=0.,
    min_separation=2,min_touches=2,formation_bars=200,max_age_bars=100)


def parameters(supplied):
    if set(supplied)-set(DEFAULTS): raise ValueError('Unknown liquidity pool parameter')
    p={**DEFAULTS,**supplied}
    for key in ('left','right','min_separation','min_touches','formation_bars','max_age_bars'):
        if type(p[key]) is not int or not 1<=p[key]<=100000: raise ValueError('Invalid pool integer '+key)
    if p['min_touches']<2: raise ValueError('A pool needs at least two confirmed pivots')
    for key in ('tolerance_bps','absolute_tolerance'):
        if type(p[key]) not in (int,float) or not math.isfinite(p[key]) or p[key]<0: raise ValueError('Invalid pool tolerance')
    if p['tolerance_bps']>1000: raise ValueError('Pool relative tolerance must not exceed 1000 bps')
    return p


class LiquidityPoolState:
    def __init__(self,symbol,timeframe,p,direction):
        if direction not in (1,-1): raise ValueError('Invalid pool direction')
        self.symbol=symbol;self.timeframe=timeframe;self.p=parameters(p);self.d=direction
        self.rows=[];self.values=[];self.pending=[];self.pools=[]
        self.events=[];self.transitions=[];self.flags=[]
    @property
    def processed(self): return len(self.values)
    @property
    def prefix(self): return 'ICT.EQH' if self.d==1 else 'ICT.EQL'
    def dump(self): return self.__dict__
    def restore(self,value):
        if set(value)!=set(self.__dict__): raise ValueError('Invalid pool state fields')
        if any(value[k]!=getattr(self,k) for k in ('symbol','timeframe','p','d')):
            raise ValueError('Pool state identity changed')
        if len(value['rows'])!=len(value['values']): raise ValueError('Pool state lengths differ')
        self.__dict__.update(value)
    def bounds(self,pool):
        return sorted((self.d*pool['lower_price'],self.d*pool['upper_price']))
    def emit(self,name,row,pool):
        self.flags.append(name)
        event_id=digest(dict(profile=PROFILE,pool=pool['id'],event=name,
            at=row['available_at'],anchors=len(pool['anchors']),touches=pool['touch_count']))
        evidence=deepcopy({k:v for k,v in pool.items() if k!='event_ids'})
        event=Event(event_id,self.prefix+'_'+name.upper(),self.symbol,Timeframe(self.timeframe),
            row['datetime'],row['available_at'],direction=-self.d,metadata={'pool':evidence,'profile':PROFILE,'parameters':self.p,'event_index':len(self.events)})
        self.events.append(event);pool['event_ids'].append(event_id)
        terminal={'reclaimed':'completed','invalidated':'invalidated','expired':'timeout'}
        self.transitions.append(SequenceMatch(self.prefix+'_RECLAIMED','1.0.0',self.symbol,
            tuple(pool['event_ids']),pool['anchors'][0]['occurred_at'],row['available_at'],
            terminal.get(name,'active'),pool['id'],Timeframe(self.timeframe),
            event_id if name=='invalidated' else None))
    def advance_pools(self,row,i,high,low,close):
        live=[]
        for pool in self.pools:
            lower,upper=self.bounds(pool)
            if i-pool['created_index']>self.p['max_age_bars']:
                pool['status']='expired';self.emit('expired',row,pool);continue
            if close>upper:
                pool['status']='invalidated';self.emit('invalidated',row,pool);continue
            if pool['status']=='swept':
                if i>pool['sweep_index'] and close<lower:
                    pool['status']='reclaimed';self.emit('reclaimed',row,pool);continue
            elif high>upper:
                pool.update(status='swept',sweep_index=i);self.emit('swept',row,pool)
            else:
                contact=low<=upper and high>=lower
                if contact and not pool['in_contact']:
                    pool['touch_count']+=1;self.emit('touched',row,pool)
                pool['in_contact']=contact
            live.append(pool)
        self.pools=live
    def confirm_pivot(self,row,index):
        p=self.p; pivot_index=index-p['right']
        if pivot_index<p['left']: return
        def height(bar): return self.d*(bar['high'] if self.d==1 else bar['low'])
        pivot=self.rows[pivot_index]; level=height(pivot)
        neighbors=self.rows[pivot_index-p['left']:pivot_index]+self.rows[pivot_index+1:index+1]
        if any(height(bar)>=level for bar in neighbors): return
        price=self.d*level
        anchor={'index':pivot_index,'price':price,'occurred_at':pivot['datetime'],
            'available_at':row['available_at']}
        live=[pool for pool in self.pools if pool['status']=='active'
            and pool['lower_price']<=price<=pool['upper_price']]
        if live:
            pool=min(live,key=lambda value:(abs(value['level']-price),value['created_index']))
            if pivot_index-pool['anchors'][-1]['index']>=p['min_separation']:
                pool['anchors'].append(anchor);self.emit('strengthened',row,pool)
            return
        matches=[item for item in self.pending if item['lower_price']<=price<=item['upper_price']]
        if matches:
            candidate=min(matches,key=lambda value:(abs(value['level']-price),value['first_index']))
            if pivot_index-candidate['anchors'][-1]['index']<p['min_separation']: return
            candidate['anchors'].append(anchor)
        else:
            tolerance=max(abs(price)*p['tolerance_bps']/10000,p['absolute_tolerance'])
            candidate={'level':price,'lower_price':price-tolerance,'upper_price':price+tolerance,
                'first_index':pivot_index,'anchors':[anchor]}
            if any(height(bar)>self.bounds(candidate)[1] for bar in self.rows[pivot_index+1:index+1]): return
            self.pending.append(candidate)
        if len(candidate['anchors'])<p['min_touches']: return
        self.pending.remove(candidate)
        pool={**candidate,'id':digest({'profile':PROFILE,'symbol':self.symbol,
            'timeframe':self.timeframe,'direction':self.d,'parameters':p,'anchors':candidate['anchors']}),
            'created_index':index,'created_at':row['available_at'],'status':'active',
            'touch_count':0,'in_contact':False,'event_ids':[]}
        self.pools.append(pool);self.emit('created',row,pool)
    def extend(self,bars):
        if set(bars['symbol'])!={self.symbol} or set(bars['timeframe'])!={self.timeframe}:
            raise ValueError('Pool continuation symbol/timeframe mismatch')
        for row in bars.iter_rows(named=True):
            if self.rows and row['datetime']<=self.rows[-1]['datetime']:
                raise ValueError('Pool continuation requires strictly later bars')
            index=len(self.rows)
            if index%128==0:
                from quantlab.progress import checkpoint
                checkpoint()
            self.rows.append(row);self.flags=[]
            high,low=(row['high'],row['low']) if self.d==1 else (-row['low'],-row['high'])
            self.advance_pools(row,index,high,low,self.d*row['close'])
            self.pending=[item for item in self.pending if index-item['first_index']<=self.p['formation_bars']
                and high<=self.bounds(item)[1]]
            self.confirm_pivot(row,index)
            newest=max(self.pools,key=lambda item:item['created_index']) if self.pools else None
            values={name:float(name in self.flags) for name in EVENTS}
            values.update(active_count=float(len(self.pools)),
                lower_price=newest['lower_price'] if newest else None,
                upper_price=newest['upper_price'] if newest else None)
            self.values.append(values)
    def result(self):
        from zoneinfo import ZoneInfo
        keys=['symbol','datetime','available_at']
        rows=[{**{k:row[k] for k in keys},**value} for row,value in zip(self.rows,self.values)]
        for row in rows:
            for key in ('datetime','available_at'):row[key]=row[key].astimezone(ZoneInfo('Asia/Shanghai'))
        frame=pl.DataFrame(rows,schema_overrides={name:pl.Float64 for name in COMPONENTS})
        return frame,self.transitions,self.events


class LiquidityPoolFactor(ComputedFactor):
    caches_structures=True
    def __init__(self,component,direction,cache=None):
        if component not in COMPONENTS or direction not in (1,-1): raise ValueError('Invalid pool component')
        self.component=component;self.direction=direction;self._cache=cache if cache is not None else [None]
        prefix='ICT.EQH' if direction==1 else 'ICT.EQL';label='等高' if direction==1 else '等低'
        names={'created':'建立','strengthened':'增强','touched':'接触','swept':'扫出',
            'reclaimed':'扫出后回收','invalidated':'突破失效','expired':'超时','active_count':'活跃数量',
            'lower_price':'最近池下沿','upper_price':'最近池上沿'}
        self.definition=FactorDefinition(prefix+'_'+component.upper(),'1.0.0',label+'流动性池 · '+names[component],
            'zone',FactorType.BOOLEAN if component in EVENTS else FactorType.SCALAR,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            '严格确认极值、冻结容差带、多点建立、接触、扫出、后续回收、突破失效与超时；只是价格形态代理，不推断真实挂单。',
            PROFILE,source_theory=('ICT','SMC'))
    def parameters(self,supplied): return parameters(supplied)
    def matrix(self,bars,supplied):
        p=parameters(supplied);bars=ordered_bars(bars)
        if bars.select(pl.struct('symbol','available_at').is_duplicated().any()).item():
            raise ValueError('Pool requires unique symbol/information timestamps')
        old=self._cache[0]
        if old is not None and old[0]==p and old[1].equals(bars): return old[2]
        values=[];transitions=[];events=[]
        for _,group in bars.group_by('symbol',maintain_order=True):
            factory=lambda:LiquidityPoolState(group['symbol'][0],group['timeframe'][0],p,self.direction)
            cache=getattr(self,'_persistent_cache',None)
            if cache is not None:
                from quantlab.factors.continuation import compute_recursive
                matrix,ts,es=compute_recursive(cache,{'profile':PROFILE,'parameters':p,'direction':self.direction},group,factory)
            else:
                state=factory();state.extend(group);matrix,ts,es=state.result()
            matrix=matrix.with_columns(*[pl.col(k).cast(group.schema[k]) for k in ('datetime','available_at')])
            values.append(matrix);transitions.extend(ts);events.extend(es)
        result=pl.concat(values),transitions,events
        self._cache[0]=(p,bars.clone(),result)
        return result
    def trace(self,bars,parameters):
        matrix,transitions,events=self.matrix(bars,parameters)
        return matrix.select('symbol','datetime','available_at',pl.col(self.component).alias('value')),transitions,events
    def compute(self,bars,parameters): return self.trace(bars,parameters)[0]


def liquidity_pool_pack():
    caches={1:[None],-1:[None]}
    return FactorPack('EqualExtremeLiquidityPoolPack','1.0.0',
        tuple(LiquidityPoolFactor(c,d,caches[d]) for d in (1,-1) for c in COMPONENTS))
