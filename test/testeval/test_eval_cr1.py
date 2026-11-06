# -*- coding: utf-8 -*-
"""
Evaluation defects found in code review CR1 (docs/design/reviews/01-CR1.md, F6).
Each test fails on the code before the fix.
"""
import json
import textwrap
import threading
from argparse import Namespace

import pytest

from ipandora.core.assertion.check import Check
from ipandora.core.eval import AgentResult, Graded, dataset, evaluate, spec
from ipandora.core.eval.annotate import agreement
from ipandora.core.eval.trial import Trial


class TestTrialStorage:
    def test_an_output_that_cannot_be_copied_is_kept_as_its_repr(self):
        _trial = Trial(task_id='t', index=0, output={'client': threading.Lock()})
        _out = _trial.to_dict()
        assert 'lock' in _out['output']['client'].lower()
        json.dumps(_out)


class TestSpecLoading:
    def test_a_spec_with_a_dataclass_loads(self, tmp_path):
        (tmp_path / 'd.yaml').write_text('tasks:\n  - id: a\n    input: x\n', encoding='utf-8')
        _spec = tmp_path / 'spec.py'
        _spec.write_text(textwrap.dedent('''
            from __future__ import annotations
            from dataclasses import dataclass

            DATASET = 'd.yaml'

            @dataclass
            class Answer:
                text: str

            def agent(task):
                return Answer('x')

            def grade(task, result):
                return []
        '''), encoding='utf-8')
        assert spec.load(str(_spec)).dataset.tasks[0].id == 'a'

    def test_a_spec_that_is_not_python_is_refused_by_name(self, tmp_path):
        _spec = tmp_path / 'spec.yaml'
        _spec.write_text('DATASET: x\n', encoding='utf-8')
        with pytest.raises(ValueError, match='Python file'):
            spec.load(str(_spec))


class TestDatasetReading:
    def test_a_missing_reference_file_is_an_error(self, tmp_path):
        with pytest.raises(ValueError, match='not found'):
            dataset.from_records([{'id': 'a', 'reference': 'refs/missing.patch'}], 'd',
                                 path=str(tmp_path / 'd.yaml'))

    def test_inline_answers_that_contain_a_dot_stay_inline(self, tmp_path):
        _d = dataset.from_records([{'id': 'a', 'reference': '3.14'},
                                   {'id': 'b', 'reference': 'v1.2'}], 'd', path=str(tmp_path / 'd.yaml'))
        assert [_d.reference(_t) for _t in _d.tasks] == ['3.14', 'v1.2']

    def test_a_missing_dataset_file_and_bad_yaml_are_value_errors(self, tmp_path):
        with pytest.raises(ValueError, match='cannot read'):
            dataset.load(str(tmp_path / 'nope.yaml'))
        (tmp_path / 'bad.yaml').write_text('tasks: [a, b\n', encoding='utf-8')
        with pytest.raises(ValueError, match='not valid YAML'):
            dataset.load(str(tmp_path / 'bad.yaml'))

    def test_zero_is_an_id(self):
        assert dataset.from_records([{'id': 0}], 'd').tasks[0].id == '0'


class TestAgreement:
    def test_labels_written_as_text(self):
        _rows = [{'judge': True, 'human': 'false'}, {'judge': False, 'human': 'False'},
                 {'judge': True, 'human': 'true'}, {'judge': True, 'human': 'maybe'}]
        _r = agreement(_rows)
        assert _r['n'] == 3 and _r['undecided'] == 1
        assert _r['agreement'] == pytest.approx(2 / 3)


def _data(*records):
    return dataset.from_records(list(records), 'd')


