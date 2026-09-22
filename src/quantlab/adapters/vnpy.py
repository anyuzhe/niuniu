"""vn.py 4.4 Alpha matching adapter with an explicit open-only replay clock.

Uses upstream order matching, trade/position callbacks and cash accounting unchanged.
Does not use upstream full-bar replay (which may inspect the bar's final high/low).
"""
import math
import re
from dataclasses import asdict
from datetime import timedelta
from importlib.metadata import version
import polars as pl
from quantlab.data.validation import ordered_bars, suspension_state_aware


def validate_config(config):
    if config.rights_trading:raise ValueError('vnpy_open does not support transferable rights; use vnpy_rules')
    if config.max_volume_participation is not None:raise ValueError('Lagged-volume capacity requires vnpy_rules')
    if config.rights_issues:raise ValueError('Use vnpy_rules for rights subscriptions')
    if config.stock_splits:raise ValueError('Use vnpy_rules for stock splits')
    if config.corporate_actions:raise ValueError('Use vnpy_rules for cash dividends')
    if config.max_actual_sector is not None or config.industry_events is not None:raise ValueError('Industry risk requires vnpy_rules')
    if config.transfer_bps or config.statutory_fees or config.fee_decimals is not None or config.max_actual_position!=1 or config.max_actual_exposure!=1:
        raise ValueError('vnpy_open does not support enhanced cost/risk settings; use vnpy_rules')
    if config.minimum_commission!=0 or config.slippage_bps!=0 or config.limit_pct!=.1:
        raise ValueError('vnpy_open requires minimum_commission=0, slippage_bps=0, limit_pct=0.1; unsupported settings are not ignored')


def vt_symbol(symbol):
    if not re.fullmatch(r'(sh|sz)\.[0-9]{6}',symbol):raise ValueError('vn.py adapter requires sh./sz. six-digit symbols')
    exchange,code=symbol.split('.')
    return code+('.SSE' if exchange=='sh' else '.SZSE')


