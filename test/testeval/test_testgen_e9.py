# -*- coding: utf-8 -*-
"""
@File  : test_testgen_e9.py
@Time  : 2026-11-07

E9: the F→P grader checked on answers whose verdict is known (oracle, noop,
bad answers), one JSON line per run with tokens and how it ended, and the
reason a failed run failed -- the rules of fresh-repro's PLAN.md 2.4 and 6.4.
"""
import json

import pytest

from ipandora.core.eval import EvalRun, records, testgen
from ipandora.core.eval.trial import Manifest, Trial

from .test_testgen import CMD, FIX, _task_dir, repo, write  # noqa: F401 -- the fixture is used by name

REFERENCE = '''\
--- /dev/null
+++ b/tests/test_add.py
@@ -0,0 +1,5 @@
+from calc import add
+
+
+def test_add():
+    assert add(1, 2) == 3
'''


def _checks(**ok):
    _names = {'f2p': 'fail to pass', 'scope': 'only test files changed', 'weak': 'not a weak reproduction',
              'flaky': 'not flaky', 'asserts': 'tests assert', 'wrote': 'agent wrote tests', 'graded': 'grading completed',
              'mutants': 'kills mutants of the fixed functions'}
    _base = dict(f2p=False, scope=True, weak=True, flaky=True, asserts=True, wrote=True, graded=True)
    _base.update(ok)
    return [{'claim': _names[_k], 'ok': _v} for _k, _v in _base.items()]


class TestSelfcheck:

    def test_every_known_answer_is_judged_right_and_the_workspace_is_left_at_base(self, repo, tmp_path):
        _d = _task_dir(tmp_path)
        (_d / 'reference_test.patch').write_text(REFERENCE)
        _rows = testgen.selfcheck(str(repo), str(_d), runs=2, oracle_runs=3)
        assert [(_r['case'], _r['got'], _r['ok']) for _r in _rows] == [
            ('oracle#1', 'F→P', True), ('oracle#2', 'F→P', True), ('oracle#3', 'F→P', True),
            ('noop', 'not F→P', True), ('source_only', 'not F→P', True),
            ('zero_assertion', 'not F→P', True), ('import_only', 'weak', True)]
        import subprocess
        assert subprocess.run(['git', '-C', str(repo), 'status', '--porcelain'], capture_output=True,
                              text=True).stdout == ''

    def test_a_reference_that_does_not_reproduce_is_caught(self, repo, tmp_path):
        _d = _task_dir(tmp_path)
        (_d / 'reference_test.patch').write_text(REFERENCE.replace('add(1, 2) == 3', 'add(2, 0) == 2'))
        _rows = testgen.selfcheck(str(repo), str(_d), runs=1, oracle_runs=1)
        assert [(_r['case'], _r['ok']) for _r in _rows][0] == ('oracle#1', False)

    def test_the_command(self, repo, tmp_path, capsys):
        from test.testeval.test_eval_cr1 import _cli
        _d = _task_dir(tmp_path)
        (_d / 'reference_test.patch').write_text(REFERENCE)
        assert _cli('f2p-selfcheck', workdir=str(repo), task=str(_d), base='HEAD', runs=1, oracle_runs=1,
                    timeout=120) == 0
        assert '5 项全部判对' in capsys.readouterr().out


class TestFailureReason:

    @pytest.mark.parametrize('kw, ctx, reason', [
        (dict(f2p=True), {}, ''),
        (dict(), {'status': 'infra'}, 'environment'),
        (dict(), {'ended': 'error'}, 'environment'),
        (dict(graded=False), {}, 'environment'),
        (dict(), {'ended': 'limit:time'}, 'timeout_or_budget'),
        (dict(), {'over_budget': True}, 'timeout_or_budget'),
        (dict(wrote=False, asserts=False), {}, 'no_tests'),
        (dict(wrote=False, asserts=False, scope=False), {}, 'modified_source'),
        (dict(weak=False), {}, 'weak_reproduction'),
        (dict(flaky=False), {}, 'flaky'),
        (dict(scope=False), {}, 'modified_source'),
        (dict(), {}, 'not_reproduced'),
    ])
    def test_rules(self, kw, ctx, reason):
        assert testgen.failure_reason(_checks(**kw), **ctx) == reason

    def test_an_environment_failure_beats_a_success_and_flags_are_apart(self):
        assert testgen.failure_reason(_checks(f2p=True), status='infra') == 'environment'
        assert testgen.flags(_checks(f2p=True, asserts=False, scope=False, mutants=False), over_budget=True) == [
            'out_of_scope', 'zero_assertion', 'weak_assertions', 'timeout_or_budget']
        assert set(testgen.REASONS) >= {'environment', 'not_reproduced', 'modified_source', 'zero_assertion',
                                        'weak_assertions', 'timeout_or_budget'}


