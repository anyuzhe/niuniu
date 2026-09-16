"""Host-authorized experimental Qimo paper runner. No broker or model calls.

Live decisions are journaled before end-of-day, raw five-minute bar settlement.
Missing evidence blocks entry; it never downgrades an existing qualification gate.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo
import fcntl
import json
import socket

import polars as pl

from quantlab.data.daily_market_archive import DailyMarketArchive
from quantlab.data.pit_universe import list_pit_universe_snapshots
from quantlab.data.qualification import _official_rule_receipt
from quantlab.data.validation import validate_bars
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.dynamic_paper import DynamicPaperAccount
from quantlab.execution.rules import MarketRules
from quantlab.experiments.campaign_state import read_checked, write_checked
from quantlab.storage.codec import digest
from .daily_orchestrator import DailyPlaybookOrchestrator
from .playbook_store import PlaybookStore

TZ = ZoneInfo('Asia/Shanghai')
VERSION = 'qimo-auto-paper-v2'
ACCOUNT = 'qimo-source-replica-v2'
CONFIG = ExecutionConfig(initial_cash=1000000, top_n=5000, exposure=1,
    max_actual_position=1, max_actual_exposure=1, price_mode='account',
    single_entry_attempt=True, entry_window_minutes=10,
    slippage_bps=5, fee_decimals=2)
POLICY = {'version': VERSION, 'candidate_scope': 'qimo_source_v2', 'fixed_weight': None,
    'max_positions': None, 'fixed_holding_days': None, 'drawdown_entry_halt': None,
    'allocation': 'available_cash_by_relative_strength_engineering_proxy',
    'exit': 'sector_weakness_and_failed_reseal_or_persistent_weakness',
    'settlement': 'raw_5m_after_18:30', 'config': asdict(CONFIG),
    'origin': 'primary_source_qualitative_rules_with_explicit_engineering_translation',
    'selection': 'qimo-source-rules-v2', 'real_trading': False}


@contextmanager
def provider_session():
    import baostock as sdk
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(20)
    try:
        result = sdk.login()
        if result.error_code != '0':raise ValueError('Baostock login: '+result.error_msg)
        yield sdk
    finally:
        try:sdk.logout()
        finally:socket.setdefaulttimeout(old)


def query_rows(query):
    if query.error_code != '0':raise ValueError('Baostock: '+query.error_msg)
    rows = []
    while query.next():
        rows.append(dict(zip(query.fields, query.get_row_data())))
        if len(rows)>20000:raise ValueError('Provider response budget exceeded')
    if query.error_code != '0':raise ValueError('Baostock page: '+query.error_msg)
    return rows


class QimoMarketData:
    def __init__(self, output, data_root):
        self.output=Path(output);self.data_root=Path(data_root)
        self.root=self.output/'_qimo_paper'/'market'
        self.root.mkdir(parents=True,exist_ok=True)

    def sessions(self, now):
        path=self.root/'calendar.json'
        saved=read_checked(path) if path.exists() else None
        # Refresh weekly, including holidays. Never infer sessions from weekdays.
        if not saved or now-datetime.fromisoformat(saved['fetched_at'])>timedelta(days=7):
            with provider_session() as sdk:
                rows=query_rows(sdk.query_trade_dates(start_date=(now.date()-timedelta(days=60)).isoformat(),
                    end_date=(now.date()+timedelta(days=60)).isoformat()))
            if not rows or any(r.get('is_trading_day') not in ('0','1') for r in rows):
                raise ValueError('INVALID_TRADING_CALENDAR')
            saved={'fetched_at':now.isoformat(),'rows':rows}
            write_checked(path,saved)
        days=sorted(date.fromisoformat(r['calendar_date']) for r in saved['rows'] if r['is_trading_day']=='1')
        if not days or days[-1]<=now.date():raise ValueError('TRADING_CALENDAR_EXPIRED')
        return days

    def official(self):
        records=[]
        for path in sorted((self.data_root/'research/official_market_rules').glob('*.json')):
            check=_official_rule_receipt(self.data_root,path.stem)
            if check.get('verified'):
                value=json.loads(path.read_text())
                records.append((path.stem,MarketRules(value['rules'])))
        return records

    def prep_evidence(self, day, previous):
        universes=list_pit_universe_snapshots(self.data_root,effective_session=day.isoformat())
        if not universes:return None,None,['pit_universe_not_certified']
        universe=max(universes,key=lambda r:r['created_at'])
        opening=datetime.combine(previous,time(9,30),TZ)
        for snapshot,rules in self.official():
            if all(rules.at(m['symbol'],opening) for m in universe['members']):
                return universe['universe_snapshot'],snapshot,[]
        return universe['universe_snapshot'],None,['official_market_rules_missing_or_incomplete']

    def execution_rules(self, day, symbol):
        at=datetime.combine(day,time(9,30),TZ)
        matches=[rules.at(symbol,at) for _,rules in self.official()]
        matches=[r for r in matches if r is not None and r['effective_at'].astimezone(TZ).date()==day]
        if not matches:raise ValueError('OFFICIAL_EXECUTION_RULES_MISSING: '+day.isoformat()+' '+symbol)
        unique={digest(r):r for r in matches}
        if len(unique)!=1:raise ValueError('CONFLICTING_EXECUTION_RULES')
        return MarketRules(list(unique.values()))

    def bars(self, day, symbol, now):
        path=self.root/(day.isoformat()+'_'+symbol+'.json')
        if path.exists():saved=read_checked(path)
        else:
            with provider_session() as sdk:
                rows=query_rows(sdk.query_history_k_data_plus(symbol,
                    'date,time,code,open,high,low,close,volume,amount,adjustflag',
                    start_date=day.isoformat(),end_date=day.isoformat(),frequency='5',adjustflag='3'))
            saved={'fetched_at':now.isoformat(),'rows':rows,'price_mode':'unadjusted'}
            # An empty/delayed response is retried; not sealed as a completed session.
            self._bars(saved,day,symbol)
            write_checked(path,saved)
        return self._bars(saved,day,symbol)

    @staticmethod
    def _bars(saved,day,symbol):
        result=[]
        for r in saved['rows']:
            if r['date']!=day.isoformat() or r['code']!=symbol or r['adjustflag']!='3':raise ValueError('RAW_BAR_IDENTITY_MISMATCH')
            at=datetime.strptime(r['time'][:14],'%Y%m%d%H%M%S').replace(tzinfo=TZ)
            result.append({'symbol':symbol,'datetime':at,'available_at':at,'timeframe':'5m',
                **{k:float(r[k]) for k in ('open','high','low','close','volume')},'turnover':float(r['amount'])})
        expected=[datetime.combine(day,t,TZ)+timedelta(minutes=i*5) for t in (time(9,30),time(13)) for i in range(1,25)]
        if sorted(r['datetime'] for r in result)!=expected:raise ValueError('INCOMPLETE_5M_SESSION')
        bars=pl.DataFrame(result).sort('datetime');validate_bars(bars)
        return bars

    def check_corporate_action(self, day, symbol, account):
        if not account or not account['summary']['ending_positions'].get(symbol):return
        if datetime.fromisoformat(account['watermark']).astimezone(TZ).date()>=day:return
        archive=DailyMarketArchive(self.output)
        if archive.accepted(day.isoformat()) is None:archive.capture(day.isoformat())
        rows=archive.read_frame(day.isoformat())[0].filter(pl.col('code')==symbol).to_dicts()
        old=[r for r in account['bars'] if r['symbol']==symbol]
        if not rows or not old or rows[0]['preclose'] is None:raise ValueError('CORPORATE_ACTION_REFERENCE_MISSING')
        if abs(float(old[-1]['close'])-rows[0]['preclose'])>.005:
            raise ValueError('CORPORATE_ACTION_REQUIRES_REVIEW: raw previous close changed')


class QimoPaperRunner:
    def __init__(self, output, data_root, *, now_fn=None, market=None):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve()
        if not self.output.is_dir() or not self.data_root.is_dir():raise ValueError('Workspace/data root missing')
        self.root=self.output/'_qimo_paper';self.root.mkdir(exist_ok=True)
        self.now_fn=now_fn or (lambda:datetime.now(TZ))
        self.market=market or QimoMarketData(self.output,self.data_root)
        self.account=DynamicPaperAccount(self.output/'paper_dynamic'/(ACCOUNT+'.json'))

    @contextmanager
    def locked(self):
        with (self.root/'runner.lock').open('a+b') as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('QIMO_RUNNER_BUSY') from None
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def enable(self,source_definition_id,*,confirmed=False):
        if confirmed is not True:raise ValueError('Explicit host paper authorization required')
        with self.locked():
            path=self.root/'control.json'
            if path.exists():
                old=read_checked(path)
                if old['policy']==POLICY and old['source_definition_id']==source_definition_id:
                    old['enabled']=True;write_checked(path,old);return old
                # Never rewrite a funded/traded old account or silently abandon its exits.
                journal=read_checked(self.root/'journal.json')
                old_account=self.output/'paper_dynamic'/(old['account']+'.json')
                if journal.get('episodes') or journal.get('events') or old_account.exists():
                    raise ValueError('旧版已有信号或账户历史；需先完成旧版结算，不能直接改本金/规则。')
                archive=self.root/'versions'/old['policy']['version'];archive.mkdir(parents=True,exist_ok=True)
                for name in ('control.json','journal.json','status.json'):
                    source=self.root/name
                    if source.exists():
                        target=archive/name
                        if not target.exists():write_checked(target,read_checked(source))
            store=PlaybookStore(self.output);source=store.get_definition(source_definition_id)
            if source['playbook_key']!='qimofenshu':raise ValueError('Qimo source definition required')
            sources=list(source['source_ids'])
            from .qimo_rules import RULES,ENGINE
            reply_ids={r for ids in RULES.values() for r in ids}
            for record in store.list_sources(expert_key='qimofenshu',limit=200)['records']:
                if any(r in record['locator'] for r in reply_ids) and record['source_id'] not in sources:sources.append(record['source_id'])
            content={'playbook_key':'qimofenshu','name':'期末50分原话规则复刻研究·百万模拟 v2',
                'version':VERSION,'state':'DRAFT','source_ids':sources,
                'market_context':{'principle':'由盘面、题材预期与核心表现联合判断；不以固定回撤阈值停手'},
                'eligibility':{'candidate_scope':'recent_limit_up_leaders_and_existing_holdings','fixed_streak':None,'max_positions':None},
                'selection':{'engine':ENGINE,'principle':'主动性+带动性；全部有效信号，不截取第一名','source_reply_ids':RULES},
                'entry':{'initial_cash':1000000,'fixed_weight':None,'allocation':'剩余可用权重按正向相对强度分配；工程近似，非作者公式'},
                'hold':{'principle':'符合预期继续持有；板块修复可等待；缺少事实不强制清仓'},
                'add':{'allowed':True,'condition':'新有效信号且有可用资金；不因价格变化机械补仓'},
                'exit':{'principle':'板块走弱且个股回封失败/持续不红/转为被动，生成退出；不固定持有天数',
                    'partial_exit':'本人有分批卖出证据；尚无固定比例，当前代理生成零目标，不声称复刻分批委托'},
                'veto':{'data':'缺失候选全集、官方规则、实时行情或板块事实不伪造入场','real_trading':False},
                'notes':'原话定性逻辑+显式量化近似，仍为DRAFT。竞价排板、题材预判、精确仓位和分批卖出不能凭现有资料完整复刻。'+json.dumps(POLICY,ensure_ascii=False)}
            definition=store.create_definition(str(uuid5(NAMESPACE_URL,VERSION)),content)
            control={'enabled':True,'policy':POLICY,'definition_id':definition['definition_id'],
                'definition_hash':definition['definition_hash'],'source_definition_id':source_definition_id,
                'data_root':str(self.data_root),'authorized_at':self.now_fn().isoformat(),'account':ACCOUNT}
            write_checked(self.root/'journal.json',{'format':'qimo-portfolio-v2','events':[],'settled_days':[]})
            write_checked(path,control)
            return control

    def pause(self):
        with self.locked():
            control=read_checked(self.root/'control.json');control['enabled']=False
            write_checked(self.root/'control.json',control)
        return {'status':'ENTRIES_PAUSED','detail':'停止新入场/加仓；既有信号继续结算，持仓仍按条件复核退出。'}

    def status(self):
        control=read_checked(self.root/'control.json') if (self.root/'control.json').exists() else {}
        heartbeat=read_checked(self.root/'status.json') if (self.root/'status.json').exists() else {}
        account=self.account.read() if self.account.path.exists() else None
        return {'control':control,'heartbeat':heartbeat,
            'heartbeat_stale':not heartbeat or self.now_fn()-datetime.fromisoformat(heartbeat['updated_at'])>timedelta(minutes=5),
            'account':account['summary'] if account else None,'account_initialized':account is not None,
            'virtual_initial_cash':CONFIG.initial_cash,'real_trading':False}

    def _status(self,now,status,**details):
        result={'updated_at':now.isoformat(),'status':status,'real_trading':False,**details}
        write_checked(self.root/'status.json',result);return result

    def tick(self):
        with self.locked():
            now=self.now_fn()
            if now.tzinfo is None:raise ValueError('Clock timezone required')
            now=now.astimezone(TZ)
            last=read_checked(self.root/'status.json') if (self.root/'status.json').exists() else {}
            if last.get('status')=='BLOCKED' and now-datetime.fromisoformat(last['updated_at'])<timedelta(minutes=5):
                return {**last,'retry_after_seconds':300,'cooldown':True}
            try:return self._tick(now)
            except (OSError,ValueError,KeyError,TypeError,pl.exceptions.PolarsError) as exc:
                return self._status(now,'BLOCKED',error=type(exc).__name__+': '+str(exc)[:800])

    def _tick(self,now):
        control=read_checked(self.root/'control.json')
        if control['policy']!=POLICY or control['data_root']!=str(self.data_root):raise ValueError('STRATEGY_IDENTITY_CHANGED')
        definition=PlaybookStore(self.output).get_definition(control['definition_id'])
        if definition['definition_hash']!=control['definition_hash']:raise ValueError('DEFINITION_CHANGED')
        journal=read_checked(self.root/'journal.json');days=self.market.sessions(now)
        settlement=self.settle(journal,days,now)
        account=self.account.read() if self.account.path.exists() else None
        holdings=sorted(account['summary']['ending_positions']) if account else []
        if not control['enabled'] and not holdings:return self._status(now,'ENTRIES_PAUSED',settlement=settlement)
        if now.date() not in days or not time(8)<=now.time()<=time(15,10):
            next_day=next(d for d in days if d>now.date());previous=days[days.index(next_day)-1]
            _,_,blockers=self.market.prep_evidence(next_day,previous)
            return self._status(now,'WAIT_NEXT_SESSION',settlement=settlement,next_session=next_day.isoformat(),blockers=blockers)
        if now.date()<=datetime.fromisoformat(control['authorized_at']).astimezone(TZ).date():
            return self._status(now,'WAIT_FIRST_FORWARD_SESSION',detail='新版本授权日不补写历史信号。')
        index=days.index(now.date());previous=days[index-1]
        universe,rules,blockers=self.market.prep_evidence(now.date(),previous)
        if blockers:return self._status(now,'BLOCKED_PREP_EVIDENCE',blockers=blockers,trading_day=now.date().isoformat())
        orchestrator=DailyPlaybookOrchestrator(self.output,self.data_root,now_fn=self.now_fn)
        orchestrator.root=self.root/'orchestrator-v2'
        day=now.date().isoformat()
        try:plan=orchestrator.get(day)
        except ValueError as exc:
            if getattr(exc,'code',None)!='NOT_FOUND':raise
            plan=orchestrator.create_plan(day,previous.isoformat(),control['definition_id'],
                candidate_scope='qimo_source_v2',include_symbols=holdings,universe_snapshot=universe,market_rules_snapshot=rules,
                allow_daily_market_capture=True,allow_market_snapshot_capture=True)
        plan=orchestrator.tick(day,now=now)
        admitted=self.admit(plan,journal,days,self.now_fn().astimezone(TZ),allow_entries=control['enabled'])
        scan=plan.get('prep',{}).get('scan',{})
        return self._status(now,admitted.get('status') or plan['status'],trading_day=day,
            blockers=scan.get('blockers',[])+admitted.get('blockers',[]),candidates=scan.get('candidate_count'),
            portfolio_events=len(journal['events']),settlement=settlement)

    def admit(self,plan,journal,days,now,*,allow_entries=True):
        from .qimo_rules import portfolio_targets
        if plan['trading_day']!=now.date().isoformat():return {}
        windows={'r1':(time(9,35),time(9,40)),'r2':(time(11,30),time(11,40)),'r3':(time(15),time(15,10))}
        store=PlaybookStore(self.output)
        for frame,(start,end) in windows.items():
            stage=plan.get(frame,{})
            if stage.get('status')!='FROZEN' or not start<=now.time()<=end:continue
            if any(e['selection_id']==stage['prediction_id'] for e in journal['events']):continue
            selection=store.get_selection(stage['prediction_id']);candidates=store.get_candidate_set(selection['candidate_set_id'])
            if (selection['kind']!='SYSTEM_PREDICTION' or candidates['completeness']!='FULL'
                    or candidates['frame']!=frame.upper() or candidates['definition_id']!=plan['definition_id']
                    or candidates['trading_day']!=plan['trading_day']):continue
            as_of=datetime.fromisoformat(selection['as_of'])
            if not timedelta(0)<=now-as_of<=timedelta(minutes=10):continue
            assessments={c['symbol']:c['features']['qimo_assessment'] for c in candidates['candidates']
                if 'qimo_assessment' in c['features']}
            previous=dict(journal['events'][-1]['weights']) if journal['events'] else {}
            account=self.account.read() if self.account.path.exists() else None
            if account and journal['events'] and journal['events'][-1]['day'] in journal['settled_days']:
                previous={s:w for s,w in previous.items() if account['summary']['ending_positions'].get(s)}
            if not assessments or all(a['action']=='WAIT_CONTEXT' for a in assessments.values()):
                return {'status':'WAIT_RULE_CONTEXT','blockers':['current_and_previous_theme_facts_missing']}
            # R3 is a hold/exit review: there is no next intraday open left for a fresh entry.
            entry_allowed=allow_entries and frame!='r3'
            for symbol,a in assessments.items():
                if a['action']=='BUY' and entry_allowed:
                    rule=self.market.execution_rules(now.date(),symbol).at(symbol,now)
                    if rule is None or rule['suspended'] or rule['st']:
                        assessments[symbol]={**a,'action':'WAIT_CONTEXT','reason':'执行规则不支持新开仓'}
            weights=portfolio_targets(previous,assessments,allow_entries=entry_allowed)
            # A HOLD does not rebalance a winning position just to maintain a percentage.
            previous_event=journal['events'][-1]['weights'] if journal['events'] else {}
            if weights==previous_event:return {'status':'HOLD_OR_NO_TRADE'}
            now=max(now,self.now_fn().astimezone(TZ))
            if now.date().isoformat()!=plan['trading_day'] or now.time()>end:return {}
            event={'id':digest({'selection':selection['selection_id'],'policy':POLICY}),
                'day':plan['trading_day'],'at':now.isoformat(),'frame':frame.upper(),'weights':weights,
                'selection_id':selection['selection_id'],'selection_hash':digest(selection),
                'assessments':assessments,'rule_origin':POLICY['origin']}
            journal['events'].append(event);write_checked(self.root/'journal.json',journal)
            return {'status':'PORTFOLIO_SIGNAL_RECORDED'}
        return {}

    def settle(self,journal,days,now):
        from quantlab.execution.paper import frame as bar_frame
        if not journal['events']:return {'status':'NO_PENDING_SIGNAL'}
        first=date.fromisoformat(journal['events'][0]['day'])
        current=self.account.read() if self.account.path.exists() else None
        last=date.fromisoformat(journal['settled_days'][-1]) if journal['settled_days'] else first
        if last<days[0]:raise ValueError('TRADING_CALENDAR_HISTORY_GAP')
        ready=[d for d in days if d>=first and datetime.combine(d,time(18,30),TZ)<=now and d.isoformat() not in journal['settled_days']]
        for day in ready:
            events=[e for e in journal['events'] if e['day']==day.isoformat()]
            current=self.account.read() if self.account.path.exists() else None
            symbols=set(current['summary']['ending_positions']) if current else set()
            if current and current['target_events']:symbols.update(current['target_events'][-1]['weights'])
            for event in events:symbols.update(event['weights'])
            all_rules=[];parts=[];cached=[]
            for symbol in sorted(symbols):
                rules=self.market.execution_rules(day,symbol);all_rules.extend(rules.records)
                rule=rules.at(symbol,datetime.combine(day,time(9,30),TZ))
                if rule is None:raise ValueError('EXECUTION_RULE_SESSION_MISMATCH')
                if rule['suspended']:
                    old=[r for r in current['bars'] if r['symbol']==symbol] if current else []
                    if not old:raise ValueError('SUSPENDED_NEW_SYMBOL_WITHOUT_PRICE')
                    cached.append(old[-1]);continue
                self.market.check_corporate_action(day,symbol,current)
                parts.append(self.market.bars(day,symbol,now))
            if cached:parts.append(bar_frame(cached))  # Reuse existing observations; never invent suspension bars.
            if parts:
                bars=pl.concat(parts).sort('datetime','symbol');rules=MarketRules(all_rules)
                for event in sorted(events,key=lambda e:e['at']):
                    current=self.account.read() if self.account.path.exists() else None
                    if current and any(t['source_ref']==event['id'] for t in current['target_events']):continue
                    at=datetime.fromisoformat(event['at']).astimezone(TZ)
                    prefix=bars.filter(pl.col('datetime')<=at)
                    if prefix.is_empty():raise ValueError('NO_TARGET_DELIVERY_BAR')
                    self.account.advance(prefix,rules,CONFIG,as_of=now,target_at=at,
                        target_weights=event['weights'],target_source_ref=event['id'])
                result=self.account.advance(bars,rules,CONFIG,as_of=now)
                journal['last_summary']=result['summary']
            journal['settled_days'].append(day.isoformat());write_checked(self.root/'journal.json',journal)
        return {'status':'SETTLED' if ready else 'WAIT_18:30_RAW_BARS','settled_days':journal['settled_days'][-5:]}
