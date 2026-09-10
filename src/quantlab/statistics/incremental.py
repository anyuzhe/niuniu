"""Paired IC differences on identical observations, not causal attribution."""

import polars as pl

from quantlab.statistics.permutation import block_sign_test
from quantlab.storage.codec import digest


def paired_ic_statistics(full, reduced, horizons, config, seed, contrast):
    keys = ['symbol', 'datetime']
    # Saved observations already reflect the actual universe/background/processor.
    def select(frame, suffix):
        if 'eligible' in frame.columns:
            frame = frame.filter(pl.col('eligible'))
        return frame.select(*keys, pl.col('value').alias('value'+suffix),
            *[pl.col(f'forward_{h}').alias(f'forward_{h}'+suffix) for h in horizons])
    left, right = select(full, '_full'), select(reduced, '_without')
    paired = left.join(right, on=keys, how='inner', validate='1:1').sort(keys)
    dates = pl.concat([left.select('datetime'), right.select('datetime')]).select(
        pl.col('datetime').dt.date().alias('date')).unique().sort('date')
    result = {}
    for horizon in horizons:
        a, b = f'forward_{horizon}_full', f'forward_{horizon}_without'
        mismatch = paired.filter((pl.col(a).is_null() != pl.col(b).is_null()) |
            (pl.col(a).is_not_null() & pl.col(b).is_not_null() & (pl.col(a) != pl.col(b))))
        if mismatch.height:
            raise ValueError('Paired IC requires identical forward labels at matching symbol/time keys')
        valid = paired.filter(pl.col('value_full').is_finite() & pl.col('value_without').is_finite() &
            pl.col(a).is_finite() & pl.col(b).is_finite())
        correlations = valid.group_by('datetime').agg(pl.len().alias('n'), *[
            pl.corr('value'+suffix, a, method=method).alias(metric+suffix)
            for suffix in ('_full', '_without') for metric, method in [('ic','pearson'),('rank_ic','spearman')]]
        ).filter(pl.col('n') >= 3).with_columns(pl.col('datetime').dt.date().alias('date'))
        result[str(horizon)] = {'permutation': {}}
        for metric in ('ic','rank_ic'):
            comparable = correlations.filter(pl.col(metric+'_full').is_finite() & pl.col(metric+'_without').is_finite())
            daily = comparable.group_by('date').agg(
                pl.col(metric+'_full').mean().alias('full'),
                pl.col(metric+'_without').mean().alias('without'),
                (pl.col(metric+'_full')-pl.col(metric+'_without')).mean().alias('value')).sort('date')
            values = dates.join(daily.select('date','value'), on='date', how='left', validate='1:1').sort('date')['value'].to_list()
            name = f'daily_mean_{metric}_difference'
            stream = int(digest({'seed':seed,'horizon':horizon,'metric':name,'contrast':contrast,'method':'paired_ic_v1'}),16)
            test = block_sign_test(values, config, stream)
            test.update(contrast=contrast, paired_periods=comparable.height,
                paired_full_mean=daily['full'].mean(), paired_without_mean=daily['without'].mean(),
                direction='full_minus_without; signed IC, not absolute IC',
                paired_observations=comparable['n'].sum())
            result[str(horizon)]['permutation'][name] = test
    return result
