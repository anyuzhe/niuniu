"""Observed eligible-universe breadth; never labelled exchange-wide breadth."""
import polars as pl

def breadth_frame(bars,mask,lookback=20):
    frame=bars.sort('symbol','datetime').with_columns(
        pl.col('close').pct_change().over('symbol').alias('_return'),
        pl.col('high').rolling_max(lookback).shift(1).over('symbol').alias('_prior_high'),
        pl.col('low').rolling_min(lookback).shift(1).over('symbol').alias('_prior_low'))
    frame=frame.join(mask,on=['symbol','datetime'],validate='1:1')
    if frame['eligible'].null_count():raise ValueError('Breadth requires complete historical eligibility')
    frame=frame.filter(pl.col('eligible'))
    return frame.group_by('datetime').agg(pl.len().alias('breadth_eligible'),
        pl.col('_return').count().alias('breadth_ready'),
        (pl.col('_return')>0).sum().alias('breadth_advances'),
        (pl.col('_return')<0).sum().alias('breadth_declines'),
        (pl.col('_return')==0).sum().alias('breadth_unchanged'),
        (pl.col('close')>pl.col('_prior_high')).sum().alias('breadth_new_highs'),
        (pl.col('close')<pl.col('_prior_low')).sum().alias('breadth_new_lows'),
        pl.col('_prior_high').count().alias('breadth_range_ready'),
    ).with_columns(pl.when(pl.col('breadth_ready')>0).then(pl.col('breadth_advances')/pl.col('breadth_ready')).otherwise(None).alias('breadth_advance_fraction')).with_columns(
        pl.when(pl.col('breadth_advance_fraction').is_null()).then(pl.lit('Unknown'))
        .when(pl.col('breadth_advance_fraction')>=.6).then(pl.lit('Expansion'))
        .when(pl.col('breadth_advance_fraction')<=.4).then(pl.lit('Contraction'))
        .otherwise(pl.lit('Balanced')).alias('regime_breadth')).sort('datetime')
