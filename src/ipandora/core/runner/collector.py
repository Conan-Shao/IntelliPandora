# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : collector.py
@Time  : 2026-08-01
"""
import ast
import textwrap
from typing import Dict, List

from ipandora.core.assertion.check import Check, Source
from ipandora.core.evidence import recorder
from ipandora.core.runner.result import CaseResult, ERROR, FAILED, PASSED, SKIPPED

# Items whose checks are not `assert` statements: unittest's assertEqual and
# doctest's expected output. The runner cannot see their judgements, so it
# must not call them unverified.
OPAQUE_ITEMS = ('TestCaseFunction', 'DoctestItem', 'DoctestTextfile')


def _names(expected) -> str:
    if isinstance(expected, tuple):
        return ' | '.join(getattr(_e, '__name__', repr(_e)) for _e in expected)
    return getattr(expected, '__name__', repr(expected))


def _constant(source: str) -> bool:
    """
    Whether an assert's expression is a literal -- `assert True`, `assert 1`.

    Such an assert cannot fail, so it judges nothing. Recording it would let
    `assert True` turn an empty test into a "verified" one, which is precisely
    the shortcut the unverified status exists to expose.
    """
    try:
        ast.literal_eval(source.strip())
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return False
    return True


def _record_judgement(claim: str, ok: bool = True, expr: str = '') -> None:
    recorder.add_checks([Check(name=claim, ok=ok, expr=expr or claim,
                               src=Source.ASSERT, claim=claim)])


class _Recording:
    """
    Wraps the context manager pytest.raises / pytest.warns returns, and
    records the judgement once it has held.

    Recorded on a clean exit only. When the expected exception never comes,
    pytest's own __exit__ raises and the case fails -- there is no passed
    judgement to record. When a different exception escapes, __exit__ returns
    False and nothing is recorded either.
    """

    def __init__(self, inner, claim: str):
        self._inner = inner
        self._claim = claim

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, *exc):
        _handled = self._inner.__exit__(*exc)
        if _handled or exc[0] is None:
            _record_judgement(self._claim)
        return _handled

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _recording(original, verb: str):
    """
    A drop-in for pytest.raises / pytest.warns that records a judgement.

    `with pytest.raises(ValueError): f()` checks something real, but it is not
    an `assert` statement, so the assertion-pass hook never sees it. Without
    this, every test written that way would read as unverified.
    """
    def _wrapped(expected, *args, **kwargs):
        _claim = '{} {}'.format(verb, _names(expected))
        if kwargs.get('match'):
            _claim += ' match {!r}'.format(kwargs['match'])
        if args and callable(args[0]):
            # function form: pytest.raises(E, func, *args) -- returns only on success
            _info = original(expected, *args, **kwargs)
            _record_judgement(_claim)
            return _info
        return _Recording(original(expected, *args, **kwargs), _claim)
    _wrapped.__wrapped__ = original
    _wrapped.__doc__ = original.__doc__
    return _wrapped


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
        self.deselected = []  # type: List[str]
        self.rootdir = ''

    def _slot(self, nodeid: str) -> CaseResult:
        if nodeid not in self.cases:
            self.cases[nodeid] = CaseResult(nodeid=nodeid, outcome=PASSED)
            self._order.append(nodeid)
        return self.cases[nodeid]

    # -- evidence ----------------------------------------------------------

    def pytest_configure(self, config):
        # Patched for the duration of the run, restored in pytest_unconfigure.
        # A module that did `from pytest import raises` during this run keeps
        # the wrapper afterwards, which is harmless: outside a case it records
        # nothing and behaves exactly like the original.
        import pytest
        self.rootdir = str(getattr(config, 'rootpath', '') or '')
        self._patched = {'raises': pytest.raises, 'warns': pytest.warns}
        pytest.raises = _recording(self._patched['raises'], 'raises')
        pytest.warns = _recording(self._patched['warns'], 'warns')
        config.addinivalue_line(
            'markers',
            'dims(**axes): place this case in the coverage matrix, '
            'e.g. @pytest.mark.dims(role="admin", channel="web")')
        config.addinivalue_line(
            'markers',
            'flaky(reason): this case is known-unstable. The reason is '
            'required -- a bare marker is how a failure gets parked forever. '
            'Run with --exclude-flaky to keep these out of a gate.')

    def pytest_unconfigure(self, config):
        import pytest
        for _name, _original in getattr(self, '_patched', {}).items():
            setattr(pytest, _name, _original)
        self._patched = {}

    # -- judgements pytest does not hand over by itself ---------------------

    def pytest_assertion_pass(self, item, lineno, orig, expl):
        """
        A plain `assert` that held.

        pytest only calls this with enable_assertion_pass_hook, which run()
        sets. `orig` is the source text -- `r['fee'] <= 100` -- and is what
        the inventory compares; `expl` carries the values it saw.
        """
        if _constant(orig):
            return
        _expr = (expl or '').splitlines()[0] if expl else orig
        _record_judgement('assert {}'.format(orig), ok=True, expr=_expr)

    def pytest_runtest_makereport(self, item, call):
        """
        A plain `assert` that failed. The pass hook only sees successes, so
        without this a case failing on a bare assert would show no failed
        judgement at all. assert_all records its own failures first, so a
        case that already has one is left alone.
        """
        _excinfo = getattr(call, 'excinfo', None)
        if call.when != 'call' or _excinfo is None \
                or not _excinfo.errisinstance(AssertionError):
            return None
        if any(not _c.get('ok') for _c in recorder.current_checks()):
            return None
        _lines = [_l for _l in str(_excinfo.value).splitlines() if _l.strip()]
        _expr = ' / '.join(_lines[:2]) or 'AssertionError'
        _record_judgement('assert (failed)', ok=False, expr=_expr)
        return None

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
        _case.judgeable = type(item).__name__ not in OPAQUE_ITEMS

        _marker = item.get_closest_marker('dims')
        if _marker is not None:
            _case.dims = {str(_k): str(_v) for _k, _v in (_marker.kwargs or {}).items()}

        _flaky = item.get_closest_marker('flaky')
        if _flaky is not None:
            # A reason is the whole value of the marker. Without one this is
            # just a quieter way of ignoring a failing test.
            _case.flaky = str(
                (_flaky.kwargs or {}).get('reason')
                or (_flaky.args[0] if _flaky.args else '')
                or '未说明原因')

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

    def pytest_deselected(self, items):
        """
        Remember what a `-m` expression removed.

        Without this, `--exclude-flaky` makes the excluded cases vanish from
        the run entirely -- and a flaky marker nobody is reminded of is a
        failure that has been parked. They are deselected, not forgotten.
        """
        self.deselected.extend(getattr(_i, 'nodeid', str(_i)) for _i in items or ())

    def pytest_collectreport(self, report):
        if report.outcome == FAILED:
            self.collect_errors.append(
                getattr(report, 'longreprtext', '') or str(report.longrepr))

    def results(self) -> List[CaseResult]:
        return [self.cases[_n] for _n in self._order]
