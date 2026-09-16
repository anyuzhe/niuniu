"""Verified point-in-time security status derived only from PIT evidence receipts."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4
import hashlib

import polars as pl

from quantlab.data.pit_evidence import audit_pit_evidence,normalize_statement
from quantlab.data.security_status_coverage import list_security_status_coverage_snapshots
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


def _coverage_receipts(root):
    receipts=list_security_status_coverage_snapshots(root);sessions={};successors={}
    for receipt in receipts:
        sessions.setdefault(receipt['effective_session'],[]).append(receipt)
        previous=receipt['previous_status_snapshot']
        if previous is not None:successors.setdefault(previous,[]).append(receipt['status_snapshot'])
    ambiguous=[day for day,values in sessions.items() if len(values)!=1]
    if ambiguous:raise ValueError('ambiguous complete daily security status snapshots: '+','.join(sorted(ambiguous)))
    if any(len(values)>1 for values in successors.values()):
        raise ValueError('security status coverage archive contains branching previous-session links')
    return receipts


def _coverage_rows(root):
    receipts=_coverage_receipts(root);rows=[]
    for receipt in receipts:
        sources={row['source_id']:row for row in receipt['sources']}
        published=max(_moment(row['published_at'],'published_at') for row in receipt['sources'])
        available=_moment(receipt['available_at'],'available_at')
        effective=_moment(receipt['effective_session']+'T09:30:00+08:00','effective_at')
        for status in receipt['records']:
            bound=[sources[value] for value in status['source_ids']]
            rows.append({'symbol':status['symbol'],'effective_at':effective,'available_at':available,
                'tradable':status['tradable'],'risk_warning':status['risk_warning'],
                'source':bound[0]['url'],'evidence_id':'security_status_coverage:'+receipt['status_snapshot'],
                'published_at':published,'document_sha256':bound[0]['document']['sha256'],
                'document_sha256s':'|'.join(sorted(source['document']['sha256'] for source in bound)),
                'coverage_complete':True,'status_snapshot':receipt['status_snapshot'],
                'universe_snapshot':receipt['universe_snapshot'],'source_ids':'|'.join(status['source_ids'])})
    return rows,receipts


def materialize_security_status(data_root):
    root,folder,target,manifest_path=_paths(data_root)
    if not root.is_dir() or folder.is_symlink():raise ValueError('security status data root invalid')
    audit=audit_pit_evidence(root);legacy=[]
    evidence_ids={receipt['evidence_id'] for receipt in audit['records'] if receipt['kind']=='security_status'}
    for receipt in audit['records']:
        if receipt['kind']!='security_status':continue
        statement=normalize_statement('security_status',receipt['statement'])
        legacy.append({**statement,'effective_at':_moment(statement['effective_at'],'effective_at'),
            'available_at':_moment(statement['available_at'],'available_at'),
            'evidence_id':receipt['evidence_id'],'published_at':_moment(receipt['published_at'],'published_at'),
            'document_sha256':receipt['document_sha256'],'document_sha256s':None,'coverage_complete':False,
            'status_snapshot':None,'universe_snapshot':None,'source_ids':None})
    complete,coverage_receipts=_coverage_rows(root)
    complete_index={(row['symbol'],row['effective_at']):row for row in complete}
    rows=[]
    for row in legacy:
        daily=complete_index.get((row['symbol'],row['effective_at']))
        if daily is not None:
            if (daily['tradable'],daily['risk_warning'])!=(row['tradable'],row['risk_warning']):
                raise ValueError('complete daily security status conflicts with verified sparse statement')
            continue
        rows.append(row)
    rows.extend(complete)
    evidence_ids.update('security_status_coverage:'+row['status_snapshot'] for row in coverage_receipts)
    evidence_ids=sorted(evidence_ids)
    if not rows:return {'created':False,'rows':0,'path':str(target),'reason':'no_verified_security_status_evidence'}
    frame=pl.DataFrame(rows).sort('symbol','effective_at','available_at')
    keys=['symbol','effective_at','available_at']
    if frame.select(pl.struct(keys).is_duplicated().any()).item():raise ValueError('duplicate verified security status revision')
    folder.mkdir(parents=True,exist_ok=True);tmp=folder/('.'+str(uuid4())+'.parquet')
    try:
        frame.write_parquet(tmp);sha=hashlib.sha256(tmp.read_bytes()).hexdigest();tmp.replace(target)
    finally:tmp.unlink(missing_ok=True)
    identity=digest(evidence_ids)
    manifest={'format':FORMAT,'rows':frame.height,'table_sha256':sha,'evidence_digest':identity,
        'evidence_ids':evidence_ids,'daily_coverage_snapshots':len(coverage_receipts),
        'scope':'Derived only from deeply verified sparse statements and complete daily SecurityStatus v2 receipts; no cross-session carry and no price-limit inference.'}
    write_checked(manifest_path,manifest)
    return {'created':True,'rows':frame.height,'path':str(target),'sha256':sha,'evidence_digest':identity,
        'daily_coverage_snapshots':len(coverage_receipts)}


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
    audit=audit_pit_evidence(root);ids={r['evidence_id'] for r in audit['records'] if r['kind']=='security_status'}
    ids.update('security_status_coverage:'+row['status_snapshot'] for row in _coverage_receipts(root))
    ids=sorted(ids)
    if digest(ids)!=manifest.get('evidence_digest') or ids!=manifest.get('evidence_ids'):raise ValueError('security status evidence set changed; rematerialize')
    return frame,manifest


class SecurityStatusHistory:
    def __init__(self,records=None):
        self.records=[];seen=set();base_fields={'symbol','effective_at','available_at','tradable','risk_warning','source'}
        audit_fields={'evidence_id','published_at','document_sha256','document_sha256s','coverage_complete',
            'status_snapshot','universe_snapshot','source_ids'}
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
