"""Two-sided block sign randomization for daily IC; explicit symmetry assumptions."""

import math
import random
from dataclasses import dataclass

import polars as pl

from quantlab.storage.codec import digest


@dataclass(frozen=True)
class PermutationConfig:
    resamples: int = 999
    block_days: int = 5
    alpha: float = 0.05

    def __post_init__(self):
        if type(self.resamples) is not int or not 20 <= self.resamples <= 100000:
            raise ValueError('Permutation resamples must be an integer in [20, 100000]')
        if type(self.block_days) is not int or self.block_days < 1:
            raise ValueError('Permutation block_days must be a positive integer')
        if type(self.alpha) not in (int, float) or not math.isfinite(self.alpha) or not 0 < self.alpha < 1:
            raise ValueError('Permutation alpha must be in (0, 1)')


def block_sign_test(values, config: PermutationConfig, seed: int):
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v)) for v in values):
        raise ValueError('Daily values must be finite numbers or null')
    valid = [v for v in values if v is not None]
    # Keep missing dates in their original slots. Flip each entire nonempty block.
    blocks = []
    for start in range(0, len(values), config.block_days):
        block = [v for v in values[start:start+config.block_days] if v is not None]
        if block:
            blocks.append(math.fsum(block))
    result = {'method': 'nonoverlapping_date_block_sign_v1', 'alternative': 'two-sided',
        'null': 'joint distribution of date blocks is invariant under independent sign flips around zero',
        'status': 'unavailable', 'reason': None, 'observed_days': len(values),
        'valid_days': len(valid), 'nonempty_blocks': len(blocks), 'minimum_blocks': 6,
        'block_days': config.block_days, 'estimate': math.fsum(valid)/len(valid) if valid else None,
        'resamples_requested': config.resamples, 'resamples_used': 0, 'seed': seed,
        'sampling': None, 'p_value': None}
    if len(blocks) < 6:
        result['reason'] = 'insufficient_nonempty_blocks'
        return result
    exact = len(blocks) < config.resamples.bit_length()
    count = (1 << len(blocks)) if exact else config.resamples
    rng = random.Random(seed)
    observed = abs(result['estimate'])
    tolerance = 1e-14 * max(1.0, observed)
    extreme = 0
    for index in range(count):
        if index%100==0:
            from quantlab.progress import checkpoint
            checkpoint()
        signs = index if exact else rng.getrandbits(len(blocks))
        statistic = abs(math.fsum(value if (signs >> i) & 1 else -value for i, value in enumerate(blocks))/len(valid))
        extreme += statistic >= observed - tolerance
    result.update(status='computed', sampling='exact' if exact else 'monte_carlo',
        resamples_used=count, p_value=extreme/count if exact else (extreme+1)/(count+1))
    return result


def permutation_statistics(observations, horizons, config, seed):
    frame = observations.sort('datetime', 'symbol')
    if 'eligible' in frame.columns:
        frame = frame.filter(pl.col('eligible'))
    frame = frame.with_columns(pl.col('datetime').dt.date().alias('date'))
    dates = frame.select('date').unique().sort('date')
    result = {}
    for horizon in horizons:
        label = f'forward_{horizon}'
        valid = frame.filter(pl.col('value').is_finite() & pl.col(label).is_finite())
        correlations = valid.group_by('datetime').agg(pl.len().alias('n'),
            pl.corr('value', label).alias('ic'),
            pl.corr('value', label, method='spearman').alias('rank_ic')).filter(pl.col('n') >= 3)
        correlations = correlations.with_columns(pl.col('datetime').dt.date().alias('date'))
        result[str(horizon)] = {}
        for metric in ('ic', 'rank_ic'):
            name = 'daily_mean_' + metric
            daily = correlations.filter(pl.col(metric).is_finite()).group_by('date').agg(pl.col(metric).mean().alias('value'))
            values = dates.join(daily, on='date', how='left', validate='1:1').sort('date')['value'].to_list()
            stream = int(digest({'seed': seed, 'horizon': horizon, 'metric': name, 'method': 'block_sign_v1'}), 16)
            result[str(horizon)][name] = block_sign_test(values, config, stream)
    return result


