# -*- coding: utf-8 -*-
"""
@File  : test_gate.py
@Time  : 2026-11-06

The regression gate (docs/design/decisions/13 §6, E4). Acceptance: a change
that really makes the agent worse is stopped; a re-run that differs only by
noise is not. Plus the per-tag gate with its correction, broken tasks, and
saturation.
"""
import json
import random

import pytest

from ipandora.core.assertion.check import Check
from ipandora.core.eval import Dataset, Task, baseline, evaluate, stats, trend

TRIALS = 5


def data(n=40, tags=None):
    return Dataset('gate', '1', [Task(id='t{:02d}'.format(_i), input=_i,
                                      tags=(tags(_i) if tags else {'kind': 'k{}'.format(_i % 4)}))
                                 for _i in range(n)])


def agent_with(rate, seed, rate_of=None):
    """An agent that succeeds on task i with probability rate (or rate_of(i)), reproducibly."""
    _calls = {}

    def agent(task):
        _n = _calls[task.id] = _calls.get(task.id, -1) + 1
        _p = rate_of(task.input) if rate_of else rate
        return random.Random('{}#{}#{}'.format(seed, task.id, _n)).random() < _p
    return agent


def grade(task, result):
    return [Check(name='answer', ok=bool(result.output))]


def run(dataset, agent):
    return evaluate(dataset, agent, grade, trials=TRIALS, check_references=False)


class TestTheGate:
    """Acceptance: a real regression is stopped, noise is not."""

    def test_a_real_regression_fails_and_noise_does_not(self):
        _d = data()
        _base = baseline.build(run(_d, agent_with(0.8, 'v1')))
        _noise = baseline.compare(run(_d, agent_with(0.8, 'v1-rerun')), _base)
        assert _noise['verdict'] == stats.INDISTINGUISHABLE and baseline.regressions(_noise) == []
        _worse = baseline.compare(run(_d, agent_with(0.5, 'v2')), _base)
        assert _worse['verdict'] == stats.WORSE
        assert baseline.regressions(_worse)[0].startswith('整体变差')

    def test_noise_never_fails_over_many_reruns(self):
        _d = data()
        _base = baseline.build(run(_d, agent_with(0.7, 'base')))
        _alarms = sum(bool(baseline.regressions(baseline.compare(run(_d, agent_with(0.7, 'rerun{}'.format(_i))),
                                                                 _base), 'tag')) for _i in range(10))
        assert _alarms <= 1                 # 5% at most per comparison, corrected across tags

    def test_a_regression_confined_to_one_tag_needs_the_tag_gate(self):
        _d = data(n=60, tags=lambda i: {'kind': 'refund' if i < 15 else 'other{}'.format(i % 3)})
        _base = baseline.build(run(_d, agent_with(0.9, 'v1')))
        _cmp = baseline.compare(run(_d, agent_with(0, 'v2', rate_of=lambda i: 0.2 if i < 15 else 0.9)), _base)
        _refund = next(_t for _t in _cmp['by_tag'] if _t['value'] == 'refund')
        assert _refund['verdict'] == stats.WORSE and _refund['level'] > 0.95
        assert any('kind=refund 变差' in _r for _r in baseline.regressions(_cmp, 'tag'))

    def test_a_broken_task_needs_the_task_gate(self):
        _d = data(n=40)
        _base = baseline.build(run(_d, agent_with(0, 'v1', rate_of=lambda i: 1.0)))
        _cmp = baseline.compare(run(_d, agent_with(0, 'v2', rate_of=lambda i: 0.0 if i == 7 else 1.0)), _base)
        assert _cmp['verdict'] == stats.INDISTINGUISHABLE and _cmp['broken'] == ['t07']
        assert baseline.regressions(_cmp, 'overall') == baseline.regressions(_cmp, 'tag') == []
        assert baseline.regressions(_cmp, 'task') == ['以前全过、现在全挂的任务：t07']

    def test_not_comparable_always_fails_and_a_bad_gate_is_named(self):
        assert baseline.regressions({'not_comparable': ['数据集内容不同'], 'by_tag': []})
        with pytest.raises(ValueError, match='unknown gate'):
            baseline.regressions({}, 'everything')

    def test_the_level_tightens_the_test(self):
        _base = {'t{}'.format(_i): [1.0] for _i in range(12)}
        _now = dict(_base, **{'t{}'.format(_i): [0.0] for _i in range(6)})
        assert stats.compare(_base, _now)['verdict'] == stats.WORSE              # p = 0.031
        assert stats.compare(_base, _now, level=0.99)['verdict'] == stats.INDISTINGUISHABLE


