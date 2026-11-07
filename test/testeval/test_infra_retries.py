# -*- coding: utf-8 -*-
"""
@File  : test_infra_retries.py
@Time  : 2026-11-07

Retrying the infrastructure, never the agent (E10): a trial whose agent
raised -- a container that did not start, an API 5xx, a rate limit -- is
tried again; an answer, right or wrong, never is. Every attempt counts in
the infrastructure error rate, which a retry that succeeded would otherwise
hide: a benchmark that retried quietly would report a clean environment.
"""
import json
import threading

import pytest

from ipandora.core.assertion.check import Check
from ipandora.core.eval import Dataset, EvalRun, evaluate, records, report
from ipandora.core.eval.dataset import Task
from ipandora.core.eval.run import run_with_retries
from ipandora.core.eval.trial import GRADED, INFRA, NO_VERDICT


def grade(task, result):
    return [Check(name='答对', ok=result.output == 'right', expr=str(result.output), src='output', claim='right')]


class Flaky:
    """An agent whose infrastructure fails the first `failures` times for each task."""

    def __init__(self, failures, answer='right', error='HTTPError: 503 Service Unavailable'):
        self.failures, self.answer, self.error = failures, answer, error
        self.calls, self._lock = {}, threading.Lock()

    def __call__(self, task):
        with self._lock:
            self.calls[task.id] = self.calls.get(task.id, 0) + 1
            _n = self.calls[task.id]
        if _n <= self.failures:
            raise RuntimeError('{} (attempt {})'.format(self.error, _n))
        return self.answer


def data(*ids):
    return Dataset('d', tasks=[Task(id=_i, input='q') for _i in ids or ('a',)])


class TestRetrying:

    def test_the_infrastructure_is_retried_and_every_attempt_kept(self):
        _agent = Flaky(2)
        _run = evaluate(data(), _agent, grade, infra_retries=2, check_references=False)
        _t = _run.trials[0]
        assert (_t.status, _t.success, _t.attempts, _t.infra_attempts) == (GRADED, True, 3, 2)
        assert _t.infra_errors == ['RuntimeError: HTTPError: 503 Service Unavailable (attempt 1)',
                                   'RuntimeError: HTTPError: 503 Service Unavailable (attempt 2)']
        _s = _run.summary()
        assert (_s['attempts'], _s['infra_attempts'], _s['infra_rate'], _s['retried'], _s['infra']) == (
            3, 2, 2 / 3, 1, 0)
        assert _run.manifest.infra_retries == 2

    def test_retries_run_out(self):
        _run = evaluate(data(), Flaky(5), grade, infra_retries=1, check_references=False)
        _t = _run.trials[0]
        assert (_t.status, _t.attempts, _t.infra_attempts, len(_t.infra_errors)) == (INFRA, 2, 2, 1)
        assert '(attempt 2)' in _t.error and '(attempt 1)' in _t.infra_errors[0]
        _s = _run.summary()
        assert (_s['infra'], _s['infra_attempts'], _s['infra_rate'], _s['success_rate']) == (1, 2, 1.0, None)

    def test_an_answer_is_never_retried(self):
        _agent = Flaky(0, answer='wrong')
        _run = evaluate(data(), _agent, grade, infra_retries=3, check_references=False)
        assert _agent.calls == {'a': 1} and _run.trials[0].success is False and _run.trials[0].infra_errors == []

    def test_a_grader_that_raises_is_not_retried(self):
        _agent = Flaky(0)

        def _broken(task, result):
            raise KeyError('x')
        _t = evaluate(data(), _agent, _broken, infra_retries=3, check_references=False).trials[0]
        assert _agent.calls == {'a': 1} and (_t.status, _t.category, _t.attempts) == (NO_VERDICT, 'grader', 1)

    def test_no_retry_unless_asked(self):
        _agent = Flaky(1)
        _run = evaluate(data(), _agent, grade, check_references=False)
        assert _agent.calls == {'a': 1} and _run.trials[0].status == INFRA
        _s = _run.summary()
        assert (_s['attempts'], _s['infra_attempts'], _s['infra_rate'], _s['retried']) == (1, 1, 1.0, 0)
        assert _run.manifest.infra_retries == 0

    def test_each_trial_retries_on_its_own_in_parallel(self):
        _agent = Flaky(1)
        _run = evaluate(data('a', 'b', 'c'), _agent, grade, trials=1, workers=3, infra_retries=1,
                        check_references=False)
        assert all(_t.success and _t.attempts == 2 for _t in _run.trials) and _agent.calls == {'a': 2, 'b': 2, 'c': 2}
        assert _run.summary()['infra_rate'] == 0.5

    def test_the_wait_doubles(self):
        _waits = []
        _t = run_with_retries(Task(id='a', input='q'), 0, Flaky(3), grade, retries=3, wait=1.5, sleep=_waits.append)
        assert _waits == [1.5, 3.0, 6.0] and _t.success
        _none = []
        run_with_retries(Task(id='a', input='q'), 0, Flaky(2), grade, retries=2, sleep=_none.append)
        assert _none == []

    @pytest.mark.parametrize('kw, error', [({'infra_retries': -1}, 'infra_retries'), ({'infra_retries': 1.5}, 'infra_retries'),
                                           ({'infra_retries': True}, 'infra_retries'), ({'retry_wait': -1}, 'retry_wait'),
                                           ({'retry_wait': '1'}, 'retry_wait')])
    def test_what_it_refuses(self, kw, error):
        with pytest.raises(ValueError, match=error):
            evaluate(data(), Flaky(0), grade, check_references=False, **kw)


