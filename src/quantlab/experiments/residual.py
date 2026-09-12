from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID,uuid4
import polars as pl
from quantlab.statistics.residual import residual_alpha
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.storage.codec import digest
from quantlab.storage.experiments import LocalExperimentStore, load_record


def run_residual(candidate_path,control_paths,train_end,output,horizon=1,run_id=None):
    paths=[Path(candidate_path),*[Path(v) for v in control_paths]]
    records=[load_record(p/'experiment.json') for p in paths]
    if any(r.get('status')!='completed' or r.get('kind','factor')!='factor' for r in records):
        raise ValueError('Residual study requires completed factor observation artifacts')
    first=records[0]['manifest']
    for record in records[1:]:
        m=record['manifest']
        for field in ('data_snapshot','universe'):
            if m.get(field)!=first.get(field):raise ValueError('Residual inputs require identical data snapshots and universe')
    frames=[pl.read_parquet(p/'observations.parquet') for p in paths]
    observations,result=residual_alpha(frames[0],frames[1:],train_end,horizon)
    manifest={'runtime':runtime_fingerprint(),'config':{'research_question':'控制已有因子后的样本外残差 IC','data':first['config']['data']},
        'source_experiments':[r['experiment_id'] for r in records],'input_hashes':[digest(f.write_json()) for f in frames],
        'train_end':train_end,'horizon':horizon,'code_hash':digest(Path(__file__).read_text()+Path(__file__).parents[1].joinpath('statistics/residual.py').read_text())}
    run_id=str(uuid4()) if run_id is None else str(UUID(run_id));record={'run_id':run_id,'experiment_id':digest(manifest),'status':'completed','kind':'residual_alpha',
        'created_at':datetime.now(timezone.utc).isoformat(),'manifest':manifest,'summary':result,
        'children':[{'run_id':r['run_id'],'artifact_path':str(p.resolve()),'name':'候选因子' if i==0 else '控制因子'} for i,(p,r) in enumerate(zip(paths,records))]}
    return {'run_id':run_id,'artifact_path':str(LocalExperimentStore(output).save(run_id,record,observations)),'summary':result}
