# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_verdict.py
@Time  : 2026-11-05

The report's first screen: the verdict, the numbers behind the pass rate,
what turned red against the baseline and against an earlier run, and the
coverage declaration that used to read as "0 / 0".
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

from ipandora.core.report import ReportCase, ReportData, Status, compare
from ipandora.core.report.render import display_path, to_html
from ipandora.core.runner import inventory
from ipandora.core.runner.result import CaseResult, RunResult


def case(name, status=Status.PASS, **kw):
    kw.setdefault('checks', [{'name': 'ok', 'ok': True, 'kind': 'assert', 'src': 'api'}]
                  if status == Status.PASS else [])
    return ReportCase(name=name, nodeid='t.py::' + name, status=status, **kw)


def failing(name, category='defect'):
    return case(name, Status.FAIL, category=category, reason='依据', next_step='下一步',
                checks=[{'name': 'fee <= 100', 'ok': False, 'kind': 'assert',
                         'expr': 'fee = 120', 'src': 'api'}])


class TestVerdict:

    def test_a_failure_blocks_and_says_who_is_to_blame(self):
        _v = ReportData(cases=[case('a'), failing('b'), failing('c', 'environment')]).verdict
        assert _v['status'] == 'fail' and not _v['releasable']
        assert _v['label'] == '不能放行'
        assert _v['sentence'] == '2 条用例失败，其中 1 条指向被测系统。'
        assert _v['reasons'][0] == {'kind': 'failed', 'count': 2, 'blames_system_under_test': 1}

    def test_all_failures_on_the_system_say_so(self):
        _v = ReportData(cases=[failing('b')]).verdict
        assert _v['sentence'].startswith('1 条用例失败，都指向被测系统')

    def test_failures_none_on_the_system_say_so(self):
        _v = ReportData(cases=[failing('b', 'data')]).verdict
        assert '没有一条指向被测系统' in _v['sentence']

    def test_a_clean_run_can_ship(self):
        _v = ReportData(cases=[case('a'), case('b')], baseline='conf/judgements.json').verdict
        assert _v['status'] == 'pass' and _v['releasable']
        assert _v['sentence'] == '2 条用例全部通过，判定没有比基线弱。'

    def test_a_pass_that_judged_nothing_needs_review_but_still_exits_zero(self):
        _v = ReportData(cases=[case('a'), case('u', Status.UNVERIFIED)]).verdict
        assert _v['status'] == 'review' and _v['releasable']
        assert '1 条用例通过了但什么都没判定' in _v['sentence']

    def test_weaker_judgements_fail_only_when_gated(self):
        _changes = [{'kind': 'removed', 'nodeid': 't.py::a', 'weakening': True}]
        _report = ReportData(cases=[case('a')], judgement_changes=_changes)
        assert _report.verdict['status'] == 'review'
        _report.gate_weakened = True
        assert _report.verdict['status'] == 'fail' and not _report.verdict['releasable']
        assert '1 处判定比基线弱' in _report.verdict['sentence']

    def test_a_collection_error_is_not_a_pass(self):
        _v = ReportData(collect_error='boom').verdict
        assert _v['status'] == 'error' and not _v['releasable']

    def test_nothing_conclusive_is_not_a_pass(self):
        _v = ReportData(cases=[case('s', Status.SKIPPED)]).verdict
        assert _v['status'] == 'review'
        assert '没有一条用例给出结论' in _v['sentence']

    def test_releasable_agrees_with_ok_without_a_gate(self):
        for _cases in ([case('a')], [failing('b')], [case('u', Status.UNVERIFIED)],
                       [case('e', Status.ERROR)]):
            _report = ReportData(cases=_cases)
            assert _report.verdict['releasable'] == _report.ok


class TestPassRateBasis:

    def test_the_denominator_leaves_out_what_judged_nothing(self):
        _report = ReportData(cases=[case('a'), case('b'), failing('c'),
                                    case('u', Status.UNVERIFIED), case('s', Status.SKIPPED)])
        assert _report.pass_rate_basis == {'passed': 2, 'denominator': 3,
                                           'not_counted': {'unverified': 1, 'skipped': 1}}
        assert _report.pass_rate == '66.7%'


