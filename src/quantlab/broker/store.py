"""Append-only storage for credential-free read-only broker snapshots."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from uuid import NAMESPACE_URL,UUID,uuid5
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest
from .contracts import FORMAT,BrokerSnapshotError,normalize_broker_snapshot

class BrokerSnapshotStore:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.root=self.output/'_broker_shadow'/'snapshots'
        self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise BrokerSnapshotError('INVALID_WORKSPACE','Broker shadow workspace 不存在。')
    def _guard(self):
        if self.root.is_symlink() or self.root.parent.is_symlink():
            raise BrokerSnapshotError('INVALID_WORKSPACE','Broker shadow 路径不能是符号链接。')
    def import_snapshot(self,raw,*,confirmed=False):
        if confirmed is not True:
            raise BrokerSnapshotError('CONFIRM_REQUIRED','导入真实账户只读快照需要宿主显式确认。')
        if isinstance(raw,dict) and raw.get('format')==FORMAT:
            keys=('format','provider','account_alias','captured_at','currency','cash','equity','positions','source_ref',
                'read_only','contains_credentials','order_submission')
            if set(raw)!={*keys,'snapshot_hash'}:
                raise BrokerSnapshotError('INVALID_SNAPSHOT','已正规化 Broker snapshot 字段异常。')
            core={k:raw[k] for k in keys}
            if digest(core)!=raw.get('snapshot_hash'):
                raise BrokerSnapshotError('CORRUPT_SNAPSHOT','已正规化 Broker snapshot hash 不匹配。')
            if raw.get('read_only') is not True or raw.get('contains_credentials') is not False or raw.get('order_submission') is not False:
                raise BrokerSnapshotError('INVALID_SNAPSHOT','Broker snapshot 权限标志不允许写入或凭证。')
            value=dict(raw)
        else:value=normalize_broker_snapshot(raw)
        stamp=self.now_fn()
        if not isinstance(stamp,datetime) or stamp.tzinfo is None:
            raise BrokerSnapshotError('INVALID_CLOCK','Broker snapshot store 时钟必须带时区。')
        self._guard();self.root.mkdir(parents=True,exist_ok=True)
        snapshot_id=str(uuid5(NAMESPACE_URL,'niuniu-broker-snapshot:'+value['snapshot_hash']))
        path=self.root/(snapshot_id+'.json')
        record={**value,'snapshot_id':snapshot_id,
            'imported_at':stamp.astimezone(timezone.utc).isoformat(),
            'storage_policy':'Append-only credential-free evidence; import does not connect or authorize orders.'}
        if path.exists():
            old=self.get(snapshot_id)
            comparable={k:v for k,v in old.items() if k not in ('imported_at','storage_policy')}
            current={k:v for k,v in record.items() if k not in ('imported_at','storage_policy')}
            if comparable!=current:raise BrokerSnapshotError('CONFLICT','同一 snapshot_id 内容变化。')
            return old
        write_checked(path,record);return record
    def get(self,snapshot_id):
        try:
            if not isinstance(snapshot_id,str) or str(UUID(snapshot_id))!=snapshot_id:raise ValueError()
        except (ValueError,TypeError,AttributeError):raise BrokerSnapshotError('INVALID_ARGUMENT','snapshot_id 必须是规范 UUID。') from None
        self._guard();path=self.root/(snapshot_id+'.json')
        if path.is_symlink() or not path.is_file():raise BrokerSnapshotError('NOT_FOUND','Broker snapshot 不存在。')
        try:value=read_checked(path)
        except (OSError,ValueError) as exc:raise BrokerSnapshotError('CORRUPT_SNAPSHOT',str(exc)) from None
        if value.get('format')!=FORMAT or value.get('snapshot_id')!=snapshot_id:
            raise BrokerSnapshotError('CORRUPT_SNAPSHOT','Broker snapshot 身份异常。')
        keys=('format','provider','account_alias','captured_at','currency','cash','equity','positions',
            'source_ref','read_only','contains_credentials','order_submission')
        core={k:value[k] for k in keys}
        if digest(core)!=value.get('snapshot_hash'):
            raise BrokerSnapshotError('CORRUPT_SNAPSHOT','Broker snapshot hash 不匹配。')
        return value
    def list(self,account_alias='',limit=200):
        if not isinstance(account_alias,str) or len(account_alias)>80 or type(limit) is not int or not 1<=limit<=2000:
            raise BrokerSnapshotError('INVALID_ARGUMENT','Broker snapshot 查询参数无效。')
        self._guard();rows=[];errors=[]
        if not self.root.exists():return {'records':[],'total':0,'errors':[]}
        for path in self.root.glob('*.json'):
            try:
                value=self.get(path.stem)
                if not account_alias or value['account_alias']==account_alias:rows.append(value)
            except (OSError,ValueError,KeyError,BrokerSnapshotError) as exc:
                errors.append({'entry':path.name,'error':type(exc).__name__})
        rows.sort(key=lambda r:(r['captured_at'],r['snapshot_id']),reverse=True)
        return {'records':rows[:limit],'total':len(rows),'errors':errors}
    def latest(self,account_alias=''):
        rows=self.list(account_alias,1)['records'];return rows[0] if rows else None

__all__=['BrokerSnapshotStore']
