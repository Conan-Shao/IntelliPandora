# -*- coding: utf-8 -*-
"""
Report defects found in code review CR1 (docs/design/reviews/01-CR1.md, F5).
Each test fails on the code before the fix.
"""
import json
import os
import xml.etree.ElementTree as ET  # nosec B405 -- parsing our own output in a test

from ipandora.core.eval import AgentResult, dataset, evaluate
from ipandora.core.eval import report as eval_report
from ipandora.core.assertion.check import Check
from ipandora.core.report import build, history
from ipandora.core.report.junit import to_junit
from ipandora.core.report.render import to_html
from ipandora.core.runner.result import CaseResult, RunResult


def _report(*outcomes, **kwargs):
    _cases = [CaseResult(nodeid='t.py::test_{}'.format(_i), outcome=_o,
                         checks=[{'name': 'c', 'ok': _o == 'passed', 'claim': 'c'}])
              for _i, _o in enumerate(outcomes)]
    return build(RunResult(run_id=kwargs.pop('run_id', 'run-1'), cases=_cases, **kwargs))


class TestHistory:
    def test_an_entry_without_a_run_id_does_not_delete_the_archive(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history, 'KEEP_REPORTS', 1)
        (tmp_path / 'keep-me').mkdir()
        (tmp_path / history.INDEX_FILE).write_text(json.dumps([{'run_id': ''}]), encoding='utf-8')
        history.archive(_report('passed'), str(tmp_path))
        assert (tmp_path / 'keep-me').is_dir()

    def test_new_failures_compare_with_the_same_selector(self, tmp_path):
        history.archive(_report('failed', 'failed', selector='smoke', run_id='run-a'), str(tmp_path))
        history.archive(_report('passed', 'passed', selector='full', run_id='run-b'), str(tmp_path))
        history.archive(_report('failed', 'passed', selector='smoke', run_id='run-c'), str(tmp_path))
        _latest = history.load_index(str(tmp_path))[0]
        assert _latest['new_failures'] == []          # test_0 was failing in the last smoke run
        assert _latest['fixed'] == ['t.py::test_1']

    def test_the_index_rate_is_the_reports_rate(self, tmp_path):
        _r = build(RunResult(run_id='run-u', cases=[
            CaseResult(nodeid='t::a', outcome='passed', checks=[{'name': 'c', 'ok': True}]),
            CaseResult(nodeid='t::b', outcome='passed')]))          # unverified
        history.archive(_r, str(tmp_path))
        _html = (tmp_path / 'index.html').read_text(encoding='utf-8')
        assert _r.pass_rate == '100.0%'
        assert '50.0' not in _html


class TestVerdictAndCaption:
    def test_errors_are_named_beside_the_rate(self):
        _r = _report('passed', *['error'] * 9)
        assert _r.pass_rate == '100.0%'
        assert '出错 9 条' in _r.pass_rate_note
        assert '出错 9 条' in to_html(_r)

    def test_gate_weakened_is_serialised(self):
        _r = _report('passed')
        _r.gate_weakened = True
        assert _r.to_dict()['gate_weakened'] is True

    def test_the_run_command_exits_by_the_verdict(self, tmp_path, monkeypatch):
        # an empty run: the report says "exit 1", and so must the command
        from argparse import Namespace
        import pytest
        from ipandora.run.commands import run as run_command
        monkeypatch.setattr('ipandora.core.runner.run', lambda *a, **k: RunResult(run_id='run-e'))
        _options = Namespace(
            selector='x', env='', title=None, report_dir=str(tmp_path), no_archive=True,
            no_report=True, exclude_flaky=False, junit_xml=None, baseline=None,
            compare_with=None, no_baseline=True, update_baseline=False, fail_on_weakened=False,
            workers=None, timeout=None, no_store=True, no_ai=True, pytest_arg=[], logger=None)
        with pytest.raises(SystemExit) as _exit:
            run_command.Command.__new__(run_command.Command).handle(_options)
        assert _exit.value.code == 1


class TestJunit:
    def test_an_unknown_status_is_counted_as_the_error_it_is_written_as(self):
        _r = _report('passed')
        _r.cases[0].status = 'MYSTERY'
        _root = ET.fromstring(to_junit(_r).split('\n', 1)[1])
        assert _root.get('errors') == '1'
        assert len(_root.findall('.//error')) == 1

    def test_write_to_creates_the_directory(self, tmp_path):
        from ipandora.core.report.junit import write_to
        _path = write_to(_report('passed'), str(tmp_path / 'deep' / 'junit.xml'))
        assert os.path.isfile(_path)


def _eval_run(trials=2):
    _data = dataset.from_records([{'id': 't1', 'input': 'x', 'tags': {'k': 'a'}}], name='d')
    return evaluate(_data, lambda task: AgentResult(output='no'),
                    lambda task, result: [Check(name='c', ok=False)], trials=trials)


class TestEvalView:
    def test_tag_rows_say_not_comparable(self):
        _run = _eval_run()
        _cmp = {'not_comparable': ['数据集哈希不同'], 'by_tag': [
            {'tag': 'k', 'value': 'a', 'tasks': 1, 'base_rate': 1.0, 'now_rate': 0.0,
             'difference': -1.0, 'low': -1.0, 'high': -1.0, 'verdict': 'worse'}],
            'worse': 1, 'better': 0, 'same': 0, 'worst': [], 'noise': 0}
        _html = eval_report.to_html(_run, _cmp)
        assert '不可比' in _html and '<b>变差</b>' not in _html

    def test_each_task_anchor_appears_once(self):
        _html = eval_report.to_html(_eval_run(trials=3))
        assert _html.count('id="task-t1"') == 1
