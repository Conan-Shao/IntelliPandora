# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_report.py
@Time  : 2026-08-01
"""
import json

import pytest

from ipandora.core.report import (Status, build, build_from_dict, to_html, to_json,
                                  write)
from ipandora.core.report.builder import suite_of
from ipandora.core.report.model import ReportCase, ReportData
from ipandora.core.report.redact import MASK
from ipandora.core.runner.result import CaseResult, RunResult

ASSERT_FAILURE = ("AssertionError: Assertion failed (1/1 checks failed)\n"
                  "\n  [FAIL] 请求成功 (2xx) (api) | status = 500")


def run_with(*cases, **kwargs):
    return RunResult(run_id=kwargs.get('run_id', 'run-1'),
                     selector=kwargs.get('selector', ''),
                     collect_error=kwargs.get('collect_error', ''),
                     coverage=kwargs.get('coverage', []),
                     cases=list(cases))


def case(nodeid='suite_a.py::test_x', outcome='passed', message='', **kwargs):
    return CaseResult(nodeid=nodeid, outcome=outcome, message=message, **kwargs)


AXES = [{'id': 'g', 'title': 'chain × path', 'note': '',
         'y': {'key': 'chain', 'label': 'Chain',
               'values': [{'key': '1', 'label': 'ETH'}, {'key': '56', 'label': 'BSC'}]},
         'x': {'key': 'pay', 'label': 'Pay',
               'values': [{'key': 'native', 'label': 'Native'},
                          {'key': 'token', 'label': 'Token'}]}}]


def judgement(name='a', ok=True, src='api', kind='assert'):
    return {'name': name, 'ok': ok, 'kind': kind, 'expr': '{} = x'.format(name), 'src': src}


class TestStatusMapping:
    @pytest.mark.parametrize('outcome,expected', [
        ('passed', Status.PASS), ('failed', Status.FAIL),
        ('error', Status.ERROR), ('skipped', Status.SKIPPED)])
    def test_outcomes_map_to_statuses(self, outcome, expected):
        report = build(run_with(case(outcome=outcome, message=ASSERT_FAILURE)))
        assert report.cases[0].status == expected

    def test_unknown_outcome_is_an_error_not_a_pass(self):
        # failing closed: an outcome we do not understand must not read as green
        report = build(run_with(case(outcome='something-new')))
        assert report.cases[0].status == Status.ERROR


class TestCountsWhatDidNotHappen:
    """
    A report that only shows what ran cannot show what is missing, and what is
    missing is usually the more interesting question.
    """

    def test_pass_rate_excludes_inconclusive_cases(self):
        report = build(run_with(
            case('s.py::a', 'passed'),
            case('s.py::b', 'skipped', 'no data')))
        # 1 of 1 conclusive passed -- the skip is neither a pass nor a fail
        assert report.pass_rate == '100.0%'
        assert report.totals['skipped'] == 1

    def test_a_suite_that_only_skips_has_no_pass_rate(self):
        report = build(run_with(case('s.py::a', 'skipped', 'no data')))
        assert report.pass_rate == 'n/a'

    def test_skips_do_not_inflate_the_rate(self):
        # 1 pass, 1 fail, 8 skips is 50%, not 90%
        cases = [case('s.py::p', 'passed'), case('s.py::f', 'failed', ASSERT_FAILURE)]
        cases += [case('s.py::s{}'.format(i), 'skipped', 'x') for i in range(8)]
        assert build(run_with(*cases)).pass_rate == '50.0%'

    def test_inconclusive_cases_are_listed(self):
        report = build(run_with(
            case('s.py::a', 'passed'),
            case('s.py::b', 'skipped', 'no data'),
            case('s.py::c', 'error', 'fixture missing')))
        assert {c.name for c in report.inconclusive} == {'b', 'c'}

    def test_blocked_and_gap_exist_in_the_model(self):
        # not inferred from a run -- a run cannot report an assertion nobody
        # wrote -- but the report can carry them once declared
        report = ReportData(cases=[
            ReportCase(name='x', status=Status.BLOCKED),
            ReportCase(name='y', status=Status.GAP)])
        assert report.totals['blocked'] == 1 and report.totals['gap'] == 1
        assert len(report.inconclusive) == 2


class TestTriageIsCarried:
    def test_category_reaches_the_case(self):
        report = build(run_with(case('s.py::a', 'failed', ASSERT_FAILURE)))
        assert report.cases[0].category == 'defect'
        assert report.cases[0].next_step

    def test_environment_failures_do_not_blame_the_product(self):
        report = build(run_with(
            case('s.py::a', 'failed', 'HttpTimeoutError: timed out')))
        assert report.triage['blames_system_under_test'] == 0

    def test_triage_can_be_skipped(self):
        report = build(run_with(case('s.py::a', 'failed', ASSERT_FAILURE)),
                       include_triage=False)
        assert report.triage == {}
        assert report.cases[0].category == ''


class TestRedactionHappensAtBuildTime:
    """
    The reason this is not done in the template: a report is downloaded,
    forwarded and archived. Masking one view leaves the JSON behind it
    readable.
    """

    SECRET = 'sk-abcdefghij0123456789'

    def test_secret_in_a_failure_message_is_masked(self):
        report = build(run_with(
            case('s.py::a', 'failed', 'token was {}'.format(self.SECRET))))
        assert self.SECRET not in report.cases[0].message
        assert MASK in report.cases[0].message

    def test_secret_never_reaches_the_json(self):
        report = build(run_with(
            case('s.py::a', 'failed', 'token was {}'.format(self.SECRET))))
        assert self.SECRET not in to_json(report)

    def test_secret_never_reaches_the_html(self):
        report = build(run_with(
            case('s.py::a', 'failed', 'token was {}'.format(self.SECRET))))
        assert self.SECRET not in to_html(report)

    def test_secret_in_the_selector_is_masked(self):
        report = build(run_with(case(), selector='-k {}'.format(self.SECRET)))
        assert self.SECRET not in report.selector

    def test_secret_in_a_collect_error_is_masked(self):
        report = build(run_with(collect_error='auth failed with {}'.format(self.SECRET)))
        assert self.SECRET not in report.collect_error


class TestRendering:
    def test_html_contains_the_essentials(self):
        report = build(run_with(case('s.py::a', 'failed', ASSERT_FAILURE)),
                       title='My Run')
        html = to_html(report)
        assert 'My Run' in html and 'FAIL' in html and 'defect' in html

    # Everything below is content the system under test controls. The report
    # now shows far more of it than a failure message -- check evidence, request
    # and response bodies, headers, URLs -- and highlight_json is the one place
    # the report emits markup it built itself rather than letting Jinja escape
    # it. Each surface is enumerated so adding one without escaping it fails
    # here rather than in someone's browser.
    PAYLOAD = '<img src=x onerror=alert(1)>'

    def _rendered(self, **case_kwargs):
        return to_html(ReportData(cases=[
            ReportCase(name='x', status='FAIL', **case_kwargs)]))

    def test_failure_message_cannot_inject_markup(self):
        html = self._rendered(message=self.PAYLOAD)
        assert '<img src=x' not in html and '&lt;img' in html

    def test_check_evidence_cannot_inject_markup(self):
        html = self._rendered(checks=[
            {'name': self.PAYLOAD, 'ok': False, 'kind': 'assert',
             'expr': self.PAYLOAD, 'src': self.PAYLOAD}])
        assert '<img src=x' not in html and '&lt;img' in html

    def test_response_body_cannot_inject_markup(self):
        # goes through highlight_json, which returns Markup
        html = self._rendered(exchanges=[
            {'method': 'GET', 'url': 'https://x.test', 'status': 200, 'ms': 1,
             'request_headers': {}, 'request_body': None,
             'response_headers': {}, 'response_body': self.PAYLOAD}])
        assert '<img src=x' not in html and '&lt;img' in html

    def test_markup_inside_a_json_string_is_escaped(self):
        # the token path of the highlighter, not the gap path
        html = self._rendered(exchanges=[
            {'method': 'GET', 'url': 'https://x.test', 'status': 200, 'ms': 1,
             'request_headers': {}, 'request_body': None, 'response_headers': {},
             'response_body': '{"k": "<script>alert(1)</script>"}'}])
        assert '<script>alert(1)' not in html
        assert '&lt;script&gt;' in html

    def test_headers_and_url_cannot_inject_markup(self):
        html = self._rendered(exchanges=[
            {'method': 'GET', 'url': 'https://x.test/' + self.PAYLOAD, 'status': 200,
             'ms': 1, 'request_headers': {self.PAYLOAD: self.PAYLOAD},
             'request_body': None,
             'response_headers': {self.PAYLOAD: self.PAYLOAD}, 'response_body': ''}])
        assert '<img src=x' not in html and '&lt;img' in html

    def test_curl_attribute_cannot_break_out_of_the_attribute(self):
        html = self._rendered(exchanges=[
            {'method': 'GET', 'url': 'https://x.test', 'status': 200, 'ms': 1,
             'request_headers': {'X-A': '" onmouseover="alert(1)'},
             'request_body': None, 'response_headers': {}, 'response_body': ''}])
        assert 'onmouseover="alert(1)"' not in html

    def test_json_is_valid_and_matches_the_model(self):
        report = build(run_with(case('s.py::a', 'failed', ASSERT_FAILURE)))
        parsed = json.loads(to_json(report))
        assert parsed['totals']['failed'] == 1
        assert parsed['run_id'] == 'run-1'

    def test_roundtrip_through_json(self):
        report = build(run_with(case('s.py::a', 'failed', ASSERT_FAILURE)))
        restored = build_from_dict(json.loads(to_json(report)))
        assert restored.totals == report.totals
        assert restored.cases[0].category == report.cases[0].category

    def test_write_produces_both_artifacts(self, tmp_path):
        report = build(run_with(case('s.py::a', 'passed')))
        paths = write(report, str(tmp_path))
        assert set(paths) == {'html', 'json'}
        for path in paths.values():
            assert open(path, encoding='utf-8').read()

    def test_empty_run_renders(self):
        to_html(build(run_with()))

    def test_collect_error_is_shown(self):
        # the reason itself, not the surrounding label -- the label is prose
        # and changes; the reason is the thing a reader needs
        report = build(run_with(collect_error='no tests were collected'))
        assert 'no tests were collected' in to_html(report)
        assert report.ok is False


class TestGrouping:
    def test_cases_group_by_file(self):
        report = build(run_with(
            case('tests/suite_a.py::x', 'passed'),
            case('tests/suite_a.py::y', 'passed'),
            case('tests/suite_b.py::z', 'passed')))
        assert set(report.by_suite) == {'suite_a.py', 'suite_b.py'}
        assert len(report.by_suite['suite_a.py']) == 2

    @pytest.mark.parametrize('nodeid,expected', [
        ('a/b/test_x.py::test_y', 'test_x.py'),
        ('test_x.py::TestC::test_y', 'test_x.py'),
        ('', 'default')])
    def test_suite_extraction(self, nodeid, expected):
        assert suite_of(nodeid) == expected


class TestCoverageMatrix:
    """
    An empty cell is a combination nobody wrote a test for. It is the one thing
    a list of results can never show, and the reason the axes are declared by
    the suite rather than derived from what ran.
    """

    def _report(self, *cases):
        return build(run_with(*cases, coverage=AXES), include_triage=False)

    def test_a_cell_with_no_test_is_reported_as_empty(self):
        report = self._report(case('s.py::a', dims={'chain': '1', 'pay': 'native'}))
        grid = report.coverage_matrix[0]
        assert grid['filled'] == 1 and grid['total'] == 4
        states = [c['status'] for row in grid['rows'] for c in row['cells']]
        assert states.count('none') == 3

    def test_a_cell_is_as_bad_as_its_worst_case(self):
        report = self._report(
            case('s.py::a', dims={'chain': '1', 'pay': 'native'}),
            case('s.py::b', 'failed', dims={'chain': '1', 'pay': 'native'}))
        assert report.coverage_matrix[0]['rows'][0]['cells'][0]['status'] == 'fail'

    def test_a_cell_of_only_skips_is_not_a_pass(self):
        report = self._report(case('s.py::a', 'skipped',
                                   dims={'chain': '1', 'pay': 'native'}))
        assert report.coverage_matrix[0]['rows'][0]['cells'][0]['status'] == 'skip'

    def test_cases_without_dims_do_not_fill_anything(self):
        report = self._report(case('s.py::a'))
        assert report.coverage_matrix[0]['filled'] == 0

    def test_no_declared_axes_means_no_matrix(self):
        assert build(run_with(case('s.py::a')), include_triage=False).coverage_matrix == []


class TestJudgementsAndGaps:
    def _report(self, *cases):
        return build(run_with(*cases), include_triage=False)

    def test_check_counts_are_judgements_not_cases(self):
        report = self._report(case('s.py::a', checks=[
            judgement('a'), judgement('b', ok=False), judgement('c', kind='gap')]))
        assert report.check_totals == {'passed': 1, 'failed': 1, 'gap': 1}

    def test_gaps_are_aggregated_with_a_count(self):
        shared = judgement('余额实际增加', kind='gap', src='onchain')
        report = self._report(case('s.py::a', checks=[dict(shared)]),
                              case('s.py::b', checks=[dict(shared)]),
                              case('s.py::c', checks=[judgement('别的', kind='gap')]))
        by_name = {g['name']: g['count'] for g in report.gaps}
        assert by_name == {'余额实际增加': 2, '别的': 1}
        assert report.gaps[0]['name'] == '余额实际增加', 'most common should sort first'

    def test_a_suite_that_only_checks_one_dimension_shows_it(self):
        report = self._report(case('s.py::a', checks=[
            judgement('a', src='api'), judgement('b', src='api')]))
        assert set(report.by_source) == {'api'}

    def test_gaps_do_not_count_as_passed_checks(self):
        report = self._report(case('s.py::a', checks=[judgement('g', kind='gap')]))
        assert report.cases[0].checks_passed == 0
        assert report.cases[0].checks_failed == 0

    def test_evidence_is_redacted_like_everything_else(self):
        report = self._report(case('s.py::a', exchanges=[{
            'method': 'GET', 'url': 'https://x.test', 'status': 200, 'ms': 1,
            'request_headers': {'Authorization': 'Bearer abcdef1234567890'},
            'request_body': None, 'response_headers': {}, 'response_body': ''}]))
        assert report.cases[0].exchanges[0]['request_headers']['Authorization'] == MASK

    def test_json_roundtrip_survives_the_derived_fields(self):
        report = self._report(case('s.py::a', checks=[judgement('a')]))
        restored = build_from_dict(json.loads(to_json(report)))
        assert restored.cases[0].checks[0]['name'] == 'a'


class TestCurlReproduction:
    def test_the_command_is_shell_safe(self):
        """
        A header value comes from whatever the suite sent, and the command is
        offered for pasting into a shell. The property that matters is not how
        it is quoted but that it parses back to the argv we meant -- a metachar
        must end up inside one argument, never as syntax.
        """
        import shlex
        from ipandora.core.report.render import to_curl
        hostile = "it's; rm -rf /"
        argv = shlex.split(to_curl({'method': 'GET', 'url': 'https://x.test/?a=1&b=2',
                                    'request_headers': {'X-A': hostile},
                                    'request_body': None}))
        assert argv == ['curl', '-X', 'GET', '-H', 'X-A: ' + hostile,
                        'https://x.test/?a=1&b=2']

    def test_a_body_is_included(self):
        from ipandora.core.report.render import to_curl
        command = to_curl({'method': 'POST', 'url': 'https://x.test',
                           'request_headers': {}, 'request_body': '{"a": 1}'})
        assert '--data' in command and '-X POST' in command