class TestCoverageDeclaration:

    def grid(self, coverage, cases=()):
        return ReportData(coverage=coverage, cases=list(cases)).coverage_matrix[0]

    def test_the_short_form_fills_its_cells(self):
        _grid = self.grid([{'role': ['admin', 'guest'], 'channel': ['web', 'app']}],
                          [case('a', dims={'role': 'admin', 'channel': 'web'}),
                           case('b', dims={'role': 'guest', 'channel': 'web'})])
        assert (_grid['filled'], _grid['total'], _grid['problem']) == (2, 4, '')
        assert _grid['title'] == 'role × channel'
        assert _grid['x_labels'] == ['web', 'app']
        assert [_r['label'] for _r in _grid['rows']] == ['admin', 'guest']

    def test_the_long_form_still_works(self):
        _grid = self.grid([{'id': 'g', 'title': 'kind x mode',
                            'y': {'key': 'kind', 'label': 'Kind',
                                  'values': [{'key': 'a', 'label': 'A'}]},
                            'x': {'key': 'mode', 'label': 'Mode',
                                  'values': [{'key': 'x', 'label': 'X'}, {'key': 'y', 'label': 'Y'}]}}],
                          [case('a', dims={'kind': 'a', 'mode': 'y'})])
        assert (_grid['filled'], _grid['total'], _grid['x_labels']) == (1, 2, ['X', 'Y'])

    def test_a_case_without_the_dim_lands_nowhere(self):
        _grid = self.grid([{'role': ['None'], 'channel': ['None']}], [case('a')])
        assert _grid['filled'] == 0

    @pytest.mark.parametrize('coverage', [
        [{'role': ['admin']}],
        [{'role': ['a'], 'channel': ['b'], 'region': ['c']}],
        [{'x': {'key': 'k'}, 'y': {'key': 'j', 'values': []}}],
        [{'role': 'admin', 'channel': ['web']}],
        ['role'],
    ])
    def test_a_declaration_it_cannot_read_says_so(self, coverage):
        _grid = self.grid(coverage)
        assert _grid['problem'] and _grid['total'] == 0

    def test_the_problem_reaches_the_page(self):
        _html = to_html(ReportData(coverage=[{'role': ['admin']}], cases=[case('a')]))
        assert 'COVERAGE 的简写要正好两个维度' in _html


class TestAgainstBaseline:

    def result(self, **outcomes):
        return RunResult(run_id='r', cases=[CaseResult(nodeid=_n, outcome=_o)
                                            for _n, _o in outcomes.items()])

    def test_failures_are_split_by_what_the_baseline_saw(self):
        _base = {'cases': {'was_green': {'state': 'passed', 'claims': ['x']},
                           'was_skipped': {'state': 'skipped', 'claims': []},
                           'still_green': {'state': 'passed', 'claims': ['x']}}}
        _out = inventory.against(_base, self.result(
            was_green='failed', was_skipped='error', never_seen='failed',
            still_green='passed', brand_new='passed'))
        assert _out == {'newly_failing': ['was_green'],
                        'no_passing_record': ['was_skipped', 'never_seen'],
                        'new_cases': ['brand_new']}

    def test_no_baseline_no_answer(self):
        assert inventory.against(None, self.result(a='failed')) == {}

    def test_it_travels_with_the_stored_run(self):
        _run = self.result(a='failed')
        _run.against_baseline = {'newly_failing': ['a']}
        assert RunResult.from_dict(_run.to_dict()).against_baseline == {'newly_failing': ['a']}
        assert _run.summary()['newly_failing'] == ['a']


