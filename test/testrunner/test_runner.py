# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_runner.py
@Time  : 2026-08-01
"""
import json

import pytest

from ipandora.core.runner import explain, run
from ipandora.core.runner import store
from ipandora.core.runner.collector import short_reason
from ipandora.core.runner.result import CaseResult, RunResult


class TestOutcomeClassification:
    """Each pytest outcome has to land in the right bucket -- an error during
    setup is not the same thing as a test that ran and failed."""

    def test_counts(self, sample_suite):
        result = run(sample_suite, persist=False)
        assert result.total == 4
        assert (result.passed, result.failed, result.skipped, result.errors) == (1, 1, 1, 1)

    def test_not_ok_when_something_failed(self, sample_suite):
        assert run(sample_suite, persist=False).ok is False

    def test_ok_when_everything_passed(self, passing_suite):
        result = run(passing_suite, persist=False)
        assert result.ok is True and result.passed == 1

    def test_skip_is_not_a_failure(self, sample_suite):
        result = run(sample_suite, persist=False)
        skipped = [c for c in result.cases if c.outcome == 'skipped']
        assert len(skipped) == 1
        assert skipped[0] not in result.failures

    def test_setup_error_is_an_error_not_a_failure(self, sample_suite):
        result = run(sample_suite, persist=False)
        errored = [c for c in result.cases if c.outcome == 'error']
        assert len(errored) == 1 and 'setup_error' in errored[0].nodeid

    def test_durations_are_recorded(self, passing_suite):
        assert run(passing_suite, persist=False).cases[0].duration >= 0


class TestSummaryIsAgentSized:
    """
    The point of the library API: an agent gets structure, not a wall of
    stdout. Returning raw pytest output floods a context window with text it
    cannot act on.
    """

    def test_summary_has_what_you_need_to_decide(self, sample_suite):
        summary = run(sample_suite, persist=False).summary()
        assert summary['ok'] is False
        assert summary['totals']['failed'] == 1
        assert {'run_id', 'summary', 'totals', 'failures', 'detail_hint'} <= set(summary)

    def test_summary_carries_the_assertion_message(self, sample_suite):
        summary = run(sample_suite, persist=False).summary()
        messages = ' '.join(f['message'] for f in summary['failures'])
        assert 'one is not two' in messages

    def test_summary_excludes_full_tracebacks(self, sample_suite):
        result = run(sample_suite, persist=False)
        summary = result.summary()
        # detail is retained on the result, just not carried in the summary
        details = [c.detail for c in result.failures if c.detail]
        assert details
        assert all('detail' not in f for f in summary['failures'])
        summary_text = json.dumps(summary, ensure_ascii=False)
        for detail in details:
            assert detail not in summary_text

    def test_summary_is_substantially_smaller_than_full_detail(self, sample_suite):
        result = run(sample_suite, persist=True)
        summary_size = len(json.dumps(result.summary(), ensure_ascii=False))
        full_size = len(json.dumps(explain(result.run_id), ensure_ascii=False))
        assert summary_size < full_size

    def test_summary_is_json_serialisable(self, sample_suite):
        json.dumps(run(sample_suite, persist=False).summary(), ensure_ascii=False)

    def test_passing_run_has_no_failures_key(self, passing_suite):
        summary = run(passing_suite, persist=False).summary()
        assert 'failures' not in summary and 'detail_hint' not in summary

    def test_headline_reads_naturally(self, sample_suite):
        assert run(sample_suite, persist=False).headline() == \
            '1 passed, 1 failed, 1 skipped, 1 error'


class TestSelectors:
    def test_path_selector(self, passing_suite):
        assert run(passing_suite, persist=False).total == 1

    def test_nodeid_selector(self, sample_suite):
        result = run('{}::test_that_passes'.format(sample_suite), persist=False)
        assert result.total == 1 and result.passed == 1

    def test_keyword_selector(self, sample_suite, monkeypatch):
        # -k needs a rootdir to search; run from the suite's directory
        import os
        monkeypatch.chdir(os.path.dirname(sample_suite))
        result = run('test_that_passes', persist=False)
        assert result.passed == 1 and result.failed == 0

    def test_bad_path_is_reported_not_raised(self, tmp_path):
        result = run(str(tmp_path / 'no_such_file.py'), persist=False)
        assert result.ok is False
        assert result.exit_code != 0

    def test_selector_matching_nothing_is_not_ok(self, passing_suite, monkeypatch):
        # A typo'd -k expression must not read as "everything passed"
        import os
        monkeypatch.chdir(os.path.dirname(passing_suite))
        result = run('no_test_has_this_name', persist=False)
        assert result.ok is False
        assert 'no tests were collected' in result.summary()['collect_error']

    def test_a_path_that_does_not_exist_is_not_treated_as_keyword(self, tmp_path):
        from ipandora.core.runner.api import looks_like_path
        assert looks_like_path(str(tmp_path / 'gone.py')) is True
        assert looks_like_path('test_something') is False


class TestRunStore:
    def test_run_is_retrievable_by_id(self, sample_suite):
        result = run(sample_suite, persist=True)
        assert explain(result.run_id) is not None

    def test_explain_returns_full_detail(self, sample_suite):
        result = run(sample_suite, persist=True)
        detail = explain(result.run_id)
        assert detail['failures']
        assert any(f['detail'] for f in detail['failures'])

    def test_explain_unknown_id(self):
        assert explain('run-does-not-exist') is None

    def test_not_persisted_when_asked_not_to(self, sample_suite):
        result = run(sample_suite, persist=False)
        assert explain(result.run_id) is None

    def test_runs_are_listed_newest_first(self, passing_suite):
        first = run(passing_suite, persist=True)
        second = run(passing_suite, persist=True)
        listed = store.list_runs(limit=5)
        assert listed.index(second.run_id) < listed.index(first.run_id)

    def test_run_ids_are_unique(self, passing_suite):
        ids = {run(passing_suite, persist=False).run_id for _ in range(3)}
        assert len(ids) == 3

    def test_repeated_runs_over_same_named_files(self, tmp_path):
        # Under pytest's default 'prepend' import mode the second run aborts
        # with "import file mismatch", because modules are keyed by basename.
        # run() is meant to be called repeatedly in one process.
        results = []
        for folder in ('first', 'second'):
            _dir = tmp_path / folder
            _dir.mkdir()
            (_dir / 'test_collide.py').write_text('def test_x():\n    assert True\n',
                                                  encoding='utf-8')
            results.append(run(str(_dir / 'test_collide.py'), persist=False))
        assert all(r.ok and r.passed == 1 for r in results), \
            [r.headline() for r in results]

    @pytest.mark.parametrize('bad', ['../escape', 'a/b', '', '.hidden'])
    def test_store_rejects_path_traversal(self, bad):
        # run_id reaches the filesystem, so it must not be able to escape
        with pytest.raises(ValueError):
            store.load(bad)

    def test_roundtrip_preserves_results(self, sample_suite):
        original = run(sample_suite, persist=True)
        restored = store.load(original.run_id)
        assert (restored.total, restored.passed, restored.failed) == \
            (original.total, original.passed, original.failed)


class TestStdoutIsProtocolSafe:
    """
    MCP's stdio transport owns stdout. Anything printed there lands inside a
    JSON-RPC message and drops the connection, so a tool that runs pytest must
    emit nothing on stdout.
    """

    # capfd (not capsys) because the concern is the file descriptor, which is
    # what a peer on the other end of stdio actually reads.

    def test_quiet_run_prints_nothing(self, sample_suite, capfd):
        capfd.readouterr()  # discard anything buffered before this point
        run(sample_suite, persist=False, quiet=True)
        leaked = capfd.readouterr().out
        assert leaked == '', 'pytest output leaked to stdout: {!r}'.format(leaked[:200])

    def test_loud_run_still_prints(self, sample_suite, capfd):
        # the default stays useful for a human running this from a script --
        # and this is the control proving the quiet assertion is not vacuous
        capfd.readouterr()
        run(sample_suite, persist=False)
        assert capfd.readouterr().out != ''

    def test_quiet_run_still_collects_results(self, sample_suite):
        result = run(sample_suite, persist=False, quiet=True)
        assert result.total == 4 and result.failed == 1

    def test_log_handler_can_move_to_stderr(self):
        import logging
        import sys
        from ipandora.utils.log import log_to_stderr, logger

        _originals = [(h, h.stream) for h in logger.handlers
                      if isinstance(h, logging.StreamHandler)
                      and getattr(h, 'stream', None) is sys.stdout]
        assert _originals, 'expected a stdout console handler to exist'
        try:
            assert log_to_stderr() == len(_originals)
            assert all(h.stream is sys.stderr for h, _ in _originals)
        finally:
            for _handler, _stream in _originals:
                _handler.setStream(_stream)


class TestShortReason:
    class _Report:
        def __init__(self, text):
            self.longreprtext = text
            self.longrepr = text

    def test_extracts_the_assertion_and_dedents(self):
        text = ('def test_x():\n'
                '>       assert_all(check)\n'
                'E       AssertionError: Assertion failed (1/2 checks failed)\n'
                'E       \n'
                'E         [FAIL] status ok | status = 500\n')
        reason = short_reason(self._Report(text))
        assert reason.startswith('AssertionError: Assertion failed')
        assert '  [FAIL] status ok | status = 500' in reason
        # pytest's alignment padding is gone
        assert '\nE' not in reason

    def test_falls_back_to_the_last_line(self):
        assert short_reason(self._Report('some\ncollection problem')) == 'collection problem'

    def test_empty_report(self):
        assert short_reason(self._Report('')) == ''


class TestResultModel:
    def test_name_strips_the_path(self):
        assert CaseResult(nodeid='a/b.py::TestX::test_y', outcome='passed').name == 'test_y'

    def test_empty_run_headline(self):
        assert RunResult(run_id='r').headline() == 'no tests ran'

    def test_collect_error_makes_the_run_not_ok(self):
        result = RunResult(run_id='r', collect_error='boom')
        assert result.ok is False
        assert result.summary()['collect_error'] == 'boom'
        # nothing ran, so there is nothing to explain per-case
        assert 'failures' not in result.summary()


class TestEvidenceReachesTheResult:
    """
    The report can only show what the run carries out. Before this the runner
    kept one string per case, so every structured fact the assertion layer
    produced was thrown away and re-parsed from prose.
    """

    def test_checks_survive_the_run(self, evidence_suite):
        result = run(evidence_suite, persist=False, quiet=True)
        case = next(c for c in result.cases if 'test_documented' in c.nodeid)
        assert [c['name'] for c in case.checks] == ['状态正确', '余额实际增加']
        assert case.checks[0]['src'] == 'api'

    def test_a_declared_gap_arrives_as_a_gap(self, evidence_suite):
        result = run(evidence_suite, persist=False, quiet=True)
        case = next(c for c in result.cases if 'test_documented' in c.nodeid)
        assert case.checks[1]['kind'] == 'gap'
        assert case.outcome == 'passed', 'a gap must not fail the case'

    def test_checks_from_a_failing_case_survive(self, evidence_suite):
        result = run(evidence_suite, persist=False, quiet=True)
        case = next(c for c in result.cases if 'test_with_a_failure' in c.nodeid)
        assert case.outcome == 'failed'
        assert [(c['name'], c['ok']) for c in case.checks] == [
            ('状态正确', True), ('金额一致', False)]

    def test_dims_and_title_are_collected(self, evidence_suite):
        result = run(evidence_suite, persist=False, quiet=True)
        case = next(c for c in result.cases if 'test_documented' in c.nodeid)
        assert case.dims == {'kind': 'a', 'mode': 'x'}
        assert case.title == '这条用例有说明'

    def test_axes_are_read_once_per_module(self, evidence_suite):
        result = run(evidence_suite, persist=False, quiet=True)
        assert len(result.coverage) == 1, 'axes duplicated per test'

    def test_a_suite_that_declares_nothing_still_runs(self, sample_suite):
        result = run(sample_suite, persist=False, quiet=True)
        assert result.total == 4
        assert all(c.checks == [] and c.dims == {} for c in result.cases)

    def test_evidence_does_not_bleed_between_cases(self, evidence_suite):
        result = run(evidence_suite, persist=False, quiet=True)
        names = {c.nodeid: [k['name'] for k in c.checks] for c in result.cases}
        assert all(len(v) == 2 for v in names.values()), names

    def test_the_report_builds_from_it(self, evidence_suite):
        from ipandora.core.report import build, to_html
        report = build(run(evidence_suite, persist=False, quiet=True))
        assert report.check_totals == {'passed': 2, 'failed': 1, 'gap': 1}
        assert report.coverage_matrix[0]['filled'] == 2
        assert [g['name'] for g in report.gaps] == ['余额实际增加']
        assert '余额实际增加' in to_html(report)
