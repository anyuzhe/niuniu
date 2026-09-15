"""Approval-time actual-byte research input freezes and read-only replay providers."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime,timezone,date
from pathlib import Path
from uuid import UUID,uuid4
import hashlib,json,shutil,tempfile

import polars as pl

from quantlab.data.base import DataBatch,DataRequest,DataSnapshot
from quantlab.data.validation import validate_bars
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest,encode

FORMAT='niuniu-approval-input-freeze-v1'
RECEIPT_FORMAT='niuniu-approval-input-freeze-receipt-v1'


def _safe_id(value):
    try:
        if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise ValueError('approval freeze id must be canonical UUID') from None
    return value


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _request(value):
    return DataRequest(tuple(value['symbols']),Timeframe(value['timeframe']),date.fromisoformat(value['start']),date.fromisoformat(value['end']))


def _request_dict(request):
    value=asdict(request);value['timeframe']=request.timeframe.value
    value['start']=request.start.isoformat();value['end']=request.end.isoformat();value['symbols']=list(request.symbols)
    return value


class ApprovalInputFreezeStore:
    def __init__(self,output,data_root):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve();self.root=self.output/'_approval_input_freezes'
        if not self.output.is_dir():raise ValueError('approval freeze workspace missing')

    def path(self,freeze_id):return self.root/_safe_id(freeze_id)

    def capture(self,freeze_id,spec,qualification):
        freeze_id=_safe_id(freeze_id);target=self.path(freeze_id);spec_digest=digest(spec)
        if target.exists():
            receipt={'format':RECEIPT_FORMAT,'freeze_id':freeze_id,'manifest_hash':self._manifest_hash(target),'spec_digest':spec_digest}
            self.verify(receipt,spec);return receipt
        if not self.data_root.is_dir():raise ValueError('approval freeze source data root missing')
        if self.root.is_symlink():raise ValueError('approval freeze root cannot be symlink')
        self.root.mkdir(exist_ok=True)
        staging=Path(tempfile.mkdtemp(prefix='.pending-',dir=self.root))
        try:
            manifest={'format':FORMAT,'freeze_id':freeze_id,'captured_at':datetime.now(timezone.utc).isoformat(),
                'spec_digest':spec_digest,'qualification':qualification,'data_entries':[],'universes':[],
                'scope':'Actual normalized research bytes frozen at host approval; execution reads this bundle, not mutable source data.'}
            self._capture_spec(spec,staging,manifest)
            self._write_manifest(staging,manifest)
            staging.rename(target)
        except Exception:
            shutil.rmtree(staging,ignore_errors=True);raise
        receipt={'format':RECEIPT_FORMAT,'freeze_id':freeze_id,'manifest_hash':digest(manifest),'spec_digest':spec_digest}
        self.verify(receipt,spec);return receipt

    def _capture_spec(self,spec,folder,manifest):
        if isinstance(spec,dict) and spec.get('mode')=='campaign':
            for node in spec.get('nodes') or []:self._capture_submission(node['spec'],folder,manifest,node.get('node_id',''))
        else:self._capture_submission(spec,folder,manifest,'')

    def _capture_submission(self,spec,folder,manifest,node_id):
        from quantlab.workbench.jobs import prepare
        from quantlab.data.provider import local_data_provider
        from quantlab.data.universe import build_universe
        submission=prepare(spec);config=submission.config
        provider=local_data_provider(self.data_root,submission.adjustment)
        main=self._capture_batch(provider,config.data,submission.adjustment,folder,manifest,node_id,'signal')
        if config.context is not None:
            self._capture_batch(provider,config.context.request(config.data),submission.adjustment,folder,manifest,node_id,'context')
        if submission.execution and submission.execution.price_mode=='account' and submission.adjustment!='raw':
            raw=local_data_provider(self.data_root,'raw')
            self._capture_batch(raw,config.data,'raw',folder,manifest,node_id,'execution')
        ukey=digest({'symbols':list(config.data.symbols),'config':asdict(submission.universe)})
        if not any(row['universe_key']==ukey for row in manifest['universes']):
            universe=build_universe(self.data_root,config.data.symbols,submission.universe)
            mask=universe.mask(main.bars).sort('symbol','datetime')
            name='universe-'+str(len(manifest['universes']))+'.parquet';path=folder/name;mask.write_parquet(path)
            manifest['universes'].append({'universe_key':ukey,'symbols':list(config.data.symbols),'config':asdict(submission.universe),
                'file':name,'sha256':_sha(path),'rows':mask.height,'universe_id':universe.universe_id,'version':universe.version,
                'metadata':getattr(universe,'metadata',{})})

    def _capture_batch(self,provider,request,adjustment,folder,manifest,node_id,role):
        key=digest({'adjustment':adjustment,'request':_request_dict(request)})
        existing=next((r for r in manifest['data_entries'] if r['entry_key']==key),None)
        if existing is not None:
            if node_id and node_id not in existing['node_ids']:existing['node_ids'].append(node_id)
            if role not in existing['roles']:existing['roles'].append(role)
            return ApprovalFrozenDataProvider._batch_from_entry(folder,existing,request)
        batch=provider.load(request);name='data-'+str(len(manifest['data_entries']))+'.parquet';path=folder/name;batch.bars.write_parquet(path)
        row={'entry_key':key,'adjustment':adjustment,'request':_request_dict(request),'file':name,'sha256':_sha(path),
            'rows':batch.bars.height,'source_snapshot':asdict(batch.snapshot),'node_ids':[node_id] if node_id else [],'roles':[role]}
        manifest['data_entries'].append(row);return batch

    @staticmethod
    def _write_manifest(folder,manifest):
        (folder/'manifest.json').write_text(encode({'manifest':manifest,'checksum':digest(manifest)}),encoding='utf-8')

    @staticmethod
    def _manifest_hash(folder):
        value=json.loads((Path(folder)/'manifest.json').read_text(encoding='utf-8'));manifest=value.get('manifest')
        if digest(manifest)!=value.get('checksum'):raise ValueError('approval freeze manifest checksum mismatch')
        return digest(manifest)

    def verify(self,receipt,spec=None):
        validate_approval_freeze_receipt(receipt);folder=self.path(receipt['freeze_id'])
        if folder.is_symlink() or not folder.is_dir():raise ValueError('approval freeze missing or symlink')
        value=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));manifest=value.get('manifest')
        if digest(manifest)!=value.get('checksum') or digest(manifest)!=receipt['manifest_hash']:raise ValueError('approval freeze manifest changed')
        if manifest.get('format')!=FORMAT or manifest.get('freeze_id')!=receipt['freeze_id']:raise ValueError('approval freeze identity mismatch')
        if manifest.get('spec_digest')!=receipt['spec_digest'] or (spec is not None and digest(spec)!=receipt['spec_digest']):raise ValueError('approval freeze spec mismatch')
        for row in [*manifest.get('data_entries',[]),*manifest.get('universes',[])]:
            path=folder/row['file']
            if path.is_symlink() or not path.is_file() or _sha(path)!=row['sha256']:raise ValueError('approval freeze input bytes changed: '+row['file'])
        return {'receipt':dict(receipt),'manifest':manifest,'path':folder}


def validate_approval_freeze_receipt(value):
    if not isinstance(value,dict) or set(value)!={'format','freeze_id','manifest_hash','spec_digest'} or value.get('format')!=RECEIPT_FORMAT:
        raise ValueError('Invalid approval freeze receipt')
    _safe_id(value['freeze_id'])
    for key in ('manifest_hash','spec_digest'):
        if not isinstance(value[key],str) or len(value[key])!=64 or any(c not in '0123456789abcdef' for c in value[key]):raise ValueError('Invalid approval freeze digest')
    return value


class ApprovalFrozenDataProvider:
    def __init__(self,root,adjustment='raw'):
        self.root=Path(root).resolve();self.adjustment=adjustment;self.manifest=_load_manifest(self.root)
        if adjustment not in ('raw','qfq'):raise ValueError('adjustment must be raw or qfq')

    @staticmethod
    def _batch_from_entry(root,row,request):
        frame=pl.read_parquet(Path(root)/row['file']).filter(pl.col('symbol').is_in(request.symbols) & pl.col('datetime').dt.date().is_between(request.start,request.end)).sort('symbol','datetime')
        if frame.is_empty() or set(frame['symbol'].unique())!=set(request.symbols):raise ValueError('Frozen approval input does not cover requested symbols/range')
        validate_bars(frame)
        original=row['source_snapshot']
        snapshot=DataSnapshot(digest({'approval_entry':row['entry_key'],'request':request}),original['source'],row['adjustment'],
            ({'path':row['file'],'sha256':row['sha256'],'bytes':(Path(root)/row['file']).stat().st_size,'approval_time_frozen':True,
              'approval_entry_key':row['entry_key'],'source_snapshot_id':original['snapshot_id'],'source_files':original.get('files',[])},))
        return DataBatch(frame,snapshot)

    def load(self,request):
        candidates=[]
        for row in self.manifest['data_entries']:
            expected=_request(row['request'])
            if row['adjustment']==self.adjustment and expected.timeframe==request.timeframe and set(request.symbols)<=set(expected.symbols) and expected.start<=request.start<=request.end<=expected.end:
                candidates.append((len(expected.symbols),(expected.end-expected.start).days,row))
        if not candidates:raise ValueError('Requested data absent from approval-time frozen inputs')
        row=min(candidates,key=lambda x:(x[0],x[1]))[2]
        return self._batch_from_entry(self.root,row,request)


class ApprovalFrozenUniverse:
    def __init__(self,root,row):
        self.root=Path(root);self.row=row;self.universe_id='approval_frozen:'+row['universe_id'];self.version='approval:'+row['sha256'];self.metadata={**row.get('metadata',{}),'approval_time_frozen':True}
        self._mask=pl.read_parquet(self.root/row['file']).sort('symbol','datetime')
    def mask(self,bars):
        keys=bars.select('symbol','datetime');joined=keys.join(self._mask,on=['symbol','datetime'],how='left',validate='1:1')
        if joined['eligible'].null_count():raise ValueError('Frozen approval universe mask does not cover requested bars')
        return joined.select('symbol','datetime','eligible')


def frozen_universe(root,symbols,config):
    from quantlab.data.base import ExplicitUniverse
    root=Path(root).resolve();manifest=_load_manifest(root)
    if config.mode=='explicit':return ExplicitUniverse(tuple(symbols))
    key=digest({'symbols':list(symbols),'config':asdict(config)})
    row=next((r for r in manifest['universes'] if r['universe_key']==key),None)
    if row is None:raise ValueError('Requested universe absent from approval-time freeze')
    return ApprovalFrozenUniverse(root,row)


def _load_manifest(root):
    root=Path(root).resolve();path=root/'manifest.json'
    if root.is_symlink() or path.is_symlink() or not path.is_file():raise ValueError('approval freeze manifest missing')
    value=json.loads(path.read_text(encoding='utf-8'));manifest=value.get('manifest')
    if digest(manifest)!=value.get('checksum') or manifest.get('format')!=FORMAT:raise ValueError('approval freeze manifest invalid')
    for row in [*manifest.get('data_entries',[]),*manifest.get('universes',[])]:
        target=root/row['file']
        if target.is_symlink() or not target.is_file() or _sha(target)!=row['sha256']:raise ValueError('approval freeze bytes changed')
    return manifest


def is_approval_freeze_root(root):
    root=Path(root).resolve();path=root/'manifest.json'
    if root.is_symlink() or path.is_symlink() or not path.is_file():return False
    try:
        value=json.loads(path.read_text(encoding='utf-8'));manifest=value.get('manifest')
        return isinstance(manifest,dict) and manifest.get('format')==FORMAT
    except (OSError,ValueError,TypeError,json.JSONDecodeError):return False


__all__=['ApprovalInputFreezeStore','ApprovalFrozenDataProvider','ApprovalFrozenUniverse','frozen_universe',
    'is_approval_freeze_root','validate_approval_freeze_receipt','FORMAT','RECEIPT_FORMAT']