class TestSaturation:

    def _archive(self, tmp_path, rates, dataset='gate'):
        from ipandora.core.eval import report
        _d = data(n=20)
        for _i, _rate in enumerate(rates):
            _run = run(_d, agent_with(_rate, 'r{}'.format(_i)))
            _run.manifest.dataset, _run.manifest.started = dataset, '2026-11-0{} 10:00:00'.format(_i + 1)
            _run.run_id = 'eval-{}'.format(_i)
            report.write(_run, str(tmp_path / _run.run_id))
        return trend.history(str(tmp_path), dataset=dataset)

    def test_three_runs_at_the_top_saturate(self, tmp_path):
        _runs = self._archive(tmp_path, [0.5, 1.0, 1.0, 1.0])
        assert [_r.run_id for _r in _runs] == ['eval-0', 'eval-1', 'eval-2', 'eval-3']
        _s = trend.saturation(_runs)
        assert _s['saturated'] and _s['rates'] == [1.0, 1.0, 1.0] and len(_s['tasks']) == 20
        assert '可以毕业' in trend.sentence(_s)

    def test_not_yet(self, tmp_path):
        _s = trend.saturation(self._archive(tmp_path, [1.0, 1.0, 0.6]))
        assert not _s['saturated']
        assert trend.saturation(self._archive(tmp_path / 'b', [1.0, 1.0]))['saturated'] is False

    def test_some_tasks_saturate_before_the_set_does(self, tmp_path):
        _d = data(n=20)
        _runs = []
        for _i in range(3):
            _runs.append(run(_d, agent_with(0, 's{}'.format(_i), rate_of=lambda i: 1.0 if i < 5 else 0.5)))
        _s = trend.saturation(_runs)
        assert not _s['saturated'] and set(_s['tasks']) >= {'t00', 't01', 't02', 't03', 't04'}
        assert '可以考虑移到回归集' in trend.sentence(_s)

    def test_a_changed_dataset_starts_the_count_again(self, tmp_path):
        _runs = self._archive(tmp_path, [1.0, 1.0, 1.0])
        _runs[-1].manifest.dataset_hash = 'different'
        assert trend.saturation(_runs)['runs'] == 1

    def test_other_datasets_and_unreadable_reports_are_skipped(self, tmp_path):
        self._archive(tmp_path, [1.0], dataset='other')
        (tmp_path / 'junk').mkdir()
        (tmp_path / 'junk' / 'report.json').write_text('{not json')
        (tmp_path / 'tests').mkdir()
        (tmp_path / 'tests' / 'report.json').write_text(json.dumps({'view': 'tests'}))
        assert trend.history(str(tmp_path), dataset='gate') == []
        assert len(trend.history(str(tmp_path), dataset='other')) == 1


def test_the_command_gates_by_the_option_and_records_it(tmp_path, monkeypatch):
    from argparse import Namespace
    from ipandora.run.commands.eval import Command
    monkeypatch.setenv('IPANDORA_REPORTS_DIR', str(tmp_path / 'reports'))
    _d = data(n=40)
    _path = str(tmp_path / 'baseline.json')
    baseline.save(_path, run(_d, agent_with(0, 'v1', rate_of=lambda i: 1.0)))
    _broken = run(_d, agent_with(0, 'v2', rate_of=lambda i: 0.0 if i == 3 else 1.0))

    def conclude(gate, out):
        return Command._conclude(_broken, Namespace(
            baseline=_path, no_baseline=False, update_baseline=False, noise=0.0, partial=False,
            out=str(tmp_path / out), title=None, fail_on_regression=gate))
    assert conclude('overall', 'a') == 0
    assert conclude('task', 'b') == 1
    _json = json.loads((tmp_path / 'b' / 'report.json').read_text(encoding='utf-8'))
    assert _json['gate']['gate'] == 'task' and _json['gate']['reasons'] == ['以前全过、现在全挂的任务：t03']
    assert '门禁（task）不通过' in (tmp_path / 'b' / 'report.html').read_text(encoding='utf-8')