class TestAgainstRun:

    def previous(self, **statuses):
        return {'run_id': 'run-old', 'selector': 's', 'env': '', 'generated': 'then',
                'cases': [{'nodeid': 't.py::' + _n, 'status': _s} for _n, _s in statuses.items()]}

    def test_new_still_and_recovered(self):
        _now = ReportData(cases=[failing('new'), failing('still'), case('fixed'),
                                 case('green')])
        _out = compare.against(_now, self.previous(still='FAIL', fixed='ERROR', green='PASS',
                                                   gone='FAIL'), compare.ARGUMENT)
        assert _out['newly_failing'] == ['t.py::new']
        assert _out['still_failing'] == ['t.py::still']
        # `gone` did not run this time: that is not a recovery
        assert _out['recovered'] == ['t.py::fixed']
        assert (_out['source'], _out['run_id']) == ('argument', 'run-old')

    def test_load_refuses_what_is_not_a_report(self, tmp_path):
        _bad = tmp_path / 'judgements.json'
        _bad.write_text(json.dumps({'cases': {}}), encoding='utf-8')
        with pytest.raises(ValueError):
            compare.load(str(_bad))
        with pytest.raises(ValueError):
            compare.load(str(tmp_path / 'missing.json'))

    def test_load_accepts_a_run_directory(self, tmp_path):
        (tmp_path / 'report.json').write_text(json.dumps(self.previous(a='PASS')), encoding='utf-8')
        assert compare.load(str(tmp_path))['run_id'] == 'run-old'

    def archive(self, root, entries):
        root.mkdir(parents=True, exist_ok=True)
        _index = []
        for _run_id, _selector, _env, _statuses in entries:
            (root / _run_id).mkdir()
            _data = dict(self.previous(**_statuses), run_id=_run_id, selector=_selector, env=_env)
            (root / _run_id / 'report.json').write_text(json.dumps(_data), encoding='utf-8')
            _index.append({'run_id': _run_id, 'selector': _selector, 'env': _env})
        (root / 'index.json').write_text(json.dumps(_index), encoding='utf-8')

    def test_the_cache_is_the_last_run_of_the_same_selector_and_env(self, tmp_path):
        _root = tmp_path / 'reports'
        self.archive(_root, [('run-3', 's', 'other', {'a': 'FAIL'}),
                             ('run-2', 'elsewhere', '', {'a': 'FAIL'}),
                             ('run-1', 's', '', {'a': 'PASS'}),
                             ('run-0', 's', '', {'a': 'FAIL'})])
        _now = ReportData(run_id='run-4', selector='s', cases=[failing('a')])
        compare.attach(_now, directory=str(_root))
        assert _now.against_run['source'] == compare.LOCAL_CACHE
        assert _now.against_run['run_id'] == 'run-1'
        assert _now.against_run['newly_failing'] == ['t.py::a']

    def test_the_cache_never_compares_a_run_with_itself(self, tmp_path):
        _root = tmp_path / 'reports'
        self.archive(_root, [('run-4', 's', '', {'a': 'FAIL'})])
        _now = ReportData(run_id='run-4', selector='s', cases=[failing('a')])
        assert compare.attach(_now, directory=str(_root)).against_run == {}

    def test_an_index_entry_cannot_point_outside_the_archive(self, tmp_path):
        _root = tmp_path / 'reports'
        _root.mkdir()
        (tmp_path / 'report.json').write_text(json.dumps(self.previous(a='PASS')), encoding='utf-8')
        (_root / 'index.json').write_text(json.dumps([{'run_id': '..', 'selector': 's', 'env': ''}]),
                                          encoding='utf-8')
        _now = ReportData(run_id='run-4', selector='s', cases=[failing('a')])
        assert compare.attach(_now, directory=str(_root)).against_run == {}

    def test_a_passed_report_wins_over_the_cache(self, tmp_path):
        _root = tmp_path / 'reports'
        self.archive(_root, [('run-1', 's', '', {'a': 'FAIL'})])
        _given = tmp_path / 'main.json'
        _given.write_text(json.dumps(dict(self.previous(a='PASS'), run_id='main-7')), encoding='utf-8')
        _now = ReportData(run_id='run-4', selector='s', cases=[failing('a')])
        compare.attach(_now, compare_with=str(_given), directory=str(_root))
        assert (_now.against_run['source'], _now.against_run['run_id']) == ('argument', 'main-7')

    def test_no_cache_no_comparison(self, tmp_path):
        _now = ReportData(run_id='run-4', cases=[failing('a')])
        assert compare.attach(_now, directory=str(tmp_path / 'none')).against_run == {}


