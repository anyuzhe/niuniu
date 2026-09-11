"""Read-only paired candidate diagnostics; never select a winner or claim alpha."""
from datetime import date
import math
import json
import polars as pl
from quantlab.storage.experiments import load_record_fields
from quantlab.storage.artifact_integrity import snapshot_tree, verify_tree
from quantlab.storage.codec import encode, digest
from quantlab.workbench.server import ArtifactCatalog

FIELDS = {'run_id','experiment_id','kind','status','manifest','limitations'}
KEYS = ['symbol','datetime']


def _source(catalog, run_id, horizon):
    record = load_record_fields(catalog.file(run_id,'experiment.json'),FIELDS)
    if record.get('kind','factor')!='factor' or record['status']!='completed':
        raise ValueError('请选择已完成的单因子归档；父研究和成交账户需选择其因子子研究')
    if horizon not in record['manifest']['config']['horizons']:
        raise ValueError('所选持有期未在两个来源中同时保存')
    path = catalog.file(run_id,'observations.parquet')
    if path.stat().st_size>150_000_000: raise ValueError('候选观测文件超过150MB预算')
    lazy = pl.scan_parquet(path)
    if lazy.select(pl.len()).collect().item()>250000: raise ValueError('候选比较最多250000行/来源')
    columns = [*KEYS,'available_at','value',f'forward_{horizon}',f'label_end_{horizon}']
    if set(columns)-set(lazy.collect_schema().names()):
        raise ValueError('来源缺少因子值或标签结束时间；请保留冻结输入重新运行该研究')
    frame = lazy.select(columns).collect().sort(KEYS)
    if any(frame[k].null_count() for k in (*KEYS,'available_at')):
        raise ValueError('来源的证券或时间键有空值')
    if frame.select(pl.struct(KEYS).is_duplicated().any()).item():
        raise ValueError('来源存在重复的证券/时间观测')
    if frame.filter(pl.col('available_at')!=pl.col('datetime')).height:
        raise ValueError('延迟可用因子需要独立事件时间比较，不能直接回填')
    label = f'forward_{horizon}'; endpoint = f'label_end_{horizon}'
    for name in ('value',label):
        if frame.filter(pl.col(name).is_not_null() & ~pl.col(name).is_finite()).height:
            raise ValueError('来源观测包含非有限值')
    end = date.fromisoformat(record['manifest']['config']['data']['end'])
    invalid = pl.col(endpoint).is_null() | (pl.col(endpoint).dt.date()>end)
    if frame.filter(pl.col(label).is_not_null() & invalid).height:
        raise ValueError('来源的未来收益越过已保存研究区间或缺少结束时间')
    return record,frame


def _finite_mean(frame, name):
    values = frame[name].filter(frame[name].is_finite())
    return float(values.mean()) if len(values) else None


def compare_candidate(output, candidate_run_id, baseline_run_id, horizon):
    if type(horizon) is not int or not 1<=horizon<=1000:
        raise ValueError('持有期必须为1–1000根的整数')
    catalog = ArtifactCatalog(output); trees = []
    for identifier in (candidate_run_id,baseline_run_id):
        catalog.file(identifier,'experiment.json')
        trees.append(snapshot_tree(catalog.root,identifier))
    records = []; frames = []
    for identifier in (candidate_run_id,baseline_run_id):
        record,frame = _source(catalog,identifier,horizon)
        records.append(record); frames.append(frame)
    left,right = [r['manifest'] for r in records]
    for field in ('data_snapshot','universe','runtime'):
        if left.get(field)!=right.get(field): raise ValueError('两个来源不可比：'+field)
    for field in ('data','context','processor','regime','regime_filter','quantiles'):
        if left['config'].get(field)!=right['config'].get(field):
            raise ValueError('两个来源的研究条件不同：'+field)
    label = f'forward_{horizon}'; endpoint = f'label_end_{horizon}'
    common = frames[0].rename({'value':'candidate'}).join(
        frames[1].rename({'value':'baseline','available_at':'baseline_available_at',
            label:'baseline_label',endpoint:'baseline_label_end'}),on=KEYS,validate='1:1')
    if not common[label].equals(common['baseline_label']):
        raise ValueError('相同证券/时间的收益标签不一致，拒绝选择性删除后比较')
    if not common[endpoint].equals(common['baseline_label_end']):
        raise ValueError('相同观测的标签结束时间不一致')
    both = common.filter(pl.col('candidate').is_finite() & pl.col('baseline').is_finite())
    correlation = both.group_by('datetime').agg(pl.len().alias('n'),
        pl.corr('candidate','baseline',method='spearman').alias('rank_correlation')).filter(pl.col('n')>=3)
    correlation = correlation.filter(pl.col('rank_correlation').is_finite())
    labelled = both.filter(pl.col(label).is_finite())
    daily = labelled.group_by('datetime').agg(pl.len().alias('n'),
        pl.corr('candidate',label,method='spearman').alias('candidate_ic'),
        pl.corr('baseline',label,method='spearman').alias('baseline_ic')).filter(pl.col('n')>=3)
    paired = daily.filter(pl.col('candidate_ic').is_finite() & pl.col('baseline_ic').is_finite())
    paired = paired.with_columns((pl.col('candidate_ic')-pl.col('baseline_ic')).alias('difference'))
    def descriptor(record):
        cfg = record['manifest']['config']
        return {'run_id':record['run_id'],'experiment_id':record['experiment_id'],
            **{key:cfg.get(key) for key in ('factor_id','factor_version','parameters')},
            'source_limitations':record.get('limitations',[])[:8]}
    result = {'method':'common_sample_candidate_review_v1',
        'status':'descriptive_comparison' if paired.height else 'insufficient_common_sample',
        'candidate':descriptor(records[0]),'baseline':descriptor(records[1]),
        'same_run':candidate_run_id==baseline_run_id,'horizon':horizon,
        'data':left['config']['data'],'adjustment':left['data_snapshot']['adjustment'],
        'coverage':{'candidate_rows':frames[0].height,'baseline_rows':frames[1].height,
            'shared_keys':common.height,'candidate_only_keys':frames[0].height-common.height,
            'baseline_only_keys':frames[1].height-common.height,'both_factors_finite':both.height,
            'mature_common_rows':labelled.height,'pending_common_rows':both.height-labelled.height,
            'paired_ic_timestamps':paired.height,'signal_correlation_timestamps':correlation.height},
        'signal_rank_correlation':{'mean':_finite_mean(correlation,'rank_correlation'),
            'mean_absolute':float(correlation['rank_correlation'].abs().mean()) if correlation.height else None,
            'uses_future_labels':False},
        'paired_rank_ic':{'candidate':_finite_mean(paired,'candidate_ic'),
            'baseline':_finite_mean(paired,'baseline_ic'),'difference':_finite_mean(paired,'difference'),
            'weighting':'Equal common bar timestamps; both ICs must be finite at each timestamp'},
        'source_fingerprints':[digest(tree) for tree in trees],
        'new_research_jobs':0,'alpha_verified':False,'p_value':None,
        'limitations':['只读共同样本诊断；不创建新研究、不自动选优、不改变因子或跟踪。',
            '低相关不是增量Alpha；IC差值没有显著性检验，不含交易成本或序贯错误率控制。',
            '只在两个因子同时有有限值的共同样本计算；覆盖损失单独报告，不补零。',
            '采用来源已保存的完整日期范围；不复用越过截止日期的未来标签。',
            '来源指纹记录本次读取的证据树，并不认证严格PIT、原始数据真实性或历史首次可用时间。']}
    for tree in trees: verify_tree(catalog.root,tree)
    return json.loads(encode(result))
