"""P13-B0 real-broker readiness gate. No connection or order execution exists here."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import json,math,re

from quantlab.storage.codec import digest
from .contracts import BrokerSnapshotError,SENSITIVE
from .shadow import BrokerShadowReconciler
from .store import BrokerSnapshotStore

POLICY_FORMAT='niuniu-real-trade-policy-v1'
CAPABILITY_FORMAT='niuniu-broker-capability-v1'
ADAPTER_ID=re.compile(r'^[A-Za-z0-9_.-]{1,120}$')

_JSON_EXPORT_PROFILE={'format':CAPABILITY_FORMAT,'adapter_id':'json-export-v1','provider':'generic-json-export',
    'transport':'offline-file','implemented':True,'live_channel':False,'account_snapshot':True,
    'account_stream':False,'quote_stream':False,'order_submit':False,'order_cancel':False,
    'fund_transfer':False,'credential_storage':False}


def json_export_capabilities():return dict(_JSON_EXPORT_PROFILE)


class BrokerCapabilityRegistry:
    def __init__(self,profiles=None):
        self._profiles={p['adapter_id']:dict(p) for p in (profiles or [_JSON_EXPORT_PROFILE])}
    def list(self):return [dict(self._profiles[key]) for key in sorted(self._profiles)]
    def get(self,adapter_id):return dict(self._profiles[adapter_id]) if adapter_id in self._profiles else None
    def live(self):return [p for p in self.list() if p['implemented'] and p['live_channel']]


def _optional_number(value,name,*,ratio=False):
    if value is None:return None
    if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
        raise BrokerSnapshotError('INVALID_POLICY',name+' 必须是正有限数或 null。')
    value=float(value)
    if ratio and value>1:raise BrokerSnapshotError('INVALID_POLICY',name+' 必须不大于1。')
    return value


def _policy_sensitive(raw):
    if not isinstance(raw,dict):return
    for key in raw:
        if SENSITIVE.search(str(key)):
            raise BrokerSnapshotError('SENSITIVE_FIELD','RealTrade policy 禁止包含敏感字段：'+str(key))


def normalize_real_trade_policy(raw):
    if not isinstance(raw,dict):raise BrokerSnapshotError('INVALID_POLICY','RealTrade policy 必须是对象。')
    _policy_sensitive(raw)
    allowed={'policy_name','enabled','broker_adapter_id','account_alias','paper_account','manual_confirmation_required',
        'kill_switch_required','shadow_required','strict_pit_required','system_health_required','snapshot_max_age_seconds',
        'max_order_notional','max_single_position_ratio','max_gross_exposure','max_daily_loss','max_orders_per_day',
        'allowed_order_types','source_ref'}
    extra=set(raw)-allowed
    if extra:raise BrokerSnapshotError('INVALID_POLICY','未知 RealTrade policy 字段：'+','.join(sorted(extra)))
    policy_name=str(raw.get('policy_name','')).strip();adapter=str(raw.get('broker_adapter_id','')).strip()
    account=str(raw.get('account_alias','')).strip();paper=str(raw.get('paper_account','')).strip()
    source_ref=str(raw.get('source_ref','')).strip()
    for value,name,limit in ((policy_name,'policy_name',120),(adapter,'broker_adapter_id',120),(account,'account_alias',80),
            (paper,'paper_account',120),(source_ref,'source_ref',500)):
        if len(value)>limit:raise BrokerSnapshotError('INVALID_POLICY',name+' 过长。')
    if adapter and not ADAPTER_ID.fullmatch(adapter):raise BrokerSnapshotError('INVALID_POLICY','broker_adapter_id 无效。')
    if account and re.fullmatch(r'\d{8,}',account):raise BrokerSnapshotError('SENSITIVE_FIELD','account_alias 不能保存券商账号。')
    enabled=raw.get('enabled',False)
    if type(enabled) is not bool:raise BrokerSnapshotError('INVALID_POLICY','enabled 必须是布尔值。')
    if enabled:raise BrokerSnapshotError('UNSUPPORTED_POLICY','P13-B0 不允许 enabled=true；真实交易启用属于 P13-B+ 单独评审。')
    required_flags={name:raw.get(name,True) for name in ('manual_confirmation_required','kill_switch_required','shadow_required','strict_pit_required','system_health_required')}
    if any(type(value) is not bool for value in required_flags.values()):raise BrokerSnapshotError('INVALID_POLICY','安全门字段必须是布尔值。')
    if any(value is not True for value in required_flags.values()):raise BrokerSnapshotError('UNSAFE_POLICY','P13-B0 不允许关闭人工确认、kill switch、Shadow、Strict PIT 或 System Health 安全门。')
    snapshot_age=raw.get('snapshot_max_age_seconds')
    if snapshot_age is not None and (type(snapshot_age) is not int or not 1<=snapshot_age<=3600):
        raise BrokerSnapshotError('INVALID_POLICY','snapshot_max_age_seconds 必须是1–3600秒或 null。')
    max_orders=raw.get('max_orders_per_day')
    if max_orders is not None and (type(max_orders) is not int or not 1<=max_orders<=10000):
        raise BrokerSnapshotError('INVALID_POLICY','max_orders_per_day 必须是1–10000或 null。')
    order_types=raw.get('allowed_order_types',[])
    if not isinstance(order_types,list) or len(order_types)>20 or any(not isinstance(v,str) for v in order_types):
        raise BrokerSnapshotError('INVALID_POLICY','allowed_order_types 必须是文本列表。')
    order_types=sorted({v.strip().upper() for v in order_types if v.strip()})
    if any(v not in {'LIMIT'} for v in order_types):raise BrokerSnapshotError('UNSUPPORTED_POLICY','P13-B0 只预留 LIMIT 订单类型。')
    core={'format':POLICY_FORMAT,'policy_name':policy_name,'enabled':False,'broker_adapter_id':adapter,
        'account_alias':account,'paper_account':paper,**required_flags,'snapshot_max_age_seconds':snapshot_age,
        'max_order_notional':_optional_number(raw.get('max_order_notional'),'max_order_notional'),
        'max_single_position_ratio':_optional_number(raw.get('max_single_position_ratio'),'max_single_position_ratio',ratio=True),
        'max_gross_exposure':_optional_number(raw.get('max_gross_exposure'),'max_gross_exposure',ratio=True),
        'max_daily_loss':_optional_number(raw.get('max_daily_loss'),'max_daily_loss'),
        'max_orders_per_day':max_orders,'allowed_order_types':order_types,'source_ref':source_ref}
    required_values=('broker_adapter_id','account_alias','paper_account','snapshot_max_age_seconds','max_order_notional',
        'max_single_position_ratio','max_gross_exposure','max_daily_loss','max_orders_per_day','allowed_order_types')
    missing=[name for name in required_values if core[name] in (None,'',[])]
    return {**core,'complete':not missing,'missing_fields':missing,'policy_hash':digest(core)}


class RealTradePolicyLoader:
    def __init__(self,path):self.path=Path(path).expanduser().absolute()
    def load(self):
        if self.path.is_symlink() or not self.path.is_file():raise BrokerSnapshotError('INVALID_POLICY_SOURCE','RealTrade policy 文件不存在或是符号链接。')
        if self.path.stat().st_size>1_000_000:raise BrokerSnapshotError('INVALID_POLICY_SOURCE','RealTrade policy 超过1MB。')
        try:raw=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,UnicodeError,json.JSONDecodeError) as exc:raise BrokerSnapshotError('INVALID_POLICY_SOURCE',str(exc)) from None
        return normalize_real_trade_policy(raw)


class RealTradeReadinessService:
    def __init__(self,output,data_root=None,policy_path=None,registry=None,now_fn=None):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve() if data_root else None
        self.policy_path=Path(policy_path).expanduser().absolute() if policy_path else None
        self.registry=registry or BrokerCapabilityRegistry();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise BrokerSnapshotError('INVALID_WORKSPACE','RealTrade readiness workspace 不存在。')
    def _now(self):
        value=self.now_fn()
        if not isinstance(value,datetime) or value.tzinfo is None:raise BrokerSnapshotError('INVALID_CLOCK','Readiness 时钟必须带时区。')
        return value.astimezone(timezone.utc)
    def build(self):
        now=self._now();blockers=[]
        def block(code,detail):blockers.append({'code':code,'detail':detail})
        profiles=self.registry.list();live_profiles=self.registry.live()
        if not live_profiles:block('NO_LIVE_BROKER_CHANNEL','当前没有已实现的实时券商 Adapter。')
        policy=RealTradePolicyLoader(self.policy_path).load() if self.policy_path else None
        if policy is None:block('REAL_TRADE_POLICY_MISSING','尚未提供宿主审核的 RealTrade safety policy。')
        else:
            if not policy['complete']:block('REAL_TRADE_POLICY_INCOMPLETE','缺少：'+','.join(policy['missing_fields']))
            if not policy['enabled']:block('REAL_TRADE_POLICY_DISABLED','P13-B0 policy 固定 enabled=false。')
        selected=self.registry.get(policy['broker_adapter_id']) if policy and policy['broker_adapter_id'] else None
        if policy and policy['broker_adapter_id'] and selected is None:
            block('BROKER_ADAPTER_NOT_IMPLEMENTED','policy 指定的 Broker Adapter 尚未实现。')
        elif selected is not None and not selected['live_channel']:
            block('BROKER_ADAPTER_OFFLINE_ONLY','当前 Adapter 只能读取离线账户导出，不能证明实时券商连接。')
        if selected is not None and not selected['order_submit']:
            block('ORDER_SUBMISSION_CAPABILITY_UNAVAILABLE','当前 Adapter 没有真实订单能力。')
        block('BROKER_AUTH_RUNTIME_NOT_IMPLEMENTED','券商认证/会话运行时尚未实现。')
        block('KILL_SWITCH_NOT_IMPLEMENTED','真实订单层的 kill switch 尚未实现。')
        block('ORDER_RISK_GATE_NOT_IMPLEMENTED','逐单资金/仓位/日损/敞口风险门尚未实现。')
        block('PER_ORDER_CONFIRMATION_GATE_NOT_IMPLEMENTED','逐单人工确认 Gate 尚未实现。')
        block('ORDER_GATEWAY_NOT_IMPLEMENTED','真实订单 Gateway 尚未实现。')
        block('LIVE_ORDER_RECEIPT_RECONCILIATION_NOT_IMPLEMENTED','真实订单回执/成交/撤单对账链尚未实现。')
        store=BrokerSnapshotStore(self.output);snapshot=store.latest(policy['account_alias'] if policy else '')
        snapshot_summary=None;shadow=None
        if snapshot is not None:
            captured=datetime.fromisoformat(snapshot['captured_at']).astimezone(timezone.utc)
            if captured>now:block('BROKER_SNAPSHOT_IN_FUTURE','账户快照时间晚于 readiness 时钟。')
            age=max(0.0,(now-captured).total_seconds())
            snapshot_summary={'snapshot_id':snapshot['snapshot_id'],'provider':snapshot['provider'],
                'account_alias':snapshot['account_alias'],'captured_at':snapshot['captured_at'],'age_seconds':age,
                'position_count':len(snapshot['positions']),'read_only':True}
            if policy and policy['snapshot_max_age_seconds'] is not None and age>policy['snapshot_max_age_seconds']:
                block('BROKER_SNAPSHOT_STALE','账户快照超过 policy 允许的新鲜度。')
        elif policy and policy['account_alias']:
            block('BROKER_SNAPSHOT_MISSING','policy 指定账户没有可用 Broker Snapshot。')
        if policy and policy['shadow_required'] and policy['account_alias'] and policy['paper_account']:
            try:shadow=BrokerShadowReconciler(self.output).reconcile(account_alias=policy['account_alias'],paper_account=policy['paper_account'])
            except BrokerSnapshotError as exc:shadow={'status':'ERROR','error':{'code':exc.code,'message':str(exc)[:300]}}
            if shadow.get('status')!='MATCH':block('SHADOW_RECONCILIATION_NOT_MATCHED','Broker 与 Dynamic Paper 尚未达到 MATCH。')
        return {'format':'niuniu-real-trade-readiness-v1','phase':'P13-B0','checked_at':now.isoformat(),
            'status':'BLOCKED' if blockers else 'READY','ready_for_live_connection':False,'ready_for_real_orders':False,
            'real_broker_connected':False,'order_submission':False,'capabilities':profiles,'selected_capability':selected,
            'policy':policy,'broker_snapshot':snapshot_summary,'shadow':shadow,'blockers':blockers,
            'next_required_decisions':['choose a supported live broker channel','freeze account scope and local alias',
                'approve credential storage/runtime design','set order/position/exposure/daily-loss/order-count limits',
                'define kill switch and recovery procedure','define per-order human confirmation','define broker receipt/fill/cancel reconciliation'],
            'required_order_preflight':['fresh broker account state','current Decision/Strategy Intent','Strict PIT/order rules',
                'System Health','per-order human confirmation','risk limits','kill switch','broker receipt/reconciliation'],
            'automatic_execution':False,'scope':'Readiness evidence only. P13-B0 cannot connect, authenticate, place/cancel orders or transfer funds.'}


__all__=['POLICY_FORMAT','CAPABILITY_FORMAT','BrokerCapabilityRegistry','RealTradePolicyLoader',
    'RealTradeReadinessService','json_export_capabilities','normalize_real_trade_policy']
