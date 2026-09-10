"""One frozen hypothesis: components, ablation, OOS, rolling and parameter sensitivity."""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from uuid import uuid4
import math
from quantlab.experiments.ablation import AblationRunner, _LoadedData
from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
from quantlab.experiments.walkforward import WalkForwardConfig, WalkForwardRunner
from quantlab.experiments.sweep import ParameterGrid, SweepRunner, SweepResult
from quantlab.experiments.runner import ExperimentRunner, runtime_fingerprint
from quantlab.factors.combinations import CombinationFactor
from quantlab.factors.wyckoff_classic import ClassicWyckoffFactor,COMPONENTS as WYCKOFF_CLASSIC_COMPONENTS
from quantlab.factors.chan_classic import ClassicChanFactor
from quantlab.adapters.chan_classic import COMPONENTS as CLASSIC_COMPONENTS
from quantlab.factors.brooks import BrooksComponent
from quantlab.factors.brooks_wedge import BrooksWedgeComponent, COMPONENTS as BROOKS_WEDGE_COMPONENTS
from quantlab.factors.brooks_context import BrooksContextComponent, COMPONENTS as BROOKS_CTX_COMPONENTS
from quantlab.factors.brooks_breakout import BrooksBreakoutComponent, COMPONENTS as BROOKS_BP_COMPONENTS
from quantlab.factors.ict import ICTComponent
from quantlab.factors.wyckoff import WyckoffComponent
from quantlab.factors.wyckoff_phases import WyckoffPhaseComponent,COMPONENTS as WYCKOFF_PHASE_COMPONENTS
from quantlab.factors.chan_inclusion import ChanInclusionComponent
from quantlab.factors.order_block import OrderBlockComponent
from quantlab.factors.liquidity_pool import LiquidityPoolFactor,COMPONENTS as POOL_COMPONENTS
from quantlab.factors.chan_progression import ChanProgressionComponent,COMPONENTS as CHAN_PROGRESSION_COMPONENTS
from quantlab.multitimeframe.source import with_context_source
from quantlab.statistics.permutation import inference_family
from quantlab.storage.codec import digest
from quantlab.storage.experiments import load_record


@dataclass(frozen=True)
class TheoryStudyPlan:
    split: ChronologicalSplit
    schedule: WalkForwardConfig
    input: str
    grid: dict
    audit_components: bool = True

    @classmethod
    def parse(cls,spec):
        if set(spec)-{'split','schedule','input','grid','audit_components'} or not {'split','schedule','input','grid'}<=set(spec):
            raise ValueError('theory_study requires split, schedule, input and grid')
        if type(spec.get('audit_components',True)) is not bool:raise ValueError('audit_components must be boolean')
        return cls(ChronologicalSplit(**{k:date.fromisoformat(v) for k,v in spec['split'].items()}),
            WalkForwardConfig(**spec['schedule']),spec['input'],spec['grid'],spec.get('audit_components',True))

    def variants(self,config,registry):
        self.split.periods(config.data);self.schedule.windows(config.data)
        combination=registry.get(config.factor_id,config.factor_version)
        if not isinstance(combination,CombinationFactor):raise ValueError('Theory study requires a combination')
        params=combination.parameters(config.parameters)
        if len(params['inputs'])<2 or self.input not in params['inputs']:
            raise ValueError('Theory study needs at least two inputs and a valid sensitivity input')
        source=params['inputs'][self.input];factor=registry.get(source['factor_id'],source['version'])
        variants=ParameterGrid(self.grid).variants(factor,source['parameters'])
        if len(variants)<2:raise ValueError('Stability comparison needs at least two variants')
        inputs=[]
        for variant in variants:
            entry=deepcopy(params['inputs']);entry[self.input]['parameters']=variant;inputs.append(entry)
        return ParameterGrid({'inputs':inputs})


def stability_summary(children):
    """Descriptive sensitivity on identical named phases; never select a winning variant."""
    groups={}
    for child in children:
        for evaluation in child['evaluations']:
            for horizon,metrics in evaluation['metrics'].items():
                values={k:metrics.get(k) for k in ('ic','rank_ic','long_short_spread')}
                if 'triggered' in metrics:values['triggered_mean_forward_return']=metrics['triggered'].get('mean_forward_return')
                for metric,value in values.items():
                    key=(evaluation['phase'],horizon,metric)
                    groups.setdefault(key,[]).append(value)
    rows=[]
    for (phase,horizon,metric),values in sorted(groups.items()):
        valid=[v for v in values if isinstance(v,(int,float)) and math.isfinite(v)]
        rows.append({'phase':phase,'horizon':horizon,'metric':metric,'planned_variants':len(values),'available_variants':len(valid),
            'minimum':min(valid) if valid else None,'maximum':max(valid) if valid else None,
            'range':max(valid)-min(valid) if valid else None,
            'positive_fraction':sum(v>0 for v in valid)/len(valid) if valid else None,
            'negative_fraction':sum(v<0 for v in valid)/len(valid) if valid else None,
            'status':'descriptive' if len(valid)>=2 else 'insufficient_variants'})
    return {'method':'fixed_grid_phase_sensitivity','automatic_selection':False,'rows':rows,
        'limitations':'Descriptive range/sign fractions, not a significance test or proof of parameter stability; repeated OOS inspection is exploratory.'}


