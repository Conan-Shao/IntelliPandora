# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_junit.py
@Time  : 2026-11-05

JUnit XML is the one report format whose shape is not ours to choose: CI gates
on it and a viewer reads it. So these cases are mostly about the seams -- what
happens to the three statuses JUnit has no word for, and what a consumer sees
when the run produced nothing at all.
"""
import os
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET

import pytest

from ipandora.core.report import ReportCase, ReportData, Status, to_junit
from ipandora.core.report.junit import COLLECT_ERROR_CASE
from ipandora.core.report.render import write


def case(name='c', status=Status.PASS, **kwargs):
    kwargs.setdefault('nodeid', 'test/t_a.py::TestX::test_{}'.format(name))
    kwargs.setdefault('suite', 'test/t_a.py')
    return ReportCase(name=name, status=status, **kwargs)


def report(*cases, **kwargs):
    _data = ReportData(title=kwargs.pop('title', 'T'), run_id='r1',
                       generated='2026-11-05T10:00:00', **kwargs)
    _data.cases = list(cases)
    return _data


def parse(data):
    return ET.fromstring(to_junit(data))


class TestItIsValidJunit:
    def test_the_document_parses(self):
        assert parse(report(case())).tag == 'testsuites'

    def test_one_testsuite_per_suite(self):
        _root = parse(report(
            case('a', suite='test/t_a.py'), case('b', suite='test/t_b.py')))
        assert {_s.get('name') for _s in _root} == {'test/t_a.py', 'test/t_b.py'}

    def test_a_passing_case_carries_no_outcome_element(self):
        """The commonest way to get this wrong is to mark everything."""
        _tc = parse(report(case())).find('.//testcase')
        assert _tc.find('failure') is None
        assert _tc.find('error') is None
        assert _tc.find('skipped') is None

    def test_classname_is_dotted_for_ci_grouping(self):
        _tc = parse(report(case(
            'x', nodeid='test/api/t_order.py::TestOrder::test_x'))).find('.//testcase')
        assert _tc.get('classname') == 'test.api.t_order.TestOrder'

    def test_duration_is_seconds_with_three_decimals(self):
        _tc = parse(report(case(duration=1.2345))).find('.//testcase')
        assert _tc.get('time') == '1.234' or _tc.get('time') == '1.235'


class TestCountsAddUp:
    @pytest.fixture
    def mixed(self):
        return report(case('p', Status.PASS), case('f', Status.FAIL),
                      case('e', Status.ERROR), case('s', Status.SKIPPED),
                      case('b', Status.BLOCKED), case('g', Status.GAP))

    def test_totals_on_the_root(self, mixed):
        _root = parse(mixed)
        assert _root.get('tests') == '6'
        assert _root.get('failures') == '1'
        assert _root.get('errors') == '1'
        # SKIPPED + BLOCKED + GAP -- none of them silently dropped
        assert _root.get('skipped') == '3'

    def test_nothing_unresolved_counts_as_a_pass(self, mixed):
        _root = parse(mixed)
        _accounted = (int(_root.get('failures')) + int(_root.get('errors'))
                      + int(_root.get('skipped')))
        assert int(_root.get('tests')) - _accounted == 1  # only the real pass


class TestTheStatusesJunitCannotName:
    """
    BLOCKED and GAP become <skipped>, which loses the word. The real status has
    to survive somewhere, or a report reader is told less than the run knew.
    """

    @pytest.mark.parametrize('status', [Status.BLOCKED, Status.GAP, Status.SKIPPED])
    def test_it_is_written_as_skipped(self, status):
        assert parse(report(case('x', status))).find('.//skipped') is not None

    @pytest.mark.parametrize('status', [Status.BLOCKED, Status.GAP, Status.SKIPPED])
    def test_the_real_status_is_kept_as_a_property(self, status):
        _props = parse(report(case('x', status))).findall('.//property')
        assert {_p.get('value') for _p in _props if
                _p.get('name') == 'ipandora.status'} == {status}

    @pytest.mark.parametrize('status,word', [(Status.BLOCKED, 'blocked'),
                                             (Status.GAP, 'gap'),
                                             (Status.SKIPPED, 'precondition')])
    def test_the_type_attribute_says_which(self, status, word):
        assert parse(report(case('x', status))).find('.//skipped').get('type') == word

    def test_a_gap_is_never_reported_as_passing(self):
        _root = parse(report(case('g', Status.GAP)))
        assert _root.get('skipped') == '1'
        assert _root.find('.//testcase/skipped') is not None


class TestACollectionFailureCannotLookGreen:
    """
    The guard that matters most. `tests="0" failures="0"` is what a clean run
    looks like to every CI there is, and it is also what a suite that failed to
    import produces if nobody writes a case for it.
    """

    def test_an_empty_run_with_a_collect_error_still_reports_a_failure(self):
        _root = parse(report(collect_error='ImportError: no module named x'))
        assert _root.get('tests') != '0'
        assert int(_root.get('errors')) >= 1

    def test_the_synthetic_case_names_the_error(self):
        _root = parse(report(collect_error='ImportError: no module named widget'))
        _error = _root.find('.//testcase/error')
        assert 'widget' in _error.get('message')
        assert 'widget' in _error.text

    def test_the_case_is_findable_by_name(self):
        _root = parse(report(collect_error='boom'))
        assert any(_tc.get('name') == COLLECT_ERROR_CASE
                   for _tc in _root.findall('.//testcase'))

    def test_a_clean_empty_run_stays_clean(self):
        """No cases and no collect error is a real zero, not a hidden failure."""
        _root = parse(report())
        assert _root.get('tests') == '0' and _root.get('errors') == '0'

    def test_a_collect_error_adds_to_an_otherwise_passing_run(self):
        _root = parse(report(case('p'), collect_error='partial import failure'))
        assert _root.get('tests') == '2'
        assert _root.get('errors') == '1'


class TestTheFailureBodyIsUsableFromACiLog:
    def test_every_judgement_is_listed(self):
        _case = case('f', Status.FAIL, message='2/3 checks failed', checks=[
            {'name': '状态码', 'ok': True, 'expr': 'status 200', 'src': 'api'},
            {'name': '手续费', 'ok': False, 'expr': 'fee 9 <= 5', 'src': 'derived'}])
        _text = parse(report(_case)).find('.//failure').text
        assert '状态码' in _text and '手续费' in _text
        assert 'fee 9 <= 5' in _text          # the actual values, escaped and back

    def test_the_triage_verdict_rides_along(self):
        _case = case('f', Status.FAIL, message='failed', reason='契约漂移',
                     category='schema', next_step='看 OpenAPI diff')
        _text = parse(report(_case)).find('.//failure').text
        assert '契约漂移' in _text and '看 OpenAPI diff' in _text

    def test_declared_gaps_appear_too(self):
        _case = case('f', Status.FAIL, message='x', checks=[
            {'name': '库存未校验', 'ok': False, 'expr': '应查数据库里的库存',
             'kind': 'gap', 'src': 'derived'}])
        assert '库存未校验' in parse(report(_case)).find('.//failure').text

    def test_coverage_dimensions_become_properties(self):
        _case = case('p', dims={'scene': 'pay', 'chain': 'bsc'})
        _props = {_p.get('name'): _p.get('value')
                  for _p in parse(report(_case)).findall('.//property')}
        assert _props['ipandora.dim.scene'] == 'pay'
        assert _props['ipandora.dim.chain'] == 'bsc'


class TestItSurvivesRealResponseBodies:
    def test_control_characters_do_not_break_the_document(self):
        """
        XML 1.0 forbids most C0 controls outright -- they cannot be escaped,
        only dropped. One stray byte in one assertion message would otherwise
        cost the whole run its report.
        """
        _case = case('f', Status.FAIL, message='bad \x00 byte \x08 here \x1f end')
        _root = parse(report(_case))          # parses at all == the point
        assert 'bad' in _root.find('.//failure').get('message')

    def test_markup_in_a_value_is_escaped_not_injected(self):
        _case = case('f', Status.FAIL,
                     message='<failure message="injected"/> & more')
        _root = parse(report(_case))
        assert len(_root.findall('.//failure')) == 1
        assert 'injected' in _root.find('.//failure').get('message')

    def test_tabs_and_newlines_are_kept(self):
        _case = case('f', Status.FAIL, message='line1\nline2\tend')
        assert 'line2' in parse(report(_case)).find('.//failure').text

    def test_a_very_long_message_does_not_bloat_the_attribute(self):
        _case = case('f', Status.FAIL, message='x' * 50000)
        assert len(parse(report(_case)).find('.//failure').get('message')) <= 1000


class TestWriteProducesIt:
    def test_write_emits_the_xml_beside_the_html(self, tmp_path):
        _paths = write(report(case()), str(tmp_path))
        assert _paths['junit'].endswith('.xml')
        assert os.path.isfile(_paths['junit'])
        ET.parse(_paths['junit'])

    def test_it_can_be_turned_off(self, tmp_path):
        assert 'junit' not in write(report(case()), str(tmp_path), junit=False)


class TestTheCliWritesItWhereAsked:
    def test_junit_xml_flag_writes_a_parseable_file(self, tmp_path):
        _suite = tmp_path / 'test_demo.py'
        _suite.write_text(textwrap.dedent('''
            def test_passes():
                """一条通过的用例"""
                assert True

            def test_fails():
                """一条失败的用例"""
                assert 1 == 2
        '''), encoding='utf-8')

        _out = tmp_path / 'ci' / 'results.xml'
        _env = dict(os.environ)
        _env['IPANDORA_REPORTS_DIR'] = str(tmp_path / 'reports')
        _done = subprocess.run(
            [sys.executable, '-m', 'ipandora.run', 'run', str(_suite),
             '--junit-xml', str(_out)],
            capture_output=True, text=True, env=_env, timeout=180)

        # one case failed, so the command must fail too
        assert _done.returncode == 1, _done.stdout + _done.stderr
        assert _out.is_file(), _done.stdout + _done.stderr

        _root = ET.parse(str(_out)).getroot()
        assert _root.get('tests') == '2'
        assert _root.get('failures') == '1'

    def test_the_history_copy_is_written_without_the_flag(self, tmp_path):
        _suite = tmp_path / 'test_ok.py'
        _suite.write_text('def test_ok():\n    """ok"""\n    assert True\n',
                          encoding='utf-8')
        _env = dict(os.environ)
        _env['IPANDORA_REPORTS_DIR'] = str(tmp_path / 'reports')
        _done = subprocess.run(
            [sys.executable, '-m', 'ipandora.run', 'run', str(_suite)],
            capture_output=True, text=True, env=_env, timeout=180)
        assert _done.returncode == 0, _done.stdout + _done.stderr

        _found = list((tmp_path / 'reports').rglob('report.xml'))
        assert _found, 'no JUnit XML in the run history'
        ET.parse(str(_found[0]))
