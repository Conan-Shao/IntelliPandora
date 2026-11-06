# -*- coding: utf-8 -*-
"""
@File  : test_inspect.py
@Time  : 2026-11-06

The Inspect path (docs/design/decisions/13 §3, E1): Inspect logs read into an
EvalRun, and the framework's graders as Inspect scorers. Every test runs a
real Inspect eval on Inspect's mock model -- no network, no API key.
"""
import asyncio
import os
import subprocess
import sys

import pytest

pytest.importorskip('inspect_ai', reason='the Inspect path needs the `inspect` extra (Python 3.11+)')

from inspect_ai import Task  # noqa: E402
from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.scorer import (CORRECT, INCORRECT, Score, accuracy, includes, match,  # noqa: E402
                               model_graded_qa, scorer)
from inspect_ai.solver import generate, solver  # noqa: E402

from ipandora.core.assertion.check import Check  # noqa: E402
from ipandora.core.eval import inspect_log, inspect_scorer  # noqa: E402
from ipandora.core.eval.trial import GRADED, INFRA, LLM_JUDGE, NO_VERDICT  # noqa: E402

MOCK = 'mockllm/model'
ANSWER = 'Default output from mockllm/model'      # what the mock model always says


def samples():
    return [Sample(id='hit', input='say something', target='Default',
                   metadata={'tags': {'kind': 'easy'}, 'polarity': 'do', 'split': 'dev'}),
            Sample(id='miss', input='say something else', target='nope',
                   metadata={'tags': {'kind': 'hard'}})]


def run(tmp_path, *tasks, model=MOCK, **kwargs):
    _logs = inspect_eval(list(tasks), model=model, log_dir=str(tmp_path / 'logs'), display='none',
                         **kwargs)
    assert all(_l.status == 'success' for _l in _logs), [_l.error for _l in _logs]
    return [_l.location for _l in _logs]


@scorer(metrics=[accuracy()])
def graded_parts():
    async def score(state, target):
        return Score(value={'exact': CORRECT, 'close': 0.5}, explanation='two parts')
    return score