def component_specs(params, registry):
    result=[]
    seen=set()
    for alias,spec in params['inputs'].items():
        candidate=registry.get(spec['factor_id'],spec['version'])
        components=[candidate]
        if isinstance(candidate,ClassicChanFactor):
            components=[registry.get("CHAN.CLASSIC_"+c.upper(),"1.0.0") for c in (*CLASSIC_COMPONENTS,"sequence_buy2")]
        if isinstance(candidate,BrooksComponent):
            components=[BrooksComponent(c,candidate.direction) for c in ('trend','pullback','first','failure','second')]
        if isinstance(candidate,BrooksBreakoutComponent):
            components=[BrooksBreakoutComponent(c,candidate.direction) for c in BROOKS_BP_COMPONENTS]
        if isinstance(candidate,BrooksContextComponent):
            components=[BrooksContextComponent(c) for c in BROOKS_CTX_COMPONENTS]
        if isinstance(candidate,BrooksWedgeComponent):
            components=[BrooksWedgeComponent(c,candidate.direction) for c in BROOKS_WEDGE_COMPONENTS]
        if isinstance(candidate,ICTComponent):
            components=[ICTComponent(c,candidate.direction) for c in ('sweep','displacement','mss')]
        if isinstance(candidate,ClassicWyckoffFactor):
            components=[ClassicWyckoffFactor(c) for c in WYCKOFF_CLASSIC_COMPONENTS]
        if isinstance(candidate,WyckoffComponent):
            components=[WyckoffComponent(c) for c in ('range','spring','upthrust','test_up','test_down','sos','sow')]
        if isinstance(candidate,WyckoffPhaseComponent):
            components=[WyckoffPhaseComponent(c) for c in WYCKOFF_PHASE_COMPONENTS]
        if isinstance(candidate,ChanInclusionComponent):
            components=[ChanInclusionComponent(c) for c in ('bar','pivot_high','pivot_low','bi','center','active_center','center_extended','center_exit_up','center_exit_down')]
        if isinstance(candidate,LiquidityPoolFactor):
            components=[LiquidityPoolFactor(c,candidate.direction) for c in POOL_COMPONENTS]
        if isinstance(candidate,OrderBlockComponent):
            components=[OrderBlockComponent(c,candidate.direction) for c in ('created','touched','invalidated','expired')]
        if isinstance(candidate,ChanProgressionComponent):
            components=[ChanProgressionComponent(c) for c in CHAN_PROGRESSION_COMPONENTS]
        for component in components:
            key=digest({'factor':component.definition.factor_id,'params':spec['parameters']})
            if key in seen:continue
            seen.add(key)
            result.append((component, spec))
    return result


class TheoryStudyRunner:
    def __init__(self,runner):self.runner=runner
    def run(self,config,plan):
        run_id=str(uuid4());manifest={'config':asdict(config),'plan':asdict(plan),'runtime':runtime_fingerprint()}
        record={'run_id':run_id,'created_at':datetime.now(timezone.utc).isoformat(),'kind':'theory_study','manifest':manifest,'children':[]}
        try:
            grid=plan.variants(config,self.runner.registry)
            if config.incremental_test:raise ValueError('Use permutation to enable study ablation contrasts; not incremental_test on the entire study')
            from quantlab.storage.frozen_inputs import CaptureData, freeze_inputs
            captured=CaptureData(self.runner.data)
            batch=captured.load(config.data);manifest['data_snapshot']=asdict(batch.snapshot)
            data=with_context_source(_LoadedData(batch,config.data),captured,config,manifest)
            runner=ExperimentRunner(data,self.runner.registry,self.runner.universe,self.runner.store,self.runner.research)
            cfg=replace(config,replay=True,sequence_audit=True)
            lightweight=cfg if plan.audit_components else replace(cfg,replay=False,sequence_audit=False)
            params=runner.registry.get(cfg.factor_id,cfg.factor_version).parameters(cfg.parameters)
            def add(name,result):
                source=load_record(result.artifact_path/'experiment.json')
                record['children'].append({'name':name,'run_id':result.run_id,'experiment_id':result.experiment_id,
                    'artifact_path':str(result.artifact_path),**{k:source[k] for k in ('metrics','children','periods','folds','contrasts') if k in source}})
            for component,spec in component_specs(params,runner.registry):
                add('组件 '+component.definition.factor_id,runner.run(replace(lightweight,factor_id=component.definition.factor_id,
                    factor_version=component.definition.version,parameters=spec['parameters'],theory_origin=None,processor=None)))
            add('完整组合',runner.run(cfg))
            add('逐输入消融',AblationRunner(runner).run(replace(lightweight,incremental_test=cfg.permutation is not None)))
            add('固定样本外',HoldoutRunner(runner).run(lightweight,plan.split))
            add('滚动验证',WalkForwardRunner(runner).run(lightweight,plan.schedule))
            sensitivity=SweepRunner(runner).run(lightweight,grid,split=plan.split)
            add('预设参数敏感性（各阶段）',sensitivity)
            record['stability']=stability_summary(sensitivity.children)
            manifest['child_experiments']=[c['experiment_id'] for c in record['children']]
            frozen=freeze_inputs(captured,self.runner.universe,manifest)
            record.update(status='completed',experiment_id=digest(manifest))
            if cfg.permutation:record['inference']=inference_family(record,cfg.permutation)
        except Exception as error:
            record.update(status='failed',experiment_id=digest(manifest),error=f'{type(error).__name__}: {error}')
            self.runner.store.save(run_id,record,None);raise
        path=self.runner.store.save(run_id,record,None,inputs=frozen)
        return SweepResult(record['experiment_id'],run_id,path,record['children'])
