# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : rules.py
@Time  : 2026-08-01

Deterministic failure classification.

Rules first, model second: this runs on every failure, costs nothing, is
reproducible, and covers the cases that have a clear signature. The optional
LLM pass (see ipandora.ai.triage) only ever adds prose on top -- it never
decides a category.
"""
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from ipandora.core.triage.category import (BLAMES_SYSTEM_UNDER_TEST, Category, Confidence,
                                           NEXT_STEP)

# Assertion sources, emitted by the assertion layer as "[FAIL] name (src) | expr"
CHECK_LINE = re.compile(r'\[FAIL\]\s*(?P<name>.*?)\s*\((?P<src>\w+)\)\s*\|\s*(?P<expr>.*)')

TRANSPORT_MARKERS = ('HttpTimeoutError', 'HttpConnectionError', 'TransportError',
                     'ConnectionError', 'ReadTimeout', 'ConnectTimeout',
                     'could not connect', 'timed out')

HARNESS_MARKERS = ('fixture', 'not found', 'ImportError', 'ModuleNotFoundError',
                   'AttributeError', 'TypeError', 'NameError')


@dataclass
class Finding:
    nodeid: str
    category: str
    confidence: str
    reason: str
    """Why this category -- the evidence, not a restatement of the label."""
    next_step: str = ''
    check_sources: List[str] = field(default_factory=list)
    """Which assertion dimensions failed (api/schema/derived/...)."""

    @property
    def blames_system_under_test(self) -> bool:
        return self.category in BLAMES_SYSTEM_UNDER_TEST

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def failed_check_sources(message: str) -> List[str]:
    """
    The `src` of every failed check in an assert_all message.

    This is the payoff from tagging checks with a source: if everything that
    failed is `schema`, the interface drifted; if it is `derived`, business
    logic is wrong. That distinction is free here because it was recorded at
    assertion time.
    """
    _seen = []
    for _match in CHECK_LINE.finditer(message or ''):
        _src = _match.group('src')
        if _src not in _seen:
            _seen.append(_src)
    return _seen


def classify(nodeid: str, outcome: str, message: str) -> Finding:
    """Classify one case. Pure function of its outcome and message."""
    _message = message or ''

    def _finding(category, confidence, reason, sources=None):
        return Finding(nodeid=nodeid, category=category, confidence=confidence,
                       reason=reason, next_step=NEXT_STEP.get(category, ''),
                       check_sources=sources or [])

    # Nothing reached the system under test.
    _transport = next((_m for _m in TRANSPORT_MARKERS if _m in _message), None)
    if _transport:
        return _finding(Category.ENVIRONMENT, Confidence.HIGH,
                        'transport failure ({}): no response was received, so nothing '
                        'about the system was actually tested'.format(_transport))

    # A skipped test is a precondition that was not met, by design -- see
    # require() in the assertion layer.
    if outcome == 'skipped':
        return _finding(Category.DATA, Confidence.HIGH,
                        'precondition not met, so the test did not run: {}'.format(
                            _message.strip().splitlines()[0] if _message.strip() else 'skipped'))

    # Setup or teardown blew up: the harness is broken, not the product.
    if outcome == 'error':
        _marker = next((_m for _m in HARNESS_MARKERS if _m in _message), '')
        return _finding(Category.HARNESS, Confidence.HIGH,
                        'the test errored outside its body{}; it never exercised the '
                        'system'.format(' ({})'.format(_marker) if _marker else ''))

    _sources = failed_check_sources(_message)
    if _sources:
        # Only schema checks failed -> the shape changed, not the value.
        if set(_sources) == {'schema'}:
            return _finding(Category.CONTRACT, Confidence.HIGH,
                            'every failed check was a schema check: the response no '
                            'longer matches its declared contract', _sources)
        return _finding(Category.DEFECT, Confidence.HIGH,
                        'assertions failed on {}: the system returned a value the test '
                        'says is wrong'.format('/'.join(_sources)), _sources)

    if 'AssertionError' in _message:
        return _finding(Category.DEFECT, Confidence.MEDIUM,
                        'a plain assertion failed; consider using assert_all so the '
                        'failure carries its own evidence')

    return _finding(Category.UNKNOWN, Confidence.LOW,
                    'no recognised signature in the failure message')


@dataclass
class TriageReport:
    findings: List[Finding] = field(default_factory=list)
    analysis: str = ''
    """Optional natural-language root cause. Empty unless AI triage ran."""

    @property
    def by_category(self) -> Dict[str, int]:
        _counts = {}
        for _f in self.findings:
            _counts[_f.category] = _counts.get(_f.category, 0) + 1
        return _counts

    @property
    def product_failures(self) -> List[Finding]:
        """Failures that implicate the system under test rather than us."""
        return [_f for _f in self.findings if _f.blames_system_under_test]

    def headline(self) -> str:
        if not self.findings:
            return 'nothing to triage'
        _parts = ['{} {}'.format(_n, _c) for _c, _n in sorted(self.by_category.items())]
        return ', '.join(_parts)

    def to_dict(self) -> Dict[str, Any]:
        _out = {
            'headline': self.headline(),
            'by_category': self.by_category,
            'blames_system_under_test': len(self.product_failures),
            'findings': [_f.to_dict() for _f in self.findings],
        }
        if self.analysis:
            _out['analysis'] = self.analysis
        return _out


def triage(result, include_skipped: bool = False) -> TriageReport:
    """
    Classify every failure in a RunResult.

    Deterministic and offline. Accepts anything exposing `failures` with
    nodeid/outcome/message, so it does not bind the triage rules to the runner.

    :param include_skipped: also classify skipped cases. Off by default -- a
        skip is a met design goal, not a failure -- but a suite that is mostly
        skipping is worth looking at, and this surfaces that.
    """
    _cases = list(getattr(result, 'failures', []))
    if include_skipped:
        _cases += [_c for _c in getattr(result, 'cases', [])
                   if _c.outcome == 'skipped']
    return TriageReport(findings=[
        classify(_c.nodeid, _c.outcome, _c.message) for _c in _cases])
