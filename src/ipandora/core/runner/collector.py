# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : collector.py
@Time  : 2026-08-01
"""
import textwrap
from typing import Dict, List

from ipandora.core.evidence import recorder
from ipandora.core.runner.result import CaseResult, ERROR, FAILED, PASSED, SKIPPED


def skip_reason(report) -> str:
    """
    The message from a skip.

    pytest reports a skip as the tuple (file, lineno, 'Skipped: <message>').
    The file and line point at whatever called skip() -- for require() that is
    always the same line inside the assertion collector, which tells a reader
    nothing. Only the message is worth keeping.
    """
    _raw = getattr(report, 'longrepr', None)
    _message = ''
    if isinstance(_raw, tuple) and len(_raw) == 3:
        _message = str(_raw[2])
    else:
        _message = str(_raw or '')
    return _message.split('Skipped: ', 1)[-1].strip()


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
        self.coverage = []  # type: List[Dict]
        self._coverage_seen = set()

    def _slot(self, nodeid: str) -> CaseResult:
        if nodeid not in self.cases:
            self.cases[nodeid] = CaseResult(nodeid=nodeid, outcome=PASSED)
            self._order.append(nodeid)
        return self.cases[nodeid]

    # -- evidence ----------------------------------------------------------

    def pytest_configure(self, config):
        config.addinivalue_line(
            'markers',
            'dims(**axes): place this case in the coverage matrix, '
            'e.g. @pytest.mark.dims(chain="56", pay="native")')

    def pytest_runtest_setup(self, item):
        """
        Open an evidence slot before the test body runs.

        Setup, not call: fixtures make requests too, and a fixture that fails
        is exactly when someone wants to see what it asked for.
        """
        recorder.begin(item.nodeid)
        self._read_declarations(item)

    def pytest_runtest_teardown(self, item):
        _evidence = recorder.end(item.nodeid)
        if _evidence is None:
            return
        _case = self._slot(item.nodeid)
        # extend rather than assign: a case that somehow files evidence twice
        # should accumulate it, and this collector is per-run so nothing older
        # can be here
        _case.checks.extend(_evidence.checks)
        _case.exchanges.extend(_evidence.exchanges)

    def _read_declarations(self, item):
        """
        Pull the two things a test can declare about itself: where it sits in
        the coverage matrix, and what it is for.
        """
        _case = self._slot(item.nodeid)

        _marker = item.get_closest_marker('dims')
        if _marker is not None:
            _case.dims = {str(_k): str(_v) for _k, _v in (_marker.kwargs or {}).items()}

        _doc = (getattr(item, 'function', None).__doc__
                if getattr(item, 'function', None) else None)
        if _doc:
            _case.title = _doc.strip().splitlines()[0].strip()

        # Axes are declared once per module, not per test: the whole point of
        # the matrix is the cells with no test in them, and a run can only know
        # those if the full value set is stated independently of what ran.
        _module = getattr(item, 'module', None)
        _axes = getattr(_module, 'COVERAGE', None)
        if _axes and id(_module) not in self._coverage_seen:
            self._coverage_seen.add(id(_module))
            self.coverage.extend(_axes)

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
            _case.message = skip_reason(report)

    def pytest_collectreport(self, report):
        if report.outcome == FAILED:
            self.collect_errors.append(
                getattr(report, 'longreprtext', '') or str(report.longrepr))

    def results(self) -> List[CaseResult]:
        return [self.cases[_n] for _n in self._order]
