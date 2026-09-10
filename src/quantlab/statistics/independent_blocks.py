"""Two-sample circular block bootstrap; unrelated dates are not paired."""
import math
import random
from quantlab.statistics.bootstrap import percentile
from quantlab.progress import checkpoint


def independent_mean_difference(candidate, baseline, config, seed):
    samples = (list(candidate), list(baseline))
    for values in samples:
        if any(v is not None and not math.isfinite(v) for v in values):
            raise ValueError('Nonfinite independent bootstrap input')
    valid = [[v for v in values if v is not None] for values in samples]
    means = [math.fsum(v)/len(v) if v else None for v in valid]
    estimate = means[0]-means[1] if all(v is not None for v in means) else None
    result = dict(method='independent_circular_date_block_bootstrap_v1',
        status='unavailable', reason=None, estimate=estimate,
        observed_days=[len(v) for v in samples], valid_days=[len(v) for v in valid],
        block_days=config.block_days, confidence=config.confidence,
        resamples_requested=config.resamples, resamples_used=0, seed=seed,
        ci_low=None, ci_high=None, p_value=None)
    if any(len(v) < 2*config.block_days for v in valid):
        result['reason'] = 'insufficient_valid_days_for_two_blocks'
        return result
    rng = random.Random(seed)
    def draw(values):
        n = len(values); sampled = []; count = 0
        while count < n:
            start = rng.randrange(n); length = min(config.block_days, n-count)
            sampled.extend(values[(start+j) % n] for j in range(length))
            count += length
        observed = [v for v in sampled if v is not None]
        return math.fsum(observed)/len(observed) if observed else None
    differences = []
    for index in range(config.resamples):
        if index % 100 == 0: checkpoint()
        a, b = (draw(values) for values in samples)
        if a is not None and b is not None: differences.append(a-b)
    result['resamples_used'] = len(differences)
    if len(differences) < 20:
        result['reason'] = 'insufficient_nonempty_resamples'
        return result
    tail = (1-config.confidence)/2
    differences.sort()
    # Approximate centered-bootstrap null test, not paired sign permutation.
    p = (1+sum(abs(d-estimate) >= abs(estimate) for d in differences))/(1+len(differences))
    result.update(status='computed', ci_low=percentile(differences, tail),
        ci_high=percentile(differences, 1-tail), p_value=p)
    return result