def holm(p_values):
    """Holm FWER adjustment, reserving missing hypotheses at p=1 internally."""
    if any(p is not None and (type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1) for p in p_values):
        raise ValueError('p-values must be in [0, 1] or null')
    result = [None] * len(p_values)
    ordered = sorted((p, i) for i, p in enumerate(p_values) if p is not None)
    previous = 0.0
    for rank, (p, i) in enumerate(ordered):
        previous = max(previous, min(1.0, (len(p_values)-rank)*p))
        result[i] = previous
    return result


def inference_family(record, config):
    """Recompute from raw p-values, not adjusted child p-values; no disk traversal."""
    tests = []
    def visit(node, path):
        for horizon, metrics in node.get('metrics', {}).items():
            for metric, test in metrics.get('permutation', {}).items():
                tests.append({'path': path, 'horizon': horizon, 'metric': metric, **test})
        for key in ('children', 'periods', 'folds', 'evaluations', 'contrasts'):
            for index, child in enumerate(node.get(key, [])):
                label = child.get('name', child.get('phase', str(index+1)))
                visit(child, f'{path}/{key}/{label}')
    visit(record, 'study')
    adjusted = holm([t['p_value'] for t in tests])
    for test, p in zip(tests, adjusted):
        test.update(p_holm=p, reject_holm=p <= config.alpha if p is not None else None)
    return {'method': 'holm_fwer', 'alpha': config.alpha, 'family_scope': 'all_record_descendant_horizons_ic_and_paired_contrasts' if record.get('contrasts') else 'all_record_descendant_horizons_and_ic_metrics',
        'planned_tests': len(tests), 'available_tests': sum(p is not None for p in adjusted), 'tests': tests,
        'limitations': 'Conditional on valid sign-symmetry assumptions. No correction across separately launched studies or for prior exploration; not proof of causal contribution or net trading profit.'}


def inference_report(summary):
    def show(value):
        return 'N/A' if value is None else f'{value:.6g}'
    lines = ['', '## 日期块符号置换与 Holm 多重检验', '',
        '检验日均 IC / Rank IC 相对零的双侧偏离；每个时点至少 3 个有效标的，先同日平均，再日期等权。',
        '零假设要求日期块的联合分布允许各块独立翻转符号；块长未经自动校准，跨块依赖和重叠标签可能使此前提不成立。',
        '连续块按样本中出现的日期划分，保留缺失日期位置；末尾短块保留。至少 6 个非空块。',
        f"Holm 检验族：当前记录全部参数/阶段/持有期的 IC、Rank IC 及已启用配对差异；计划 {summary['planned_tests']} 项，可检验 {summary['available_tests']} 项，alpha={summary['alpha']}。缺失项仍占校正名额。",
        '父研究使用全部子项的原始 p 值重新校正；单个子实验的校正结果不能替代整个扫描研究。未校正独立启动的其他研究或此前探索。', '',
        '| 路径 | 持有期 | 统计量 | 日均值 | 非空块 | 方式/次数 | 原始 p | Holm p | 拒绝零假设 | 状态 |',
        '|---|---|---|---:|---:|---|---:|---:|---|---|']
    if any('contrast' in t for t in summary['tests']):
        lines[2:2] = ['配对差异 = 完整组合有符号 IC − 删减组合有符号 IC；双方使用相同股票、时点及收益标签。只保留双方 IC 均可计算的时点，再同日平均。',
            '配对均值仅使用双方 IC 均有效的共同截面，可能不同于分别计算后相减的描述性汇总差值。正差异表示有符号 IC 更高，不等同于绝对预测强度更高。双侧拒绝也可能是负贡献；缺失/常数截面不填零。差异与各子实验 IC 检验共同纳入 Holm。', '']
    for t in summary['tests']:
        reject = 'N/A' if t['reject_holm'] is None else ('是' if t['reject_holm'] else '否')
        lines.append(f"| {t['path']} | {t['horizon']} | {t['metric']} | {show(t['estimate'])} | {t['nonempty_blocks']} | {t['sampling'] or 'N/A'}/{t['resamples_used']} | {show(t['p_value'])} | {show(t['p_holm'])} | {reject} | {t['reason'] or t['status']} |")
    lines += ['', '精确模式枚举全部符号组合；Monte Carlo 均匀有放回抽取，并以 (极端次数+1)/(抽样次数+1) 计算 p 值。',
        '该检验不等于因子/标签完全独立置换、不证明因果贡献或扣成本后的策略盈利。', '']
    return '\n'.join(lines)
