"""Native vn.py matching/accounting for platform-prepared rule-aware orders.

The platform owns dated limits, costs and risk. Native fixed-10% checks are
neutralized around the modeled execution quote. This tests kernel accounting,
not an independent implementation of order selection or historical market rules.
"""
from dataclasses import asdict
from importlib.metadata import version
import polars as pl
from quantlab.adapters.vnpy import vt_symbol
from quantlab.execution.backtest import OpenExecutionBacktester


class RuleAwareNativeMatcher:
    def __init__(self,config,symbols,start,end):
        if version('vnpy')!='4.4.0':raise ValueError('vnpy_rules requires vnpy 4.4.0')
        from vnpy.alpha.strategy.backtesting import BacktestingEngine
        from vnpy.alpha.strategy.template import AlphaStrategy
        from vnpy.trader.constant import Interval
        contracts={vt_symbol(s):{'long_rate':0.,'short_rate':0.,'size':1,'pricetick':1e-8} for s in symbols}
        class Contracts:
            def load_contract_setttings(self):return contracts
        class Strategy(AlphaStrategy):
            def on_init(self):pass
            def on_bars(self,bars):pass
            def on_trade(self,trade):pass
        self.engine=BacktestingEngine(Contracts());self.engine.set_parameters(list(contracts),Interval.MINUTE,start,end,capital=config.initial_cash)
        self.engine.add_strategy(Strategy,{},pl.DataFrame());self.rows=[]

    def stock_distribution(self, symbol, quantity):
        self.engine.strategy.pos_data[vt_symbol(symbol)] += quantity

    def cash_distribution(self, amount):
        self.engine.cash += amount

    def fill(self,symbol,at,buying,quantity,price,fee,expected_cash):
        from vnpy.trader.object import BarData
        from vnpy.trader.constant import Exchange
        engine=self.engine;vt=vt_symbol(symbol);code,exchange=vt.split('.')
        engine.datetime=at;engine.pre_closes={vt:price}
        engine.bars={vt:BarData(symbol=code,exchange=Exchange(exchange),datetime=at,
            open_price=price,high_price=price,low_price=price,close_price=price,gateway_name='QUANTLAB_MODELED_QUOTE')}
        rate=fee/(quantity*price);engine.long_rates[vt]=rate;engine.short_rates[vt]=rate
        before=engine.trade_count
        ids=(engine.strategy.buy if buying else engine.strategy.sell)(vt,price+2e-8 if buying else max(1e-8,price-2e-8),quantity)
        engine.cross_order()
        for order_id in ids:engine.strategy.cancel_order(order_id)
        if engine.trade_count!=before+1:raise ValueError('Native matching did not execute the prepared order')
        trade=next(reversed(engine.trades.values()))
        if trade.volume!=quantity or abs(trade.price-price)>1e-7:raise ValueError('Native fill differs from prepared quote')
        cash_error=abs(engine.cash-expected_cash)
        if cash_error>1e-6:raise ValueError('Native per-fill cash failed reconciliation')
        self.rows.append({'cash_error':cash_error,'trade':asdict(trade),'charged_fee':fee,'cash':engine.cash})
        return {'vnpy_trade_id':trade.vt_tradeid}


class VnpyRulesBacktester:
    def __init__(self,config,rules):self.config=config;self.rules=rules;self.diagnostics={}
    def run(self,targets,bars):
        symbols=sorted(bars['symbol'].unique().to_list())
        matcher=RuleAwareNativeMatcher(self.config,symbols,bars['datetime'].min(),bars['datetime'].max())
        engine=OpenExecutionBacktester(self.config,self.rules,matcher)
        result=engine.run(targets,bars)
        self.execution_audit=engine.execution_audit
        curve,_,_,summary=result
        positions={s:int(matcher.engine.strategy.pos_data[vt_symbol(s)]) for s in symbols if matcher.engine.strategy.pos_data[vt_symbol(s)]}
        error=abs(matcher.engine.cash-curve['cash'][-1])
        if error>1e-6 or positions!=summary['ending_positions']:raise ValueError('Native cash/positions failed reconciliation')
        self.diagnostics={'vnpy_version':version('vnpy'),'driver':'platform rule-aware order preparation -> native cross_order and cash/position callbacks',
            'max_per_fill_cash_error':max((r['cash_error'] for r in matcher.rows),default=0.),'native_cash':matcher.engine.cash,'native_positions':positions,'cash_error':error,'native_trades':matcher.rows,
            'native_orders':[asdict(o) for o in matcher.engine.get_all_orders()],
            'limitations':'Shared platform order/risk/cost decisions. Synthetic open-only modeled execution quote includes configured slippage. Per-order rate represents rounded commission/tax/transfer. Upstream fixed 10% guard neutralized; no independent native market-rule validation or native daily PnL claim.'}
        return result