class TestReadingLogs:

    def test_every_sample_and_epoch_is_a_trial(self, tmp_path):
        _logs = run(tmp_path, Task(name='qa', dataset=samples(), solver=generate(), scorer=includes()),
                    epochs=3)
        _run = inspect_log.read(_logs[0])
        assert sorted((_t.task_id, _t.index) for _t in _run.trials) == [
            ('hit', 0), ('hit', 1), ('hit', 2), ('miss', 0), ('miss', 1), ('miss', 2)]
        _by = {_t.task_id: _t for _t in _run.trials}
        assert _by['hit'].success is True and _by['miss'].success is False
        assert _by['miss'].category == 'agent'
        assert _by['hit'].output == ANSWER
        assert _by['hit'].checks[0]['name'] == 'Inspect 评分：includes'
        assert _by['hit'].cost['tokens_out'] > 0
        assert _by['hit'].trajectory[0]['kind'] == 'message'
        _s = _run.summary()
        assert (_s['trials'], _s['successes'], _s['k'], _s['pass_hat_k']) == (6, 3, 3, 0.5)
        assert _run.manifest.model == MOCK and _run.manifest.trials == 3
        assert _run.manifest.harness.startswith('inspect_ai ')
        assert {_t['id']: (_t['tags'], _t['split']) for _t in _run.tasks} == {
            'hit': ({'kind': 'easy'}, 'dev'), 'miss': ({'kind': 'hard'}, 'test')}

    def test_the_dataset_hash_follows_the_samples(self, tmp_path):
        _a = inspect_log.read(run(tmp_path / 'a', Task(name='qa', dataset=samples(), scorer=match()))[0])
        _b = inspect_log.read(run(tmp_path / 'b', Task(name='qa', dataset=samples(), scorer=match()))[0])
        _changed = samples()
        _changed[1] = Sample(id='miss', input='a different question', target='nope')
        _c = inspect_log.read(run(tmp_path / 'c', Task(name='qa', dataset=_changed, scorer=match()))[0])
        assert _a.manifest.dataset_hash == _b.manifest.dataset_hash != _c.manifest.dataset_hash
        assert _a.manifest.comparable_with(_b.manifest) == []

    def test_a_dict_score_is_one_check_per_entry_and_threshold_applies(self, tmp_path):
        _log = run(tmp_path, Task(name='parts', dataset=samples()[:1], scorer=graded_parts()))[0]
        _checks = {_c['name']: _c['ok'] for _c in inspect_log.read(_log).trials[0].checks}
        assert _checks == {'Inspect 评分：graded_parts.exact': True, 'Inspect 评分：graded_parts.close': False}
        _half = inspect_log.read(_log, threshold={'graded_parts': 0.5}).trials[0]
        assert _half.success is True
        assert inspect_log.read(_log, threshold={'*': 0.5}).trials[0].success is True

    def test_a_model_graded_score_is_a_judge_and_decides_nothing(self, tmp_path):
        _log = run(tmp_path, Task(name='judged', dataset=samples()[:1],
                                  scorer=model_graded_qa(model=MOCK)))[0]
        _trial = inspect_log.read(_log).trials[0]
        assert [_c['src'] for _c in _trial.checks] == [LLM_JUDGE]
        assert _trial.success is None and _trial.status == NO_VERDICT

    def test_a_custom_judge_is_named(self, tmp_path):
        _log = run(tmp_path, Task(name='qa', dataset=samples()[:1], scorer=includes()))[0]
        _trial = inspect_log.read(_log, judges=['includes']).trials[0]
        assert _trial.checks[0]['src'] == LLM_JUDGE and _trial.success is None

    def test_an_error_is_the_infrastructure_not_the_agent(self, tmp_path):
        @solver
        def broken():
            async def solve(state, generate):
                raise RuntimeError('the sandbox did not start')
            return solve
        _logs = inspect_eval(Task(name='broken', dataset=samples()[:1], solver=broken(), scorer=match()),
                             model=MOCK, log_dir=str(tmp_path / 'logs'), display='none',
                             fail_on_error=False)
        _trial = inspect_log.read(_logs[0].location).trials[0]
        assert (_trial.status, _trial.category) == (INFRA, 'infra')
        assert 'the sandbox did not start' in _trial.error
        assert inspect_log.read(_logs[0].location).summary()['infra'] == 1

    def test_a_time_limit_is_the_infrastructure(self, tmp_path):
        @solver
        def slow():
            async def solve(state, generate):
                await asyncio.sleep(5)
                return state
            return solve
        _log = run(tmp_path, Task(name='slow', dataset=samples()[:1], solver=slow(), scorer=match(),
                                  time_limit=1))[0]
        _trial = inspect_log.read(_log).trials[0]
        assert _trial.status == INFRA and 'time' in _trial.error

    def test_another_limit_is_a_failed_budget_check(self, tmp_path):
        _log = run(tmp_path, Task(name='chatty', dataset=samples()[:1], solver=generate(), scorer=includes(),
                                  message_limit=1))[0]
        _trial = inspect_log.read(_log).trials[0]
        _budget = [_c for _c in _trial.checks if _c['src'] == 'budget']
        assert _budget and not _budget[0]['ok'] and _budget[0]['name'] == '预算内：message'
        assert _trial.success is False

    def test_several_tasks_are_one_run_with_prefixed_ids(self, tmp_path):
        _logs = run(tmp_path, Task(name='one', dataset=samples(), scorer=includes()),
                    Task(name='two', dataset=samples(), scorer=includes()))
        _run = inspect_log.read(str(tmp_path / 'logs'))
        assert sorted({_t.task_id for _t in _run.trials}) == ['one/hit', 'one/miss', 'two/hit', 'two/miss']
        assert {_t['tags']['task'] for _t in _run.tasks} == {'one', 'two'}
        assert len(_logs) == 2

    def test_two_runs_of_one_task_are_refused(self, tmp_path):
        run(tmp_path, Task(name='qa', dataset=samples(), scorer=includes()))
        run(tmp_path, Task(name='qa', dataset=samples(), scorer=includes()))
        with pytest.raises(ValueError, match='more than one log of task qa'):
            inspect_log.read(str(tmp_path / 'logs'))

    def test_two_models_are_refused(self, tmp_path):
        _a = run(tmp_path, Task(name='a', dataset=samples(), scorer=includes()))[0]
        _b = run(tmp_path, Task(name='b', dataset=samples(), scorer=includes()), model='mockllm/other')[0]
        with pytest.raises(ValueError, match='different models'):
            inspect_log.read([_a, _b])

    def test_a_missing_path_is_named(self, tmp_path):
        with pytest.raises(ValueError, match='no such log'):
            inspect_log.read(str(tmp_path / 'nowhere.eval'))
        (tmp_path / 'empty').mkdir()
        with pytest.raises(ValueError, match='no Inspect logs'):
            inspect_log.read(str(tmp_path / 'empty'))


def contains_default(task, result):
    return [Check(name='answer mentions Default', ok='Default' in (result.output or ''),
                  expr=repr(result.output)),
            Check(name='expected is the target', ok=task.expected in ('Default', 'nope'),
                  expr=repr(task.expected))]


