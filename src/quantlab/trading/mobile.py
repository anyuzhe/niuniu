"""P12 stateless mobile/bot facade over the authoritative Niuniu stores."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.agent.system_health import SystemHealthService
from .cockpit import CANDIDATE_ACTIONS,PLAN_ACTIONS,STATE_PRIORITY
from .decision import FRAME_ORDER
from .decision_store import DecisionStore,DecisionError
from .paper_lifecycle import PaperLifecycleAnalytics
from .stock_dossier import StockDossier
from .theme_store import ThemeStore

FORMAT='niuniu-mobile-brief-v1'
DECISION_FIELDS=('decision_id','symbol','trading_day','frame','action','theme','theme_role','submitted_at',
    'ai_thesis','risk_flags','invalidation','confirm_trigger','entry_condition','exit_condition')


def _pick(value,fields):
    return {field:value.get(field) for field in fields if value.get(field) not in (None,'',[],{})}


def _decision(value):
    return _pick(value,DECISION_FIELDS) if isinstance(value,dict) else None


def _theme(value):
    return _pick(value,('snapshot_id','theme','trading_day','frame','machine_state','ai_state','risk_review','facts','facts_as_of','facts_source'))


class MobileBriefService:
    """Read-only presentation layer. It has no mobile-owned persistence."""
    def __init__(self,output,data_root=None):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve() if data_root else None
        if not self.output.is_dir():raise ValueError('Mobile workspace does not exist')

    @staticmethod
    def _policy():
        return {'read_only':True,'mobile_state_store':None,'bot_state_store':None,'automatic_execution':False,
            'real_trade':False,'authoritative_sources':{
                'decisions':'shared Decision Ledger','stocks':'shared Stock Dossier evidence','paper':'shared Paper Lifecycle',
                'health':'shared System Health','memory':'shared Agent/Research Memory through existing APIs'},
            'remote_access':'Workbench and MCP remain loopback-only without an authenticated reverse proxy or tunnel.'}

    def system_health(self):
        return SystemHealthService(self.output,self.data_root).build()

    def decisions(self,symbol,limit=100):
        symbol=StockDossier.validate_symbol(symbol)
        if type(limit) is not int or not 1<=limit<=200:raise ValueError('limit must be 1..200')
        try:rows=DecisionStore(self.output).timeline(symbol,include_superseded=True,limit=limit)['records']
        except DecisionError as exc:
            if exc.code=='NOT_FOUND':rows=[]
            else:raise
        return {'format':FORMAT,'symbol':symbol,'records':[_decision(row) for row in rows],
            'total':len(rows),'policy':self._policy()}

    def stock(self,symbol):
        symbol=StockDossier.validate_symbol(symbol)
        try:value=StockDossier(self.output).get(symbol)
        except DecisionError as exc:
            if exc.code!='NOT_FOUND':raise
            value={'symbol':symbol,'current_decision':None,'decision_current':[],'decision_history':[],
                'experiments':[],'watches':[],'playbooks':[],'unreadable_watches':0,'themes':[],
                'counts':{'decision_current':0,'decision_history':0,'experiments':0,'watches':0,'playbooks':0}}
        experiments=[_pick(row,('run_id','created_at','status','kind','question','factor_id','theory_id','timeframe','start','end')) for row in value['experiments'][:20]]
        watches=[_pick(row,('watch_id','name','status','latest_snapshot_id','latest_source_run_id','latest_change','latest_alerts')) for row in value['watches'][:20]]
        playbooks=[_pick(row,('definition_id','playbook_key','version','case_id','trading_day','frame','candidate_set_id','completeness','pit_status','selected_by','unselected_by')) for row in value['playbooks'][:30]]
        return {'format':FORMAT,'symbol':symbol,'current_decision':_decision(value.get('current_decision')),
            'decision_history':[_decision(row) for row in value['decision_history'][:50]],'themes':value.get('themes',[])[:20],
            'experiments':experiments,'watches':watches,'playbooks':playbooks,'counts':value['counts'],
            'omitted':{'decision_history':max(0,len(value['decision_history'])-50),'experiments':max(0,len(value['experiments'])-20),
                'watches':max(0,len(value['watches'])-20),'playbooks':max(0,len(value['playbooks'])-30)},'policy':self._policy()}

    def build(self,trading_day='',symbol=''):
        if not isinstance(trading_day,str) or len(trading_day)>10:raise ValueError('trading_day must be YYYY-MM-DD or blank')
        if not isinstance(symbol,str) or len(symbol)>16:raise ValueError('symbol is invalid')
        decisions=DecisionStore(self.output);themes_store=ThemeStore(self.output)
        current=decisions.latest_by_symbol(limit=500);all_themes=themes_store.list(limit=2000)['records']
        known_days={row['trading_day'] for row in current};known_days.update(row['trading_day'] for row in all_themes)
        if trading_day:day=trading_day;day_source='explicit'
        elif known_days:day=max(known_days);day_source='latest_workspace_evidence'
        else:day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat();day_source='natural_day_fallback'
        day_decisions=decisions.list(trading_day=day,include_superseded=False,limit=200)['records']
        latest_index=max((FRAME_ORDER.get(row['frame'],-1) for row in day_decisions),default=-1)
        latest_frame=next((name for name,index in FRAME_ORDER.items() if index==latest_index),None)
        themes=[row for row in all_themes if row['trading_day']==day]
        themes.sort(key=lambda row:(STATE_PRIORITY.get(row['machine_state'],0),STATE_PRIORITY.get(row['ai_state'],0),row['theme']),reverse=True)
        candidates=[row for row in current if row['action'] in CANDIDATE_ACTIONS];plans=[row for row in current if row['action'] in PLAN_ACTIONS]
        risks=[]
        for row in current:
            if row.get('risk_flags') or row.get('invalidation') or row.get('exit_condition'):
                risks.append({'kind':'decision','symbol':row['symbol'],'action':row['action'],'risk_flags':row.get('risk_flags') or [],
                    'invalidation':row.get('invalidation',''),'exit_condition':row.get('exit_condition',''),'decision_id':row['decision_id']})
        for row in themes:
            if row.get('risk_review'):risks.append({'kind':'theme','theme':row['theme'],'risk_review':row['risk_review'],'snapshot_id':row['snapshot_id']})
        try:paper=PaperLifecycleAnalytics(self.output).build()
        except (OSError,ValueError,KeyError,TypeError):paper={'paper_plans':0,'paper_executions':0,'paper_reviews':0,'dynamic_account_count':0,'paper_rebalances':0,'automatic_real_trade':False}
        health=self.system_health();compact_current=[_decision(row) for row in current[:60]]
        result={'format':FORMAT,'trading_day':day,'day_source':day_source,'latest_saved_frame':latest_frame,
            'state_counts':dict(Counter(row['action'] for row in current)),'candidates':[_decision(row) for row in candidates[:20]],
            'plans':[_decision(row) for row in plans[:20]],'themes':[_theme(row) for row in themes[:12]],'risks':risks[:20],
            'current_states':compact_current,'paper_lifecycle':paper,'system_health':{'checked_at':health['checked_at'],'summary':health['summary'],
                'blockers':health['blockers'][:20],'warnings':health['warnings'][:20]},
            'counts':{'current_states':len(current),'candidates':len(candidates),'plans':len(plans),'themes':len(themes),'risks':len(risks)},
            'policy':self._policy()}
        result['limit_review']=self.limit_review(day)
        if symbol.strip():result['stock']=self.stock(symbol.strip())
        return result

    def limit_review(self,day):
        """Latest layered close review on or before ``day`` from the shared research store; no mobile-owned state."""
        from .daily_review import DailyReviewError,DailyReviewLibrary,render_markdown
        try:review=DailyReviewLibrary(self.output).latest_on_or_before(day)
        except (DailyReviewError,OSError,ValueError,KeyError) as exc:return {'available':False,'error':type(exc).__name__}
        if review is None:return {'available':False}
        limit=review['facts']['limit'];state=review['machine_state']
        return {'available':True,'trading_day':review['trading_day'],'review_id':review['review_id'],'phase':state['phase'],
            'temperature':state['temperature'],'limit_up_count':limit['limit_up_count'],'limit_down_count':limit['limit_down_count'],
            'broken_rate':limit['broken_rate'],'max_streak':limit['max_streak'],'markdown':render_markdown(review),
            'qualification':'research_only'}


__all__=['FORMAT','MobileBriefService']