class TestThePage:

    def report(self):
        _r = ReportData(run_id='run-9', baseline='conf/judgements.json',
                        cases=[failing('fee'), failing('net', 'environment'),
                               case('u', Status.UNVERIFIED), case('flaky', flaky='沙箱偶发超时')])
        _r.against_baseline = {'newly_failing': ['t.py::fee'], 'no_passing_record': ['t.py::net'],
                               'new_cases': []}
        _r.against_run = {'source': 'local_cache', 'run_id': 'run-8', 'generated': '', 'selector': '',
                          'env': '', 'newly_failing': ['t.py::net'], 'still_failing': ['t.py::fee'],
                          'recovered': []}
        return _r

    def test_the_first_screen(self):
        _html = to_html(self.report())
        assert 'data-verdict="fail"' in _html and '不能放行' in _html
        assert '2 条用例失败，其中 1 条指向被测系统' in _html
        assert '基线通过，这次失败' in _html and '新红' in _html
        assert '本机缓存' in _html and 'run-8' in _html
        assert '33.3% = 1 / 3' in _html

    def test_failures_are_grouped_system_first_and_in_chinese(self):
        _html = to_html(self.report())
        assert _html.index('产品缺陷 · 1') < _html.index('环境 · 1') < _html.index('通过但不可信 · 2')
        assert 'data-category="defect"' in _html

    def test_the_groups(self):
        _keys = [_g['key'] for _g in self.report().attention]
        assert _keys == ['defect', 'environment', 'untrusted']

    def test_without_baseline_or_history_the_comparison_is_absent(self):
        _html = to_html(ReportData(cases=[case('a')]))
        assert '这次新红的' not in _html and '可以放行' in _html

    def test_both_themes(self):
        _html = to_html(ReportData(cases=[case('a')]))
        assert '@media (prefers-color-scheme:dark)' in _html

    def test_paths_inside_the_project_are_shown_relative(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert display_path(str(tmp_path / 'conf' / 'judgements.json')) == os.path.join(
            'conf', 'judgements.json')
        assert display_path('/elsewhere/x.json') == '/elsewhere/x.json'
        assert display_path('') == ''

    def test_it_round_trips_through_json(self):
        from ipandora.core.report import build_from_dict, to_json
        _back = build_from_dict(json.loads(to_json(self.report())))
        assert _back.against_baseline == self.report().against_baseline
        assert _back.against_run['run_id'] == 'run-8'
        assert _back.verdict == self.report().verdict


SUITE = '''
    from ipandora.core.assertion import assert_all, failed, passed

    def test_ok():
        assert_all(passed('状态正确', 'status = 200', src='api'))

    def test_broken():
        assert_all({verdict}('金额一致', 'got 3, want 5', src='api'))
'''


def ipandora(*args, reports):
    _env = dict(os.environ, IPANDORA_REPORTS_DIR=str(reports))
    return subprocess.run([sys.executable, '-m', 'ipandora.run'] + list(args),
                          capture_output=True, text=True, env=_env, timeout=180)


class TestTheCommand:

    def test_the_second_run_compares_with_the_first_from_the_local_archive(self, tmp_path):
        _suite = tmp_path / 'test_cmp.py'
        _reports = tmp_path / 'reports'
        _suite.write_text(textwrap.dedent(SUITE.format(verdict='passed')), encoding='utf-8')
        assert ipandora('run', str(_suite), '--no-baseline', reports=_reports).returncode == 0

        _suite.write_text(textwrap.dedent(SUITE.format(verdict='failed')), encoding='utf-8')
        _done = ipandora('run', str(_suite), '--no-baseline', reports=_reports)
        assert _done.returncode == 1, _done.stdout + _done.stderr
        assert '本机缓存' in _done.stdout and '新失败 1' in _done.stdout
        assert '不能放行：1 条用例失败' in _done.stdout

        _latest = json.loads((_reports / 'index.json').read_text(encoding='utf-8'))[0]
        _data = json.loads((_reports / _latest['run_id'] / 'report.json').read_text(encoding='utf-8'))
        assert _data['against_run']['source'] == 'local_cache'
        assert _data['against_run']['newly_failing'][0].endswith('::test_broken')
        assert _data['verdict']['releasable'] is False

    def test_compare_with_a_file_that_is_not_a_report_is_an_error(self, tmp_path):
        _suite = tmp_path / 'test_cmp.py'
        _suite.write_text(textwrap.dedent(SUITE.format(verdict='passed')), encoding='utf-8')
        _done = ipandora('run', str(_suite), '--compare-with', str(tmp_path / 'nope.json'),
                         reports=tmp_path / 'reports')
        assert _done.returncode == 2 and '--compare-with' in _done.stderr
