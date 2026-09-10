"""Frozen research inputs, including historical eligibility and timeframe bars."""
from dataclasses import asdict
from datetime import date
from pathlib import Path
import polars as pl
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot, ExplicitUniverse
from quantlab.data.universe import HistoricalUniverse, UniverseConfig
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest


class CaptureData:
    def __init__(self, source, *, memoize=False):
        self.source=source
        self.loads=[]
        self.memoize=memoize

    def load(self, request):
        if self.memoize:
            for expected,previous in self.loads:
                if request==expected:return previous
        batch=self.source.load(request)
        self.loads.append((request,batch))
        return batch


def freeze_inputs(data, universe, manifest):
    frames={}
    def save(frame):
        name=f'input-{len(frames)}.parquet';frames[name]=frame
        return {'file':name,'hash':digest(frame.write_json())}
    def universe_spec(provider):
        from quantlab.experiments.holdout import _PeriodUniverse
        from quantlab.experiments.ablation import _CommonUniverse
        if isinstance(provider,ExplicitUniverse):return {'kind':'explicit','symbols':list(provider.symbols)}
        if isinstance(provider,HistoricalUniverse):
            frame=provider.frame
            if provider.config.mode=='listing':
                frame=frame.select(pl.col('symbol').alias('code'),pl.col('listed').dt.strftime('%Y-%m-%d').alias('ipoDate'),pl.col('delisted').dt.strftime('%Y-%m-%d').fill_null('').alias('outDate'))
            return {'kind':'historical','symbols':list(provider.symbols),'config':asdict(provider.config),'metadata':provider.metadata,'frame':save(frame),'version':provider.version}
        if isinstance(provider,_PeriodUniverse):return {'kind':'period','source':universe_spec(provider.source),'name':provider.name,'start':provider.start.isoformat(),'end':provider.end.isoformat()}
        if isinstance(provider,_CommonUniverse):return {'kind':'common','frame':save(provider.values),'id':provider.universe_id,'version':provider.version}
        return {'kind':'unsupported','id':provider.universe_id,'version':provider.version}
    inputs={'version':1,'universe':universe_spec(universe),'data':[]}
    for request,batch in data.loads:
        inputs['data'].append({'request':asdict(request),'snapshot':asdict(batch.snapshot),'frame':save(batch.bars)})
    manifest['frozen_inputs']=inputs
    return frames


def load_frozen_inputs(path, manifest):
    path=Path(path);inputs=manifest.get('frozen_inputs')
    if not inputs or inputs.get('version')!=1:raise ValueError('归档缺少完整冻结输入；请用对应旧版源码或重新运行并保存 K 线快照')
    def frame(spec):
        name=spec['file']
        if Path(name).name!=name or not name.startswith('input-') or not name.endswith('.parquet'):raise ValueError('Invalid frozen input path')
        target=path/name
        if target.is_symlink():raise ValueError('Frozen input cannot be a symlink')
        result=pl.read_parquet(target)
        if digest(result.write_json())!=spec['hash']:raise ValueError('Frozen input hash mismatch: '+name)
        return result
    def universe(spec):
        kind=spec['kind']
        if kind=='explicit':return ExplicitUniverse(tuple(spec['symbols']))
        if kind=='historical':
            result=HistoricalUniverse(spec['symbols'],frame(spec['frame']),UniverseConfig(**spec['config']),spec['metadata'])
            if result.version!=spec['version']:raise ValueError('Historical universe version mismatch')
            return result
        if kind=='period':
            from quantlab.experiments.holdout import _PeriodUniverse
            return _PeriodUniverse(universe(spec['source']),spec['name'],date.fromisoformat(spec['start']),date.fromisoformat(spec['end']))
        if kind=='common':
            from quantlab.experiments.ablation import _CommonUniverse
            return _CommonUniverse(frame(spec['frame']),spec['id'],spec['version'])
        raise ValueError('Unsupported frozen universe; no substitution allowed')
    provider=universe(inputs['universe']);batches=[]
    for item in inputs['data']:
        request=item['request'];request=DataRequest(tuple(request['symbols']),Timeframe(request['timeframe']),date.fromisoformat(request['start']),date.fromisoformat(request['end']))
        snapshot=item['snapshot'];snapshot=DataSnapshot(**{**snapshot,'files':tuple(snapshot['files'])})
        batches.append((request,DataBatch(frame(item['frame']),snapshot)))
    class FrozenData:
        def load(self,request):
            matches=[batch for expected,batch in batches if request==expected]
            if not matches:raise ValueError('Requested range/timeframe absent from frozen inputs')
            if any(batch.snapshot!=matches[0].snapshot or not batch.bars.equals(matches[0].bars) for batch in matches[1:]):raise ValueError('Conflicting frozen input snapshots')
            return matches[0]
    return FrozenData(),provider
