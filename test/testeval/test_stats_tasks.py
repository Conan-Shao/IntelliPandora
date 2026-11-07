# -*- coding: utf-8 -*-
"""
@File  : test_stats_tasks.py
@Time  : 2026-11-07

The success rate is the mean of the tasks' rates, and its interval resamples
tasks: the trials of one task are not independent, so pooling them all into
one Wilson interval made it too narrow. Configurations are compared pairwise
on the tasks they share, Bonferroni-corrected, and an interval spanning zero
is "no reliable difference".
"""
import json

import pytest

from ipandora.core.eval import EvalRun, stats
from ipandora.core.eval.trial import Manifest, Trial


def _run(rates, k=5, harness='h', run_id='r'):
    """rates: task -> successes out of k."""
    _trials = [Trial(task_id=_t, index=_i, checks=[{'name': 'x', 'ok': _i < _c, 'required': True}])
               for _t, _c in rates.items() for _i in range(k)]
    return EvalRun(run_id=run_id, manifest=Manifest(trials=k, harness=harness, dataset_hash='d'),
                   tasks=[{'id': _t} for _t in rates], trials=_trials)


class TestTaskMean:

    def test_every_task_counts_once(self):
        # a task with more decided trials does not weigh more
        _m, _, _ = stats.task_mean({'a': [1.0] * 10, 'b': [0.0, 0.0]})
        assert _m == 0.5

    def test_the_interval_is_wider_than_pooled_wilson_when_tasks_are_all_or_nothing(self):
        # 30 tasks x 5 trials: an agent either can do a task or cannot
        _outcomes = {'t{}'.format(_i): [1.0 if _i % 2 else 0.0] * 5 for _i in range(30)}
        _m, _lo, _hi = stats.task_mean(_outcomes)
        _wlo, _whi = stats.wilson(75, 150)
        assert _m == 0.5 and (_hi - _lo) > 1.4 * (_whi - _wlo)
        assert 0.3 <= _lo <= 0.4 and 0.6 <= _hi <= 0.7                # about ±15 points, as PLAN.md expects

    def test_reproducible_and_empty(self):
        _o = {'a': [1.0, 0.0], 'b': [1.0, 1.0], 'c': [0.0]}
        assert stats.task_mean(_o) == stats.task_mean(_o)
        assert stats.task_mean({}) == (None, None, None) and stats.task_mean({'a': []}) == (None, None, None)

    def test_the_summary_uses_it(self):
        _s = _run({'a': 5, 'b': 0, 'c': 5, 'd': 0}).summary()
        assert _s['success_rate'] == 0.5 and _s['pooled_rate'] == 0.5
        assert _s['interval'] == list(stats.task_mean(_run({'a': 5, 'b': 0, 'c': 5, 'd': 0}).outcomes())[1:])
        assert _s['interval'][1] - _s['interval'][0] > _s['wilson'][1] - _s['wilson'][0]


class TestPairwise:

    def test_every_pair_once_with_a_bonferroni_level(self):
        _runs = {_n: {'a': [1.0], 'b': [0.0]} for _n in ('x', 'y', 'z')}
        _c = stats.pairwise(_runs)
        assert [(_r['a'], _r['b']) for _r in _c] == [('x', 'y'), ('x', 'z'), ('y', 'z')]
        assert all(abs(_r['level'] - (1 - 0.05 / 3)) < 1e-12 for _r in _c)

    def test_no_reliable_difference_and_a_real_one(self):
        _same = {'a': {'t{}'.format(_i): [1.0, 0.0, 1.0, 0.0, 1.0] for _i in range(20)},
                 'b': {'t{}'.format(_i): [1.0, 1.0, 0.0, 0.0, 1.0] for _i in range(20)}}
        assert stats.pairwise(_same)[0]['verdict'] == stats.INDISTINGUISHABLE
        _better = {'a': {'t{}'.format(_i): [0.0] * 5 for _i in range(20)},
                   'b': {'t{}'.format(_i): [1.0] * 5 for _i in range(20)}}
        _c = stats.pairwise(_better)[0]
        assert _c['verdict'] == stats.BETTER and _c['difference'] == 1.0 and _c['tasks'] == 20

    def test_only_shared_tasks(self):
        _c = stats.pairwise({'a': {'x': [1.0], 'only-a': [1.0]}, 'b': {'x': [1.0]}})[0]
        assert _c['tasks'] == 1 and _c['only_in_base'] == ['only-a']


class TestCompareCommand:

    def _save(self, tmp_path, name, run):
        _p = tmp_path / '{}.json'.format(name)
        _p.write_text(json.dumps(run.to_dict(), ensure_ascii=False), encoding='utf-8')
        return str(_p)

    def test_pairs_and_names(self, tmp_path, capsys):
        from test.testeval.test_eval_cr1 import _cli
        _tasks = {'t{}'.format(_i): 5 for _i in range(20)}
        _a = self._save(tmp_path, 'a', _run({_t: 0 for _t in _tasks}, harness='dsh'))
        _b = self._save(tmp_path, 'b', _run(_tasks, harness='opencode'))
        assert _cli('compare', runs=[_a, _b], name=None) == 0
        _out = capsys.readouterr().out
        assert 'dsh → opencode  差 +100.0 个点' in _out and 'opencode 比 dsh 好' in _out
        assert _cli('compare', runs=[_a, _b], name=['x']) == 2              # one name per run
        assert _cli('compare', runs=[_a, _a], name=None) == 2               # two runs with one name

    def test_runs_on_different_datasets_are_not_comparable(self, tmp_path, capsys):
        from test.testeval.test_eval_cr1 import _cli
        _other = _run({'a': 5}, harness='b')
        _other.manifest.dataset_hash = 'other'
        assert _cli('compare', runs=[self._save(tmp_path, 'a', _run({'a': 5}, harness='a')),
                                     self._save(tmp_path, 'b', _other)], name=None) == 1
        assert '不可比  数据集内容不同' in capsys.readouterr().out