class TestWhereItShows:

    def test_kept_with_the_run(self, tmp_path):
        _run = evaluate(data(), Flaky(1), grade, infra_retries=1, check_references=False)
        _back = EvalRun.load(_run.save(str(tmp_path / 'run.json')))
        assert _back.trials[0].infra_errors == _run.trials[0].infra_errors and _back.manifest.infra_retries == 1
        assert _back.summary()['infra_rate'] == 0.5

    def test_old_runs_have_no_retries(self):
        _old = EvalRun.from_dict({'kind': 'ipandora.eval', 'trials': [{'task_id': 'a', 'index': 0, 'status': 'graded'}]})
        assert _old.trials[0].infra_errors == [] and _old.summary()['infra_rate'] == 0.0

    def test_the_report_redacts_and_states_the_rate(self):
        _agent = Flaky(1, error='connect failed: password=hunter2-very-secret')  # pragma: allowlist secret
        _run = evaluate(data(), _agent, grade, infra_retries=1, check_references=False)
        _dict = report.to_dict(_run)
        assert 'hunter2' not in json.dumps(_dict) and len(_dict['trials'][0]['infra_errors']) == 1
        _html = report.to_html(_run)
        assert '基础设施错误率 50.0%（2 次尝试里 1 次，1 次试验重试过）' in _html and 'hunter2' not in _html
        assert '基础设施错误率' not in report.to_html(evaluate(data(), Flaky(0), grade, check_references=False))

    def test_each_record_line_says_how_often_it_was_retried(self):
        _run = evaluate(data(), Flaky(2), grade, infra_retries=2, check_references=False)
        _row = records.records(_run)[0]
        assert _row['infra_retries'] == 2 and len(_row['infra_errors']) == 2 and _row['success'] is True


class TestTheCommand:

    def test_infra_retries_reach_the_run(self, tmp_path):
        import subprocess
        import sys
        import yaml
        (tmp_path / 'd.yaml').write_text(yaml.safe_dump({'tasks': [{'id': 'a', 'input': 'q', 'reference': 'right'}]}))
        (tmp_path / 'spec.py').write_text(
            "from ipandora.core.assertion.check import Check\n"
            "DATASET = 'd.yaml'\n_N = []\n\n"
            "def agent(task):\n    _N.append(1)\n    if len(_N) < 2:\n        raise RuntimeError('rate limited')\n"
            "    return 'right'\n\n"
            "def grade(task, result):\n"
            "    return [Check(name='答对', ok=result.output == 'right', expr='', src='output', claim='right')]\n")
        _done = subprocess.run([sys.executable, '-m', 'ipandora.run', 'eval', 'run', str(tmp_path / 'spec.py'),
                                '--infra-retries', '1', '--retry-wait', '0', '--no-baseline', '-o', str(tmp_path / 'out')],
                               capture_output=True, text=True, timeout=180)
        assert _done.returncode == 0, _done.stderr
        assert '基础设施错误率 50.0%（2 次尝试里 1 次；1 次试验重试过）' in _done.stdout
        _saved = json.loads((tmp_path / 'out' / 'report.json').read_text())
        assert _saved['manifest']['infra_retries'] == 1 and _saved['trials'][0]['infra_errors'] == [
            'RuntimeError: rate limited']


class TestInspect:

    def test_retried_errors_are_read_from_the_log(self, tmp_path):
        pytest.importorskip('inspect_ai', reason='the Inspect path needs the `inspect` extra (Python 3.11+)')
        from inspect_ai import Task as InspectTask
        from inspect_ai import eval as inspect_eval
        from inspect_ai.dataset import Sample
        from inspect_ai.scorer import includes
        from inspect_ai.solver import generate, solver
        from ipandora.core.eval import inspect_log
        _seen = {}

        @solver
        def flaky():
            async def solve(state, generate_):
                _seen[state.sample_id] = _seen.get(state.sample_id, 0) + 1
                if _seen[state.sample_id] == 1:
                    raise RuntimeError('the sandbox did not start')
                return await generate_(state)
            return solve
        _logs = inspect_eval(InspectTask(name='qa', dataset=[Sample(id='s', input='hi', target='Default')],
                                         solver=[flaky(), generate()], scorer=includes()),
                             model='mockllm/model', log_dir=str(tmp_path / 'logs'), display='none', retry_on_error=2)
        _run = inspect_log.read(_logs[0].location)
        _t = _run.trials[0]
        assert _t.status == GRADED and _t.success is True and _t.attempts == 2
        assert len(_t.infra_errors) == 1 and 'the sandbox did not start' in _t.infra_errors[0]
        assert _run.summary()['infra_rate'] == 0.5
