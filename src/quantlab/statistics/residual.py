"""Train-only linear projection of a candidate on controls; held-out residual IC."""
import math
from datetime import date
import polars as pl
from quantlab.statistics.permutation import PermutationConfig, block_sign_test


def fit_projection(rows):
    """Modified Gram-Schmidt OLS with standardized nonconstant controls."""
    count=len(rows); width=len(rows[0])-1
    if count<max(10,2*(width+1)): raise ValueError('Insufficient training observations')
    means=[math.fsum(r[j] for r in rows)/count for j in range(width)]
    scales=[math.sqrt(math.fsum((r[j]-means[j])**2 for r in rows)/count) for j in range(width)]
    if any(s<1e-12 for s in scales): raise ValueError('Constant training control')
    columns=[[1.0]*count]+[[(r[j]-means[j])/scales[j] for r in rows] for j in range(width)]
    q=[]; triangular=[[0.]*(width+1) for _ in columns]
    for j,col in enumerate(columns):
        v=col[:]
        for k,axis in enumerate(q):
            value=math.fsum(a*b for a,b in zip(axis,v)); triangular[k][j]=value
            v=[a-value*b for a,b in zip(v,axis)]
        norm=math.sqrt(math.fsum(a*a for a in v))
        if norm<1e-9*math.sqrt(count):raise ValueError('Collinear training controls')
        triangular[j][j]=norm; q.append([a/norm for a in v])
    rhs=[math.fsum(axis[i]*rows[i][-1] for i in range(count)) for axis in q]; coefficients=[0.]*(width+1)
    for j in reversed(range(width+1)):
        coefficients[j]=(rhs[j]-math.fsum(triangular[j][k]*coefficients[k] for k in range(j+1,width+1)))/triangular[j][j]
    return {'means':means,'scales':scales,'coefficients':coefficients,'train_rows':count,'candidate_scale':max(abs(r[-1]) for r in rows)}


def residual_alpha(candidate, controls, train_end, horizon=1, permutation=None, seed=0):
    if type(train_end) is not date or type(horizon) is not int or horizon<1:raise ValueError('Invalid split or horizon')
    if not 1<=len(controls)<=20:raise ValueError('Supply 1–20 existing control factors')
    keys=['symbol','datetime','available_at']; label=f'forward_{horizon}'
    def eligible(frame):return frame.filter(pl.col('eligible')) if 'eligible' in frame.columns else frame
    frame=eligible(candidate).select(*keys,pl.col('value').alias('candidate'),label)
    for i,control in enumerate(controls):
        frame=frame.join(eligible(control).select(*keys,pl.col('value').alias(f'control_{i}'),
            pl.col(label).alias('_label')),on=keys,how='inner',validate='1:1')
        if frame.filter((pl.col(label)!=pl.col('_label')) | (pl.col(label).is_null()!=pl.col('_label').is_null())).height:
            raise ValueError('Control and candidate labels differ')
        frame=frame.drop('_label')
    names=[f'control_{i}' for i in range(len(controls))]
    valid=frame.filter(pl.all_horizontal(pl.col(c).is_finite() for c in ['candidate',*names]))
    train=valid.filter(pl.col('available_at').dt.date()<=train_end)
    if train.is_empty():raise ValueError('Empty training period')
    # The projection uses factors only, never training or evaluation returns.
    model=fit_projection(list(train.select(*names,'candidate').iter_rows()))
    values=[]
    for row in valid.select(*names,'candidate').iter_rows():
        prediction=model['coefficients'][0]+math.fsum(model['coefficients'][j+1]*(row[j]-model['means'][j])/model['scales'][j] for j in range(len(names)))
        residual=row[-1]-prediction
        tolerance=1e-12*max(model['candidate_scale'],abs(row[-1]),abs(prediction))
        values.append(0. if abs(residual)<=tolerance else residual)
    valid=valid.with_columns(pl.Series('value',values)).with_columns(
        pl.when(pl.col('available_at').dt.date()<=train_end).then(pl.lit('train')).otherwise(pl.lit('test')).alias('phase'))
    test=valid.filter((pl.col('phase')=='test') & pl.col(label).is_finite())
    if test.is_empty():raise ValueError('No held-out observations')
    dates=test.select(pl.col('datetime').dt.date().alias('date')).unique().sort('date')
    daily=test.group_by('datetime').agg(pl.len().alias('n'),pl.corr('value',label).alias('ic'),
        pl.corr('candidate',label).alias('raw_ic')).filter(pl.col('n')>=3).with_columns(pl.col('datetime').dt.date().alias('date'))
    daily=daily.group_by('date').agg(pl.col('ic').filter(pl.col('ic').is_finite()).mean(),pl.col('raw_ic').filter(pl.col('raw_ic').is_finite()).mean())
    daily=dates.join(daily,on='date',how='left').sort('date')
    return valid, {'method':'train_only_control_projection_v1','train_end':train_end,'model':model,'horizon':horizon,
        'test_rows':test.height,'test_residual_ic':daily['ic'].mean(),'test_raw_ic':daily['raw_ic'].mean(),
        'test':block_sign_test(daily['ic'].to_list(),permutation or PermutationConfig(),seed),
        'limitations':'Residual IC tests linear novelty against specified controls using frozen training projection. Not causal attribution, return alpha, or proof of independence; no model/parameter selection or cross-study multiple-testing correction.'}
