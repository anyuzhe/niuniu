"""Immutable normalized bar versions with explicit observation time and revision audit.

A vintage records when this archive observed data. It does not certify that a
historical bar was actually published at its nominal close.
"""
from datetime import datetime,timezone,date
from pathlib import Path
from uuid import uuid4
import hashlib
import io
import json
import os
import shutil
import tempfile
import fcntl
import polars as pl
from quantlab.data.base import DataBatch,DataSnapshot
from quantlab.data.validation import ordered_bars
from quantlab.storage.codec import encode,digest


class BarArchive:
    def __init__(self, root):self.root=Path(root).resolve()

    def publish(self, bars, source, parent=None, accept_revisions=False, observed_at=None):
        if not isinstance(source,dict) or not source:raise ValueError('Archive source provenance is required')
        if source.get('adjustment')!='raw':raise ValueError('Archive source must explicitly declare raw adjustment')
        observed_at=observed_at or datetime.now(timezone.utc)
        if not isinstance(observed_at,datetime) or observed_at.tzinfo is None:raise ValueError('Archive observation requires timezone')
        if type(accept_revisions) is not bool:raise ValueError('accept_revisions must be boolean')
        bars=ordered_bars(bars)
        if bars['available_at'].max()>observed_at:raise ValueError('Cannot archive bars not yet available at observation')
        for column in ('datetime','available_at'):
            if not isinstance(bars.schema[column],pl.Datetime) or bars.schema[column].time_zone is None:raise ValueError('Archive bar timestamps require timezone')
        current={};parent_id=None;old_bars=None
        if parent:
            provider=ArchivedBarProvider(parent);old_bars=provider.all_bars();metadata=provider.manifest
            if datetime.fromisoformat(metadata['observed_at'])>observed_at:raise ValueError('Archive observation precedes parent')
            if set(old_bars['symbol'])!=set(bars['symbol']) or old_bars['timeframe'][0]!=bars['timeframe'][0] or old_bars.schema!=bars.schema:
                raise ValueError('Incremental delivery must cover the same symbols, timeframe and normalized schema')
            current={(r['symbol'],r['datetime']):r for r in old_bars.to_dicts()};parent_id=metadata['version_id']
        changes=[];new=0;duplicates=0
        for row in bars.to_dicts():
            key=(row['symbol'],row['datetime']);previous=current.get(key)
            if previous is None:new+=1;current[key]=row
            elif previous==row:duplicates+=1
            else:
                changes.append({'symbol':row['symbol'],'datetime':row['datetime'],'previous':previous,'incoming':row})
                if accept_revisions:current[key]=row
        if changes and not accept_revisions:
            raise ValueError(f'{len(changes)} historical revisions detected; publish with explicit accept_revisions to retain a new version')
        if old_bars is not None and not new and not changes:
            return {'status':'unchanged','manifest':str(Path(parent).resolve()),'version_id':parent_id,'duplicate_rows':duplicates}
        merged=ordered_bars(pl.DataFrame(list(current.values()),schema=bars.schema))
        version_id=digest({'parent':parent_id,'bars':merged.write_json(),'observed_at':observed_at,'source':source,'revisions':changes})
        self.root.mkdir(parents=True,exist_ok=True)
        with (self.root/'.publish.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            existing=list(self.root.glob('*/manifest.json'))
            if existing and parent is None:raise ValueError('Existing archive requires an explicit parent version')
            if parent and Path(parent).resolve().parent.parent!=self.root:raise ValueError('Parent must belong to this archive')
            target=self.root/version_id
            if target.exists():return {'status':'existing','manifest':str(target/'manifest.json'),'version_id':version_id}
            temporary=Path(tempfile.mkdtemp(prefix='.publish-',dir=self.root))
            try:
                payload=temporary/'bars.parquet';merged.write_parquet(payload)
                manifest={'format_version':'1.0.0','version_id':version_id,'parent_version_id':parent_id,'observed_at':observed_at,
                    'source':source,'adjustment':'raw','timeframe':merged['timeframe'][0],'symbols':sorted(set(merged['symbol'])),
                    'rows':merged.height,'start':merged['datetime'].min(),'end':merged['datetime'].max(),'data_file':'bars.parquet',
                    'sha256':hashlib.sha256(payload.read_bytes()).hexdigest(),'new_rows':new,'duplicate_rows':duplicates,'revisions':changes,
                    'knowledge_policy':'Observation-time version archive. Historical nominal close availability is not PIT-certified.'}
                (temporary/'manifest.json').write_text(encode(manifest))
                for p in temporary.iterdir():
                    with p.open('rb') as f:os.fsync(f.fileno())
                os.rename(temporary,target)
                fd=os.open(self.root,os.O_RDONLY)
                try:os.fsync(fd)
                finally:os.close(fd)
            finally:
                if temporary.exists():shutil.rmtree(temporary)
        return {'status':'published','manifest':str(target/'manifest.json'),'version_id':version_id,'new_rows':new,'revised_rows':len(changes),'duplicate_rows':duplicates}

    def at(self, as_of):
        if not isinstance(as_of,datetime) or as_of.tzinfo is None:raise ValueError('Archive as_of requires timezone')
        candidates=[]
        for path in self.root.glob('*/manifest.json'):
            if path.parent.name.startswith('.'):continue
            record=json.loads(path.read_text());observed=datetime.fromisoformat(record['observed_at'])
            if observed<=as_of:candidates.append((observed,path))
        if not candidates:raise ValueError('No archived version observed by as_of')
        last=max(t for t,_ in candidates);matches=[p for t,p in candidates if t==last]
        if len(matches)!=1:raise ValueError('Ambiguous archive versions at same observation time; choose a manifest explicitly')
        return ArchivedBarProvider(matches[0])


class ArchivedBarProvider:
    def __init__(self, manifest):
        self.path=Path(manifest).resolve();self.manifest=json.loads(self.path.read_text())
        if self.manifest.get('format_version')!='1.0.0' or self.manifest.get('data_file')!='bars.parquet':raise ValueError('Unsupported archive manifest')
        if self.manifest.get('adjustment')!='raw':raise ValueError('Archive currently supports raw prices only')

    def all_bars(self):
        payload=(self.path.parent/'bars.parquet').read_bytes()
        if hashlib.sha256(payload).hexdigest()!=self.manifest['sha256']:raise ValueError('Archived data checksum mismatch')
        frame=ordered_bars(pl.read_parquet(io.BytesIO(payload)))
        if frame.height!=self.manifest['rows'] or sorted(set(frame['symbol']))!=self.manifest['symbols'] or frame['timeframe'][0]!=self.manifest['timeframe']:
            raise ValueError('Archive manifest does not match data')
        identity=digest({'parent':self.manifest['parent_version_id'],'bars':frame.write_json(),
            'observed_at':self.manifest['observed_at'],'source':self.manifest['source'],'revisions':self.manifest['revisions']})
        if identity!=self.manifest['version_id']:raise ValueError('Archive manifest identity mismatch')
        return frame

    def load(self, request):
        if request.timeframe.value!=self.manifest['timeframe'] or not set(request.symbols)<=set(self.manifest['symbols']):raise ValueError('Request outside archived symbols/timeframe')
        frame=self.all_bars().filter(pl.col('symbol').is_in(request.symbols)&pl.col('datetime').dt.date().is_between(request.start,request.end))
        if frame.is_empty() or set(frame['symbol'])!=set(request.symbols):raise ValueError('Archive missing requested symbol data')
        metadata={'version_id':self.manifest['version_id'],'observed_at':self.manifest['observed_at'],'sha256':self.manifest['sha256'],
            'knowledge_policy':self.manifest['knowledge_policy']}
        return DataBatch(frame,DataSnapshot(digest({'archive':metadata,'request':request}), 'versioned_bar_archive','raw',(metadata,)))
