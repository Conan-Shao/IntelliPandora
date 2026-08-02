# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_ai_triage.py
@Time  : 2026-08-01
"""
import pytest

# See the note in test_ai_provider.py: the ai/ package is optional and
# deletable, so its own tests skip rather than break collection when it is
# absent. Module level, not conftest -- a conftest imports ipandora earlier
# than pytest's output capture is in place for the tests that follow.
pytest.importorskip('ipandora.ai', reason='optional ai/ package is absent')

import ipandora.ai  # noqa: E402
from ipandora.ai import triage as ai_triage
from ipandora.core.runner.result import CaseResult, RunResult
from ipandora.core.schedule.runtime import Runtime
from ipandora.core.triage import Category, has_analyzer, register_analyzer, triage

ASSERT_FAILURE = ("AssertionError: Assertion failed (1/1 checks failed)\n"
                  "\n  [FAIL] 请求成功 (2xx) (api) | status = 500")


@pytest.fixture(autouse=True)
def clean_state():
    register_analyzer(None)
    yield
    register_analyzer(None)
    Runtime.reset()


@pytest.fixture
def failing_run():
    return RunResult(run_id='r', cases=[
        CaseResult(nodeid='t.py::test_a', outcome='failed', message=ASSERT_FAILURE)])


class FakeProvider:
    def __init__(self, reply='one root cause', error=None):
        self.reply = reply
        self.error = error
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply


@pytest.fixture
def provider(monkeypatch):
    _fake = FakeProvider()
    monkeypatch.setattr(
        'ipandora.ai.aifactory.AIProviderFactory.default',
        property(lambda self: _fake))
    return _fake


class TestOffByDefault:
    """
    The cost model depends on this: a green run of ten thousand tests must
    make zero model calls. See docs/design/03-LLM接入边界.md.
    """

    def test_disabled_in_default_config(self):
        assert Runtime.Ai.enabled is False

    def test_enable_is_a_no_op_while_disabled(self):
        assert ipandora.ai.enable() is False
        assert has_analyzer() is False

    def test_analyze_makes_no_call_while_disabled(self, failing_run, provider):
        assert ai_triage.analyze(triage(failing_run), failing_run) == ''
        assert provider.calls == 0

    def test_importing_the_package_does_not_enable_it(self):
        import importlib
        importlib.reload(ipandora.ai)
        assert has_analyzer() is False

    def test_enable_registers_once_switched_on(self, provider):
        Runtime.Ai.enabled = True
        assert ipandora.ai.enable() is True
        assert has_analyzer() is True

    def test_force_overrides_the_config_flag(self):
        assert ipandora.ai.enable(force=True) is True
        assert has_analyzer() is True


class TestCostIsBoundedByFailures:
    def test_no_failures_means_no_call(self, provider):
        Runtime.Ai.enabled = True
        empty = RunResult(run_id='r', cases=[
            CaseResult(nodeid='t::a', outcome='passed')])
        assert ai_triage.analyze(triage(empty), empty) == ''
        assert provider.calls == 0

    def test_one_call_per_run_not_per_failure(self, provider):
        Runtime.Ai.enabled = True
        many = RunResult(run_id='r', cases=[
            CaseResult(nodeid='t::{}'.format(i), outcome='failed', message=ASSERT_FAILURE)
            for i in range(25)])
        ai_triage.analyze(triage(many), many)
        assert provider.calls == 1

    def test_budget_of_zero_blocks_the_call(self, failing_run, provider):
        Runtime.Ai.enabled = True
        Runtime.Ai.max_calls_per_run = 0
        assert ai_triage.analyze(triage(failing_run), failing_run) == ''
        assert provider.calls == 0

    def test_prompt_is_capped_regardless_of_failure_count(self, failing_run):
        many = RunResult(run_id='r', cases=[
            CaseResult(nodeid='t::{}'.format(i), outcome='failed',
                       message='x' * 5000)
            for i in range(50)])
        prompt = ai_triage.build_prompt(triage(many), many)
        assert len(prompt) < 50 * 5000
        assert 'and 40 more' in prompt


class TestFailOpen:
    """
    A model being unreachable must never change whether a run passed. It costs
    the analysis, nothing else.
    """

    def test_provider_error_yields_empty_not_an_exception(self, failing_run, monkeypatch):
        Runtime.Ai.enabled = True
        broken = FakeProvider(error=RuntimeError('provider down'))
        monkeypatch.setattr('ipandora.ai.aifactory.AIProviderFactory.default',
                            property(lambda self: broken))
        assert ai_triage.analyze(triage(failing_run), failing_run) == ''

    def test_missing_sdk_yields_empty(self, failing_run, monkeypatch):
        Runtime.Ai.enabled = True
        monkeypatch.setattr(
            'ipandora.ai.aifactory.AIProviderFactory.default',
            property(lambda self: (_ for _ in ()).throw(ImportError('no anthropic'))))
        assert ai_triage.analyze(triage(failing_run), failing_run) == ''

    def test_rule_based_verdict_survives_analyzer_failure(self, failing_run, monkeypatch):
        Runtime.Ai.enabled = True
        monkeypatch.setattr(
            'ipandora.ai.aifactory.AIProviderFactory.default',
            property(lambda self: (_ for _ in ()).throw(RuntimeError('down'))))
        report = triage(failing_run)
        report.analysis = ai_triage.analyze(report, failing_run)
        # the classification is untouched; only the prose is missing
        assert report.findings[0].category == Category.DEFECT
        assert report.analysis == ''


class TestEnrichment:
    def test_analysis_is_attached(self, failing_run, provider):
        Runtime.Ai.enabled = True
        report = triage(failing_run)
        ai_triage.enrich(report, failing_run)
        assert report.analysis == 'one root cause'
        assert report.to_dict()['analysis'] == 'one root cause'

    def test_prompt_carries_the_rule_classification(self, failing_run):
        report = triage(failing_run)
        prompt = ai_triage.build_prompt(report, failing_run)
        assert Category.DEFECT in prompt
        assert 'status = 500' in prompt

    def test_prompt_tells_the_model_not_to_reclassify(self):
        # categories are the rules' job; the model only adds prose
        assert 'Do not re-classify' in ai_triage.SYSTEM_PROMPT

    def test_disable_unregisters(self, provider):
        Runtime.Ai.enabled = True
        ipandora.ai.enable()
        ipandora.ai.disable()
        assert has_analyzer() is False
