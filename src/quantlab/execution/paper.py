"""Durable bar-driven paper account. No broker connectivity or live orders.

Full append-only replay is intentionally used for recovery; suitable for research
accounts, not a low-latency trading service. Atomic state contains inputs and ledger.
"""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import json
import os
import tempfile
import polars as pl
from quantlab.execution.backtest import ExecutionConfig, OpenExecutionBacktester
from quantlab.execution.rules import MarketRules
from quantlab.storage.codec import encode, digest


def frame(rows):
    return pl.DataFrame([{k:datetime.fromisoformat(v) if k in ('datetime','available_at') and isinstance(v,str) else v for k,v in r.items()} for r in rows]).with_columns(pl.col("datetime","available_at").dt.convert_time_zone("Asia/Shanghai"))


def engine_hash():
    root=Path(__file__).parents[1]
    return digest({name:(root/name).read_text() for name in ('execution/backtest.py','execution/diagnostics.py','execution/corporate_actions.py','execution/holding_tax.py','execution/rights_trading.py','data/industry.py','execution/rules.py','execution/paper.py','adapters/vnpy_rules.py')})


class PaperAccount:
    def __init__(self,path):self.path=Path(path).resolve()

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock,fcntl.LOCK_UN)

    def read(self):
        with self.locked():return json.loads(self.path.read_text())

    def advance(self,bars,targets,rules,config=None,backend='open',as_of=None):
        if backend not in ('open','vnpy_rules'):raise ValueError('Paper supports open or vnpy_rules')
        if not isinstance(rules,MarketRules):raise ValueError('Paper requires explicit dated market rules')
        as_of=as_of or datetime.now(timezone.utc)
        if as_of.tzinfo is None:raise ValueError('Paper clock must be timezone aware')
        cfg=config or ExecutionConfig()
        for incoming in (bars,targets):
            if incoming.is_empty():raise ValueError('Paper input snapshots cannot be empty')
            if incoming['available_at'].max()>as_of:raise ValueError('Paper input is not yet available at the delivery clock')
        with self.locked():
            previous=json.loads(self.path.read_text()) if self.path.exists() else None
            identity=json.loads(encode({'config':asdict(cfg),'backend':backend,'engine_hash':engine_hash()}))
            if previous and previous['identity']!=identity:raise ValueError('Account configuration/code changed; use a new account')
            old_rules=previous['rules'] if previous else []
            encoded_rules=json.loads(encode(rules.records))
            if any(r not in encoded_rules for r in old_rules):raise ValueError('Historical paper rules cannot be removed or rewritten')
            def merge(name,new):
                old=previous[name] if previous else []
                known={(r['symbol'],r['datetime'],r['available_at']):r for r in old}
                added=0
                for row in json.loads(encode(new.to_dicts())):
                    key=(row['symbol'],row['datetime'],row['available_at'])
                    if key in known:
                        if known[key]!=row:raise ValueError('Previously processed paper input was revised')
                        continue
                    if previous:
                        at=datetime.fromisoformat(row['datetime'] if name=='bars' else row['available_at'])
                        watermark=datetime.fromisoformat(previous['watermark'])
                        if at<watermark or (name=='bars' and at==watermark):raise ValueError('Late paper input would change processed history')
                    known[key]=row;added+=1
                return sorted(known.values(),key=lambda r:(r['datetime'],r['symbol'])),added
            all_bars,new_bars=merge('bars',bars);all_targets,new_targets=merge('targets',targets)
            if previous and not new_bars and not new_targets and encoded_rules==old_rules:return previous
            market=frame(all_bars); signals=frame(all_targets)
            if backend=='vnpy_rules':
                from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
                engine=VnpyRulesBacktester(cfg,rules)
            else:engine=OpenExecutionBacktester(cfg,rules)
            curve,fills,rejections,summary=engine.run(signals,market)
            curve_rows=json.loads(encode(curve.to_dicts()));fill_rows=json.loads(encode(fills));reject_rows=json.loads(encode(rejections))
            if previous:
                if curve_rows[:len(previous['nav'])]!=previous['nav'] or fill_rows[:len(previous['fills'])]!=previous['fills'] or reject_rows[:len(previous['rejections'])]!=previous['rejections']:
                    raise ValueError('New delivery changed a committed paper ledger; update rejected')
            # Stable ledger IDs survive repeat delivery and process restart.
            orders=[{'order_id':digest({'account':str(self.path),'fill':r}),'status':'filled',**r} for r in fill_rows]
            orders += [{'order_id':digest({'account':str(self.path),'rejection':r}),'status':'remainder_rejected',**r} for r in reject_rows]
            state={'version':'1.0.0','identity':identity,'revision':previous['revision']+1 if previous else 1,
                'delivered_at':as_of.isoformat(),'watermark':market['available_at'].max().isoformat(),
                'bars':all_bars,'targets':all_targets,'rules':encoded_rules,'nav':curve_rows,'fills':fill_rows,
                'rejections':reject_rows,'orders':orders,'summary':summary,'execution_audit':engine.execution_audit,
                'backend_details':getattr(engine,'diagnostics',{}),
                'mode':'paper_bar_feed','limitations':'Completed-bar delivery with modeled next-open fills; no live quote subscription, broker gateway, order queue or real capacity guarantee. Optional capacity uses lagged same-timeframe volume. Only explicitly configured dividends, distributions, splits and rights subscriptions are processed. Fees, fractional settlement, entitlement overrides and cancellation/refund terms are supplied assumptions; named pending conversions, allocation and recovery terms, quoted rights and explicit holding-tax schedules are supported; no inferred investor identity or official historical data.'}
            # Convert datetimes once so first response and restart response have identical shape.
            encoded=encode(state);state=json.loads(encoded)
            fd,temp=tempfile.mkstemp(prefix='.paper-',dir=self.path.parent)
            try:
                with os.fdopen(fd,'w') as handle:handle.write(encoded);handle.flush();os.fsync(handle.fileno())
                os.replace(temp,self.path)
                directory=os.open(self.path.parent,os.O_RDONLY)
                try:os.fsync(directory)
                finally:os.close(directory)
            finally:
                if os.path.exists(temp):os.unlink(temp)
            return state


def advance_from_files(account,bars,targets,rules,config=None,backend='open'):
    state=PaperAccount(account).advance(pl.read_parquet(bars),pl.read_parquet(targets),
        MarketRules(json.loads(Path(rules).read_text())),config,backend)
    return {k:state[k] for k in ('mode','revision','watermark','summary','limitations')}
