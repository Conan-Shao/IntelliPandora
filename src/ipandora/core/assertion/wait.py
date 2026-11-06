# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : wait.py
@Time  : 2026-11-05

Judging something that becomes true later.

A write to one node is read back from another; an order moves from PENDING
to PAID after a queue consumer runs; a cache is invalidated a moment after the
database. Tests of such systems wait, and the usual way to wait is
`time.sleep(3)` -- which is either too short on a slow day (a flaky failure)
or too long every day (a slow suite), and says nothing when it goes wrong.

    assert_all(
        status_ok(OrderApi().pay(7)),
        eventually(lambda: field(OrderApi().get(7), 'data.status') == 'PAID', within=10),
    )

eventually() re-runs a probe until its checks hold or the time is up, and
returns one Check -- a value, like every other judgement -- so it goes into
assert_all with the rest. The evidence says how long it took and how many
reads it needed when it held, and what the reads kept seeing when it did not:
"10 s, 21 reads, saw 'CREATED' -> 'PENDING'" tells a stuck consumer apart from
a slow one, which a bare timeout cannot.

`within` is part of the claim, so the judgement inventory sees it: raising it
from 10 s to 60 s is a changed judgement, gated by --fail-on-weakened like
any other. Waiting longer is how a latency regression gets hidden.
"""
import time
from typing import Callable, List, Optional

from ipandora.core.assertion.check import Check, Source, brief
from ipandora.core.assertion.collector import _flatten

MAX_SEEN = 6
"""How many distinct observations the evidence keeps: the first ones and the last."""

MAX_ERROR_CHARS = 160
"""How much of an exception raised by a read the evidence keeps."""

_clock = time.monotonic
_sleep = time.sleep


def _skip_types() -> tuple:
    """
    What require() raises when a precondition is unmet: pytest's skip outcome,
    or PreconditionNotMet without pytest.
    """
    from ipandora.utils.error import PreconditionNotMet
    try:
        import pytest
        return (PreconditionNotMet, pytest.skip.Exception)
    except ImportError:
        return (PreconditionNotMet,)


def _read(probe: Callable):
    # judgements made inside the probe are not the case's: see checks_withheld
    try:
        from ipandora.core.evidence import recorder
    except ImportError:  # pragma: no cover -- evidence is part of core
        return probe()
    with recorder.checks_withheld():
        return probe()


def _attempt(probe: Callable) -> List[Check]:
    """
    One read. A probe that raises -- a node not answering yet, an assert_all
    inside the probe -- is a read that did not hold, not the end of waiting:
    during a failover that is exactly what the first reads look like.

    So is a require() inside the probe. Its skip is a BaseException and used
    to escape the loop: the first read before the data had arrived skipped
    the whole case, which is the one thing the wait was there to prevent.
    """
    try:
        _result = _read(probe)
    except _skip_types() as exc:
        _text = str(getattr(exc, 'msg', '') or exc).strip()
        return [Check(name='probe', ok=False,
                      expr='前置条件不满足：' + (_text.splitlines()[0] if _text else ''))]
    except AssertionError as exc:
        _first = str(exc).strip().splitlines()[0] if str(exc).strip() else 'AssertionError'
        return [Check(name='probe', ok=False, expr=_first)]
    except Exception as exc:  # noqa: BLE001 -- any error is an observation here
        _text = str(exc)
        return [Check(name='probe', ok=False, expr='{}: {}'.format(
            type(exc).__name__, _text if len(_text) <= MAX_ERROR_CHARS else brief(_text, MAX_ERROR_CHARS)))]
    # A probe returning a bool, or a bare field(), is a bug in the test, not a
    # read that failed: say so at once instead of waiting out the deadline.
    _checks = [_c for _c in _flatten([_result]) if not _c.is_gap]
    if not _checks:
        raise TypeError('eventually(): the probe returned no Check to judge')
    return _checks


def _observed(checks: List[Check]) -> str:
    _bad = [_c for _c in checks if not _c.ok] or checks
    return '; '.join(_c.expr or _c.name for _c in _bad)


def _seconds(value: float) -> str:
    return '{:g} s'.format(round(value, 3))


def eventually(probe: Callable, within: float, every: float = 0.5,
               name: Optional[str] = None) -> Check:
    """
    Re-run `probe` until every Check it returns holds, for at most `within` seconds.

    :param probe:  a callable returning a Check or a list of Checks -- typically
                   a lambda around a request and a field() comparison. It is
                   called afresh each time, so the request is re-sent.
    :param within: seconds to wait, measured from the first read. At least one
                   read is always made; the last one starts no later than the
                   deadline (a read that is slow to answer can end after it, and
                   the evidence reports the real elapsed time).
    :param every:  seconds between reads.
    :param name:   what the report calls this judgement. Default: the probe's
                   own check names.

    Returns a Check that holds if some read held. Pass it to assert_all.
    """
    if within < 0 or every <= 0:
        raise ValueError('eventually(): within must be >= 0 and every > 0')

    _start = _clock()
    _deadline = _start + within
    _reads = 0
    _seen = []
    _checks = []
    while True:
        _checks = _attempt(probe)
        _reads += 1
        _now = _clock()
        if all(_c.ok for _c in _checks):
            break
        _what = _observed(_checks)
        if not _seen or _seen[-1] != _what:
            _seen.append(_what)
        if _now >= _deadline:
            break
        _sleep(min(every, max(_deadline - _now, 0.0)))

    _elapsed = _clock() - _start
    _held = all(_c.ok for _c in _checks)
    _inner = [_c for _c in _checks if _c.name != 'probe']
    _label = name or ', '.join(_c.name for _c in _inner) or 'probe'
    _claim = '{} (within {})'.format(
        ' and '.join(sorted(_c.subject for _c in _inner)) or 'probe', _seconds(within))
    _src = _inner[0].src if _inner else Source.DERIVED

    if _held:
        _expr = '第 {} 次读到成立，用时 {}（上限 {}）'.format(
            _reads, _seconds(_elapsed), _seconds(within))
        if _seen:
            _expr += '；之前读到：{}'.format(_trail(_seen))
    else:
        _expr = '{} 内读了 {} 次都不成立；读到的依次是：{}'.format(
            _seconds(within), _reads, _trail(_seen))
    return Check(name='最终成立：{}'.format(_label), ok=_held, expr=_expr, src=_src,
                 claim='eventually {}'.format(_claim))


def _trail(seen: List[str]) -> str:
    """The distinct observations in order, the middle elided when there are many."""
    if len(seen) <= MAX_SEEN:
        return ' → '.join(seen)
    _half = MAX_SEEN // 2
    return ' → '.join(seen[:_half] + ['…（另有 {} 种）'.format(len(seen) - MAX_SEEN)]
                      + seen[-_half:])