class VnpyOpenBacktester:
    def __init__(self,config):
        validate_config(config);self.config=config;self.diagnostics={}

    def run(self,targets,bars):
        # Optional imports only here. No GUI application, database or live gateway is created.
        if version('vnpy')!='4.4.0':raise ValueError('vnpy_open validated with vnpy==4.4.0 only')
        from vnpy.alpha.strategy.backtesting import BacktestingEngine
        from vnpy.alpha.strategy.template import AlphaStrategy
        from vnpy.trader.object import BarData
        from vnpy.trader.constant import Direction, Interval, Exchange
        cfg=self.config;bars=ordered_bars(bars);symbols=sorted(bars['symbol'].unique().to_list())
        if suspension_state_aware(bars) and bars.filter(pl.col('bs_trade_status')==0).height:
            raise ValueError('vnpy_open does not accept preserved suspension rows; use open or vnpy_rules so suspension is modeled explicitly')
        if bars['timeframe'][0] not in ('1d','1m','5m','15m','30m','60m') or bars.filter(pl.col('available_at')!=pl.col('datetime')).height:
            raise ValueError('vnpy_open requires immediate-close registered bars')
        for col in ('datetime','available_at'):
            if not isinstance(targets.schema[col],pl.Datetime) or targets.schema[col].time_zone is None:
                raise ValueError('Target timestamps require timezone')
        snapshots=[]
        for key,group in targets.sort('available_at','symbol').group_by('available_at',maintain_order=True):
            if group.height!=len(symbols) or set(group['symbol'])!=set(symbols):raise ValueError('Targets must be complete unique snapshots')
            if any(group[c].null_count() for c in ('symbol','datetime','available_at','weight')):raise ValueError('Null target')
            if group.filter((pl.col('datetime')>pl.col('available_at')) | ~pl.col('weight').is_finite() | (pl.col('weight')<0)).height or group['weight'].sum()>1+1e-12:
                raise ValueError('Invalid target weights or information times')
            snapshots.append((key[0],dict(zip(group['symbol'],group['weight']))))
        mapping={s:vt_symbol(s) for s in symbols}
        # Numerical grid, not a claim of historical A-share tick sizes.
        contracts={v:{'long_rate':cfg.commission_bps/10000,'short_rate':(cfg.commission_bps+cfg.sell_tax_bps)/10000,
            'size':1,'pricetick':1e-8} for v in mapping.values()}
        class Contracts:
            def load_contract_setttings(self):return contracts
        class TargetsStrategy(AlphaStrategy):
            def on_init(self):pass
            def on_bars(self,bars):pass
            def on_trade(self,trade):pass
        engine=BacktestingEngine(Contracts())
        engine.set_parameters(list(mapping.values()),Interval.DAILY if bars['timeframe'][0]=='1d' else Interval.MINUTE,
            bars['datetime'].min(),bars['datetime'].max(),capital=cfg.initial_cash)
        engine.add_strategy(TargetsStrategy,{},pl.DataFrame());engine.strategy.on_init()
        lots={s:[] for s in symbols};marks={};previous_close={};fills=[];rejections=[];nav=[]
        index=0;decision=None;weights={}
        def position(s):return engine.strategy.pos_data[mapping[s]]
        def bar_object(row,opening,open_only):
            price=row['open'];parts=mapping[row['symbol']].split('.')
            return BarData(symbol=parts[0],exchange=Exchange(parts[1]),datetime=opening,
                interval=engine.interval,open_price=price,high_price=price if open_only else row['high'],
                low_price=price if open_only else row['low'],close_price=price if open_only else row['close'],
                volume=0 if open_only else row['volume'],turnover=0 if open_only else row['turnover'],gateway_name='QUANTLAB_REPLAY')
        total_periods=bars['datetime'].n_unique()
        for period,(key,group) in enumerate(bars.sort('datetime','symbol').group_by('datetime',maintain_order=True)):
            if period % 25 == 0:
                from quantlab.progress import checkpoint
                checkpoint('vn.py 逐期撮合',period,total_periods)
            end=key[0];opening=end.replace(hour=9,minute=30,second=0,microsecond=0) if group['timeframe'][0]=='1d' else end-timedelta(minutes=int(group['timeframe'][0][:-1]))
            while index<len(snapshots) and snapshots[index][0]<=opening:
                decision,weights=snapshots[index];index+=1
            current=group.to_dicts();prices={r['symbol']:r['open'] for r in current}
            valuation={**marks,**prices};equity=engine.cash+sum(position(s)*valuation.get(s,0) for s in symbols)
            engine.datetime=opening
            engine.bars={mapping[r['symbol']]:bar_object(r,opening,True) for r in current}
            engine.pre_closes={mapping[s]:p for s,p in previous_close.items()}
            orders=[]
            if weights:
                for s,price in prices.items():
                    delta=math.floor(equity*weights[s]/price/cfg.lot_size)*cfg.lot_size-int(position(s))
                    if delta:orders.append((delta>0,s,delta,price))
            for buying,s,delta,price in sorted(orders):
                requested=abs(delta);size=requested;reason=None
                if not buying:
                    size=min(size,sum(q for day,q in lots[s] if not cfg.t_plus_one or day<opening.date()))
                    if size<requested:reason='t_plus_one'
                    proceeds=size*price*(1-(cfg.commission_bps+cfg.sell_tax_bps)/10000)
                    if engine.cash+proceeds<0:size=0;reason='cash_for_sell_fees'
                else:
                    affordable=math.floor(engine.cash/(price*(1+cfg.commission_bps/10000))/cfg.lot_size)*cfg.lot_size
                    size=min(size,max(0,affordable))
                    if size<requested:reason='cash_or_lot'
                matched=0
                if size:
                    # Tiny limit cushion only avoids numerical tick rounding; open-only
                    # matching still fills at the observed open, never a future bar price.
                    limit=price+2e-8 if buying else max(1e-8,price-2e-8)
                    ids=(engine.strategy.buy if buying else engine.strategy.sell)(mapping[s],limit,size)
                    before=engine.trade_count
                    engine.cross_order()
                    if engine.trade_count>before:
                        trade=next(reversed(engine.trades.values()));matched=int(trade.volume)
                        notional=trade.price*matched
                        fills.append({'symbol':s,'decision_at':decision,'filled_at':trade.datetime,'bar_end':end,
                            'side':'buy' if buying else 'sell','quantity':matched,'price':trade.price,
                            'commission':notional*cfg.commission_bps/10000,'tax':0. if buying else notional*cfg.sell_tax_bps/10000,
                            'slippage_cost':0.,'vnpy_trade_id':trade.vt_tradeid})
                        if buying:lots[s].append([opening.date(),matched])
                        else:
                            remaining=matched
                            for lot in lots[s]:
                                if cfg.t_plus_one and lot[0]>=opening.date():continue
                                used=min(remaining,lot[1]);lot[1]-=used;remaining-=used
                    else:reason='vnpy_price_limit_or_missing_previous_close'
                    for order_id in ids:engine.strategy.cancel_order(order_id)
                if matched<requested:rejections.append({'symbol':s,'at':opening,'side':'buy' if buying else 'sell',
                    'requested':requested,'filled':matched,'reason':reason})
                if engine.cash < -1e-7:raise ValueError('vn.py produced negative cash')
            for row in current:marks[row['symbol']]=row['close'];previous_close[row['symbol']]=row['close']
            value=sum(position(s)*marks.get(s,0) for s in symbols)
            nav.append({'datetime':end,'cash':engine.cash,'position_value':value,'equity':engine.cash+value})
            # Carry last known marks only for daily valuation; never submit these as fill bars.
            closing={}
            for s,mark in marks.items():
                code,exchange=mapping[s].split('.')
                closing[mapping[s]]=BarData(symbol=code,exchange=Exchange(exchange),datetime=end,
                    close_price=mark,gateway_name='QUANTLAB_VALUATION')
            engine.update_daily_close(closing,end)
        curve=pl.DataFrame(nav);peak=cfg.initial_cash;drawdown=0.
        for value in curve['equity']:peak=max(peak,value);drawdown=min(drawdown,value/peak-1)
        summary={'initial_cash':cfg.initial_cash,'final_equity':curve['equity'][-1],
            'net_return':curve['equity'][-1]/cfg.initial_cash-1,'max_drawdown':drawdown,'fills':len(fills),'rejections':len(rejections),
            'commission':sum(f['commission'] for f in fills),'sell_tax':sum(f['tax'] for f in fills),'slippage_cost':0.,
            'ending_positions':{s:int(position(s)) for s in symbols if position(s)},'unprocessed_target_snapshots':len(snapshots)-index}
        daily=engine.calculate_result()
        self.diagnostics={'vnpy_version':version('vnpy'),'dependencies':{name:version(name) for name in ('vnpy','alphalens-reloaded','numpy','pandas','ta-lib')},'engine':'vnpy.alpha.strategy.backtesting.BacktestingEngine',
            'driver':'open-only slices; native send_order/cross_order/update_trade/cash; not native full-bar new_bars',
            'pricetick':1e-8,'native_orders':[asdict(o) for o in engine.get_all_orders()],
            'native_daily_result':daily.to_dicts() if daily is not None else [],
            'daily_net_pnl_error':float(daily['net_pnl'].sum()-(summary['final_equity']-cfg.initial_cash)) if daily is not None else 0.,
            'limitations':'Native fixed 10% prior-close guard; no minimum fee/slippage. No live gateway. No synthetic fills on missing bars.'}
        from quantlab.execution.performance import performance_metrics
        summary.update(performance_metrics(curve, cfg.initial_cash))
        return curve,fills,rejections,summary


