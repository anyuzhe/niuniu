"""Read-only broker snapshot contract. Credentials and order submission are out of scope."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from typing import Protocol
import json,math,re
from quantlab.storage.codec import digest

FORMAT='niuniu-broker-snapshot-v1'
SYMBOL=re.compile(r'^(?:sh|sz|bj)\.\d{6}$')
SENSITIVE=re.compile(r'(?:password|passwd|token|secret|api[_-]?key|credential|cookie|session|account[_-]?(?:number|no)|client[_-]?id)',re.I)

class BrokerSnapshotError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code

def _finite(value,name):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise BrokerSnapshotError('INVALID_SNAPSHOT',name+' 必须是非负有限数。')
    return float(value)

def _text(value,name,limit=120):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>limit:
        raise BrokerSnapshotError('INVALID_SNAPSHOT',name+' 文本无效。')
    return value.strip()

def _reject_sensitive(value,path='root'):
    if isinstance(value,dict):
        for key,child in value.items():
            if SENSITIVE.search(str(key)):
                raise BrokerSnapshotError('SENSITIVE_FIELD','Broker snapshot 禁止包含敏感字段：'+path+'.'+str(key))
            _reject_sensitive(child,path+'.'+str(key))
    elif isinstance(value,list):
        for i,child in enumerate(value):_reject_sensitive(child,path+'['+str(i)+']')

def normalize_broker_snapshot(raw):
    if not isinstance(raw,dict):raise BrokerSnapshotError('INVALID_SNAPSHOT','Broker snapshot 必须是对象。')
    _reject_sensitive(raw)
    allowed={'provider','account_alias','captured_at','currency','cash','equity','positions','source_ref'}
    extra=set(raw)-allowed
    if extra:raise BrokerSnapshotError('INVALID_SNAPSHOT','未知 Broker snapshot 字段：'+','.join(sorted(extra)))
    provider=_text(raw.get('provider'),'provider',80);alias=_text(raw.get('account_alias'),'account_alias',80)
    if re.fullmatch(r'\d{8,}',alias):
        raise BrokerSnapshotError('SENSITIVE_FIELD','account_alias 必须使用本地别名，不能保存券商账号。')
    currency=_text(raw.get('currency','CNY'),'currency',8).upper()
    if currency!='CNY':raise BrokerSnapshotError('INVALID_SNAPSHOT','P13-A v1 仅接受 CNY 账户快照。')
    try:captured=datetime.fromisoformat(str(raw.get('captured_at','')).replace('Z','+00:00'))
    except ValueError:raise BrokerSnapshotError('INVALID_SNAPSHOT','captured_at 必须是 ISO8601。') from None
    if captured.tzinfo is None:raise BrokerSnapshotError('INVALID_SNAPSHOT','captured_at 必须带时区。')
    cash=_finite(raw.get('cash'),'cash');equity=_finite(raw.get('equity'),'equity')
    positions=raw.get('positions',[])
    if not isinstance(positions,list) or len(positions)>10000:
        raise BrokerSnapshotError('INVALID_SNAPSHOT','positions 必须是列表且不超过10000项。')
    normalized=[];seen=set()
    for item in positions:
        if not isinstance(item,dict) or set(item)-{'symbol','quantity','available_quantity','market_value'}:
            raise BrokerSnapshotError('INVALID_SNAPSHOT','position 字段无效。')
        symbol=str(item.get('symbol','')).lower()
        if not SYMBOL.fullmatch(symbol) or symbol in seen:
            raise BrokerSnapshotError('INVALID_SNAPSHOT','position symbol 无效或重复。')
        seen.add(symbol);quantity=item.get('quantity');available=item.get('available_quantity',quantity)
        if type(quantity) is not int or quantity<0 or type(available) is not int or not 0<=available<=quantity:
            raise BrokerSnapshotError('INVALID_SNAPSHOT','持仓数量必须是非负整数且可用数量不能超过总量。')
        market_value=_finite(item.get('market_value',0.0),'market_value')
        if quantity:normalized.append({'symbol':symbol,'quantity':quantity,'available_quantity':available,'market_value':market_value})
    normalized.sort(key=lambda row:row['symbol'])
    source_ref=_text(raw.get('source_ref'),'source_ref',500)
    core={'format':FORMAT,'provider':provider,'account_alias':alias,
        'captured_at':captured.astimezone(timezone.utc).isoformat(),'currency':currency,'cash':cash,
        'equity':equity,'positions':normalized,'source_ref':source_ref,'read_only':True,
        'contains_credentials':False,'order_submission':False}
    return {**core,'snapshot_hash':digest(core)}

class ReadOnlyBrokerAdapter(Protocol):
    """Future broker-specific adapters may only expose normalized read-only snapshots in P13-A."""
    def snapshot(self)->dict: ...

class JsonBrokerExportAdapter:
    """Read a user-exported JSON snapshot; never connects to a broker."""
    def __init__(self,path):self.path=Path(path).expanduser().absolute()
    def snapshot(self):
        if self.path.is_symlink() or not self.path.is_file():
            raise BrokerSnapshotError('INVALID_SOURCE','Broker export 文件不存在或是符号链接。')
        if self.path.stat().st_size>5_000_000:
            raise BrokerSnapshotError('INVALID_SOURCE','Broker export 超过5MB。')
        try:raw=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,UnicodeError,json.JSONDecodeError) as exc:
            raise BrokerSnapshotError('INVALID_SOURCE',str(exc)) from None
        return normalize_broker_snapshot(raw)

__all__=['FORMAT','BrokerSnapshotError','ReadOnlyBrokerAdapter','JsonBrokerExportAdapter','normalize_broker_snapshot']