class TestScoring:
    def test_mean_score_includes_trials_judged_only_by_optional_checks(self):
        _run = evaluate(_data({'id': 'a'}), lambda task: 'x', lambda task, result: [
            Graded(Check(name='nice', ok=True), required=False),
            Graded(Check(name='nicer', ok=False), required=False)])
        assert _run.trials[0].success is None
        assert _run.summary()['mean_score'] == pytest.approx(0.5)

    def test_a_budget_overrun_fails_the_trial(self):
        _run = evaluate(_data({'id': 'a', 'budget': {'usd': 0.5}}),
                        lambda task: AgentResult(output='ok', cost={'usd': 2.0}),
                        lambda task, result: [Check(name='answer', ok=True)])
        _trial = _run.trials[0]
        assert _trial.success is False
        assert any(_c['src'] == 'budget' and not _c['ok'] for _c in _trial.checks)

    def test_within_budget_still_succeeds(self):
        _run = evaluate(_data({'id': 'a', 'budget': {'usd': 5, 'seconds': 60}}),
                        lambda task: AgentResult(output='ok', cost={'usd': 0.1}),
                        lambda task, result: [Check(name='answer', ok=True)])
        assert _run.trials[0].success is True

    def test_polarity_is_reported_apart(self):
        _run = evaluate(_data({'id': 'a'}, {'id': 'b', 'polarity': 'dont'}),
                        lambda task: 'x', lambda task, result: [Check(name='c', ok=task.id == 'b')])
        assert _run.tag_values()['polarity'] == ['do', 'dont']
        assert _run.task_ids(polarity='dont') == ['b']


def _project(tmp_path, ok=True):
    (tmp_path / 'd.yaml').write_text('tasks:\n  - id: a\n    input: x\n', encoding='utf-8')
    (tmp_path / 'spec.py').write_text(textwrap.dedent('''
        from ipandora.core.assertion.check import Check

        DATASET = 'd.yaml'
        OK = {}

        def agent(task):
            return 'x'

        def grade(task, result):
            return [Check(name='c', ok=OK)]
    '''.format(ok)), encoding='utf-8')
    return str(tmp_path / 'spec.py')


def _cli(action, **kwargs):
    from ipandora.run.commands.eval import Command
    _defaults = dict(eval_action=action, trials=1, split=None, workers=1, out=None, title=None,
                     baseline=None, no_baseline=False, update_baseline=False, noise=0.0,
                     partial=False)
    _defaults.update(kwargs)
    with pytest.raises(SystemExit) as _exit:
        Command.__new__(Command).handle(Namespace(**_defaults))
    return _exit.value.code


class TestCommandLine:
    def test_a_run_worse_than_the_baseline_exits_one(self, tmp_path, monkeypatch):
        monkeypatch.setenv('IPANDORA_REPORTS_DIR', str(tmp_path / 'reports'))
        _base = str(tmp_path / 'base.json')
        (tmp_path / 'good').mkdir()
        _good = _project(tmp_path / 'good', ok=True)
        assert _cli('run', spec=_good, trials=3, baseline=_base, update_baseline=True) == 0
        _bad = _project(tmp_path / 'good', ok=False)
        assert _cli('run', spec=_bad, trials=3, baseline=_base) == 1

    def test_an_explicit_baseline_that_does_not_exist_is_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv('IPANDORA_REPORTS_DIR', str(tmp_path / 'reports'))
        assert _cli('run', spec=_project(tmp_path), baseline=str(tmp_path / 'typo.json')) == 2

    def test_a_missing_dataset_is_a_message_not_a_traceback(self, tmp_path, capsys):
        (tmp_path / 'spec.py').write_text("DATASET = 'gone.yaml'\ndef agent(t): pass\n"
                                          "def grade(t, r): pass\n", encoding='utf-8')
        assert _cli('selfcheck', spec=str(tmp_path / 'spec.py')) == 2
        assert 'cannot read dataset' in capsys.readouterr().err

    def test_selfcheck_without_references_does_not_fail(self, tmp_path, capsys):
        assert _cli('selfcheck', spec=_project(tmp_path)) == 0
        assert '没有参考解' in capsys.readouterr().out
