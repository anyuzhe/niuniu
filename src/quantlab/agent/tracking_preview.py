"""Read-only monitoring preview from saved values; never creates a watch or job."""
from datetime import datetime
import polars as pl
from quantlab.agent.tracking_metrics import compute_tracking,VERSION
from quantlab.storage.experiments import load_record_fields
from quantlab.storage.artifact_integrity import snapshot_tree,verify_tree
from quantlab.storage.codec import digest,encode
from quantlab.workbench.server import ArtifactCatalog


def tracking_fingerprint():
    from pathlib import Path
    from importlib import import_module
    modules = ('quantlab.agent.tracking_metrics','quantlab.experiments.research','quantlab.experiments.event_metrics')
    return digest({'modules':{name:Path(import_module(name).__file__).read_text() for name in modules},
        'polars':pl.__version__})


def tracking_preview(output,run_id,as_of,windows=(20,60,120),min_dates=20):
    if not isinstance(windows,(list,tuple)) or not 1<=len(windows)<=4:
        raise ValueError('Choose one to four observed-session windows')
    if any(type(w) is not int or not 1<=w<=1000 for w in windows) or len(set(windows))!=len(windows):
        raise ValueError('Windows must be distinct integers from 1 to 1000')
    if type(min_dates) is not int or not 1<=min_dates<=1000:raise ValueError('Invalid minimum observed dates')
    cutoff=datetime.fromisoformat(as_of)
    if cutoff.tzinfo is None:raise ValueError('Cutoff must include timezone')
    catalog=ArtifactCatalog(output);path=catalog.file(run_id,'experiment.json')
    tree=snapshot_tree(catalog.root,run_id)
    record=load_record_fields(path,{'run_id','status','kind','manifest'})
    if record['status']!='completed' or record.get('kind','factor')!='factor':
        raise ValueError('Choose a completed factor run, not a parent or account backtest')
    cfg=record['manifest']['config']
    if len(cfg['horizons'])>5 or len(cfg['data']['symbols'])>100:
        raise ValueError('Preview budget: at most 5 horizons and 100 symbols')
    frames=[]
    for name in ('bars.parquet','observations.parquet'):
        source=catalog.file(run_id,name)
        if source.stat().st_size>150_000_000:raise ValueError('Preview file exceeds 150 MB budget')
        lazy=pl.scan_parquet(source)
        if lazy.select(pl.len()).collect().item()>250000:raise ValueError('Preview exceeds 250000 rows')
        frames.append(lazy.collect())
    result,_,_=compute_tracking(*frames,cfg,cutoff,windows,min_dates)
    verify_tree(catalog.root,tree)
    result.update(source_run_id=run_id,source_fingerprint=digest(tree),
        source_context={'factor_id':cfg['factor_id'],'factor_version':cfg['factor_version'],
            'parameters':cfg['parameters'],'data':cfg['data'],
            'adjustment':record['manifest']['data_snapshot']['adjustment'],
            'source_runtime':record['manifest']['runtime']},
        tracking_version=VERSION,tracking_source_hash=tracking_fingerprint(),
        automatic_tracking=False,new_research_jobs=0,
        limitations=['只读预览：使用已保存因子值重算成熟标签和窗口指标，没有创建跟踪池或定时任务。',
            '窗口按归档中实际观察到的交易日期；持有期按后续实际K线根数，不补造停牌或缺失行情。',
            '未成熟标签保留为空；最少有效日期不足时标记不足，不视为无效因子或零收益。',
            '时间口径依赖归档available_at，不认证供应商历史发布时间、严格PIT或实盘可成交性。',
            '因子值沿用历史研究，没有重新计算因子；前缀一致性、数据修订及跨快照监控仍需单独验证。',
            'IC与分位收益是毛收益诊断，不是成本后账户收益；没有衰减显著性或连续检验结论。'])
    return __import__('json').loads(encode(result))
