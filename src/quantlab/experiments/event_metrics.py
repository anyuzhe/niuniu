"""Long-direction event paths. Thresholds are descriptive, never fill rules."""
import polars as pl


def event_path_metrics(bars, triggered, horizon, target_return=0.02, stop_return=0.02):
    # Keep the cohort fixed at events with a complete future horizon. Compute
    # shifts on original bars so universe filters cannot jump over observations.
    futures = bars.sort('symbol', 'datetime').select('symbol', 'datetime', *[
        (pl.col('close').shift(-step).over('symbol') / pl.col('close') - 1).alias(f'r{step}')
        for step in range(1, horizon + 1)])
    paths = triggered.select('symbol', 'datetime').join(futures, on=['symbol', 'datetime'], validate='1:1')
    first_loss = first_target = first_stop = recovery = None
    for step in range(1, horizon + 1):
        value = pl.col(f'r{step}')
        loss = pl.when(value < 0).then(pl.lit(step))
        target = pl.when(value >= target_return).then(pl.lit(step))
        stop = pl.when(value <= -stop_return).then(pl.lit(step))
        first_loss = loss if first_loss is None else pl.coalesce(first_loss, loss)
        first_target = target if first_target is None else pl.coalesce(first_target, target)
        first_stop = stop if first_stop is None else pl.coalesce(first_stop, stop)
        hit = pl.when((first_loss < step) & (value >= 0)).then(pl.lit(step))
        recovery = hit if recovery is None else pl.coalesce(recovery, hit)
    paths = paths.with_columns(first_loss.alias('loss'), first_target.alias('target'), first_stop.alias('stop'), recovery.alias('recovery'))
    count = paths.height
    losses = paths.filter(pl.col('loss').is_not_null())
    recovered = losses.filter(pl.col('recovery').is_not_null())
    targets = paths.filter(pl.col('target').is_not_null())
    failures = paths.filter(pl.col('stop').is_not_null() & (pl.col('target').is_null() | (pl.col('stop') < pl.col('target'))))
    return {'target_return': target_return, 'stop_return': stop_return, 'complete_events': count,
        'forward_path': [{'bar': step, 'mean_return': paths[f'r{step}'].mean(), 'median_return': paths[f'r{step}'].median()} for step in range(1, horizon + 1)],
        'target_count': targets.height, 'target_rate': targets.height / count if count else None,
        'mean_time_to_target_bars': targets['target'].mean(),
        'failure_count': failures.height, 'failure_rate': failures.height / count if count else None,
        'adverse_event_count': losses.height, 'recovered_count': recovered.height,
        'recovery_rate': recovered.height / losses.height if losses.height else None,
        'mean_recovery_bars': recovered.select((pl.col('recovery') - pl.col('loss')).mean()).item(),
        'convention': 'Long direction, future closes relative to event close; complete fixed cohort; failure=stop reached before target; recovery=first nonnegative close after first negative close; times conditional on observed hits; incomplete/right-censored events excluded; not intrabar fills.'}


def signal_turnover(frame, quantiles):
    """Equal-weight top quantile, ranked without future labels. Exits included."""
    dates = frame.select('datetime').unique().sort('datetime')
    if dates.height < 2:
        return {'mean_one_way': None, 'transitions': 0}
    finite = frame.filter(pl.col('value').is_not_null())
    ranked = finite.with_columns(pl.col('value').rank('average').over('datetime').alias('rank'), pl.len().over('datetime').alias('n'), pl.col('value').n_unique().over('datetime').alias('unique'))
    top = ranked.filter((pl.col('n') >= quantiles) & (pl.col('unique') >= quantiles) & ((((pl.col('rank')-1)/pl.col('n')*quantiles).floor()+1) == quantiles))
    weights = top.select('symbol', 'datetime', (1 / pl.len().over('datetime')).alias('weight'))
    transitions = dates.with_columns(pl.col('datetime').shift(-1).alias('next')).drop_nulls()
    previous = weights.join(transitions, on='datetime').select('symbol', pl.col('next').alias('datetime'), pl.col('weight').alias('previous'))
    paired = weights.join(previous, on=['symbol', 'datetime'], how='full', coalesce=True).fill_null(0)
    changes = paired.group_by('datetime').agg((pl.col('weight')-pl.col('previous')).abs().sum().alias('stock_change'), pl.col('weight').sum().alias('gross'), pl.col('previous').sum().alias('old_gross'))
    result = transitions.select(pl.col('next').alias('datetime')).join(changes, on='datetime', how='left').fill_null(0).with_columns(((pl.col('stock_change')+(pl.col('gross')-pl.col('old_gross')).abs())/2).alias('one_way'))
    return {'mean_one_way': result['one_way'].mean(), 'transitions': result.height,
        'convention': 'Equal-weight top quantile at each observed eligible timestamp; ranks use factor only, never forward labels; half L1 change including cash; insufficient cross-section goes to cash; first establishment excluded; target turnover, not executed turnover.'}
