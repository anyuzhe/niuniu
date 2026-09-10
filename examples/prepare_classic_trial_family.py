"""Register each actual top-level study child, using the supported parent planners."""
import json
from dataclasses import asdict,replace
from pathlib import Path
from quantlab.workbench.jobs import prepare
from quantlab.app import default_registry
from quantlab.adapters.chan_classic import COMPONENTS
from quantlab.storage.codec import encode
root=Path('artifacts/core-completion');submission=prepare(json.loads((root/'classic-500-study-spec.json').read_text()))
config=submission.config;plan=submission.theory_study
light=replace(config,replay=False,sequence_audit=False)
trials=[];mapping={}
for component in (*COMPONENTS,'sequence_buy2'):
    identifier='CHAN.CLASSIC_'+component.upper();trial_id='component_'+component
    cfg=replace(light,factor_id=identifier,parameters={},theory_origin=None,processor=None)
    trials.append({'trial_id':trial_id,'config':asdict(cfg)});mapping['组件 '+identifier]=trial_id
trials.append({'trial_id':'component_momentum','config':asdict(replace(light,factor_id='BASE.MOMENTUM',parameters={'lookback':20},theory_origin=None,processor=None))});mapping['组件 BASE.MOMENTUM']='component_momentum'
trials.append({'trial_id':'score','config':asdict(config)});mapping['完整组合']='score'
for trial_id,name,kind,cfg,design in [
 ('ablation','逐输入消融','ablation',replace(light,incremental_test=True),{}),
 ('holdout','固定样本外','holdout',light,{'split':asdict(plan.split)}),
 ('walkforward','滚动验证','walkforward',light,{'schedule':asdict(plan.schedule)}),
 ('sensitivity','预设参数敏感性（各阶段）','sweep',light,{'grid':asdict(plan.variants(config,default_registry())),'split':asdict(plan.split),'schedule':None}),
]:
 trials.append({'trial_id':trial_id,'config':asdict(cfg),'study':{'kind':kind,'design':design}});mapping[name]=trial_id
out={'name':'经典缠论新500股十年完整子研究检验族（事后研究）','alpha':.05,'trials':trials}
(root/'classic-trial-plan.json').write_text(encode(out));(root/'classic-trial-child-mapping.json').write_text(encode(mapping))
# Validate the design without creating a second registry; the client creates it.
from quantlab.experiments.trial_layout import planned_layout,hypotheses
canonical=json.loads(encode(out))
for trial in canonical['trials']:
 if 'study' in trial:trial['layout']=planned_layout(trial)
print('Trials',len(trials),'hypotheses',sum(len(hypotheses(t)) for t in canonical['trials']))
