# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_merge.py
@Time  : 2026-11-05

One verdict from many shards: nothing counted twice, a disagreement between
shards reported rather than resolved quietly, and red never turned green.
"""
import json
import os
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET

import pytest

from ipandora.core.report import (ReportCase, ReportData, Status, build_from_dict, merge,
                                  to_html, to_json)
from ipandora.core.report.merge import SEVERITY, _rank


def case(name, status=Status.PASS, **kw):
    kw.setdefault('checks', [{'name': 'ok', 'ok': status != Status.FAIL, 'kind': 'assert',
                              'src': 'api', 'expr': 'x'}] if status in (Status.PASS, Status.FAIL) else [])
    return ReportCase(name=name, nodeid='t.py::' + name, status=status, **kw)


def shard(run_id, *cases, **kw):
    return json.loads(to_json(ReportData(run_id=run_id, cases=list(cases), **kw)))


class TestUnion:

    def test_disjoint_shards_add_up(self):
        _m = merge([shard('s1', case('a'), case('b'), selector='tests/api', duration=4.0),
                    shard('s2', case('c', Status.FAIL, category='defect'), selector='tests/web',
                          duration=9.0)],
                   sources=['shard-1/report.json', 'shard-2/report.json'])
        assert [_c.name for _c in _m.cases] == ['a', 'b', 'c']
        assert _m.totals['total'] == 3 and _m.totals['failed'] == 1
        assert _m.duration == 9.0          # side by side: the slowest shard
        assert _m.selector == 'tests/api + tests/web'
        assert [(_s['run_id'], _s['source'], _s['cases']) for _s in _m.shards] == [
            ('s1', 'shard-1/report.json', 2), ('s2', 'shard-2/report.json', 1)]
        assert _m.merge_conflicts == [] and _m.duplicates == 0
        assert _m.run_id.startswith('merge-')
        assert _m.verdict['status'] == 'fail'

    def test_a_case_in_two_shards_is_counted_once(self):
        _m = merge([shard('s1', case('a'), case('b')), shard('s2', case('a'))])
        assert _m.totals['total'] == 2 and _m.totals['passed'] == 2
        assert _m.duplicates == 1 and _m.merge_conflicts == []
        assert _m.verdict['status'] == 'pass'


class TestConflicts:

    def test_red_in_one_shard_is_red_after_the_merge(self):
        _m = merge([shard('s1', case('a')),
                    shard('s2', case('a', Status.FAIL, category='defect', reason='值不对'))])
        assert _m.cases[0].status == Status.FAIL and _m.cases[0].reason == '值不对'
        assert _m.merge_conflicts == [{'nodeid': 't.py::a', 'status': Status.FAIL, 'seen': [
            {'run_id': 's1', 'status': Status.PASS}, {'run_id': 's2', 'status': Status.FAIL}]}]
        assert '1 条用例在分片之间结论不一致' in _m.verdict['sentence']
        assert {'kind': 'conflict', 'count': 1} in _m.verdict['reasons']
        assert not _m.verdict['releasable']

    def test_a_pass_against_a_skip_needs_review(self):
        _m = merge([shard('s1', case('a', Status.SKIPPED)), shard('s2', case('a'))])
        assert _m.cases[0].status == Status.SKIPPED
        assert _m.verdict['status'] == 'review' and _m.verdict['releasable']

    def test_the_order_of_shards_does_not_change_the_answer(self):
        _a = merge([shard('s1', case('a', Status.UNVERIFIED)), shard('s2', case('a'))])
        _b = merge([shard('s2', case('a')), shard('s1', case('a', Status.UNVERIFIED))])
        assert _a.cases[0].status == _b.cases[0].status == Status.UNVERIFIED

    def test_severity(self):
        assert SEVERITY[0] == Status.FAIL and SEVERITY[-1] == Status.PASS
        assert _rank(Status.ERROR) < _rank(Status.UNVERIFIED) < _rank(Status.SKIPPED) \
            < _rank(Status.PASS)
        assert _rank('SOMETHING_NEW') == 0      # unknown counts as the worst


class TestRefusals:

    def test_nothing(self):
        with pytest.raises(ValueError, match='nothing to merge'):
            merge([])

    def test_the_same_run_twice(self):
        with pytest.raises(ValueError, match='more than once: s1'):
            merge([shard('s1', case('a')), shard('s1', case('a'))])

    def test_mixed_environments_unless_asked(self):
        _shards = [shard('s1', case('a'), env='dev'), shard('s2', case('b'), env='staging')]
        with pytest.raises(ValueError, match='dev, staging'):
            merge(_shards)
        assert merge(_shards, allow_mixed_env=True).env == 'dev + staging'


class TestWhatIsCombined:

    def test_the_coverage_matrix_spans_the_shards(self):
        _axes = [{'role': ['admin', 'guest'], 'channel': ['web', 'app']}]
        _m = merge([shard('s1', case('a', dims={'role': 'admin', 'channel': 'web'}), coverage=_axes),
                    shard('s2', case('b', dims={'role': 'guest', 'channel': 'app'}), coverage=_axes)])
        _grid = _m.coverage_matrix
        assert len(_grid) == 1 and (_grid[0]['filled'], _grid[0]['total']) == (2, 4)

    def test_judgement_changes_are_combined_once(self):
        _change = {'kind': 'removed', 'nodeid': 't.py::a', 'before': 'x', 'weakening': True,
                   'label': '删除', 'case': 'a', 'line': '- 删除 a x'}
        _m = merge([shard('s1', case('a'), judgement_changes=[_change], baseline='conf/j.json'),
                    shard('s2', case('b'), judgement_changes=[_change], baseline='conf/j.json')])
        assert _m.judgement_changes == [_change] and _m.baseline == 'conf/j.json'
        assert _m.verdict['status'] == 'review'
        _m.gate_weakened = True
        assert _m.verdict['status'] == 'fail'

    def test_against_baseline_is_combined(self):
        _s1 = shard('s1', case('a', Status.FAIL, category='defect'), case('n'))
        _s1['against_baseline'] = {'newly_failing': ['t.py::a'], 'no_passing_record': [],
                                   'new_cases': ['t.py::n']}
        _s2 = shard('s2', case('n', Status.FAIL, category='defect'))
        _s2['against_baseline'] = {'newly_failing': [], 'no_passing_record': ['t.py::n'],
                                   'new_cases': []}
        _m = merge([_s1, _s2])
        assert _m.against_baseline == {'newly_failing': ['t.py::a'],
                                       'no_passing_record': ['t.py::n'], 'new_cases': []}

    def test_collection_errors_name_their_shard(self):
        _m = merge([shard('s1', case('a')), shard('s2', collect_error='ImportError: x')])
        assert _m.collect_error == '[s2] ImportError: x'
        assert _m.verdict['status'] == 'error'

    def test_triage_is_recounted(self):
        _m = merge([shard('s1', case('a', Status.FAIL, category='defect')),
                    shard('s2', case('b', Status.FAIL, category='environment'),
                          case('c', Status.FAIL, category='contract'))])
        assert _m.triage['by_category'] == {'defect': 1, 'environment': 1, 'contract': 1}
        assert _m.triage['blames_system_under_test'] == 2

    def test_the_merged_report_survives_its_own_json_and_shows_its_shards(self):
        _m = merge([shard('s1', case('a')), shard('s2', case('a', Status.FAIL, category='defect'))])
        _back = build_from_dict(json.loads(to_json(_m)))
        assert _back.shards == _m.shards and _back.merge_conflicts == _m.merge_conflicts
        assert _back.verdict == _m.verdict
        _html = to_html(_m)
        assert '合并自' in _html and '2 个分片' in _html and '分片之间结论不一致' in _html

    def test_a_single_run_still_round_trips_its_coverage(self):
        _r = ReportData(cases=[case('a', dims={'r': 'x', 'c': 'y'})],
                        coverage=[{'r': ['x'], 'c': ['y']}])
        assert build_from_dict(json.loads(to_json(_r))).coverage_matrix[0]['filled'] == 1


SUITE = '''
    from ipandora.core.assertion import assert_all, failed, passed

    def test_{name}_ok():
        assert_all(passed('状态正确', 'status = 200', src='api'))

    def test_{name}_other():
        assert_all({verdict}('金额一致', 'got 3, want 5', src='api'))
'''


def ipandora(*args, cwd=None, env=None):
    return subprocess.run([sys.executable, '-m', 'ipandora.run'] + list(args), cwd=cwd,
                          capture_output=True, text=True, timeout=180,
                          env=dict(os.environ, **(env or {})))


class TestTheCommand:

    @pytest.fixture
    def shards(self, tmp_path):
        _out = []
        for _name, _verdict in (('api', 'passed'), ('web', 'failed')):
            _suite = tmp_path / 'test_{}.py'.format(_name)
            _suite.write_text(textwrap.dedent(SUITE.format(name=_name, verdict=_verdict)),
                              encoding='utf-8')
            _dir = tmp_path / 'shard-{}'.format(_name)
            _done = ipandora('run', str(_suite), '--no-baseline', '-d', str(_dir), '--no-archive',
                             env={'IPANDORA_REPORTS_DIR': str(tmp_path / 'archive')})
            assert (_dir / 'report.json').is_file(), _done.stdout + _done.stderr
            _out.append(_dir)
        return _out

    def test_the_merged_verdict_is_the_exit_code(self, tmp_path, shards):
        _done = ipandora('merge', str(shards[0]), str(shards[1] / 'report.json'),
                         '-o', str(tmp_path / 'merged'), '--junit-xml', str(tmp_path / 'ci.xml'))
        assert _done.returncode == 1, _done.stdout + _done.stderr
        assert '不能放行' in _done.stdout and '合并 2 个分片 · 4 条用例' in _done.stdout
        _data = json.loads((tmp_path / 'merged' / 'report.json').read_text(encoding='utf-8'))
        assert len(_data['cases']) == 4 and len(_data['shards']) == 2
        assert _data['verdict']['releasable'] is False
        _xml = ET.parse(str(tmp_path / 'ci.xml')).getroot()
        assert _xml.get('tests') == '4' and _xml.get('failures') == '1'

    def test_only_the_green_shard_exits_zero(self, tmp_path, shards):
        _done = ipandora('merge', str(shards[0]), '-o', str(tmp_path / 'merged'))
        assert _done.returncode == 0, _done.stdout + _done.stderr

    def test_a_file_that_is_not_a_report_is_an_error(self, tmp_path, shards):
        _bad = tmp_path / 'x.json'
        _bad.write_text('{}', encoding='utf-8')
        _done = ipandora('merge', str(shards[0]), str(_bad), '-o', str(tmp_path / 'merged'))
        assert _done.returncode == 2 and 'not an IntelliPandora report.json' in _done.stderr

    def test_the_same_shard_twice_is_an_error(self, tmp_path, shards):
        _done = ipandora('merge', str(shards[0]), str(shards[0]), '-o', str(tmp_path / 'merged'))
        assert _done.returncode == 2 and 'more than once' in _done.stderr


class TestDetails:

    def test_a_tie_keeps_the_first_shards_copy(self):
        _m = merge([shard('s1', case('a', Status.FAIL, reason='first')),
                    shard('s2', case('a', Status.FAIL, reason='second'))])
        assert _m.cases[0].reason == 'first' and _m.merge_conflicts == []

    def test_what_each_shard_is_recorded_as(self):
        _m = merge([shard('s1', case('a'), selector='tests/api', env='dev', duration=2.5,
                          generated='2026-11-05 10:00:00')], sources=['a/report.json'])
        assert _m.shards == [{'run_id': 's1', 'source': 'a/report.json', 'selector': 'tests/api',
                              'env': 'dev', 'generated': '2026-11-05 10:00:00', 'duration': 2.5,
                              'cases': 1, 'ok': True}]
        assert _m.env == 'dev'

    def test_ids_and_times_have_the_usual_shape(self):
        import re
        _m = merge([shard('s1', case('a'))])
        assert re.fullmatch(r'merge-\d{8}-\d{6}-\d{3}', _m.run_id)
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', _m.generated)

    def test_the_title(self):
        assert merge([shard('s1', case('a'), title='回归')]).title == '回归'
        assert merge([shard('s1', case('a'), title='回归')], title='合并').title == '合并'
        assert merge([shard('s1', case('a'), title='')]).title == 'IntelliPandora Test Report'

    def test_an_unnamed_environment_reads_as_default(self):
        _m = merge([shard('s1', case('a')), shard('s2', case('b'), env='staging')],
                   allow_mixed_env=True)
        assert _m.env == 'default + staging'
        with pytest.raises(ValueError, match=r'\(default, staging\)'):
            merge([shard('s1', case('a')), shard('s2', case('b'), env='staging')])

    def test_a_collection_error_without_a_run_id_names_its_file(self):
        _m = merge([shard('', collect_error='boom'), shard('s2', collect_error='bang')],
                   sources=['shard-a.json', 'shard-b.json'])
        assert _m.collect_error == '[shard-a.json] boom\n[s2] bang'

    def test_the_triage_findings(self):
        _m = merge([shard('s1', case('a', Status.FAIL, category='defect', confidence='high',
                                     reason='值不对', next_step='核对需求'),
                          case('b', Status.FAIL, category='defect'))])
        assert _m.triage['headline'] == '2 defect'
        assert _m.triage['findings'][0] == {'nodeid': 't.py::a', 'category': 'defect',
                                            'confidence': 'high', 'reason': '值不对',
                                            'next_step': '核对需求'}
        assert merge([shard('s1', case('a'))]).triage['headline'] == 'nothing to triage'

    def test_the_same_change_written_in_another_key_order_is_one_change(self):
        _a = {'kind': 'removed', 'nodeid': 't.py::a', 'weakening': True}
        _b = {'weakening': True, 'nodeid': 't.py::a', 'kind': 'removed'}
        _m = merge([shard('s1', case('a'), judgement_changes=[_a]),
                    shard('s2', case('b'), judgement_changes=[_b])])
        assert len(_m.judgement_changes) == 1

    def test_baselines_are_named_once(self):
        _m = merge([shard('s1', case('a'), baseline='a.json'), shard('s2', case('b'), baseline='b.json'),
                    shard('s3', case('c'), baseline='a.json')])
        assert _m.baseline == 'a.json + b.json'


class TestTheWholeSuite:

    BASELINE = {'version': 1, 'selector': 'tests', 'cases': {
        't.py::a': {'state': 'passed', 'claims': ['x', 'y']},
        't.py::b': {'state': 'passed', 'claims': ['x']},
        't.py::lost': {'state': 'passed', 'claims': ['x', 'y', 'z']},
        't.py::flaky': {'state': 'passed', 'claims': ['x']},
        't.py::was_skipped': {'state': 'skipped', 'claims': []}}}

    def test_a_case_no_shard_reported_is_a_deleted_judgement(self):
        _excluded = {'kind': 'now_excluded', 'nodeid': 't.py::flaky', 'weakening': True}
        _m = merge([shard('s1', case('a'), judgement_changes=[_excluded]), shard('s2', case('b'))],
                   baseline=self.BASELINE)
        _deleted = [_c for _c in _m.judgement_changes if _c['kind'] == 'deleted']
        assert [_c['nodeid'] for _c in _deleted] == ['t.py::lost']
        assert _deleted[0]['weakening'] and '基线里有 3 条判定' in _deleted[0]['note']
        assert _m.verdict['status'] == 'review'
        _m.gate_weakened = True
        assert not _m.verdict['releasable']

    def test_without_the_baseline_nothing_is_assumed_missing(self):
        _m = merge([shard('s1', case('a'))])
        assert _m.judgement_changes == []

    def test_a_missing_shard_is_caught(self, tmp_path):
        from ipandora.core.report import merge_files
        _base = tmp_path / 'judgements.json'
        _base.write_text(json.dumps(self.BASELINE), encoding='utf-8')
        _s1 = tmp_path / 's1.json'
        _s1.write_text(json.dumps(shard('s1', case('a'), case('flaky'))), encoding='utf-8')
        _m, _ = merge_files([str(_s1)], baseline=str(_base))
        assert sorted(_c['nodeid'] for _c in _m.weakened) == ['t.py::b', 't.py::lost']
        assert _m.baseline == str(_base)
        with pytest.raises(ValueError, match='does not exist'):
            merge_files([str(_s1)], baseline=str(tmp_path / 'none.json'))
