# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : stats.py
@Time  : 2026-11-05

Trial statistics, and when a difference between two runs is real.

Everything here is a closed formula or a seeded resampling, so the same
trials always give the same numbers. See docs/design/decisions/13 §6.

    wilson(k, n)        95% interval for a success rate
    pass_at_k(n, c, k)  chance that at least one of k tries succeeds
    pass_hat_k(n, c, k) chance that all k tries succeed (tau-bench's pass^k)
    compare(...)        paired comparison of two runs over the same tasks

Two versions are compared task by task, because each task is its own
difficulty: an unpaired test over pooled trials throws that away. With one
trial per task the outcomes are 0/1 and McNemar's exact test applies; with
several, or with partial scores, the comparison is resampled at both levels
-- tasks, and the trials inside each task -- so a task's own trial noise is
counted (paired, hierarchical bootstrap). A difference is only called better or worse when it is
outside the statistical error *and* larger than the infrastructure noise
measured for the environment -- otherwise it is "indistinguishable".
"""
import bisect
import math
import random
from typing import Dict, List, Optional, Sequence, Tuple

Z95 = 1.959963984540054

BETTER, WORSE, INDISTINGUISHABLE = 'better', 'worse', 'indistinguishable'


def wilson(successes: int, n: int, z: float = Z95) -> Tuple[float, float]:
    """Wilson score interval. (0, 1) for n == 0: no trials, no information."""
    if n <= 0:
        return 0.0, 1.0
    _p = successes / n
    _den = 1 + z * z / n
    _centre = (_p + z * z / (2 * n)) / _den
    _half = z * math.sqrt(_p * (1 - _p) / n + z * z / (4 * n * n)) / _den
    return max(0.0, _centre - _half), min(1.0, _centre + _half)


def pass_at_k(n: int, c: int, k: int) -> Optional[float]:
    """
    Unbiased estimate of P(at least one of k samples succeeds), from n samples
    with c successes: 1 - C(n-c, k) / C(n, k). None when k > n.
    """
    if k <= 0 or k > n:
        return None
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> Optional[float]:
    """
    Unbiased estimate of P(all of k samples succeed): C(c, k) / C(n, k)
    (tau-bench, arXiv 2406.12045). None when k > n. This is what a user who
    runs the agent k times and needs every run right experiences.
    """
    if k <= 0 or k > n:
        return None
    return math.comb(c, k) / math.comb(n, k)


def mcnemar_exact(b: int, c: int) -> float:
    """
    Two-sided exact McNemar p-value: b tasks went from pass to fail, c from
    fail to pass. Under no difference each discordant task is a fair coin.
    """
    _n = b + c
    if _n == 0:
        return 1.0
    _tail = sum(math.comb(_n, _i) for _i in range(0, min(b, c) + 1)) / (2 ** _n)
    return min(1.0, 2 * _tail)


def paired_bootstrap(differences: Sequence[float], resamples: int = 2000,
                     seed: int = 0, level: float = 0.95) -> Tuple[float, float, float]:
    """(mean, low, high) of the mean of per-task differences. Seeded: reproducible."""
    _d = list(differences)
    if not _d:
        return 0.0, 0.0, 0.0
    _mean = sum(_d) / len(_d)
    # bandit B311: resampling for a confidence interval, not secrecy
    _rng = random.Random(seed)  # nosec B311
    _means = sorted(sum(_rng.choice(_d) for _ in _d) / len(_d) for _ in range(resamples))
    _lo = _means[int((1 - level) / 2 * resamples)]
    _hi = _means[min(resamples - 1, int((1 + level) / 2 * resamples))]
    return _mean, _lo, _hi


def _sampler(outcomes: List[float]):
    """
    A function drawing the mean of len(outcomes) outcomes resampled with
    replacement. For 0/1 outcomes that mean is a binomial count over n, drawn
    from its precomputed distribution with one random number -- the same
    distribution as n separate draws, at a fraction of the cost.
    """
    _n = len(outcomes)
    if all(_x in (0.0, 1.0) for _x in outcomes):
        _p = sum(outcomes) / _n
        _cdf, _acc = [], 0.0
        for _k in range(_n + 1):
            _acc += math.comb(_n, _k) * _p ** _k * (1 - _p) ** (_n - _k)
            _cdf.append(_acc)
        _cdf[-1] = 1.0
        return lambda rng: bisect.bisect_left(_cdf, rng.random()) / _n
    return lambda rng: sum(rng.choices(outcomes, k=_n)) / _n


def hierarchical_bootstrap(base: Dict[str, List[float]], now: Dict[str, List[float]],
                           tasks: Sequence[str], resamples: int = 2000, seed: int = 0,
                           level: float = 0.95) -> Tuple[float, float]:
    """
    Interval for the mean per-task difference, resampling at both levels:
    tasks, and the trials within each task on each side.

    Resampling tasks alone treats a task's success rate as known exactly. With
    5 trials it is not: a task that went from 5/5 to 3/5 is within what
    sampling alone produces, and a one-task comparison resampled only over
    tasks came out with a zero-width interval and a confident "worse".
    """
    _tasks = list(tasks)
    if not _tasks:
        return 0.0, 0.0
    # bandit B311: resampling for a confidence interval, not secrecy
    _rng = random.Random(seed)  # nosec B311
    _sides = [(_sampler(base[_t]), _sampler(now[_t])) for _t in _tasks]
    _means = []
    for _ in range(resamples):
        _total = 0.0
        for _base, _now in _rng.choices(_sides, k=len(_sides)):
            _total += _now(_rng) - _base(_rng)
        _means.append(_total / len(_sides))
    _means.sort()
    return (_means[int((1 - level) / 2 * resamples)],
            _means[min(resamples - 1, int((1 + level) / 2 * resamples))])


def compare(base: Dict[str, List[float]], now: Dict[str, List[float]], noise: float = 0.0,
            resamples: int = 2000, seed: int = 0) -> Dict[str, object]:
    """
    Compare two runs task by task.

    :param base, now: task id -> the outcomes of its trials (1.0/0.0, or a
                      partial score). Only tasks present in both are compared.
    :param noise:     the infrastructure noise, as a rate (0.021 for ±2.1
                      points), measured by running one version repeatedly.

    Returns the verdict, the mean difference in success rate and its interval,
    how many tasks got better, worse or stayed, and the test used.
    """
    _tasks = sorted(set(base) & set(now))
    _rate = {_t: (sum(base[_t]) / len(base[_t]), sum(now[_t]) / len(now[_t]))
             for _t in _tasks if base[_t] and now[_t]}
    _diffs = [_n - _b for _b, _n in _rate.values()]
    _worse = sum(1 for _d in _diffs if _d < 0)
    _better = sum(1 for _d in _diffs if _d > 0)
    _out = {'tasks': len(_rate), 'worse': _worse, 'better': _better,
            'same': len(_rate) - _worse - _better, 'noise': noise,
            'only_in_base': sorted(set(base) - set(now)),
            'only_in_now': sorted(set(now) - set(base))}
    if not _rate:
        _out.update({'verdict': INDISTINGUISHABLE, 'difference': 0.0, 'low': 0.0, 'high': 0.0,
                     'test': 'none', 'p': 1.0})
        return _out

    _binary = all(len(base[_t]) == 1 and len(now[_t]) == 1
                  and base[_t][0] in (0.0, 1.0) and now[_t][0] in (0.0, 1.0) for _t in _rate)
    if _binary:
        _mean, _lo, _hi = paired_bootstrap(_diffs, resamples=resamples, seed=seed)
        _p = mcnemar_exact(_worse, _better)
        _significant = _p < 0.05
        _out.update({'test': 'mcnemar', 'p': _p})
    else:
        _mean = sum(_diffs) / len(_diffs)
        _lo, _hi = hierarchical_bootstrap(base, now, sorted(_rate), resamples=resamples, seed=seed)
        _significant = _lo > 0 or _hi < 0
        _out.update({'test': 'paired_bootstrap', 'p': None})
    _out.update({'difference': _mean, 'low': _lo, 'high': _hi})
    if _significant and abs(_mean) > noise:
        _out['verdict'] = BETTER if _mean > 0 else WORSE
    else:
        _out['verdict'] = INDISTINGUISHABLE
    return _out