class TestRecords:

    def _run(self):
        _ok = Trial(task_id='calc-12', index=0, checks=_checks(f2p=True), seconds=30.0, ended='completed',
                    cost={'tokens_in': 1000, 'tokens_out': 50, 'tokens_cache_read': 800, 'usd': 0.7, 'turns': 4,
                          'tool_calls': 9})
        _slow = Trial(task_id='calc-12', index=1, checks=_checks(), seconds=1500.0, ended='limit:time',
                      cost={'usd': 0.1})
        _plain = Trial(task_id='other', index=0, checks=[{'claim': 'x', 'ok': True}], seconds=1.0)
        return EvalRun(run_id='r1', manifest=Manifest(harness='dsh-standard', model='m'), trials=[_ok, _slow, _plain])

    def test_one_line_per_run(self):
        _rows = records.records(self._run(), {'calc-12': {'max_usd': 0.5, 'max_minutes': 20}})
        assert [(_r['task'], _r['attempt'], _r['config'], _r['success']) for _r in _rows] == [
            ('calc-12', 1, 'dsh-standard', True), ('calc-12', 2, 'dsh-standard', False), ('other', 1, 'dsh-standard', True)]
        _a, _b, _c = _rows
        assert (_a['tokens_cache_read'], _a['usd'], _a['turns'], _a['tool_calls']) == (800, 0.7, 4, 9)
        assert _a['over_budget'] and _a['reason'] == '' and _a['flags'] == ['timeout_or_budget']   # flagged, still a success
        assert _b['over_budget'] and _b['reason'] == 'timeout_or_budget' and _b['ended'] == 'limit:time'
        assert 'reason' not in _c and _c['over_budget'] is False
        assert json.loads(json.dumps(_rows))

    def test_the_command_reads_budgets_from_the_tasks(self, tmp_path, capsys):
        from test.testeval.test_eval_cr1 import _cli
        _d = _task_dir(tmp_path)
        _p = tmp_path / 'report.json'
        _p.write_text(json.dumps(self._run().to_dict()), encoding='utf-8')
        _out = tmp_path / 'r.jsonl'
        assert _cli('records', runs=[str(_p)], out=str(_out), tasks=str(_d.parent)) == 0
        _lines = [json.loads(_l) for _l in open(_out, encoding='utf-8')]
        assert len(_lines) == 3 and _lines[0]['over_budget'] is True


class TestPlumbing:

    def test_from_json_reads_the_command_output_back(self, repo, capsys):
        from test.testeval.test_eval_cr1 import _cli
        write(repo, 'tests/test_add.py', 'from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n')
        _cli('f2p', workdir=str(repo), fix=str(repo.parent / 'fix.patch'), task=None, base='HEAD', test_cmd=CMD,
             runs=1, max_mutants=0, timeout=120, json=True)
        _checks = testgen.from_json('some log line\n' + capsys.readouterr().out)
        assert _checks[0].claim == 'fail to pass' and _checks[0].ok
        assert testgen.failure_reason([{'claim': _c.claim, 'ok': _c.ok} for _c in _checks]) == ''
        with pytest.raises(ValueError, match='not the output'):
            testgen.from_json('garbage')

    def test_graded_requires_only_f2p(self, repo):
        write(repo, 'tests/test_add.py', 'from calc import add\n\ndef test_add():\n    assert add(2, 0) == 2\n')
        _g = testgen.grade(str(repo), str(repo.parent / 'fix.patch'), test_cmd=CMD, runs=1, max_mutants=0).graded()
        assert [(_x.check.claim, _x.required) for _x in _g][:2] == [('fail to pass', True), ('only test files changed', False)]
        assert sum(_x.required for _x in _g) == 1

    def test_inspect_cache_tokens_and_how_it_ended(self):
        from types import SimpleNamespace
        from ipandora.core.eval import inspect_log
        _usage = SimpleNamespace(input_tokens=100, output_tokens=10, input_tokens_cache_read=80,
                                 input_tokens_cache_write=5, total_cost=None)
        _sample = SimpleNamespace(model_usage={'m': _usage}, turn_count=3)
        assert inspect_log._cost(_sample, []) == {'tokens_in': 100, 'tokens_out': 10, 'tool_calls': 0,
                                                  'tokens_cache_read': 80, 'tokens_cache_write': 5, 'turns': 3}

    def test_a_pytest_path_trial_records_how_it_ended(self):
        from ipandora.core.eval import dialogue, evaluate
        from ipandora.core.eval.dataset import Dataset, Task
        _d = Dataset('x', tasks=[Task(id='a', input='hi', expected={})])
        _talk = lambda t: dialogue.converse(lambda m: 'ok', dialogue.ScriptedUser('hi'), max_turns=1)  # noqa: E731
        assert evaluate(_d, agent=_talk, grade=lambda t, r: []).trials[0].ended == 'user'
        assert evaluate(_d, agent=lambda t: 'x', grade=lambda t, r: []).trials[0].ended == 'completed'
        assert evaluate(_d, agent=lambda t: 1 / 0, grade=lambda t, r: []).trials[0].ended == 'error'