def compare_backends(reference,candidate,tolerance=1e-6):
    left,lf,_,ls=reference;right,rf,_,rs=candidate
    keys=('symbol','decision_at','filled_at','bar_end','side','quantity','price','commission','tax','slippage_cost','transfer_fee')
    normalized=lambda rows:[{k:r.get(k,0.) if k=='transfer_fee' else r[k] for k in keys} for r in rows]
    # Exact identities/quantities plus numerical tolerance on prices and cash.
    mismatches=[]
    for i in range(max(len(lf),len(rf))):
        a=normalized(lf[i:i+1]);b=normalized(rf[i:i+1])
        if not a or not b or any(abs(a[0][k]-b[0][k])>tolerance if isinstance(a[0][k],(int,float)) else a[0][k]!=b[0][k] for k in keys):
            mismatches.append({'index':i,'open':a,'vnpy':b})
    joined=left.join(right,on='datetime',how='full',suffix='_vnpy',coalesce=True)
    comparable=left.height==right.height==joined.height and not any(joined[c].null_count() for c in joined.columns)
    errors={c:(joined[c]-joined[c+'_vnpy']).abs().max() if comparable else None for c in ('cash','position_value','equity',*(['pending_stock_value'] if 'pending_stock_value' in left.columns and 'pending_stock_value' in right.columns else []))}
    matched=comparable and not mismatches and all(e<=tolerance for e in errors.values()) and ls['ending_positions']==rs['ending_positions'] and ls.get('pending_stock_positions',{})==rs.get('pending_stock_positions',{})
    return {'status':'matched' if matched else 'different','tolerance':tolerance,'maximum_errors':errors,
        'fill_mismatches':mismatches,'open_summary':ls,'vnpy_summary':rs,
        'scope':'Same saved targets/bars/config; fixed 10% guard rounding and missing previous quotes may differ. No claim of live equivalence.'}
