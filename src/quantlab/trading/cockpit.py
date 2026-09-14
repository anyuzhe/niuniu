"""Read-only Trading Cockpit aggregation over durable workspace evidence."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.agent.research_agenda import ResearchAgendaService
from quantlab.agent.watch_store import WatchStore
from .decision import FRAME_ORDER
from .decision_store import DecisionStore
from .theme_store import ThemeStore
from .market_snapshot import MarketSnapshotStore
from .playbook_paper_plan import PlaybookPaperPlanService

CANDIDATE_ACTIONS={'DISCOVERED','WATCH','READY'}
PLAN_ACTIONS={'PLAN_OPEN','OPEN','ADD','HOLD','REDUCE','EXIT','INVALIDATED'}
STATE_PRIORITY={'MAIN_RISE':8,'ACCELERATION':7,'START':6,'REPAIR':5,'PREHEAT':4,'DIVERGENCE':3,'OVERHEAT':2,'DECLINE':1,'UNKNOWN':0}


class TradingCockpitService:
    def __init__(self,output,data_root=None):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve() if data_root else None
        if not self.output.is_dir():raise ValueError('Trading Cockpit workspace does not exist')
        self.decisions=DecisionStore(self.output);self.themes=ThemeStore(self.output);self.watches=WatchStore(self.output)
        self.market_snapshots=MarketSnapshotStore(self.output)

    def _theme_records(self,day):
        try:return self.themes.list(start=day,end=day,limit=2000)['records']
        except Exception:return []

    def _watch_rows(self,limit=30):
        listing=self.watches.list();rows=[]
        for item in listing['watches'][:limit]:
            latest=None;alerts=[]
            try:
                _,state=self.watches.read(item['watch_id'])
                if state['history']:
                    latest=self.watches.snapshot(item['watch_id'],state['history'][-1]);alerts=latest.get('alerts') or []
            except (OSError,ValueError,KeyError,TypeError):pass
            rows.append({**item,'latest':latest,'alerts':alerts,'alert_count':len(alerts)})
        return {'rows':rows,'unreadable':listing['unreadable']}

    def _agenda(self,limit=10):
        try:return ResearchAgendaService(self.output,self.data_root).build(limit=limit)
        except Exception as exc:
            return {'items':[],'total':0,'counts':{},'error':type(exc).__name__,'new_research_jobs':0,'automatic_execution':False}

    def build(self,trading_day='',agenda_limit=10):
        if not isinstance(trading_day,str):raise ValueError('trading_day must be text')
        current=self.decisions.latest_by_symbol(limit=500)
        known_days={d['trading_day'] for d in current}
        try:
            known_days.update(r['trading_day'] for r in self.themes.list(limit=2000)['records'])
        except Exception:pass
        if trading_day:
            day=trading_day;day_source='explicit'
        elif known_days:
            day=max(known_days);day_source='latest_workspace_evidence'
        else:
            day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat();day_source='natural_day_fallback'
        day_decisions=self.decisions.list(trading_day=day,include_superseded=False,limit=200)['records']
        latest_frame=max((FRAME_ORDER.get(d['frame'],-1) for d in day_decisions),default=-1)
        saved_frame=next((name for name,index in FRAME_ORDER.items() if index==latest_frame),None)
        themes=self._theme_records(day)
        themes.sort(key=lambda r:(STATE_PRIORITY.get(r['machine_state'],0),STATE_PRIORITY.get(r['ai_state'],0),r['theme']),reverse=True)
        try:market_snapshots=self.market_snapshots.list(trading_day=day,limit=100)['records']
        except Exception:market_snapshots=[]
        latest_market_snapshots={}
        for snapshot in market_snapshots:latest_market_snapshots.setdefault(snapshot['frame'],snapshot)
        candidates=[d for d in current if d['action'] in CANDIDATE_ACTIONS]
        plans=[d for d in current if d['action'] in PLAN_ACTIONS]
        risks=[]
        for d in current:
            flags=d.get('risk_flags') or []
            if flags or d.get('invalidation') or d.get('exit_condition'):
                risks.append({'kind':'decision','symbol':d['symbol'],'action':d['action'],'risk_flags':flags,
                    'invalidation':d.get('invalidation',''),'exit_condition':d.get('exit_condition',''),'decision_id':d['decision_id']})
        for t in themes:
            if t.get('risk_review'):
                risks.append({'kind':'theme','theme':t['theme'],'risk_review':t['risk_review'],'snapshot_id':t['snapshot_id']})
        agenda=self._agenda(agenda_limit);watch=self._watch_rows()
        try:paper_plans=PlaybookPaperPlanService(self.output).list(limit=200)
        except Exception:paper_plans=[]
        return {
            'trading_day':day,'day_source':day_source,'latest_saved_frame':saved_frame,
            'current_states':current,'state_counts':dict(Counter(d['action'] for d in current)),
            'day_decisions':day_decisions,'candidates':candidates,'plans':plans,
            'themes':themes,'theme_fact_snapshots':sum(bool(t.get('facts')) for t in themes),
            'market_snapshots':market_snapshots,'latest_market_snapshots':latest_market_snapshots,
            'ai_conclusions':[d for d in current if d.get('ai_thesis')][:12],
            'risks':risks[:30],'agenda':agenda,'watches':watch,'paper_plans':paper_plans,
            'paper_plan_executed':sum(p.get('status','').startswith('EXECUTED') for p in paper_plans),
            'market_facts_policy':'只展示正式 Theme Snapshot 中带 facts_source/facts_as_of 的事实；不跨主题加总，不用 AI 文本补市场数字。',
            'new_research_jobs':0,'automatic_execution':False,
        }
