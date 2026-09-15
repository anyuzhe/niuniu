"""Verified point-in-time security status derived only from PIT evidence receipts."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4
import hashlib

import polars as pl

from quantlab.data.pit_evidence import audit_pit_evidence,normalize_statement
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest

FORMAT='niuniu-security-status-v1'
RISK_WARNINGS=('NONE','ST','STAR_ST','UNKNOWN')


def _moment(value,name):
    if isinstance(value,str):value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if not isinstance(value,datetime) or value.tzinfo is None:raise ValueError(name+' must be timezone-aware')
    return value


def _paths(root):
    root=Path(root).resolve();folder=root/'lake/silver/security_status'
    return root,folder,folder/'security_status.parquet',folder/'manifest.json'


def materialize_security_status(data_root):
    root,folder,target,manifest_path=_paths(data_root)
    if not root.is_dir() or folder.is_symlink():raise ValueError('security status data root invalid')
    audit=audit_pit_evidence(root);rows=[]
    for receipt in audit['records']:
        if receipt['kind']!='security_status':continue
        statement=normalize_statement('security_status',receipt['statement'])
        rows.append({**statement,'effective_at':_moment(statement['effective_at'],'effective_at'),
            'available_at':_moment(statement['available_at'],'available_at'),
            'evidence_id':receipt['evidence_id'],'published_at':_moment(receipt['published_at'],'published_at'),
            'document_sha256':receipt['document_sha256']})
    if not rows:return {'created':False,'rows':0,'path':str(target),'reason':'no_verified_security_status_evidence'}
    frame=pl.DataFrame(rows).sort('symbol','effective_at','available_at')
    keys=['symbol','effective_at','available_at']
    if frame.select(pl.struct(keys).is_duplicated().any()).item():raise ValueError('duplicate verified security status revision')
    folder.mkdir(parents=True,exist_ok=True);tmp=folder/('.'+str(uuid4())+'.parquet')
    try:
        frame.write_parquet(tmp);sha=hashlib.sha256(tmp.read_bytes()).hexdigest();tmp.replace(target)
    finally:tmp.unlink(missing_ok=True)
    identity=digest(sorted(row['evidence_id'] for row in rows))
    manifest={'format':FORMAT,'rows':frame.height,'table_sha256':sha,'evidence_digest':identity,
        'evidence_ids':sorted(row['evidence_id'] for row in rows),
        'scope':'Derived only from deeply verified security_status PIT receipts; no price-limit inference.'}
    write_checked(manifest_path,manifest)
    return {'created':True,'rows':frame.height,'path':str(target),'sha256':sha,'evidence_digest':identity}


def load_security_status(data_root):
    root,folder,target,manifest_path=_paths(data_root)
    if folder.is_symlink() or target.is_symlink() or manifest_path.is_symlink():raise ValueError('security status path cannot be symlink')
    if not target.is_file() or not manifest_path.is_file():raise ValueError('security status materialization missing')
    manifest=read_checked(manifest_path)
    if manifest.get('format')!=FORMAT:raise ValueError('security status manifest format invalid')
    payload=target.read_bytes()
    if hashlib.sha256(payload).hexdigest()!=manifest.get('table_sha256'):raise ValueError('security status table hash mismatch')
    frame=pl.read_parquet(target)
    if frame.height!=manifest.get('rows'):raise ValueError('security status row count mismatch')
    audit=audit_pit_evidence(root);ids=sorted(r['evidence_id'] for r in audit['records'] if r['kind']=='security_status')
    if digest(ids)!=manifest.get('evidence_digest') or ids!=manifest.get('evidence_ids'):raise ValueError('security status evidence set changed; rematerialize')
    return frame,manifest


class SecurityStatusHistory:
    def __init__(self,records=None):
        self.records=[];seen=set();base_fields={'symbol','effective_at','available_at','tradable','risk_warning','source'}
        audit_fields={'evidence_id','published_at','document_sha256'}
        for raw in records or []:
            if not isinstance(raw,dict) or not base_fields<=set(raw) or set(raw)-base_fields-audit_fields:
                raise ValueError('security status record fields invalid')
            row=normalize_statement('security_status',{k:raw[k] for k in base_fields})
            row={**row,'effective_at':_moment(row['effective_at'],'effective_at'),
                'available_at':_moment(row['available_at'],'available_at'),
                **{k:raw[k] for k in audit_fields if k in raw}}
            if 'published_at' in row:row['published_at']=_moment(row['published_at'],'published_at')
            key=(row['symbol'],row['effective_at'],row['available_at'])
            if key in seen:raise ValueError('duplicate security status revision')
            seen.add(key);self.records.append(row)
    def at(self,symbol,at):
        if not isinstance(at,datetime) or at.tzinfo is None:raise ValueError('security status query time requires timezone')
        rows=[r for r in self.records if r['symbol']==symbol and r['effective_at']<=at and r['available_at']<=at]
        return max(rows,key=lambda r:(r['effective_at'],r['available_at'])) if rows else None


__all__=['FORMAT','RISK_WARNINGS','SecurityStatusHistory','materialize_security_status','load_security_status']
