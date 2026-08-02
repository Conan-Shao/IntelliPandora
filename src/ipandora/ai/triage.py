# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : triage.py
@Time  : 2026-08-01

Optional LLM enrichment for failure triage.

This is the *only* place in the framework that calls a model, and it runs
after a test run has already finished and been classified. Cost therefore
scales with failures, not with how many tests you run: a green suite of ten
thousand cases makes zero calls. See docs/design/03-LLM接入边界.md.

It never decides a category -- the deterministic rules in core/triage do
that. All this adds is prose explaining what the failures have in common.
"""
from typing import List

from ipandora.ai.aifactory import AIProviderFactory
from ipandora.core.schedule.runtime import Runtime
from ipandora.utils.log import logger

# The assertion layer caps each value it puts into a Check, so a failure message
# is bounded per check -- but a test with many checks, or a failure that did not
# come from assert_all at all, still has no ceiling. This is the one that is
# billed, so it keeps its own.
#
# (That first clause was untrue when written: the assertion layer had no cap,
# and one real response produced a 195,000-character message. It does now.)
MAX_CHARS_PER_FAILURE = 600
MAX_FAILURES_IN_PROMPT = 10

SYSTEM_PROMPT = (
    'You are helping a test engineer triage a failed test run. '
    'You are given failures that have already been classified by deterministic '
    'rules. Do not re-classify them. '
    'In at most four sentences, say what these failures most likely have in '
    'common and what to check first. '
    'If the evidence does not support a single root cause, say so plainly '
    'rather than guessing.'
)


class BudgetExceeded(Exception):
    """The per-run call budget is spent."""


class _Budget:
    """
    Hard cap on model calls per run.

    Without one, a suite that starts failing in bulk turns into an unbounded
    bill at exactly the moment nobody is watching.
    """

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def spend(self):
        if self.used >= self.limit:
            raise BudgetExceeded(
                'AI triage budget exhausted ({} calls); raise ai.max_calls_per_run '
                'to allow more'.format(self.limit))
        self.used += 1


def build_prompt(report, result) -> str:
    _lines = ['Run: {}'.format(getattr(result, 'headline', lambda: '')() or 'unknown'),
              'Rule-based classification: {}'.format(report.headline()),
              '', 'Failures:']

    _findings = report.findings[:MAX_FAILURES_IN_PROMPT]
    _by_node = {_f.nodeid: _f for _f in report.findings}

    for _case in getattr(result, 'failures', [])[:MAX_FAILURES_IN_PROMPT]:
        _finding = _by_node.get(_case.nodeid)
        _lines.append('- {} [{}]'.format(
            _case.nodeid, _finding.category if _finding else 'unknown'))
        if _case.message:
            _lines.append('    {}'.format(
                _case.message[:MAX_CHARS_PER_FAILURE].replace('\n', '\n    ')))

    if len(report.findings) > MAX_FAILURES_IN_PROMPT:
        _lines.append('... and {} more'.format(
            len(report.findings) - MAX_FAILURES_IN_PROMPT))

    return '\n'.join(_lines)


def analyze(report, result) -> str:
    """
    Root-cause prose for a triaged run, or '' when unavailable.

    Returns '' rather than raising on every failure path -- unconfigured, no
    SDK installed, budget spent, provider down. A model being unreachable must
    not change whether a test run passed.
    """
    if not Runtime.Ai.enabled:
        return ''
    if not report.findings:
        return ''

    _budget = _Budget(Runtime.Ai.max_calls_per_run)
    try:
        _budget.spend()
        _provider = AIProviderFactory().default
        return _provider.chat(messages=[
            {'role': 'user',
             'content': '{}\n\n{}'.format(SYSTEM_PROMPT, build_prompt(report, result))},
        ]).strip()
    except BudgetExceeded as exc:
        logger.warning('%s', exc)
        return ''
    except Exception as exc:  # noqa: BLE001 - triage must never fail a run
        logger.warning('AI triage unavailable, continuing without it: %s', exc)
        return ''


def enrich(report, result) -> str:
    """Run the analysis and attach it to the report."""
    report.analysis = analyze(report, result)
    return report.analysis
