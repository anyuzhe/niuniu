"""Checksummed recursive checkpoints. Data-only codec; never pickle/eval."""
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path
import hashlib
import io
import json
import math
import shutil
import tempfile
import polars as pl
from quantlab.domain import Event, SequenceMatch, Timeframe
from quantlab.progress import checkpoint

_TYPES = {c.__name__:c for c in (Event,SequenceMatch)}


def pack_state(value):
    if isinstance(value,Timeframe): return ['timeframe',value.value]
    if isinstance(value,datetime): return ['datetime',value.isoformat()]
    if isinstance(value,date): return ['date',value.isoformat()]
    if type(value) in (Event,SequenceMatch):
        return ['record',type(value).__name__,{f.name:pack_state(getattr(value,f.name)) for f in fields(value)}]
    if isinstance(value,dict):
        if any(not isinstance(k,str) for k in value): raise ValueError('State keys must be strings')
        return ['dict',{k:pack_state(v) for k,v in value.items()}]
    if isinstance(value,(list,tuple)):
        return ['tuple' if isinstance(value,tuple) else 'list',[pack_state(v) for v in value]]
    if type(value) in (str,int,bool,type(None)): return value
    if type(value) is float and math.isfinite(value): return value
    raise ValueError('Unsupported or nonfinite recursive state value')


def unpack_state(value):
    if not isinstance(value,list):
        if type(value) in (str,int,bool,type(None)): return value
        if type(value) is float and math.isfinite(value): return value
        raise ValueError('Invalid state scalar')
    if len(value)==2:
        tag,payload=value
        if tag=='datetime': return datetime.fromisoformat(payload)
        if tag=='date': return date.fromisoformat(payload)
        if tag=='timeframe': return Timeframe(payload)
        if tag=='dict': return {k:unpack_state(v) for k,v in payload.items()}
        if tag=='list': return [unpack_state(v) for v in payload]
        if tag=='tuple': return tuple(unpack_state(v) for v in payload)
    if len(value)==3 and value[0]=='record' and value[1] in _TYPES:
        cls=_TYPES[value[1]]
        if set(value[2])!={f.name for f in fields(cls)}: raise ValueError('Invalid state record fields')
        return cls(**{k:unpack_state(v) for k,v in value[2].items()})
    raise ValueError('Unknown recursive state type')


def _sha(data): return hashlib.sha256(data).hexdigest()

def _publish(cache, identity, bars, state, pointer):
    key=cache.key(identity,bars); destination=cache.root/('recursive-state-'+key)
    staging=Path(tempfile.mkdtemp(prefix='.recursive-pending-',dir=cache.root))
    try:
        bars.write_parquet(staging/'input.parquet')
        (staging/'state.json').write_text(json.dumps(pack_state(state.dump()),ensure_ascii=False,allow_nan=False,separators=(',',':')))
        manifest={name:_sha((staging/name).read_bytes()) for name in ('input.parquet','state.json')}
        (staging/'manifest.json').write_text(json.dumps(manifest))
        if destination.exists():
            if destination.is_symlink(): raise ValueError('Recursive cache symlink')
            shutil.rmtree(destination)
        staging.rename(destination)
        with tempfile.NamedTemporaryFile(mode='w',dir=cache.root,delete=False) as f:
            f.write(key); temporary=Path(f.name)
        try: temporary.replace(pointer)
        finally: temporary.unlink(missing_ok=True)
    finally:
        if staging.exists(): shutil.rmtree(staging)


def compute_recursive(cache, identity, bars, factory, chunk_size=512):
    if bars.is_empty(): return factory().result()
    if bars['symbol'].n_unique()!=1 or bars['timeframe'].n_unique()!=1:
        raise ValueError('A recursive checkpoint belongs to one symbol and timeframe')
    pointer=cache.root/('recursive-'+cache._prefix_family(identity,bars))
    state=factory(); resumed=0
    try:
        if pointer.is_symlink(): raise ValueError('Recursive pointer symlink')
        key=pointer.read_text()
        if len(key)!=64 or any(c not in '0123456789abcdef' for c in key): raise ValueError('Invalid recursive key')
        folder=cache.root/('recursive-state-'+key)
        if folder.is_symlink(): raise ValueError('Recursive state symlink')
        manifest=json.loads((folder/'manifest.json').read_text())
        payload={name:(folder/name).read_bytes() for name in ('input.parquet','state.json')}
        if manifest!={name:_sha(data) for name,data in payload.items()}: raise ValueError('Recursive state checksum mismatch')
        prefix=pl.read_parquet(io.BytesIO(payload['input.parquet']))
        if prefix.height>bars.height or cache.key(identity,prefix)!=key or not prefix.equals(bars.head(prefix.height)):
            raise ValueError('Changed historical recursive prefix')
        candidate=factory(); candidate.restore(unpack_state(json.loads(payload['state.json'])))
        if candidate.processed!=prefix.height: raise ValueError('Recursive state length mismatch')
        state=candidate; resumed=prefix.height
    except (OSError,ValueError,KeyError,TypeError,AttributeError,pl.exceptions.PolarsError):
        state=factory()
    cache.recursive_resumed_bars=getattr(cache,'recursive_resumed_bars',0)+resumed
    for offset in range(state.processed,bars.height,chunk_size):
        checkpoint('递归状态追加 · '+str(identity.get('profile','factor')),offset,bars.height)
        stop=min(offset+chunk_size,bars.height)
        state.extend(bars.slice(offset,stop-offset))
        if state.processed!=stop: raise ValueError('Recursive engine did not consume the complete chunk')
        _publish(cache,identity,bars.head(stop),state,pointer)
    cache.recursive_processed_bars=getattr(cache,'recursive_processed_bars',0)+bars.height-resumed
    return state.result()
