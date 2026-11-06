# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : collector.py
@Time  : 2026-08-01
"""
import os
import textwrap
from typing import Dict, List

import pytest

from ipandora.core.runner import plugin
from ipandora.core.runner.result import CaseResult, ERROR, FAILED, PASSED, SKIPPED

# Kept importable from here: they moved to plugin.py, which is where a case
# actually runs.
OPAQUE_ITEMS = plugin.OPAQUE_ITEMS

ARTIFACT_PREFIX = 'playwright_'
"""pytest-playwright's user_properties keys: playwright_screenshot, _trace, _video."""


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
    The main-process half of the runner: turns reports into CaseResult objects.

    This is why the runner can be called as a library: pytest hands us
    structured reports, so nothing has to shell out and scrape stdout.

    It reads reports and nothing else. What a case judged, requested and
    declared is recorded where the case runs -- plugin.py, in every xdist
    worker -- and arrives here inside the teardown report. Reading the case
    directly would work serially and see nothing in parallel, which is the
    bug this split exists to remove.
    """

    def __init__(self):
        self.cases = {}  # type: Dict[str, CaseResult]
        self._order = []  # type: List[str]
        self._index = {}  # type: Dict[str, int]
        self.collect_errors = []  # type: List[str]
        self._coverage = {}  # type: Dict[str, tuple]
        self.deselected = []  # type: List[str]
        self._called = set()
        self.narrowed = False
        """`-k` or `-m` left cases out: a case missing from this run is not deleted."""
        self.rootdir = ''

    def _slot(self, nodeid: str) -> CaseResult:
        if nodeid not in self.cases:
            self.cases[nodeid] = CaseResult(nodeid=nodeid, outcome=PASSED)
            self._order.append(nodeid)
        return self.cases[nodeid]

    def pytest_configure(self, config):
        self.rootdir = str(getattr(config, 'rootpath', '') or '')
        # xdist runs collection, and so deselection, in the workers and does
        # not forward pytest_deselected. Each worker reports what it removed
        # when it shuts down; the hook for that only exists when xdist does,
        # so the implementation is marked optional. (Testing for the hook with
        # hasattr(config.hook, ...) stopped working in pytest 9.2, which
        # answers yes for any name: without xdist installed, every run then
        # died with "unknown hook 'pytest_testnodedown'".)
        config.pluginmanager.register(_WorkerOutput(self), 'ipandora-worker-output')

    # -- what the case itself sent --------------------------------------------

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_logreport(self, report):
        _case = self._slot(report.nodeid)
        self._take_evidence(_case, report)
        _case.duration += getattr(report, 'duration', 0.0) or 0.0

        if report.when == 'call':
            self._called.add(report.nodeid)
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

        if report.outcome == FAILED:
            _case.detail = getattr(report, 'longreprtext', '') or _case.detail
            _case.message = short_reason(report) or _case.message
        elif report.outcome == SKIPPED and not _case.message:
            _case.message = skip_reason(report)

    def _take_evidence(self, case: CaseResult, report):
        """
        Move the plugin's entry out of the report into the case.

        Out, not just read: tryfirst puts this ahead of pytest's own junitxml,
        which writes every user_properties entry as an XML property -- a
        user's `--junitxml` would otherwise carry every request body of the
        run. Their own record_property entries are left alone.
        """
        _props = getattr(report, 'user_properties', None) or []
        # pytest-playwright's screenshots and traces arrive the same way, on
        # the teardown report, relative to the directory pytest started in
        for _k, _v in _props:
            if isinstance(_k, str) and _k.startswith(ARTIFACT_PREFIX):
                _entry = {'kind': _k[len(ARTIFACT_PREFIX):], 'path': os.path.abspath(str(_v))}
                if _entry not in case.artifacts:
                    case.artifacts.append(_entry)
        _ours = [_v for _k, _v in _props if _k == plugin.KEY]
        if not _ours:
            return
        report.user_properties = [(_k, _v) for _k, _v in _props if _k != plugin.KEY]
        for _payload in _ours:
            # extend rather than assign: a case that somehow files evidence
            # twice should accumulate it, and this collector is per-run so
            # nothing older can be here
            case.checks.extend(_payload.get('checks') or [])
            case.exchanges.extend(_payload.get('exchanges') or [])
            case.locators.update(_payload.get('locators') or {})
            case.locator_failures.extend(_payload.get('locator_failures') or [])
            case.faults.extend(_payload.get('faults') or [])
            if _payload.get('trace_id'):
                case.trace_id = _payload['trace_id']
            for _artifact in _payload.get('artifacts') or []:
                if _artifact not in case.artifacts:
                    case.artifacts.append(_artifact)
            case.judgeable = bool(_payload.get('judgeable', case.judgeable))
            if 'dims' in _payload:
                case.dims = dict(_payload['dims'])
            if 'flaky' in _payload:
                case.flaky = _payload['flaky']
            if 'title' in _payload:
                case.title = _payload['title']
            if 'index' in _payload:
                self._index[case.nodeid] = _payload['index']
            _coverage = _payload.get('coverage')
            if _coverage:
                # one entry per module, placed at the first of its cases in
                # collection order -- not at whichever worker reported first
                _module = _coverage.get('module')
                _at = _payload.get('index', len(self._index) + len(self._coverage) + 10 ** 9)
                if _module not in self._coverage or _at < self._coverage[_module][0]:
                    self._coverage[_module] = (_at, list(_coverage.get('axes') or []))

    # -- what the run as a whole reports --------------------------------------

    def pytest_deselected(self, items):
        """
        Remember what --exclude-flaky removed.

        Without this the excluded cases vanish from the run entirely -- and a
        flaky marker nobody is reminded of is a failure that has been parked.
        They are deselected, not forgotten.

        Only those: what `-k` or the user's own `-m` leaves out is outside the
        run, not excluded from it (plugin.pytest_collection_modifyitems).
        """
        _items = list(items or ())
        self.add_deselected(_i.nodeid for _i in _items if plugin.excluded(_i))
        if any(not plugin.excluded(_i) for _i in _items):
            self.narrowed = True

    def add_deselected(self, nodeids):
        for _nodeid in nodeids:
            if _nodeid not in self.deselected:
                self.deselected.append(_nodeid)

    def pytest_collectreport(self, report):
        if report.outcome == FAILED:
            _text = getattr(report, 'longreprtext', '') or str(report.longrepr)
            # every xdist worker collects the whole suite and may report the
            # same broken module
            if _text not in self.collect_errors:
                self.collect_errors.append(_text)

    @property
    def coverage(self) -> List[Dict]:
        """Each module's COVERAGE axes, in collection order."""
        return [_axis for _at, _axes in sorted(self._coverage.values(), key=lambda v: v[0])
                for _axis in _axes]

    def results(self) -> List[CaseResult]:
        """
        In collection order, whatever order they finished in.

        Serially the two are the same. In parallel, arrival order depends on
        which worker was faster, and the report, the JSON and the judgement
        inventory would differ between two runs of the same suite for no
        reason. A case with no index -- its worker died before it could send
        one -- goes last, in arrival order.
        """
        _arrival = {_n: _i for _i, _n in enumerate(self._order)}
        _late = len(_arrival) + max(self._index.values(), default=0) + 1
        for _nodeid, _case in self.cases.items():
            if _case.outcome == PASSED and _nodeid not in self._called:
                # Setup passed and then nothing: the process died, or the run
                # was interrupted, before the test body reported. The default
                # outcome is PASSED so that a later teardown error can still
                # mark a passed case; left alone here, a case that never ran
                # would count as a pass.
                _case.outcome = ERROR
                _case.message = _case.message or '没有收到用例执行结果：进程在用例执行中退出，或运行被中断'
        return [self.cases[_n] for _n in sorted(
            self._order, key=lambda n: (self._index.get(n, _late + _arrival[n])))]


class _WorkerOutput:
    """What xdist workers report on shutdown. Its hook exists only with xdist."""

    def __init__(self, collector: ResultCollector):
        self._collector = collector

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error):
        _output = getattr(node, 'workeroutput', None) or {}
        self._collector.add_deselected(_output.get(plugin.DESELECTED_KEY) or ())
        if _output.get(plugin.NARROWED_KEY):
            self._collector.narrowed = True
