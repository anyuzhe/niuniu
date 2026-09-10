"""Pairwise cross-sectional correlations and deterministic complete-link groups."""

import math
from itertools import combinations, combinations_with_replacement

import polars as pl
import numpy as np
from quantlab.statistics.bootstrap import BootstrapConfig, block_mean_interval
from quantlab.storage.codec import digest


def cross_section_correlations(panel: pl.DataFrame, aliases: list[str], min_symbols: int = 3,
                               min_periods: int = 5, *, bootstrap: BootstrapConfig | None = None,
                               random_seed: int = 0, boolean_aliases=(), return_labels=None) -> list[dict]:
    if type(random_seed) is not int:
        raise ValueError('random_seed must be an integer')
    if type(min_symbols) is not int or min_symbols < 3 or type(min_periods) is not int or min_periods < 1:
        raise ValueError("Require min_symbols >= 3 and min_periods >= 1")
    if not aliases or len(set(aliases)) != len(aliases):
        raise ValueError("Provide unique factor aliases")
    if panel.select(pl.struct('symbol', 'datetime').is_duplicated().any()).item():
        raise ValueError("Duplicate factor-panel keys")
    if panel['symbol'].null_count() or panel['datetime'].null_count():
        raise ValueError("Null factor-panel keys")
    panel = panel.sort('datetime', 'symbol')
    dates = panel.select(pl.col('datetime').dt.date().alias('date')).unique().sort('date') if bootstrap is not None else None
    for alias in aliases:
        column = pl.col(f'factor_{alias}')
        if panel.filter(column.is_not_null() & ~column.is_finite()).height:
            raise ValueError("Nonfinite factor-panel value")
    pairs = []
    for left, right in combinations_with_replacement(sorted(aliases), 2):
        x, y = f'factor_{left}', f'factor_{right}'
        matched = panel.filter(pl.col(x).is_not_null() & pl.col(y).is_not_null())
        periods = matched.group_by('datetime', maintain_order=True).agg(
            pl.len().alias('n'), pl.corr(x, y).alias('pearson'),
            pl.corr(x, y, method='spearman').alias('spearman'))
        sufficient = periods.filter(pl.col('n') >= min_symbols)
        item = {'left': left, 'right': right, 'common_rows': matched.height,
            'common_periods': periods.height, 'sufficient_symbol_periods': sufficient.height}
        if return_labels is not None:
            labelled=matched.join(return_labels,on=['symbol','datetime'],how='left',validate='1:1').filter(pl.col('forward_return').is_finite())
            ic=labelled.group_by('datetime').agg(pl.len().alias('n'),pl.corr(x,'forward_return').alias('left_ic'),pl.corr(y,'forward_return').alias('right_ic'))
            ic=ic.filter((pl.col('n')>=min_symbols)&pl.col('left_ic').is_finite()&pl.col('right_ic').is_finite()).sort('datetime')
            value=ic.select(pl.corr('left_ic','right_ic')).item() if ic.height>=min_periods else None
            item['ic_correlation']={'method':'paired_cross_section_ic_time_correlation_v1','horizon':1,'valid_periods':ic.height,
                'estimate':float(value) if value is not None and math.isfinite(value) else None,
                'scope':'One observed bar close-to-close research label; paired common security-date rows, no trade simulation.'}
        information=[]
        for group in matched.partition_by('datetime',maintain_order=True):
            if group.height<max(min_symbols,20):continue
            a=group[x].to_numpy();b=group[y].to_numpy()
            codes=[];sizes=[]
            for values in (a,b):
                unique=np.unique(values)
                if len(unique)<=5:codes.append(np.searchsorted(unique,values));sizes.append(len(unique))
                else:
                    edges=np.unique(np.quantile(values,np.linspace(0,1,6)))
                    codes.append(np.searchsorted(edges[1:-1],values,side='right'));sizes.append(len(edges)-1)
            if min(sizes)<2:continue
            cells=np.zeros(tuple(sizes));ai,bi=codes
            np.add.at(cells,(ai,bi),1);prob=cells/cells.sum();px=prob.sum(axis=1);py=prob.sum(axis=0)
            expected=px[:,None]*py[None,:];nonzero=prob>0
            mi=float(np.sum(prob[nonzero]*np.log(prob[nonzero]/expected[nonzero])))
            entropy=[float(-np.sum(v[v>0]*np.log(v[v>0]))) for v in (px,py)]
            if min(entropy)>0:information.append((mi,mi/math.sqrt(entropy[0]*entropy[1])))
        item['mutual_information']={'method':'five_quantile_bins_per_timestamp_v1','units':'nats','minimum_symbols':max(min_symbols,20),
            'valid_periods':len(information),'estimate':float(np.mean([v[0] for v in information])) if len(information)>=min_periods else None,
            'normalized':float(np.mean([v[1] for v in information])) if len(information)>=min_periods else None,
            'scope':'Descriptive sample estimate; finite-sample upward bias. Not an independence or significance test.'}
        if left in boolean_aliases and right in boolean_aliases:
            if matched.filter(~pl.col(x).is_in([0,1]) | ~pl.col(y).is_in([0,1])).height:raise ValueError('Boolean overlap requires 0/1 values')
            counts=matched.select((pl.col(x)==1).sum().alias('left'),(pl.col(y)==1).sum().alias('right'),
                ((pl.col(x)==1)&(pl.col(y)==1)).sum().alias('intersection'),((pl.col(x)==1)|(pl.col(y)==1)).sum().alias('union')).row(0,named=True)
            item['signal_overlap']={**counts,'jaccard':counts['intersection']/counts['union'] if counts['union'] and matched.height and sufficient.height>=min_periods else None,
                'method':'exact_symbol_timestamp_binary_jaccard_v1','scope':'Only paired non-null rows; counts shared triggers, not chronological sequence similarity.'}
        for method in ('pearson', 'spearman'):
            valid = sufficient.filter(pl.col(method).is_finite())[method]
            enough = len(valid) >= min_periods
            item[method] = max(-1.0, min(1.0, float(valid.mean()))) if enough else None
            item[f'{method}_periods'] = len(valid)
            item[f'{method}_status'] = 'computed' if enough else 'insufficient_valid_periods'
            if bootstrap is not None:
                daily = sufficient.filter(pl.col(method).is_finite()).with_columns(pl.col('datetime').dt.date().alias('date')).group_by('date', maintain_order=True).agg(
                    pl.col(method).clip(-1,1).mean().alias('value'))
                daily_values = dates.join(daily, on='date', how='left', validate='1:1').sort('date')['value'].to_list()
                seed = int(digest({'seed':random_seed,'left':left,'right':right,'method':method}),16)
                if enough:
                    interval = block_mean_interval(daily_values, bootstrap, seed)
                else:
                    interval = block_mean_interval([], bootstrap, seed)
                    finite = [v for v in daily_values if v is not None]
                    interval.update({'reason':'insufficient_valid_periods', 'observed_days':len(daily_values),
                        'valid_days':len(finite), 'estimate':math.fsum(finite)/len(finite) if finite else None})
                interval.update({'estimand':'equal_date_mean_cross_section_correlation', 'valid_periods':len(valid), 'min_periods':min_periods})
                item.setdefault('bootstrap', {})[method] = interval
        pairs.append(item)
    return pairs


def complete_link_groups(aliases: list[str], pairs: list[dict], threshold: float = 0.8) -> list[list[str]]:
    """Merge the strongest complete-link pair; absolute mean Spearman similarity.

    Missing/insufficient pairs never qualify. Lexical ties give stable output.
    All members of a returned group meet the threshold pairwise.
    """
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("Cluster threshold must be in (0, 1]")
    if len(set(aliases)) != len(aliases):
        raise ValueError("Provide unique factor aliases")
    scores = {tuple(sorted((p['left'], p['right']))): abs(p['spearman'])
        for p in pairs if p['left'] != p['right'] and p['spearman'] is not None and math.isfinite(p['spearman'])}
    groups = [(alias,) for alias in sorted(aliases)]
    while True:
        candidates = []
        for first, second in combinations(groups, 2):
            similarities = [scores.get(tuple(sorted((a, b)))) for a in first for b in second]
            if all(s is not None and s >= threshold for s in similarities):
                candidates.append((-min(similarities), first, second))
        if not candidates:
            return [list(group) for group in groups]
        _, first, second = min(candidates)
        groups.remove(first)
        groups.remove(second)
        groups.append(tuple(sorted(first + second)))
        groups.sort()
