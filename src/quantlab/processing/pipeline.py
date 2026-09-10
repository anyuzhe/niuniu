"""Training-only fitted scalar processors; no label access or backward filling."""
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import math
from pathlib import Path
import polars as pl
from quantlab.processing.cross_section import CrossSectionConfig, transform_cross_section
from quantlab.storage.codec import digest
from quantlab.processing.neutralization import CrossSectionNeutralizer, SizeHistory
from quantlab.data.industry import IndustryHistory


@dataclass(frozen=True)
class PipelineConfig:
    steps: list
    fit_start: date | None = None
    fit_end: date | None = None
    industry_events: list | None = None
    size_events: list | None = None

    def __post_init__(self):
        IndustryHistory(self.industry_events)
        SizeHistory(self.size_events)
        for name in ('fit_start', 'fit_end'):
            value = getattr(self, name)
            if isinstance(value, str): object.__setattr__(self, name, date.fromisoformat(value))
        if (self.fit_start is None) != (self.fit_end is None):
            raise ValueError('Provide both fit_start and fit_end, or use holdout/walkforward boundaries')
        if self.fit_start is not None and (type(self.fit_start) is not date or type(self.fit_end) is not date or self.fit_start > self.fit_end):
            raise ValueError('Invalid processor fit period')
        allowed = {'replace_inf':set(), 'fill_na':{'value'}, 'winsorize':{'lower','upper'},
            'robust_zscore':set(), 'clip':{'lower','upper'}, 'cs_rank':set(), 'cs_zscore':set(), 'industry_neutralization':set(), 'size_neutralization':set(), 'neutralization':set()}
        if not isinstance(self.steps, list) or not self.steps: raise ValueError('Pipeline requires ordered steps')
        seen_neutralization=False
        for step in self.steps:
            if not isinstance(step, dict) or step.get('method') not in allowed or set(step)-{'method'}-allowed[step['method']]:
                raise ValueError('Unsupported processor step')
            method=step['method']
            if method in ('industry_neutralization','neutralization') and self.industry_events is None:
                raise ValueError('Industry neutralization requires explicit industry_events (empty means unknown)')
            if method in ('size_neutralization','neutralization') and self.size_events is None:
                raise ValueError('Size neutralization requires explicit size_events (empty means unknown)')
            if method in ('industry_neutralization','size_neutralization','neutralization'):seen_neutralization=True
            if seen_neutralization and method=='fill_na':raise ValueError('FillNA after neutralization would invent residuals for missing controls')
            for key, value in step.items():
                if key != 'method' and (type(value) not in (int,float) or not math.isfinite(value)):
                    raise ValueError('Processor parameters must be finite numbers')
            if step['method'] in ('winsorize','clip'):
                lo,hi=step.get('lower',.01),step.get('upper',.99)
                if lo>=hi or (step['method']=='winsorize' and not 0<=lo<hi<=1):raise ValueError('Invalid processor bounds')
                if step['method']=='clip' and not {'lower','upper'}<=set(step):raise ValueError('Clip requires explicit bounds')


class FactorPipeline:
    def __init__(self, config):
        self.config=config; self.states=None; self.fitted_at=None; self.audit=[]
        self.neutralizer=CrossSectionNeutralizer(config.industry_events,config.size_events)

    def _step(self, values, mask, state, audit=False):
        method=state['method']; x=pl.col('value')
        if method in ('industry_neutralization','size_neutralization','neutralization'):
            result,rows=self.neutralizer.transform(values,mask,method)
            if audit:self.audit.extend(rows)
            return result
        if method in ('cs_rank','cs_zscore'):return transform_cross_section(values,mask,CrossSectionConfig(method))
        if method=='replace_inf':expr=pl.when(x.is_finite()).then(x).otherwise(None)
        elif method=='fill_na':expr=x.fill_null(state['value'])
        elif method in ('winsorize','clip'):expr=x.clip(state['lower'],state['upper'])
        elif method=='robust_zscore':expr=(x-state['median'])/state['scale']
        return values.with_columns(expr.cast(pl.Float64).alias('value'))

    def fit(self, values, mask):
        cfg=self.config
        if cfg.fit_start is None:raise ValueError('Fitted pipeline needs an explicit training period')
        joined=values.join(mask.select('symbol','datetime','eligible'),on=['symbol','datetime'],validate='1:1')
        if joined.height!=values.height or joined['eligible'].null_count():raise ValueError('Training universe must cover all rows')
        train=joined.filter(pl.col('eligible') & pl.col('datetime').dt.date().is_between(cfg.fit_start,cfg.fit_end)
            & (pl.col('available_at').dt.date()<=cfg.fit_end)).drop('eligible')
        if train.is_empty():raise ValueError('Empty processor training sample')
        self.fitted_at=train['available_at'].max(); self.states=[]
        train_mask=train.select('symbol','datetime').with_columns(pl.lit(True).alias('eligible'))
        for step in cfg.steps:
            state=dict(step);method=step['method'];series=train['value'].drop_nulls()
            if method!='replace_inf' and not series.is_finite().all():raise ValueError('Use replace_inf before fitting nonfinite values')
            if method=='fill_na' and 'value' not in state:
                if not len(series):raise ValueError('Cannot fit median on empty training values')
                state['value']=series.median()
            if method=='winsorize':
                if not len(series):raise ValueError('Cannot fit quantiles on empty training values')
                state.update(lower=series.quantile(step.get('lower',.01),interpolation='linear'),upper=series.quantile(step.get('upper',.99),interpolation='linear'))
            if method=='robust_zscore':
                if not len(series):raise ValueError('Cannot fit scale on empty training values')
                median=series.median();scale=(series-median).abs().median()*1.4826
                state.update(median=median,scale=scale or 1.,constant_training_scale=not bool(scale))
            train=self._step(train,train_mask,state);self.states.append(state)
        self.training_rows=train.height
        return self

    def transform(self, values, mask):
        if self.states is None:raise ValueError('Fit pipeline before transform')
        result=values
        self.audit=[]
        for state in self.states:result=self._step(result,mask,state,audit=True)
        # Fitted parameters cannot produce historical executable signals before fitting.
        result=result.with_columns(pl.when(pl.col('datetime')>=self.fitted_at).then(pl.col('value')).otherwise(None).alias('value'))
        eligible=mask.select('symbol','datetime','eligible')
        joined=result.join(eligible,on=['symbol','datetime'],how='left',validate='1:1')
        if joined['eligible'].null_count():raise ValueError('Universe mask must cover every factor row')
        return joined.with_columns(pl.when(pl.col('eligible')).then(pl.col('value')).otherwise(None).alias('value')).drop('eligible')

    def manifest(self):
        if self.states is None:raise ValueError('Pipeline not fitted')
        state={'version':'1.1.0','parameters':asdict(self.config),'fit_period':{'start':self.config.fit_start,'end':self.config.fit_end},
            'fitted_at':self.fitted_at,'fitted_parameters':self.states,'training_rows':self.training_rows,
            'code_hash':digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),Path(__file__).with_name('cross_section.py'),Path(__file__).with_name('neutralization.py'),Path(__file__).parents[1]/'data/industry.py')}),
            'scope':'Historical location/scale parameters use eligible training rows only and freeze for validation/test. Neutralization fits the eligible contemporaneous cross-section using only controls known at that close; pre-fit outputs unavailable.'}
        return {**state,'state_hash':digest(state)}
