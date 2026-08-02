# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : collector.py
@Time  : 2026-08-01
"""
import textwrap
from typing import Dict, List

from ipandora.core.runner.result import CaseResult, ERROR, FAILED, PASSED, SKIPPED


def short_reason(report) -> str:
    """
    A one-or-few-line reason from a pytest report.

    pytest's longreprtext is the whole traceback. What a reader (or an agent)
    needs first is the assertion message, which sits at the end -- and for
    assert_all that message is already structured, listing every failed check.
    """
    _text = getattr(report, 'longreprtext', '') or str(getattr(report, 'longrepr', ''))
    if not _text:
        return ''

    _lines = [_l for _l in _text.splitlines() if _l.strip()]
    if not _lines:
        return ''

    # pytest prefixes the assertion body with 'E   ' and indents it to line up
    # under the source. That indentation is noise once the source is gone.
    _error_lines = [_l[1:] for _l in _lines if _l.startswith('E ')]
    if not _error_lines:
        return _lines[-1].strip()

    return textwrap.dedent('\n'.join(_error_lines)).strip()


class ResultCollector:
    """
    A pytest plugin that turns reports into CaseResult objects.

    This is why the runner can be called as a library: pytest hands us
    structured reports, so nothing has to shell out and scrape stdout.
    """

    def __init__(self):
        self.cases = {}  # type: Dict[str, CaseResult]
        self._order = []  # type: List[str]
        self.collect_errors = []  # type: List[str]

    def _slot(self, nodeid: str) -> CaseResult:
        if nodeid not in self.cases:
            self.cases[nodeid] = CaseResult(nodeid=nodeid, outcome=PASSED)
            self._order.append(nodeid)
        return self.cases[nodeid]

    def pytest_runtest_logreport(self, report):
        _case = self._slot(report.nodeid)
        _case.duration += getattr(report, 'duration', 0.0) or 0.0

        if report.when == 'call':
            if report.outcome == FAILED:
                _case.outcome = FAILED
            elif report.outcome == SKIPPED:
                _case.outcome = SKIPPED
            # a passed call leaves the default, so a later teardown error can
            # still mark the case
        elif report.outcome == FAILED:
            # setup or teardown blew up: that is an error, not a test failure
            _case.outcome = ERROR
        elif report.when == 'setup' and report.outcome == SKIPPED:
            _case.outcome = SKIPPED

        if report.outcome == FAILED or (report.when != 'call' and report.outcome == FAILED):
            _case.detail = getattr(report, 'longreprtext', '') or _case.detail
            _case.message = short_reason(report) or _case.message
        elif report.outcome == SKIPPED and not _case.message:
            _case.message = short_reason(report)

    def pytest_collectreport(self, report):
        if report.outcome == FAILED:
            self.collect_errors.append(
                getattr(report, 'longreprtext', '') or str(report.longrepr))

    def results(self) -> List[CaseResult]:
        return [self.cases[_n] for _n in self._order]
