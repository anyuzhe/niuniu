"""Long-only target-weight simulation at the next observable bar open.

Open liquidity is assumed. Current bar high/low/close/volume never decide fills.
"""
import math
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.storage.codec import digest
from quantlab.data.industry import IndustryHistory
from quantlab.execution.corporate_actions import CashDividends, StockSplits, RightsIssues
from quantlab.execution.diagnostics import ExecutionAudit
from quantlab.execution.holding_tax import HoldingTax
from quantlab.execution.rights_trading import RightsTrading


@dataclass(frozen=True)
class ExecutionConfig:
    initial_cash: float = 1000000
    top_n: int = 5
    threshold: float = 0
    exposure: float = 1
    lot_size: int = 100
    t_plus_one: bool = True
    commission_bps: float = 3
    minimum_commission: float = 5
    sell_tax_bps: float = 0
    slippage_bps: float = 2
    limit_pct: float | None = None
    transfer_bps: float = 0
    fee_decimals: int | None = None
    max_actual_position: float = 1
    max_actual_exposure: float = 1
    allow_st: bool = False
    max_actual_sector: float | None = None
    industry_events: list | None = None
    corporate_actions: list | None = None
    corporate_action_mode: str = "strict"
    stock_splits: list | None = None
    rights_issues: list | None = None
    rights_trading: list | None = None
    max_volume_participation: float | None = None
    price_mode: str = "research"

    def __post_init__(self):
        if self.price_mode not in ('research','account'):raise ValueError('price_mode must be research or account')
        IndustryHistory(self.industry_events)
        traded=RightsTrading(self.rights_trading,self.corporate_action_mode)
        dividends=CashDividends(self.corporate_actions, self.corporate_action_mode)
        splits=StockSplits(self.stock_splits, self.corporate_action_mode)
        rights=RightsIssues(self.rights_issues,self.corporate_action_mode);rights.validate_other_actions(dividends,splits)
        splits.validate_bindings(dividends,rights,traded)
        if self.max_volume_participation is not None and (type(self.max_volume_participation) not in (int,float) or not math.isfinite(self.max_volume_participation) or not 0<self.max_volume_participation<=1):
            raise ValueError('max_volume_participation must be null or in (0,1]')
        if self.max_actual_sector is not None and (type(self.max_actual_sector) not in (int,float) or not math.isfinite(self.max_actual_sector) or not 0<self.max_actual_sector<=1):raise ValueError('Invalid actual sector limit')
        for key in ('initial_cash','threshold','exposure','commission_bps','minimum_commission','sell_tax_bps','slippage_bps','transfer_bps','max_actual_position','max_actual_exposure'):
            value=getattr(self,key)
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError(f'{key} must be finite')
        if self.initial_cash<=0 or not 0<=self.exposure<=1:raise ValueError('Invalid cash or exposure')
        if any(getattr(self,k)<0 for k in ('commission_bps','minimum_commission','sell_tax_bps','slippage_bps','transfer_bps')) or self.slippage_bps>=10000:
            raise ValueError('Invalid execution cost')
        if any(type(getattr(self,k)) is not int or getattr(self,k)<1 for k in ('lot_size','top_n')):raise ValueError('lot_size/top_n must be positive integers')
        if any(not 0<=getattr(self,k)<=1 for k in ('max_actual_position','max_actual_exposure')):raise ValueError('Invalid actual risk cap')
        if type(self.allow_st) is not bool:raise ValueError('allow_st must be boolean')
        if self.fee_decimals is not None and (type(self.fee_decimals) is not int or not 0<=self.fee_decimals<=8):raise ValueError('Invalid fee precision')
        if type(self.t_plus_one) is not bool:raise ValueError('t_plus_one must be boolean')
        if self.limit_pct is not None and (type(self.limit_pct) not in (int,float) or not math.isfinite(self.limit_pct) or not 0<self.limit_pct<1):
            raise ValueError('limit_pct must be null or in (0,1)')

    def validate_price_inputs(self, rules=None):
        if self.price_mode=='research':
            if any((self.corporate_actions,self.stock_splits,self.rights_issues,self.rights_trading)):
                raise ValueError('研究价格回测不重复处理公司行动；请清空事件或选择精细账户模式 price_mode=account')
            if rules and any(r.get('limit_up') is not None or r.get('limit_down') is not None for r in rules.records):
                raise ValueError('绝对涨跌停价格须使用精细账户模式；研究模式可保留历史费用规则')


