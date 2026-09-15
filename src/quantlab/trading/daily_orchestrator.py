"""Durable host-side daily orchestration for PREP/AUCTION/R1/R2/R3 Playbook research."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date,datetime,time,timedelta
from pathlib import Path
from uuid import NAMESPACE_URL,uuid5
from zoneinfo import ZoneInfo
import fcntl

from quantlab.data.daily_market_archive import DailyMarketArchive,DailyMarketArchiveError
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest
from .market_snapshot import MarketSnapshotError,MarketSnapshotStore
from .playbook_forward import forward_frame_status,freeze_forward_snapshot
from .playbook_scanner import DailyPlaybookScanner,PlaybookScanError
from .playbook_store import PlaybookError,PlaybookStore,identifier
from .playbook_decision_bridge import PlaybookDecisionBridge,PlaybookDecisionBridgeError
from .prep_scanner import PrepScanError,build_prep_forward_payload,prep_market_snapshot_content,scan_prep_universe

FORMAT='daily-playbook-orchestrator-v1'
TZ=ZoneInfo('Asia/Shanghai')
CAPTURE_READY=time(18,30)
CAPTURE_COOLDOWN=timedelta(minutes=15)
MAX_CAPTURE_ATTEMPTS=8
R1_SNAPSHOT_CUTOFF=time(9,40)
R2_SNAPSHOT_READY=time(11,30)
R2_SNAPSHOT_CUTOFF=time(11,40)
R3_SNAPSHOT_READY=time(15,0)
R3_SNAPSHOT_CUTOFF=time(15,10)
TERMINAL={'COMPLETE','COMPLETE_WITH_MISSED','BLOCKED_PREP_MISSED','BLOCKED_ROUTE_UNKNOWN','BLOCKED_CAPTURE_BUDGET'}


class DailyOrchestratorError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _day(value,name):
    try:return date.fromisoformat(value).isoformat()
    except (TypeError,ValueError):raise DailyOrchestratorError('INVALID_ARGUMENT',name+' 必须为 YYYY-MM-DD。') from None


def _stamp(value):
    if not isinstance(value,datetime) or value.tzinfo is None:
        raise DailyOrchestratorError('INVALID_CLOCK','Orchestrator 时钟必须带时区。')
    return value.astimezone(TZ)


def _snapshot_request(content):
    return str(uuid5(NAMESPACE_URL,'niuniu-daily-orchestrator:market-snapshot:'+digest(content)))


class DailyPlaybookOrchestrator:
    def __init__(self,output,data_root,now_fn=None):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve()
        self.now_fn=now_fn or (lambda:datetime.now().astimezone())
        if not self.output.is_dir():raise DailyOrchestratorError('INVALID_WORKSPACE','产物目录不存在。')
        if not self.data_root.is_dir():raise DailyOrchestratorError('INVALID_DATA_ROOT','行情目录不存在。')
        self.root=self.output/'_daily_orchestrator'

    def _path(self,trading_day):return self.root/(_day(trading_day,'trading_day')+'.json')

    @contextmanager
    def _locked(self,trading_day):
        if self.root.is_symlink():raise DailyOrchestratorError('INVALID_WORKSPACE','Orchestrator 目录不能是符号链接。')
        self.root.mkdir(exist_ok=True);lock=self.root/(trading_day+'.lock')
        if lock.is_symlink():raise DailyOrchestratorError('INVALID_WORKSPACE','Orchestrator lock 不能是符号链接。')
        with lock.open('a+b') as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise DailyOrchestratorError('BUSY','该交易日 Orchestrator 正在运行。') from None
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def _load(self,trading_day):
        path=self._path(trading_day)
        if not path.exists():raise DailyOrchestratorError('NOT_FOUND','该交易日尚未创建 Daily Orchestrator 计划。')
        try:value=read_checked(path)
        except (OSError,ValueError) as exc:raise DailyOrchestratorError('CORRUPT_STATE',str(exc)) from None
        if value.get('format')!=FORMAT or value.get('trading_day')!=trading_day:
            raise DailyOrchestratorError('CORRUPT_STATE','Daily Orchestrator 状态身份不一致。')
        if value['data_root']!=str(self.data_root):
            raise DailyOrchestratorError('DATA_ROOT_CHANGED','计划绑定的行情目录变化。')
        return value

    def _save(self,state):
        if len(str(state))>5_000_000:raise DailyOrchestratorError('STATE_BUDGET','Orchestrator 状态超过5MB。')
        write_checked(self._path(state['trading_day']),state)

    @staticmethod
    def _event(state,stamp,status,detail=''):
        if state.get('status')==status and state.get('events') and state['events'][-1].get('detail')==detail:return
        state['status']=status;state['updated_at']=stamp.isoformat()
        state.setdefault('events',[]).append({'at':stamp.isoformat(),'status':status,'detail':str(detail)[:500]})
        if len(state['events'])>500:state['events']=state['events'][-500:]

    def create_plan(self,trading_day,as_of_session,definition_id,*,target_streak=None,allow_daily_market_capture=False,bridge_to_trading_desk=False):
        trading_day=_day(trading_day,'trading_day');as_of_session=_day(as_of_session,'as_of_session')
        if date.fromisoformat(as_of_session)>=date.fromisoformat(trading_day):
            raise DailyOrchestratorError('INVALID_ARGUMENT','as_of_session 必须早于 trading_day。')
        identifier(definition_id,'definition_id');PlaybookStore(self.output).get_definition(definition_id)
        if target_streak is not None and (type(target_streak) is not int or not 1<=target_streak<=10):
            raise DailyOrchestratorError('INVALID_ARGUMENT','target_streak 必须为1–10或None。')
        if type(allow_daily_market_capture) is not bool or type(bridge_to_trading_desk) is not bool:
            raise DailyOrchestratorError('INVALID_ARGUMENT','capture/bridge 开关必须是布尔值。')
        spec={'trading_day':trading_day,'as_of_session':as_of_session,'definition_id':definition_id,
            'target_streak':target_streak,'allow_daily_market_capture':allow_daily_market_capture,
            'bridge_to_trading_desk':bridge_to_trading_desk,'data_root':str(self.data_root)}
        plan_id=str(uuid5(NAMESPACE_URL,'niuniu-daily-orchestrator-plan:'+digest(spec)))
        stamp=_stamp(self.now_fn())
        with self._locked(trading_day):
            path=self._path(trading_day)
            if path.exists():
                old=self._load(trading_day)
                if old['plan_id']!=plan_id:raise DailyOrchestratorError('PLAN_CONFLICT','同一交易日已有不同 Daily Orchestrator 计划。')
                return old
            state={'format':FORMAT,'plan_id':plan_id,**spec,'created_at':stamp.isoformat(),'updated_at':stamp.isoformat(),
                'status':'CREATED','daily_market':{'status':'PENDING','attempts':0,'last_attempt_at':None,'snapshot_id':None},
                'prep':{'status':'PENDING'},'auction':{'status':'PENDING'},'r1':{'status':'PENDING'},
                'r2':{'status':'PENDING'},'r3':{'status':'PENDING'},
                'supported_frames':['PREP','AUCTION','R1','R2','R3'],'events':[]}
            self._event(state,stamp,'CREATED','计划已创建；不会隐式下载或回填历史预测。');self._save(state);return state

    def get(self,trading_day):
        trading_day=_day(trading_day,'trading_day')
        with self._locked(trading_day):return self._load(trading_day)

    def _revision_count(self,archive,day):
        row=next((r for r in archive.list_days(limit=5000) if r['date']==day),None)
        return row['revision_candidates'] if row else 0

    def _ensure_daily_market(self,state,stamp,sdk=None):
        day=state['as_of_session'];archive=DailyMarketArchive(self.output,now_fn=lambda:stamp)
        try:accepted=archive.accepted(day)
        except DailyMarketArchiveError as exc:raise DailyOrchestratorError(exc.code,str(exc)) from None
        if accepted is not None:
            revisions=self._revision_count(archive,day)
            state['daily_market'].update(status='READY',snapshot_id=accepted['snapshot_id'],revision_candidates=revisions)
            if revisions:
                state['daily_market']['status']='REVISION_REVIEW';self._event(state,stamp,'BLOCKED_REVISION_REVIEW','DailyMarket 存在未接受修订。');return False
            return True
        ready_at=datetime.combine(date.fromisoformat(day),CAPTURE_READY,tzinfo=TZ)
        if stamp<ready_at:
            self._event(state,stamp,'WAIT_DAILY_MARKET_READY','等待 '+ready_at.isoformat());return False
        if not state['allow_daily_market_capture']:
            self._event(state,stamp,'WAIT_DAILY_MARKET','尚无 accepted DailyMarket；计划未授权联网 capture。');return False
        dm=state['daily_market'];last=dm.get('last_attempt_at')
        if last and stamp-datetime.fromisoformat(last).astimezone(TZ)<CAPTURE_COOLDOWN:
            self._event(state,stamp,'WAIT_DAILY_MARKET_COOLDOWN','DailyMarket capture 冷却中。');return False
        if dm['attempts']>=MAX_CAPTURE_ATTEMPTS:
            self._event(state,stamp,'BLOCKED_CAPTURE_BUDGET','DailyMarket capture 已达到单计划8次预算。');return False
        dm['attempts']+=1;dm['last_attempt_at']=stamp.isoformat();dm['status']='CAPTURING';self._save(state)
        try:result=archive.capture(day,sdk=sdk)
        except (DailyMarketArchiveError,OSError,ValueError) as exc:
            dm.update(status='FAILED',last_error=type(exc).__name__+': '+str(exc)[:300])
            self._event(state,stamp,'DAILY_MARKET_CAPTURE_FAILED',dm['last_error']);return False
        if result.get('revision_detected'):
            dm.update(status='REVISION_REVIEW',snapshot_id=result['snapshot_id'])
            self._event(state,stamp,'BLOCKED_REVISION_REVIEW','新抓取结果与 accepted DailyMarket 不同，等待宿主修订确认。');return False
        accepted=archive.accepted(day)
        dm.update(status='READY',snapshot_id=accepted['snapshot_id'] if accepted else result['snapshot_id'],last_error=None)
        return True

    def _prep(self,state,stamp):
        stage=state['prep']
        if stage.get('status')=='FROZEN':return True
        status=forward_frame_status(self.output,state['trading_day'],'PREP',lambda:stamp)
        if not status['can_freeze']:
            if status['forward_status']=='EARLY':self._event(state,stamp,'WAIT_PREP_WINDOW','PREP 尚未开放。')
            else:
                stage['status']='MISSED';self._event(state,stamp,'BLOCKED_PREP_MISSED','PREP 实时窗口已错过，禁止历史补写 SYSTEM_PREDICTION。')
            return False
        if stage.get('status')!='RESERVED':
            try:scan=scan_prep_universe(self.data_root,state['as_of_session'],target_streak=state['target_streak'],daily_market_output=self.output)
            except PrepScanError as exc:
                self._event(state,stamp,'BLOCKED_PREP_DATA',exc.code+': '+str(exc));return False
            if scan['route']['action']=='UNKNOWN' and scan['target_streak'] is None:
                self._event(state,stamp,'BLOCKED_ROUTE_UNKNOWN','Router 未给目标身位且宿主未覆盖 target_streak。');return False
            content=prep_market_snapshot_content(scan,state['trading_day'],stamp.isoformat(),self.data_root)
            stage.update(status='RESERVED',reserved_at=stamp.isoformat(),scan=scan,snapshot_content=content,
                snapshot_request_id=_snapshot_request(content));self._save(state)
        try:
            snapshot=MarketSnapshotStore(self.output,now_fn=lambda:stamp).create(stage['snapshot_request_id'],stage['snapshot_content'])
            if 'forward_payload' not in stage:
                definition=PlaybookStore(self.output).get_definition(state['definition_id'])
                stage['forward_payload']=build_prep_forward_payload(stage['scan'],snapshot,definition);self._save(state)
            frozen=freeze_forward_snapshot(self.output,stage['forward_payload'],now_fn=lambda:stamp)
        except (MarketSnapshotError,PlaybookError,PrepScanError,OSError,ValueError) as exc:
            code=getattr(exc,'code','PREP_FREEZE_FAILED')
            self._event(state,stamp,'BLOCKED_PREP_FREEZE',code+': '+str(exc));return False
        stage.update(status='FROZEN',snapshot_id=snapshot['snapshot_id'],case_id=frozen['case']['case_id'],
            candidate_set_id=frozen['candidate_set']['candidate_set_id'],prediction_id=frozen['prediction']['selection_id'],
            frozen_at=stamp.isoformat());self._event(state,stamp,'PREP_FROZEN','PREP 已冻结。');return True

    def _live_snapshots(self,day,frame,start_clock,end_clock):
        rows=MarketSnapshotStore(self.output).list(trading_day=day,frame=frame,limit=200)['records']
        result=[]
        for row in rows:
            if row.get('capture_status')!='LIVE_NEAR_REALTIME':continue
            moment=datetime.fromisoformat(row['as_of']).astimezone(TZ)
            start=datetime.combine(date.fromisoformat(day),start_clock,tzinfo=TZ)
            end=datetime.combine(date.fromisoformat(day),end_clock,tzinfo=TZ)
            if start<=moment<=end:result.append(row)
        result.sort(key=lambda row:(row['as_of'],row['snapshot_id']))
        return result

    def _freeze_scan(self,state,stage_name,snapshot,stamp,auction_snapshot=None,previous_snapshot=None,reference_prediction_id=''):
        stage=state[stage_name]
        try:
            result=DailyPlaybookScanner(self.output).scan(state['prep']['candidate_set_id'],snapshot['snapshot_id'],
                auction_snapshot['snapshot_id'] if auction_snapshot else '',
                previous_snapshot['snapshot_id'] if previous_snapshot else '',reference_prediction_id)
            frozen=freeze_forward_snapshot(self.output,result['forward_payload'],now_fn=lambda:stamp)
        except (PlaybookScanError,PlaybookError,MarketSnapshotError,OSError,ValueError) as exc:
            code=getattr(exc,'code','SCAN_FREEZE_FAILED')
            if code in ('LOOKAHEAD_BLOCKED','FORWARD_FRAME_NOT_OPEN'):
                stage['status']='MISSED';self._event(state,stamp,stage_name.upper()+'_MISSED',code+': '+str(exc));return False
            self._event(state,stamp,'BLOCKED_'+stage_name.upper(),code+': '+str(exc));return False
        stage.update(status='FROZEN',snapshot_id=snapshot['snapshot_id'],case_id=frozen['case']['case_id'],
            candidate_set_id=frozen['candidate_set']['candidate_set_id'],prediction_id=frozen['prediction']['selection_id'],
            selected_symbols=result['selected_symbols'],ranked_symbols=result['ranked_symbols'],frozen_at=stamp.isoformat())
        self._event(state,stamp,stage_name.upper()+'_FROZEN',f"selected={','.join(result['selected_symbols']) or 'NO_TRADE'}");return True

    def _bridge_stage(self,state,stage_name,stamp):
        if not state.get('bridge_to_trading_desk',False):return True
        stage=state[stage_name]
        if stage.get('status')!='FROZEN' or not stage.get('prediction_id'):return True
        if stage.get('decision_bridge',{}).get('status')=='APPLIED':return True
        try:receipt=PlaybookDecisionBridge(self.output,now_fn=lambda:stamp).apply(stage['prediction_id'])
        except PlaybookDecisionBridgeError as exc:
            stage['decision_bridge']={'status':'FAILED','code':exc.code,'error':str(exc)[:400]}
            self._event(state,stamp,'DECISION_BRIDGE_FAILED',stage_name+': '+exc.code+': '+str(exc));return False
        stage['decision_bridge']={'status':'APPLIED','selection_id':receipt['selection_id'],
            'no_trade':receipt['no_trade'],'decisions':receipt['decisions'],'skipped':receipt['skipped']}
        return True

    def _auction(self,state,stamp):
        stage=state['auction']
        if stage.get('status') in ('FROZEN','MISSED'):return stage['status']=='FROZEN'
        status=forward_frame_status(self.output,state['trading_day'],'AUCTION',lambda:stamp)
        if status['can_freeze']:
            rows=self._live_snapshots(state['trading_day'],'AUCTION',time(9,25),time(9,30))
            if not rows:self._event(state,stamp,'WAIT_AUCTION_MARKET_SNAPSHOT','等待09:25后正式 LIVE_NEAR_REALTIME AUCTION MarketSnapshot。');return False
            return self._freeze_scan(state,'auction',rows[0],stamp)
        if status['forward_status'] in ('EARLY','WAIT_DATA'):
            self._event(state,stamp,'WAIT_AUCTION_DATA_READY','等待09:25竞价数据就绪。');return False
        stage['status']='MISSED';self._event(state,stamp,'AUCTION_MISSED','AUCTION 实时冻结窗口已错过；不回填预测。');return False

    def _r1(self,state,stamp):
        stage=state['r1']
        if stage.get('status')=='FROZEN':return True
        if stage.get('status')=='MISSED':return False
        status=forward_frame_status(self.output,state['trading_day'],'R1',lambda:stamp)
        if status['forward_status'] in ('EARLY','WAIT_DATA'):
            self._event(state,stamp,'WAIT_R1_DATA_READY','等待09:35首个完整5分钟窗口。');return False
        auction_rows=self._live_snapshots(state['trading_day'],'AUCTION',time(9,25),time(9,30))
        r1_rows=self._live_snapshots(state['trading_day'],'R1',time(9,35),R1_SNAPSHOT_CUTOFF)
        if not status['can_freeze']:
            stage['status']='MISSED';self._event(state,stamp,'R1_MISSED','R1 实时冻结窗口已错过；不回填预测。');return False
        if not auction_rows:
            if stamp.time()>R1_SNAPSHOT_CUTOFF:
                stage['status']='MISSED';self._event(state,stamp,'R1_MISSED','缺少09:25–09:30实时AUCTION快照。')
            else:self._event(state,stamp,'WAIT_AUCTION_SNAPSHOT_FOR_R1','R1 需要同日实时AUCTION快照。')
            return False
        if not r1_rows:
            if stamp.time()>R1_SNAPSHOT_CUTOFF:
                stage['status']='MISSED';self._event(state,stamp,'R1_MISSED','09:35–09:40未取得正式实时R1快照。')
            else:self._event(state,stamp,'WAIT_R1_MARKET_SNAPSHOT','等待09:35–09:40正式 LIVE_NEAR_REALTIME R1 MarketSnapshot。')
            return False
        snapshot=r1_rows[0]
        as_of=datetime.fromisoformat(snapshot['as_of']).astimezone(TZ)
        if stamp-as_of>timedelta(minutes=10):
            stage['status']='MISSED';self._event(state,stamp,'R1_MISSED','首个R1快照已超过10分钟实时冻结限制。');return False
        return self._freeze_scan(state,'r1',snapshot,stamp,auction_rows[0])

    def _later_review(self,state,stage_name,frame,previous_stage,previous_frame,ready_clock,cutoff,previous_window):
        stage=state[stage_name]
        if stage.get('status')=='FROZEN':return True
        if stage.get('status')=='MISSED':return False
        stamp=state['_tick_stamp']
        status=forward_frame_status(self.output,state['trading_day'],frame,lambda:stamp)
        if status['forward_status'] in ('EARLY','WAIT_DATA'):
            self._event(state,stamp,'WAIT_'+frame+'_DATA_READY','等待'+ready_clock.strftime('%H:%M')+' '+frame+'复核快照。');return False
        current_rows=self._live_snapshots(state['trading_day'],frame,ready_clock,cutoff)
        previous=None
        prior_stage=state[previous_stage]
        if status['can_freeze'] and prior_stage.get('status')!='FROZEN':
            stage['status']='MISSED';self._event(state,stamp,frame+'_MISSED','前一阶段 '+previous_frame+' 没有冻结 prediction，continuation review 不补造选择。');return False
        if prior_stage.get('status')=='FROZEN' and prior_stage.get('snapshot_id'):
            try:previous=MarketSnapshotStore(self.output).get(prior_stage['snapshot_id'])
            except MarketSnapshotError:previous=None
        if previous is None:
            previous_rows=self._live_snapshots(state['trading_day'],previous_frame,*previous_window)
            previous=previous_rows[0] if previous_rows else None
        if not status['can_freeze']:
            stage['status']='MISSED';self._event(state,stamp,frame+'_MISSED',frame+' 实时冻结窗口已错过；不回填预测。');return False
        if previous is None:
            if stamp.time()>cutoff:
                stage['status']='MISSED';self._event(state,stamp,frame+'_MISSED','缺少前一阶段 '+previous_frame+' LIVE_NEAR_REALTIME 快照。')
            else:self._event(state,stamp,'WAIT_'+previous_frame+'_SNAPSHOT_FOR_'+frame,frame+' 需要同日 '+previous_frame+' 实时事实快照。')
            return False
        if not current_rows:
            if stamp.time()>cutoff:
                stage['status']='MISSED';self._event(state,stamp,frame+'_MISSED',ready_clock.strftime('%H:%M')+'–'+cutoff.strftime('%H:%M')+'未取得正式实时 '+frame+' 快照。')
            else:self._event(state,stamp,'WAIT_'+frame+'_MARKET_SNAPSHOT','等待正式 LIVE_NEAR_REALTIME '+frame+' MarketSnapshot。')
            return False
        snapshot=current_rows[0];as_of=datetime.fromisoformat(snapshot['as_of']).astimezone(TZ)
        if stamp-as_of>timedelta(minutes=10):
            stage['status']='MISSED';self._event(state,stamp,frame+'_MISSED',frame+'快照已超过10分钟实时冻结限制。');return False
        return self._freeze_scan(state,stage_name,snapshot,stamp,previous_snapshot=previous,
            reference_prediction_id=prior_stage.get('prediction_id',''))

    def _r2(self,state,stamp):
        state['_tick_stamp']=stamp
        try:return self._later_review(state,'r2','R2','r1','R1',R2_SNAPSHOT_READY,R2_SNAPSHOT_CUTOFF,(time(9,35),R1_SNAPSHOT_CUTOFF))
        finally:state.pop('_tick_stamp',None)

    def _r3(self,state,stamp):
        state['_tick_stamp']=stamp
        try:return self._later_review(state,'r3','R3','r2','R2',R3_SNAPSHOT_READY,R3_SNAPSHOT_CUTOFF,(R2_SNAPSHOT_READY,R2_SNAPSHOT_CUTOFF))
        finally:state.pop('_tick_stamp',None)

    def tick(self,trading_day,*,now=None,daily_market_sdk=None):
        trading_day=_day(trading_day,'trading_day');stamp=_stamp(now or self.now_fn())
        with self._locked(trading_day):
            state=self._load(trading_day)
            if state['status'] in TERMINAL:return state
            # Old v1 in-progress plans are upgraded in place; historical terminal plans remain untouched.
            state.setdefault('r2',{'status':'PENDING'});state.setdefault('r3',{'status':'PENDING'})
            state['supported_frames']=['PREP','AUCTION','R1','R2','R3'];state.pop('unsupported_frames',None)
            try:
                if not self._ensure_daily_market(state,stamp,sdk=daily_market_sdk):self._save(state);return state
                if not self._prep(state,stamp):self._save(state);return state
                self._auction(state,stamp)
                if state['auction'].get('status') not in ('FROZEN','MISSED'):
                    self._save(state);return state
                if state['auction'].get('status')=='FROZEN' and not self._bridge_stage(state,'auction',stamp):
                    self._save(state);return state
                self._r1(state,stamp)
                if state['r1'].get('status') not in ('FROZEN','MISSED'):
                    self._save(state);return state
                if state['r1'].get('status')=='FROZEN' and not self._bridge_stage(state,'r1',stamp):
                    self._save(state);return state
                self._r2(state,stamp)
                if state['r2'].get('status') not in ('FROZEN','MISSED'):
                    self._save(state);return state
                if state['r2'].get('status')=='FROZEN' and not self._bridge_stage(state,'r2',stamp):
                    self._save(state);return state
                self._r3(state,stamp)
                if state['r3'].get('status') not in ('FROZEN','MISSED'):
                    self._save(state);return state
                if state['r3'].get('status')=='FROZEN' and not self._bridge_stage(state,'r3',stamp):
                    self._save(state);return state
                missed=[name.upper() for name in ('auction','r1','r2','r3') if state[name].get('status')=='MISSED']
                self._event(state,stamp,'COMPLETE_WITH_MISSED' if missed else 'COMPLETE',
                    'PREP/AUCTION/R1/R2/R3 v2 编排结束。'+((' missed='+','.join(missed)) if missed else ''))
            except DailyOrchestratorError:raise
            except (OSError,ValueError,KeyError,TypeError) as exc:
                self._event(state,stamp,'BLOCKED',type(exc).__name__+': '+str(exc)[:400])
            self._save(state);return state


__all__=['FORMAT','TERMINAL','DailyOrchestratorError','DailyPlaybookOrchestrator']
