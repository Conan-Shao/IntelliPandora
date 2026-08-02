# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : collector.py
@Time  : 2026-08-01
"""
from typing import Iterable, List

from ipandora.core.assertion.check import Check
from ipandora.utils.error import PreconditionNotMet


def _flatten(checks: Iterable) -> List[Check]:
    """Accept both `assert_all(a, b)` and `assert_all(*COMMON, [c, d])`."""
    _out = []
    for _item in checks:
        if _item is None:
            continue
        if isinstance(_item, Check):
            _out.append(_item)
        elif isinstance(_item, (list, tuple, set)):
            _out.extend(_flatten(_item))
        else:
            raise TypeError(
                'assert_all/require accept Check objects, got {!r}. '
                'A check function must return a Check, not a bool.'.format(type(_item).__name__))
    return _out


def _judged(checks: List[Check]) -> List[Check]:
    """The checks that actually judged something -- gaps did not."""
    return [_c for _c in checks if not _c.is_gap]


def _report(checks: List[Check], failures: List[Check], header: str) -> str:
    _judgements = _judged(checks)
    _lines = ['{} ({}/{} checks failed)'.format(
        header, len(failures), len(_judgements)), '']
    _lines.extend('  {}'.format(_c) for _c in failures)

    _passed = [_c for _c in _judgements if _c.ok]
    if _passed:
        _lines.append('')
        _lines.append('  passed: {}'.format(', '.join(_c.name for _c in _passed)))

    # Named here too, not only in the report: someone reading a red build in a
    # terminal should see that the case was never checking these to begin with.
    _gaps = [_c for _c in checks if _c.is_gap]
    if _gaps:
        _lines.append('  not covered: {}'.format(', '.join(_c.name for _c in _gaps)))
    return '\n'.join(_lines)


def _record(checks: List[Check]) -> None:
    """
    Hand the checks to the evidence recorder, if a run is collecting.

    Import is local and failure is swallowed inside the recorder: assertion is
    the one path that must not acquire a dependency on reporting.
    """
    try:
        from ipandora.core.evidence import add_checks
        add_checks(checks)
    except Exception:  # noqa: BLE001
        pass


def assert_all(*checks) -> List[Check]:
    """
    Evaluate every check and fail once, listing all failures.

    Every check has already been computed by the time this is called -- this
    only decides the verdict. That is the point: one run tells you everything
    that is wrong, not just the first thing.

    Raises AssertionError (not a framework exception) so pytest and Robot
    Framework both render it natively.
    """
    _checks = _flatten(checks)
    _record(_checks)
    _failures = [_c for _c in _judged(_checks) if not _c.ok]
    if _failures:
        raise AssertionError(_report(_checks, _failures, 'Assertion failed'))
    return _checks


def require(*checks) -> List[Check]:
    """
    Assert a *precondition*: unmet means the test could not run, not that the
    system is broken.

    Unmet preconditions skip rather than fail. Mixing the two is the single
    biggest source of noise in a long-running suite -- "the account had no
    balance" and "the code is wrong" must not look the same on a dashboard.

    Skips via pytest when available, otherwise raises PreconditionNotMet.
    """
    _checks = _flatten(checks)
    _record(_checks)
    _failures = [_c for _c in _judged(_checks) if not _c.ok]
    if not _failures:
        return _checks

    _message = _report(_checks, _failures, 'Precondition not met')
    try:
        import pytest
    except ImportError:
        raise PreconditionNotMet(_message)
    pytest.skip(_message)