def factor_targets(observations,bars,config):
    from quantlab.execution.portfolio import TargetWeightBuilder
    return TargetWeightBuilder().build(observations,bars,top_n=config.top_n,threshold=config.threshold,exposure=config.exposure)[0]


class OpenExecutionBacktester:
    def __init__(self,config=None,rules=None,matcher=None):
        self.config=config or ExecutionConfig(); self.rules=rules; self.matcher=matcher

    def run(self,targets,bars):
        bars=ordered_bars(bars);cfg=self.config;industry=IndustryHistory(cfg.industry_events)
        audit=ExecutionAudit(cfg.initial_cash)
        if bars['timeframe'][0] not in ('1d','1m','5m','15m','30m','60m'):
            raise ValueError('Execution requires one of the six registered timeframes')
        if bars.filter(pl.col('available_at')!=pl.col('datetime')).height:
            raise ValueError('Execution requires bars available at their close')
        for column in ('datetime','available_at'):
            if not isinstance(targets.schema[column],pl.Datetime) or targets.schema[column].time_zone is None:
                raise ValueError('Target timestamps must have an explicit timezone')
        symbols=set(bars['symbol'])
        dividends=CashDividends(cfg.corporate_actions,cfg.corporate_action_mode)
        splits=StockSplits(cfg.stock_splits,cfg.corporate_action_mode)
        rights=RightsIssues(cfg.rights_issues,cfg.corporate_action_mode)
        traded_rights=RightsTrading(cfg.rights_trading,cfg.corporate_action_mode)
        holding_tax=HoldingTax(dividends.records,cfg.corporate_action_mode)
        first_bar=bars['datetime'].min()
        snapshots=[]
        for key,group in targets.sort('available_at','symbol').group_by('available_at',maintain_order=True):
            if group.height!=len(symbols) or set(group['symbol'])!=symbols:raise ValueError('Targets must be complete unique symbol snapshots')
            if any(group[c].null_count() for c in ('symbol','datetime','available_at','weight')):raise ValueError('Null target fields')
            if group.filter((pl.col('datetime')>pl.col('available_at')) | ~pl.col('weight').is_finite() | (pl.col('weight')<0)).height:
                raise ValueError('Invalid target weights or information times')
            if group['weight'].sum()>1+1e-12:raise ValueError('Long-only target exposure cannot exceed one')
            snapshots.append((key[0],dict(zip(group['symbol'],group['weight']))))
        cash=cfg.initial_cash;lots={s:[] for s in symbols};marks={};index=0;weights={};decision=None
        fills=[];rejections=[];nav=[];last_close={};risk_audit=[];rule_gaps=set()
        prior_volume={}
        def quantity(symbol):return sum(lot[1] for lot in lots[symbol])
        def pending(symbol):return dividends.pending(symbol)+rights.pending(symbol)+traded_rights.pending(symbol)
        def economic_quantity(symbol):return quantity(symbol)+pending(symbol)
        def deliver_shares(symbol,size,at):
            if size:
                # list_at is explicitly the first tradable instant, not a fresh market purchase.
                lots[symbol].append([at.date()-timedelta(days=1),size])
                if self.matcher:self.matcher.stock_distribution(symbol,size)
        def recover_shares(symbol,size,at):
            remaining=size;recovered=0;disposed=[]
            for lot in lots[symbol]:
                used=min(lot[1],remaining);lot[1]-=used;remaining-=used;recovered+=used
                if used:disposed.append((lot[0],used))
            holding_tax.dispose(symbol,disposed,at,end,'recovery')
            if recovered and self.matcher:self.matcher.stock_distribution(symbol,-recovered)
            return recovered
        def rounded(value):
            return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-cfg.fee_decimals),rounding=ROUND_HALF_UP)) if cfg.fee_decimals is not None else value
        def costs(notional, buying, rule):
            get=lambda k:rule[k] if rule is not None else getattr(cfg,k)
            return (rounded(max(get('minimum_commission'),notional*get('commission_bps')/10000)),
                rounded(notional*get('sell_tax_bps')/10000) if not buying else 0.,rounded(notional*get('transfer_bps')/10000))
        total_periods=bars['datetime'].n_unique()
        for period,(key,group) in enumerate(bars.sort('datetime','symbol').group_by('datetime',maintain_order=True)):
            if period % 25 == 0:
                from quantlab.progress import checkpoint
                checkpoint('逐期成交与账务回测',period,total_periods)
            end=key[0]
            fills_before=len(fills)
            opening=end.replace(hour=9,minute=30,second=0,microsecond=0) if group['timeframe'][0]=='1d' else end-timedelta(minutes=int(group['timeframe'][0][:-1]))
            if any(dt<opening for dt in group['available_at']):raise ValueError('Bar available before its open')
            while index<len(snapshots) and snapshots[index][0]<=opening:
                decision,weights=snapshots[index];index+=1
            for action in dividends.records:
                if action['record_at']>=first_bar and action['action_id'] not in dividends.accrued and action['ex_at']<=opening and action['symbol'] in symbols and (economic_quantity(action['symbol']) or ('stock_per_share' in action and dividends.entitlements.get(action['action_id'],{}).get('shares',0))) and action['symbol'] not in set(group['symbol']):
                    raise ValueError('Missing ex-date valuation bar for held dividend stock')
            prices=dict(zip(group['symbol'],group['open']))
            split_count=len(splits.ledger)
            cash+=splits.advance(opening,end,lots,prices,marks,last_close,dividends,self.matcher,rights,holding_tax,traded_rights)
            cash+=splits.settle(opening,end,self.matcher)
            for conversion in splits.ledger[split_count:]:
                if conversion['kind']!='stock_split':continue
                symbol=conversion['symbol']
                if symbol in prior_volume:
                    prior_volume[symbol]['volume']*=conversion['numerator']/conversion['denominator']
            distribution=dividends.advance(opening,end,first_bar,symbols,deliver_shares)
            cash+=distribution
            if distribution and self.matcher:self.matcher.cash_distribution(distribution)
            subscription=rights.advance(opening,end,first_bar,symbols,prices,cash,deliver_shares,recover_shares)
            cash+=subscription
            if subscription and self.matcher:self.matcher.cash_distribution(subscription)
            exercise=traded_rights.advance(opening,end,first_bar,symbols,prices,cash,quantity,deliver_shares,recover_shares);cash+=exercise
            if exercise and self.matcher:self.matcher.cash_distribution(exercise)
            withheld=holding_tax.settle(opening,end,cash,'opening');cash+=withheld
            if withheld and self.matcher:self.matcher.cash_distribution(withheld)
            prices=dict(zip(group['symbol'],group['open']))
            valuation={**marks,**prices}
            equity=cash+dividends.receivable+rights.prepaid+splits.receivable-holding_tax.payable+sum(economic_quantity(s)*valuation.get(s,0) for s in symbols)
            if weights:
                orders=[]
                for symbol,price in prices.items():
                    desired=math.floor(equity*weights[symbol]/price/cfg.lot_size)*cfg.lot_size
                    delta=desired-economic_quantity(symbol)
                    if delta:orders.append((delta>0,symbol,delta,price))
                    else:audit.previous_attempt.pop(symbol,None)
                for buying,symbol,delta,price in sorted(orders):
                    requested=abs(delta);size=requested;reason=None;capacity=None
                    rule=self.rules.at(symbol,opening) if self.rules else None
                    if self.rules and rule is None:
                        size=0;reason='missing_market_rule';rule_gaps.add((symbol,opening.isoformat()))
                    elif rule is not None:
                        if rule['suspended']:size=0;reason='suspended'
                        elif buying and rule['st'] and not cfg.allow_st:size=0;reason='st_buy_blocked'
                        elif (buying and rule['limit_up'] is not None and price>=rule['limit_up']-1e-10) or (not buying and rule['limit_down'] is not None and price<=rule['limit_down']+1e-10):
                            size=0;reason='session_price_limit'
                    if any(r['rights_symbol']==symbol and not r['deliver_at']<=opening<r['expires_at'] for r in traded_rights.records):size=0;reason='rights_outside_trading_lifetime'
                    if size and self.rules is None and cfg.limit_pct is not None and symbol in last_close:
                        bound=last_close[symbol]*(1+cfg.limit_pct if buying else 1-cfg.limit_pct)
                        if (buying and price>=bound-1e-10) or (not buying and price<=bound+1e-10):
                            size=0;reason='configured_price_limit'
                    if cfg.max_volume_participation is not None:
                        previous=prior_volume.get(symbol)
                        cap=math.floor(previous['volume']*cfg.max_volume_participation) if previous else 0
                        if buying:cap=cap//cfg.lot_size*cfg.lot_size
                        capacity={'reference':previous,'participation':cfg.max_volume_participation,'quantity_cap':cap}
                        if size>cap:
                            size=cap;reason='lagged_volume_capacity' if previous else 'capacity_history_missing'
                    sector=industry.at(symbol,opening)
                    if size and buying and cfg.max_actual_sector is not None and sector is None:
                        size=0;reason='unknown_industry'
                    execution_price=price*(1+(cfg.slippage_bps/10000)*(1 if buying else -1))
                    if not buying and size:
                        settled=sum(n for day,n in lots[symbol] if not cfg.t_plus_one or day<opening.date())
                        before_limit=size
                        size=min(size,settled)
                        if size<before_limit:reason='pending_stock_or_t_plus_one' if pending(symbol) else 't_plus_one'
                    if buying and size:
                        account_equity=cash+dividends.receivable+rights.prepaid+splits.receivable-holding_tax.payable+sum(economic_quantity(s)*valuation.get(s,0) for s in symbols)
                        current_value=sum(economic_quantity(s)*valuation.get(s,0) for s in symbols)
                        if cfg.max_actual_position<1 or cfg.max_actual_exposure<1:
                            # Price/fee losses lower post-fill equity; validate the resulting account below.
                            allowed=min(account_equity*cfg.max_actual_position-economic_quantity(symbol)*price,
                                account_equity*cfg.max_actual_exposure-current_value)
                            before_limit=size
                            size=min(size,max(0,math.floor(allowed/price/cfg.lot_size)*cfg.lot_size))
                            if size<before_limit:reason='actual_position_or_exposure_cap'
                        rate=(rule['commission_bps']+rule['transfer_bps'] if rule else cfg.commission_bps+cfg.transfer_bps)/10000
                        before_limit=size
                        size=min(size,max(0,math.floor(cash/(execution_price*(1+rate))/cfg.lot_size)*cfg.lot_size))
                        if size<before_limit:reason='cash_lot_or_actual_risk'
                        sector_value=sum(economic_quantity(s)*valuation.get(s,0) for s in symbols if industry.at(s,opening)==sector)
                        if cfg.max_actual_sector is not None:
                            before_limit=size
                            size=min(size,max(0,math.floor((account_equity*cfg.max_actual_sector-sector_value)/price/cfg.lot_size)*cfg.lot_size))
                            if size<before_limit:reason='actual_sector_cap'
                        before_limit=size
                        while size:
                            total_fee=sum(costs(size*execution_price,True,rule))
                            after_equity=account_equity-total_fee-size*(execution_price-price)
                            if (cfg.max_actual_sector is None or sector_value+size*price<=after_equity*cfg.max_actual_sector+1e-8) and size*execution_price+total_fee<=cash+1e-8 and \
                                (economic_quantity(symbol)+size)*price<=after_equity*cfg.max_actual_position+1e-8 and \
                                current_value+size*price<=after_equity*cfg.max_actual_exposure+1e-8:break
                            size-=cfg.lot_size
                        if size<before_limit:reason='cash_lot_or_actual_risk'
                    if not buying and size and cash+size*execution_price-sum(costs(size*execution_price,False,rule))<0:
                        size=0;reason='cash_for_sell_fees'
                    if size:
                        notional=size*execution_price;commission,tax,transfer=costs(notional,buying,rule)
                        if buying:
                            cash-=notional+commission+transfer;lots[symbol].append([opening.date(),size])
                        else:
                            remaining=size;disposed=[]
                            for lot in lots[symbol]:
                                if cfg.t_plus_one and lot[0]>=opening.date():continue
                                used=min(lot[1],remaining);lot[1]-=used;remaining-=used
                                if used:disposed.append((lot[0],used))
                            cash+=notional-commission-tax-transfer
                        if cash < -1e-7:raise ValueError('Execution would create negative cash')
                        native=self.matcher.fill(symbol,opening,buying,size,execution_price,commission+tax+transfer,cash) if self.matcher else {}
                        fills.append({**native,'symbol':symbol,'decision_at':decision,'filled_at':opening,'bar_end':end,
                            'side':'buy' if buying else 'sell','quantity':size,'price':execution_price,
                            'commission':commission,'tax':tax,'transfer_fee':transfer,'rule_snapshot':digest(rule) if rule else None,'slippage_cost':size*abs(execution_price-price)})
                        if not buying:
                            holding_tax.dispose(symbol,disposed,opening,end)
                            withheld=holding_tax.settle(opening,end,cash,'sale');cash+=withheld
                            if withheld and self.matcher:self.matcher.cash_distribution(withheld)
                    if size<requested:
                        rejections.append({'symbol':symbol,'at':opening,'side':'buy' if buying else 'sell',
                            'requested':requested,'filled':size,'reason':reason})
                    audit.attempt(opening,decision,symbol,buying,requested,size,reason,capacity)
            for row in group.iter_rows(named=True):
                marks[row['symbol']]=row['close'];last_close[row['symbol']]=row['close']
                prior_volume[row['symbol']]={'at':end,'volume':row['volume']}
            prices=dict(zip(group['symbol'],group['open']))
            cash+=splits.settle(end,end,self.matcher)
            distribution=dividends.advance(end,end,first_bar,symbols,deliver_shares)
            cash+=distribution
            if distribution and self.matcher:self.matcher.cash_distribution(distribution)
            withheld=holding_tax.settle(end,end,cash,'close');cash+=withheld
            if withheld and self.matcher:self.matcher.cash_distribution(withheld)
            dividends.capture(end,set(group['symbol']),quantity)
            holding_tax.capture(end,lots,dividends.entitlements)
            rights.capture(end,set(group['symbol']),quantity)
            traded_rights.capture(end,set(group['symbol']),quantity,pending)
            position_value=sum(economic_quantity(s)*marks.get(s,0) for s in symbols)
            close_equity=cash+position_value+dividends.receivable+rights.prepaid+splits.receivable-holding_tax.payable
            breaches={s:economic_quantity(s)*marks.get(s,0)/close_equity for s in symbols if economic_quantity(s)*marks.get(s,0)>close_equity*cfg.max_actual_position+1e-7}
            sector_values={}
            if cfg.max_actual_sector is not None:
                for s in symbols:
                    sector=industry.at(s,end) or 'UNKNOWN'
                    sector_values[sector]=sector_values.get(sector,0)+economic_quantity(s)*marks.get(s,0)
            sector_breaches={s:v/close_equity for s,v in sector_values.items() if v>close_equity*(cfg.max_actual_sector if s!='UNKNOWN' else 0)+1e-7}
            if sector_breaches or breaches or position_value>close_equity*cfg.max_actual_exposure+1e-7:
                risk_audit.append({'at':end,'position_weights':breaches,'sector_weights':sector_breaches,'exposure':position_value/close_equity,
                    'action':'block risk-increasing buys; target reductions remain subject to T+1, suspension and price limits'})
            nav.append({'datetime':end,'cash':cash,'position_value':position_value,'equity':close_equity,**({'dividend_receivable':dividends.receivable,**({'pending_stock_value':sum(pending(s)*marks.get(s,0) for s in symbols)} if any('stock_per_share' in r for r in dividends.records) else {})} if cfg.corporate_actions else {})})
            if holding_tax.records:nav[-1]['dividend_tax_payable']=holding_tax.payable
            if cfg.stock_splits:nav[-1]['split_receivable']=splits.receivable
            if cfg.rights_trading:nav[-1]['pending_stock_value']=sum(pending(s)*marks.get(s,0) for s in symbols)
            if cfg.rights_issues:nav[-1].update(subscription_receivable=rights.prepaid,pending_stock_value=sum(pending(s)*marks.get(s,0) for s in symbols))
            audit.close(end,decision,weights,{s:quantity(s) for s in sorted(symbols)},{s:pending(s) for s in sorted(symbols)},marks,set(group['symbol']),close_equity,cash,dividends.receivable+rights.prepaid+splits.receivable-holding_tax.payable,fills[fills_before:])
        curve=pl.DataFrame(nav)
        peak=cfg.initial_cash;drawdown=0
        for equity in curve['equity']:
            peak=max(peak,equity);drawdown=min(drawdown,equity/peak-1)
        summary={'initial_cash':cfg.initial_cash,'final_equity':curve['equity'][-1],
            'net_return':curve['equity'][-1]/cfg.initial_cash-1,'max_drawdown':drawdown,
            'fills':len(fills),'rejections':len(rejections),'commission':sum(v['commission'] for v in fills),
            'sell_tax':sum(v['tax'] for v in fills),'slippage_cost':sum(v['slippage_cost'] for v in fills),
            'risk_audit':risk_audit,'missing_rule_orders':[{'symbol':s,'at':at} for s,at in sorted(rule_gaps)],
            'transfer_fee':sum(v['transfer_fee'] for v in fills),
            'ending_positions':{s:quantity(s) for s in sorted(symbols) if quantity(s)},
            'unprocessed_target_snapshots':len(snapshots)-index}
        if holding_tax.records:summary.update(dividend_tax_ledger=holding_tax.ledger,dividend_tax_payable=holding_tax.payable,dividend_tax=sum(e.get('tax',0.) for e in holding_tax.ledger))
        if cfg.stock_splits:
            summary['split_receivable']=splits.receivable
            summary.update(split_ledger=splits.ledger,split_scope='Explicit new/old share ratio; per-lot conversion preserves acquisition dates. Explicit floor cash-in-lieu may settle later. Named pending entitlements convert with the same units or explicit allocations; paid principal adjustments and source rules remain auditable.')
        if cfg.corporate_actions:
            summary.update(corporate_action_ledger=dividends.ledger,dividend_receivable=dividends.receivable,
                dividend_cash=sum(r['cash_delta'] for r in dividends.ledger),corporate_action_mode=cfg.corporate_action_mode,
                corporate_action_scope='Explicit cash and stock distributions; fixed tax and fractional allocation assumptions, stock_splits configured separately; rights_issues configured separately; holding_tax supports explicit calendar-month FIFO disposal assessment; no inferred investor identity or statutory rates')
        if cfg.rights_issues:
            summary.update(rights_ledger=rights.ledger,subscription_receivable=rights.prepaid,rights_scope='Explicit nontransferable subscription instructions; prepaid at cost until ex-date, then unlisted shares at underlying mark. Explicit fees are expensed at subscription. Explicit allocation and oversubscription results refund unused funds; cancellation supports pre-listing removal and post-listing recovery/compensation. Transferable quoted rights use rights_trading. No inferred allocation or tax/fees.')
        if cfg.rights_trading:summary['rights_trading_ledger']=traded_rights.ledger
        if cfg.rights_issues or cfg.rights_trading or any('stock_per_share' in r for r in dividends.records):
            summary['pending_stock_positions']={s:pending(s) for s in sorted(symbols) if pending(s)}
        summary['execution_diagnostics'],self.execution_audit=audit.result()
        from quantlab.execution.performance import performance_metrics
        summary.update(performance_metrics(curve, cfg.initial_cash))
        return curve,fills,rejections,summary
