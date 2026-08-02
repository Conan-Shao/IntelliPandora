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
                     cases=list(cases))


def case(nodeid='suite_a.py::test_x', outcome='passed', message=''):
    return CaseResult(nodeid=nodeid, outcome=outcome, message=message)


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

    def test_response_content_cannot_inject_markup(self):
        # failure messages contain whatever the system under test returned
        report = ReportData(cases=[
            ReportCase(name='x', message='<img src=x onerror=alert(1)>')])
        html = to_html(report)
        assert '<img src=x' not in html
        assert '&lt;img' in html

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
        report = build(run_with(collect_error='no tests were collected'))
        assert 'Nothing ran' in to_html(report)
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
