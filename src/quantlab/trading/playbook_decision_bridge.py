"""Deterministic bridge from frozen Playbook SYSTEM_PREDICTION to Strategy Intent.

The bridge may create/maintain WATCH/READY only. It never creates PLAN_OPEN/OPEN,
never writes Paper positions, and never turns NO_TRADE into a synthetic stock Decision.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from uuid import NAMESPACE_URL,UUID,uuid5
import fcntl

from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest
from .decision import FRAME_ORDER,business_order_key
from .decision_store import DecisionError
from .playbook_store import PlaybookError,PlaybookStore
from .strategy_intent import StrategyIntentService

FORMAT='playbook-decision-bridge-v1'
CANDIDATE_ACTIONS={'DISCOVERED','WATCH','READY'}


class PlaybookDecisionBridgeError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _uuid(value,name):
    try:
        if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise PlaybookDecisionBridgeError('INVALID_ARGUMENT',name+' 需要规范 UUID。') from None
    return value


class PlaybookDecisionBridge:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise PlaybookDecisionBridgeError('INVALID_WORKSPACE','工作空间不存在。')
        self.root=self.output/'_trading'/'playbook_bridge'
        self.playbooks=PlaybookStore(self.output);self.intent=StrategyIntentService(self.output,now_fn=self.now_fn)

    def _path(self,selection_id):return self.root/(selection_id+'.json')

    @contextmanager
    def _locked(self,selection_id):
        _uuid(selection_id,'selection_id')
        if self.root.is_symlink():raise PlaybookDecisionBridgeError('INVALID_WORKSPACE','Playbook bridge 目录不能是符号链接。')
        self.root.mkdir(parents=True,exist_ok=True);lock=self.root/(selection_id+'.lock')
        if lock.is_symlink():raise PlaybookDecisionBridgeError('INVALID_WORKSPACE','Playbook bridge lock 不能是符号链接。')
        with lock.open('a+b') as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise PlaybookDecisionBridgeError('BUSY','该 Selection 正在桥接。') from None
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def _read(self,selection_id):
        path=self._path(selection_id)
        if not path.exists():return None
        try:value=read_checked(path)
        except (OSError,ValueError) as exc:raise PlaybookDecisionBridgeError('CORRUPT_RECEIPT',str(exc)) from None
        if value.get('format')!=FORMAT or value.get('selection_id')!=selection_id:
            raise PlaybookDecisionBridgeError('CORRUPT_RECEIPT','Playbook bridge receipt 身份不一致。')
        return value

    def get(self,selection_id):
        with self._locked(_uuid(selection_id,'selection_id')):
            value=self._read(selection_id)
            if value is None:raise PlaybookDecisionBridgeError('NOT_FOUND','该 Selection 尚无 bridge receipt。')
            return value

    def list(self,limit=200):
        if type(limit) is not int or not 1<=limit<=2000:raise PlaybookDecisionBridgeError('INVALID_ARGUMENT','limit 必须为1–2000。')
        if not self.root.exists():return []
        rows=[]
        for path in sorted(self.root.glob('*.json'),reverse=True):
            try:value=self._read(path.stem)
            except PlaybookDecisionBridgeError:continue
            rows.append(value)
            if len(rows)>=limit:break
        return rows

    @staticmethod
    def _snapshot_for_frame(bundle,frame):
        matching=[s for s in bundle.get('market_snapshots',[]) if s.get('frame')==frame]
        if not matching:return None
        return sorted(matching,key=lambda s:(s['as_of'],s['snapshot_id']))[-1]

    @staticmethod
    def _execution_profile(bundle,symbol,frame):
        snapshot=PlaybookDecisionBridge._snapshot_for_frame(bundle,frame)
        if snapshot:
            item=next((x for x in snapshot.get('instruments',[]) if x['symbol']==symbol),None)
            if item:return item.get('execution_profile','UNKNOWN')
        candidate=bundle.get('candidate_set') or {}
        item=next((x for x in candidate.get('candidates',[]) if x['symbol']==symbol),None)
        return ((item or {}).get('features') or {}).get('execution_profile','UNKNOWN')

    def _decision_content(self,selection,bundle,symbol,target_action,current):
        case=bundle['case'];definition=bundle['definition'];candidate=bundle['candidate_set'];frame=case['frame']
        snapshot=self._snapshot_for_frame(bundle,frame);profile=self._execution_profile(bundle,symbol,frame)
        reasons=selection.get('reasons',{}).get(symbol,[])
        risk=['PLAYBOOK_SYSTEM_PREDICTION_NOT_FILL']
        if candidate['completeness']!='FULL':risk.append('CANDIDATE_SET_NOT_FULL')
        if candidate['pit_status']!='STRICT_PIT':risk.append('PIT_NOT_STRICT')
        if profile=='QUEUE_DEPENDENT':risk.append('QUEUE_DEPENDENT')
        evidence=[f"playbook_selection:{selection['selection_id']}",f"candidate_set:{candidate['candidate_set_id']}",
            f"playbook_case:{case['case_id']}",f"playbook_definition:{definition['definition_id']}"]
        evidence.extend(f'market_snapshot:{value}' for value in case.get('market_snapshot_ids',[]))
        previous=current['action'] if current else 'EMPTY'
        machine=f"Playbook {definition['playbook_key']}@{definition['version']} SYSTEM_PREDICTION selected; " \
            f"intent {previous}->{target_action}; execution={profile}"
        if reasons:machine+='; reasons='+' / '.join(reasons[:6])
        return {'symbol':symbol,'trading_day':case['trading_day'],'frame':frame,'action':target_action,
            'role_id':'system','agent_id':'playbook_decision_bridge','model_provider':'','model_id':'',
            'prompt_version':'deterministic-v1','market_snapshot_id':snapshot['snapshot_id'] if snapshot else '',
            'rule_snapshot_id':f"playbook:{definition['definition_id']}:{definition['definition_hash']}",
            'research_evidence_ids':evidence[:100],'risk_flags':risk,'theme':'','theme_role':'',
            'machine_state':machine,'ai_thesis':'','buy_zone':'','confirm_trigger':'',
            'invalidation':'','hold_reason':'','add_condition':'','reduce_condition':'','exit_condition':'',
            'transition_reason':'SYSTEM_PREDICTION 只同步为观察/准备状态，不表示计划开仓或成交。',
            'outcome':'','source':'playbook_system_prediction','effective_at':selection['as_of']}

    def apply(self,selection_id):
        selection_id=_uuid(selection_id,'selection_id')
        with self._locked(selection_id):
            try:selection=self.playbooks.get_selection(selection_id)
            except PlaybookError as exc:raise PlaybookDecisionBridgeError(exc.code,str(exc)) from None
            if selection['kind']!='SYSTEM_PREDICTION':
                raise PlaybookDecisionBridgeError('NOT_SYSTEM_PREDICTION','只有真实 SYSTEM_PREDICTION 可以进入 Trading Desk bridge。')
            selection_hash=digest(selection);existing=self._read(selection_id)
            if existing:
                if existing['selection_hash']!=selection_hash:raise PlaybookDecisionBridgeError('SOURCE_CHANGED','Selection 在 bridge 后发生变化。')
                return existing
            try:bundle=self.playbooks.case_bundle(selection['case_id'])
            except PlaybookError as exc:raise PlaybookDecisionBridgeError(exc.code,str(exc)) from None
            case=bundle['case'];created=[];skipped=[]
            for symbol in selection['selected_symbols']:
                same=self.intent.store.list(symbol=symbol,trading_day=case['trading_day'],frame=case['frame'],include_superseded=False,limit=20)['records']
                evidence_key='playbook_selection:'+selection_id
                linked=next((row for row in same if evidence_key in row.get('research_evidence_ids',[])),None)
                if linked:
                    created.append({'symbol':symbol,'decision_id':linked['decision_id'],'action':linked['action'],'created':False});continue
                if same:
                    skipped.append({'symbol':symbol,'reason':'FRAME_OCCUPIED','decision_id':same[0]['decision_id']});continue
                current=self.intent.current(symbol)
                new_key=(case['trading_day'],FRAME_ORDER.get(case['frame'],-1),selection['as_of'])
                if current and business_order_key(current)>new_key:
                    skipped.append({'symbol':symbol,'reason':'LATER_INTENT_EXISTS','decision_id':current['decision_id']});continue
                if current is None:target='WATCH'
                elif current['action']=='DISCOVERED':target='WATCH'
                elif current['action'] in ('WATCH','READY'):target=current['action']
                else:
                    skipped.append({'symbol':symbol,'reason':'EXISTING_PLAN_OR_POSITION','decision_id':current['decision_id'],'action':current['action']});continue
                content=self._decision_content(selection,bundle,symbol,target,current)
                request=str(uuid5(NAMESPACE_URL,'niuniu-playbook-decision:'+selection_id+':'+symbol+':'+target))
                try:decision=self.intent.transition(request,content)
                except DecisionError as exc:raise PlaybookDecisionBridgeError(exc.code,str(exc)) from None
                created.append({'symbol':symbol,'decision_id':decision['decision_id'],'action':decision['action'],'created':True})
            stamp=self.now_fn()
            if not isinstance(stamp,datetime) or stamp.tzinfo is None:raise PlaybookDecisionBridgeError('INVALID_CLOCK','Bridge 时钟必须带时区。')
            receipt={'format':FORMAT,'selection_id':selection_id,'selection_hash':selection_hash,
                'candidate_set_id':selection['candidate_set_id'],'case_id':selection['case_id'],'definition_id':selection['definition_id'],
                'trading_day':case['trading_day'],'frame':case['frame'],'selected_symbols':selection['selected_symbols'],
                'no_trade':not bool(selection['selected_symbols']),'decisions':created,'skipped':skipped,
                'created_at':stamp.astimezone(timezone.utc).isoformat(),
                'policy':'SYSTEM_PREDICTION may create/maintain WATCH/READY only; never PLAN_OPEN/OPEN/Paper fill.'}
            write_checked(self._path(selection_id),receipt);return receipt


__all__=['PlaybookDecisionBridgeError','PlaybookDecisionBridge']