class TestScorer:

    def test_the_graders_checks_reach_the_report_by_name(self, tmp_path):
        _log = run(tmp_path, Task(name='qa', dataset=samples(), scorer=inspect_scorer.scorer(contains_default)))[0]
        _run = inspect_log.read(_log)
        _by = {_t.task_id: _t for _t in _run.trials}
        assert [_c['name'] for _c in _by['hit'].checks] == ['answer mentions Default', 'expected is the target']
        assert _by['hit'].success is True and _by['miss'].success is True      # the mock always says Default

    def test_the_inspect_score_is_correct_or_incorrect(self, tmp_path):
        def strict(task, result):
            return [Check(name='exact', ok=result.output == task.expected)]
        _logs = inspect_eval(Task(name='qa', dataset=samples(), scorer=inspect_scorer.scorer(strict)),
                             model=MOCK, log_dir=str(tmp_path), display='none')
        _values = {_s.id: _s.scores['ipandora'].value for _s in _logs[0].samples}
        assert _values == {'hit': INCORRECT, 'miss': INCORRECT}
        _ok = inspect_eval(Task(name='qa2', dataset=samples(), scorer=inspect_scorer.scorer(contains_default)),
                           model=MOCK, log_dir=str(tmp_path), display='none')
        assert {_s.scores['ipandora'].value for _s in _ok[0].samples} == {CORRECT}

    def test_a_grader_that_judges_nothing_is_no_answer_not_a_pass(self, tmp_path):
        _log = run(tmp_path, Task(name='qa', dataset=samples()[:1],
                                  scorer=inspect_scorer.scorer(lambda task, result: [])))[0]
        _trial = inspect_log.read(_log).trials[0]
        assert _trial.status == NO_VERDICT and _trial.success is None

    def test_a_grader_that_raises_is_the_graders_problem(self, tmp_path):
        def broken(task, result):
            raise KeyError('expected')
        _log = run(tmp_path, Task(name='qa', dataset=samples()[:1], scorer=inspect_scorer.scorer(broken)))[0]
        _trial = inspect_log.read(_log).trials[0]
        assert (_trial.status, _trial.category) == (NO_VERDICT, 'grader')
        assert 'KeyError' in _trial.error

    def test_an_async_grader_is_awaited(self, tmp_path):
        async def grade(task, result):
            await asyncio.sleep(0)
            return [Check(name='async', ok=True)]
        _trial = inspect_log.read(run(tmp_path, Task(name='qa', dataset=samples()[:1],
                                                     scorer=inspect_scorer.scorer(grade)))[0]).trials[0]
        assert _trial.status == GRADED and _trial.success is True

    def test_a_judge_check_from_the_grader_decides_nothing(self, tmp_path):
        def judged(task, result):
            return [Check(name='tone', ok=True, src=LLM_JUDGE)]
        _log = run(tmp_path, Task(name='qa', dataset=samples()[:1], scorer=inspect_scorer.scorer(judged)))[0]
        _trial = inspect_log.read(_log).trials[0]
        assert _trial.success is None and _trial.judge_checks


class TestCommand:

    def test_eval_inspect_writes_the_report_and_gates(self, tmp_path):
        run(tmp_path, Task(name='qa', dataset=samples(), scorer=includes()), epochs=2)
        _env = dict(os.environ, IPANDORA_REPORTS_DIR=str(tmp_path / 'reports'))
        _base = str(tmp_path / 'baseline.json')
        _first = subprocess.run([sys.executable, '-m', 'ipandora.run', 'eval', 'inspect', str(tmp_path / 'logs'),
                                 '-o', str(tmp_path / 'out'), '--baseline', _base, '--update-baseline'],
                                capture_output=True, text=True, timeout=300, env=_env)
        assert _first.returncode == 0, _first.stderr
        assert os.path.isfile(tmp_path / 'out' / 'report.html') and os.path.isfile(_base)
        assert '成功率 50.0%' in _first.stdout
        _again = subprocess.run([sys.executable, '-m', 'ipandora.run', 'eval', 'inspect', str(tmp_path / 'logs'),
                                 '-o', str(tmp_path / 'out2'), '--baseline', _base],
                                capture_output=True, text=True, timeout=300, env=_env)
        assert _again.returncode == 0, _again.stdout + _again.stderr
        assert '和基线无法区分' in _again.stdout

    def test_a_bad_threshold_is_a_message(self, tmp_path):
        _done = subprocess.run([sys.executable, '-m', 'ipandora.run', 'eval', 'inspect', str(tmp_path),
                                '--threshold', 'match=high'], capture_output=True, text=True, timeout=120)
        assert _done.returncode == 2 and 'SCORER=NUMBER' in _done.stderr


def test_without_inspect_the_error_says_how_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, 'inspect_ai', None)
    for _name in ('inspect_ai.log', 'inspect_ai.scorer'):
        monkeypatch.setitem(sys.modules, _name, None)
    with pytest.raises(ImportError, match='intellipandora\\[inspect\\]'):
        inspect_log.read('anything.eval')
    with pytest.raises(ImportError, match='intellipandora\\[inspect\\]'):
        inspect_scorer.scorer(lambda task, result: [])
