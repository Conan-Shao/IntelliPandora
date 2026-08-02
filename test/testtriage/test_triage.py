# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_triage.py
@Time  : 2026-08-01
"""
import pytest

from ipandora.core.runner.result import CaseResult, RunResult
from ipandora.core.triage import (Category, Confidence, classify,
                                  failed_check_sources, has_analyzer,
                                  register_analyzer, triage)
from ipandora.core.triage import hooks


def case(nodeid='t.py::test_x', outcome='failed', message=''):
    return CaseResult(nodeid=nodeid, outcome=outcome, message=message)


def result_with(*cases):
    return RunResult(run_id='r', cases=list(cases))


ASSERT_FAILURE = (
    "AssertionError: Assertion failed (1/2 checks failed)\n"
    "\n"
    "  [FAIL] 请求成功 (2xx) (api) | status = 500\n"
    "\n"
    "  passed: data.name == 'alice'")

SCHEMA_FAILURE = (
    "AssertionError: Assertion failed (1/1 checks failed)\n"
    "\n"
    "  [FAIL] 响应符合 schema (schema) | at id: 'x' is not of type 'integer'")


class TestClassification:
    """
    The operational distinction that matters: is the system under test wrong,
    or is it our harness, our data, or the network. A suite that cannot
    separate those teaches people to ignore red builds.
    """

    def test_assertion_failure_is_a_defect(self):
        finding = classify('t::a', 'failed', ASSERT_FAILURE)
        assert finding.category == Category.DEFECT
        assert finding.blames_system_under_test

    def test_schema_only_failure_is_a_contract_change(self):
        finding = classify('t::a', 'failed', SCHEMA_FAILURE)
        assert finding.category == Category.CONTRACT
        assert finding.blames_system_under_test

    def test_mixed_sources_is_a_defect_not_a_contract_change(self):
        mixed = ASSERT_FAILURE + '\n  [FAIL] shape (schema) | bad'
        assert classify('t::a', 'failed', mixed).category == Category.DEFECT

    @pytest.mark.parametrize('marker', [
        'HttpTimeoutError', 'HttpConnectionError', 'ConnectTimeout', 'could not connect'])
    def test_transport_failure_is_environment(self, marker):
        finding = classify('t::a', 'failed', '{}: GET https://x timed out'.format(marker))
        assert finding.category == Category.ENVIRONMENT
        # nothing was tested, so this must not be reported as a product defect
        assert not finding.blames_system_under_test

    def test_skip_is_missing_data_not_a_defect(self):
        finding = classify('t::a', 'skipped', 'Precondition not met (1/1 checks failed)')
        assert finding.category == Category.DATA
        assert not finding.blames_system_under_test

    def test_setup_error_is_a_broken_harness(self):
        finding = classify('t::a', 'error', "fixture 'wallet' not found")
        assert finding.category == Category.HARNESS
        assert not finding.blames_system_under_test

    def test_plain_assertion_is_a_lower_confidence_defect(self):
        finding = classify('t::a', 'failed', 'AssertionError: assert 1 == 2')
        assert finding.category == Category.DEFECT
        assert finding.confidence == Confidence.MEDIUM

    def test_unrecognised_failure_is_not_guessed_at(self):
        finding = classify('t::a', 'failed', 'something entirely unexpected')
        assert finding.category == Category.UNKNOWN
        assert finding.confidence == Confidence.LOW

    def test_transport_beats_assertion_when_both_appear(self):
        # a timeout raised inside a test still means nothing was verified
        both = ASSERT_FAILURE + '\nHttpTimeoutError: timed out'
        assert classify('t::a', 'failed', both).category == Category.ENVIRONMENT

    def test_every_finding_says_what_to_do_next(self):
        for outcome, message in [('failed', ASSERT_FAILURE), ('skipped', 'x'),
                                 ('error', 'fixture missing'), ('failed', 'huh')]:
            assert classify('t::a', outcome, message).next_step

    def test_reason_is_evidence_not_a_restatement(self):
        finding = classify('t::a', 'failed', ASSERT_FAILURE)
        assert finding.category not in finding.reason


class TestCheckSourceExtraction:
    """The payoff from tagging checks with a source at assertion time."""

    def test_extracts_sources(self):
        assert failed_check_sources(ASSERT_FAILURE) == ['api']
        assert failed_check_sources(SCHEMA_FAILURE) == ['schema']

    def test_deduplicates_preserving_order(self):
        message = ('  [FAIL] a (derived) | x\n'
                   '  [FAIL] b (api) | y\n'
                   '  [FAIL] c (derived) | z')
        assert failed_check_sources(message) == ['derived', 'api']

    def test_ignores_passed_checks(self):
        # the "passed:" line must not contribute sources
        assert 'name' not in failed_check_sources(ASSERT_FAILURE)

    def test_empty_message(self):
        assert failed_check_sources('') == []


class TestReport:
    def test_counts_by_category(self):
        report = triage(result_with(
            case('t::a', 'failed', ASSERT_FAILURE),
            case('t::b', 'failed', SCHEMA_FAILURE),
            case('t::c', 'failed', 'HttpTimeoutError: timed out')))
        assert report.by_category == {Category.DEFECT: 1, Category.CONTRACT: 1,
                                      Category.ENVIRONMENT: 1}

    def test_separates_product_failures_from_our_own(self):
        report = triage(result_with(
            case('t::a', 'failed', ASSERT_FAILURE),
            case('t::b', 'failed', 'HttpConnectionError: refused'),
            case('t::c', 'error', 'fixture missing')))
        assert len(report.product_failures) == 1

    def test_skips_excluded_by_default(self):
        report = triage(result_with(case('t::a', 'skipped', 'no data')))
        assert report.findings == []

    def test_skips_included_on_request(self):
        report = triage(result_with(case('t::a', 'skipped', 'no data')),
                        include_skipped=True)
        assert len(report.findings) == 1

    def test_empty_run(self):
        assert triage(result_with()).headline() == 'nothing to triage'

    def test_serialisable(self):
        import json
        report = triage(result_with(case('t::a', 'failed', ASSERT_FAILURE)))
        json.dumps(report.to_dict(), ensure_ascii=False)

    def test_analysis_absent_unless_set(self):
        report = triage(result_with(case('t::a', 'failed', ASSERT_FAILURE)))
        assert 'analysis' not in report.to_dict()


class TestAnalyzerHookIsOptional:
    """
    core/ owns the slot; it must work with nothing in it. This is what
    `rm -rf ai/` leaves behind.
    """

    @pytest.fixture(autouse=True)
    def clean_hook(self):
        register_analyzer(None)
        yield
        register_analyzer(None)

    def test_no_analyzer_by_default(self):
        assert has_analyzer() is False
        assert hooks.analyze(triage(result_with()), result_with()) == ''

    def test_registered_analyzer_is_used(self):
        register_analyzer(lambda report, result: 'looks like one root cause')
        assert hooks.analyze(triage(result_with()), result_with()) == \
            'looks like one root cause'

    def test_analyzer_failure_does_not_propagate(self):
        # a model being unreachable must not change a test verdict
        def boom(report, result):
            raise RuntimeError('provider down')

        register_analyzer(boom)
        assert hooks.analyze(triage(result_with()), result_with()) == ''

    def test_analyzer_returning_none_is_tolerated(self):
        register_analyzer(lambda report, result: None)
        assert hooks.analyze(triage(result_with()), result_with()) == ''

    def test_can_be_cleared(self):
        register_analyzer(lambda report, result: 'x')
        register_analyzer(None)
        assert has_analyzer() is False
