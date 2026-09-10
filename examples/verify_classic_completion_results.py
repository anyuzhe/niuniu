"""Verify the actual client study artifacts, without choosing parameters or rerunning results."""
import json
from pathlib import Path
from datetime import date
import polars as pl
from quantlab.statistics.permutation import holm
root=Path('artifacts/chan-500-full-ten-year-qfq/runs');out=Path('artifacts/core-completion')
parent=json.loads((root/'88697ba9-f6f6-44be-8ef9-faff0a518bc9/experiment.json').read_text())
spec=json.loads((out/'classic-500-study-spec.json').read_text());children={c['name']:c for c in parent['children']}
assert parent['status']=='completed' and len(children)==22
assert parent['manifest']['config']['data']['symbols']==spec['symbols']
assert parent['manifest']['config']['data']['start']==spec['start']
assert parent['manifest']['config']['data']['end']==spec['end']
score=pl.read_parquet(root/children['完整组合']['run_id']/'observations.parquet')
assert score.height==1214000 and score['symbol'].n_unique()==500
assert set(score['symbol'].unique())==set(spec['symbols'])
assert score.group_by('symbol').len()['len'].unique().to_list()==[2428]
assert score.filter(pl.col('available_at')<pl.col('datetime')).is_empty()
keys=['symbol','datetime','available_at'];checked=score.select(*keys,'value')
for alias,entry in spec['parameters']['inputs'].items():
 component=children['组件 '+entry['factor_id']]
 values=pl.read_parquet(root/component['run_id']/'observations.parquet',columns=[*keys,'value'])
 checked=checked.join(values.rename({'value':alias}),on=keys,validate='1:1')
expected=sum(pl.col(alias)*weight for alias,weight in spec['parameters']['weights'].items())
checked=checked.with_columns(expected.alias('expected'))
assert checked.filter(pl.col('value').is_null()!=pl.col('expected').is_null()).is_empty()
error=checked.select((pl.col('value')-pl.col('expected')).abs().max()).item()
assert error<1e-12,error
inference=parent['inference'];assert len(inference['tests'])==294
assert holm([t['p_value'] for t in inference['tests']])==[t['p_holm'] for t in inference['tests']]
assert all(t['p_value'] is not None for t in inference['tests'])
# Each held-out segment's labels must end inside that segment, not cross the next split.
periods=list(children['固定样本外']['periods']);folds=children['滚动验证']['folds']
assert len(folds)==4
windows=[]
for i,fold in enumerate(folds):
 assert fold['start']==spec['start'];parts=fold['periods'];periods.extend(parts)
 test=next(p for p in parts if p['name']=='test');windows.append({k:fold[k] for k in ('start','train_end','valid_end','end')})
 if i:assert test['start']>folds[i-1]['end']
for period in periods:
 observations=pl.read_parquet(Path(period['artifact_path'])/'observations.parquet')
 assert str(observations['datetime'].dt.date().min())>=period['start']
 assert str(observations['datetime'].dt.date().max())<=period['end']
 for horizon in spec['horizons']:
  tail=observations.sort('symbol','datetime').group_by('symbol',maintain_order=True).tail(horizon)
  assert tail[f'forward_{horizon}'].null_count()==tail.height
liquidity=score.group_by('regime_liquidity').len().sort('regime_liquidity').to_dicts()
breadth=score.select('datetime','regime_breadth').unique().group_by('regime_breadth').len().sort('regime_breadth').to_dicts()
assert any(r['regime_liquidity']!='Unknown' and r['len'] for r in liquidity)
assert any(r['regime_breadth']!='Unknown' and r['len'] for r in breadth)
result={'status':'passed','parent_run_id':parent['run_id'],'top_level_children':len(children),'rows':score.height,'symbols':500,'bars_per_symbol':2428,
 'score_formula_max_error':error,'fixed_and_rolling_segments_checked':len(periods),'expanding_windows':windows,
 'inference':{'planned':294,'available':294,'holm_rejections':sum(t['reject_holm'] is True for t in inference['tests']),
 'positive_rejections':sum(t['reject_holm'] is True and t['estimate']>0 for t in inference['tests']),
 'negative_rejections':sum(t['reject_holm'] is True and t['estimate']<0 for t in inference['tests'])},
 'liquidity_rows':liquidity,'breadth_dates':breadth,
 'score_metrics':{h:{k:m[k] for k in ('observations','ic','rank_ic','long_short_spread')} for h,m in children['完整组合']['metrics'].items()},
 'limitations':['Previously viewed surviving-stock sample; retrospective split evaluation, not untouched OOS','Prediction labels are not executable net returns','No automatic selection of weights, parameters, or folds']}
(out/'classic-study-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
