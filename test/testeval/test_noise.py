# -*- coding: utf-8 -*-
"""
@File  : test_noise.py
@Time  : 2026-11-07

Measuring the infrastructure noise (E11): one configuration run again on
the same tasks, and how far apart the runs are. Two versions differ only
when the difference is outside the statistical error *and* beyond this
noise (docs/design/decisions/13 §6) -- which was a number given by hand,
measured by nothing.
"""
import json
import random
import subprocess
import sys

import pytest

from ipandora.core.assertion.check import Check
from ipandora.core.eval import Dataset, EvalRun, evaluate, stats
from ipandora.core.eval.dataset import Task


class TestMeasure:

    def test_the_largest_gap_between_runs(self):
        _runs = [{'a': [1, 1], 'b': [0, 0]}, {'a': [1, 0], 'b': [0, 0]}, {'a': [1, 1], 'b': [1, 0]}]
        _n = stats.measure_noise(_runs)
        assert (_n['runs'], _n['tasks'], _n['rates']) == (3, 2, [0.5, 0.25, 0.75])
        assert _n['noise'] == 0.5 and _n['mean'] == 0.5 and abs(_n['sd'] - 0.25) < 1e-12

    def test_only_the_tasks_every_run_decided(self):
        # a task one run did not decide (infrastructure) would move that run's rate, not measure noise
        _n = stats.measure_noise([{'a': [1], 'b': [0], 'c': [1]}, {'a': [1], 'b': [], 'c': [0]}, {'a': [0], 'c': [0]}])
        assert _n['tasks'] == 2 and _n['rates'] == [1.0, 0.5, 0.0]

    def test_a_task_counts_once_however_many_trials(self):
        _n = stats.measure_noise([{'a': [1] * 10, 'b': [0]}, {'a': [1], 'b': [0] * 10}])
        assert _n['rates'] == [0.5, 0.5] and _n['noise'] == 0 and _n['sd'] == 0

    @pytest.mark.parametrize('runs, error', [([{'a': [1]}], 'two or more runs'), ([], 'two or more runs'),
                                             ([{'a': [1]}, {'b': [1]}], 'no task that every one')])
    def test_what_it_cannot_measure(self, runs, error):
        with pytest.raises(ValueError, match=error):
            stats.measure_noise(runs)


def grade(task, result):
    return [Check(name='答对', ok=result.output == 'right', expr='', src='output', claim='right')]


def coin(seed, p=0.6):
    """An agent right with probability p: nothing about it changes between runs but chance."""
    _rng = random.Random(seed)

    def _agent(task):
        return 'right' if _rng.random() < p else 'wrong'
    return _agent


DATA = Dataset('d', tasks=[Task(id='t{}'.format(_i), input='q') for _i in range(30)])


class TestAgainstTheGate:

    def test_a_rerun_is_within_the_noise_it_measured(self):
        _runs = [evaluate(DATA, coin(_s), grade, trials=3, check_references=False,
                          manifest={'harness': 'h', 'model': 'm'}) for _s in range(4)]
        _n = stats.measure_noise([_r.outcomes() for _r in _runs])
        assert _n['noise'] > 0
        _again = evaluate(DATA, coin(99), grade, trials=3, check_references=False).outcomes()
        _cmp = stats.compare(_runs[0].outcomes(), _again, noise=_n['noise'])
        assert _cmp['verdict'] == stats.INDISTINGUISHABLE

    def test_a_real_drop_is_beyond_it(self):
        _runs = [evaluate(DATA, coin(_s), grade, trials=3, check_references=False) for _s in range(4)]
        _n = stats.measure_noise([_r.outcomes() for _r in _runs])
        _worse = evaluate(DATA, coin(7, p=0.1), grade, trials=3, check_references=False).outcomes()
        assert stats.compare(_runs[0].outcomes(), _worse, noise=_n['noise'])['verdict'] == stats.WORSE


def save(tmp_path, name, seed, **manifest):
    _run = evaluate(DATA, coin(seed), grade, trials=2, check_references=False,
                    manifest=dict({'harness': 'h', 'model': 'm'}, **manifest))
    return _run.save(str(tmp_path / '{}.json'.format(name)))


def command(*args):
    return subprocess.run([sys.executable, '-m', 'ipandora.run', 'eval', 'noise', *args],
                          capture_output=True, text=True, timeout=120)


class TestTheCommand:

    def test_it_says_what_noise_to_use(self, tmp_path):
        _paths = [save(tmp_path, 'r{}'.format(_i), _i) for _i in range(3)]
        _done = command(*_paths)
        assert _done.returncode == 0, _done.stderr
        _n = stats.measure_noise([EvalRun.load(_p).outcomes() for _p in _paths])
        assert '和基线比较时用：--noise {:.3f}'.format(_n['noise']) in _done.stdout
        assert '3 次重跑之间成功率最多相差' in _done.stdout and '基础设施错误率 0.0%' in _done.stdout
        assert '只有两次运行' not in _done.stdout
        _json = json.loads(command(*_paths, '--json').stdout)
        assert _json['runs'] == 3 and abs(_json['noise'] - _n['noise']) < 1e-12 and _json['infra_rate'] == [0.0] * 3

    def test_two_runs_are_measured_with_a_warning(self, tmp_path):
        _done = command(save(tmp_path, 'a', 1), save(tmp_path, 'b', 2))
        assert _done.returncode == 0 and '只有两次运行' in _done.stdout

    @pytest.mark.parametrize('change, why', [({'model': 'other'}, '模型不同（m ≠ other）'),
                                             ({'harness': 'h2'}, '外壳不同（h ≠ h2）'),
                                             ({'config': {'temperature': 1}}, '配置不同'),
                                             ({'resources': {'cpu': 4}}, '沙箱资源不同')])
    def test_a_different_configuration_is_not_noise(self, tmp_path, change, why):
        _done = command(save(tmp_path, 'a', 1), save(tmp_path, 'b', 2, **change))
        assert _done.returncode == 1 and why in _done.stdout and '不是同一配置' in _done.stdout

    def test_one_run_or_a_missing_file(self, tmp_path):
        assert command(save(tmp_path, 'a', 1)).returncode == 2
        assert command(str(tmp_path / 'none.json'), str(tmp_path / 'a.json')).returncode == 2
