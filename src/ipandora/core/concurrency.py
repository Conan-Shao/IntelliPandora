# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : concurrency.py
@Time  : 2026-11-05

Fire N operations at the same moment from inside one test, and judge what the
product did: charged exactly once, did not oversell, honoured the idempotency
key.

    from ipandora.core.concurrency import concurrently

    results = concurrently(lambda: OrderApi().pay(order_id, key='idem-1'), n=20)
    codes = [status_code(r.value) for r in results]
    assert_all(
        results.overlap_check(),                          # it really was concurrent
        that(codes, '各请求状态').each().is_in([200, 409]),
        that(codes.count(200), '成功扣款次数') == 1,         # exactly once
    )

This is about correctness under concurrency, not load: no requests-per-second
target, no latency percentiles. That is what Locust and k6 are for.

Threads, not asyncio: test code and the HTTP layer are synchronous
(requests), and asyncio would mean rewriting the tests.

Three things a plain thread gets wrong, each found in this code base and each
handled here:

- **Login state.** SessionManager keeps one requests.Session per thread. A new
  thread got a brand-new session with no cookies and no headers, so a test that
  logged in first sent all its concurrent requests anonymously -- and a 401 for
  every one of them looks a lot like "only one succeeded". Each thread gets a
  copy of the caller's session: headers, cookies, auth, TLS and proxy settings.
  A copy, not the same object, because requests does not promise a Session is
  thread-safe. Cookies set by responses during the burst stay in that thread.
- **Evidence.** The recorder is per-thread, and a new thread has no case, so
  every concurrent request vanished from the report. Each thread records into
  the case that started it. So do steps (Runtime.Case).
- **A start that did not happen.** If one thread fails while getting ready,
  the others must not run anyway: a burst of 19 that the test believes is 20,
  or 20 that trickle out one by one, would be judged as if it were the real
  thing. The start is a barrier; a failure before it aborts the whole burst
  with NotConcurrent, and nothing is sent.

Even with a barrier, threads wake a little apart, and an operation that takes
less time than that skew finishes before the last one starts. Whether every
operation was in flight at once is measured, not assumed:
`results.overlapped`, and `results.overlap_check()` to make it a judgement.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Union

from ipandora.core.assertion.check import Check
from ipandora.core.evidence import recorder
from ipandora.core.evidence.recorder import CaseEvidence
from ipandora.core.schedule.runtime import Runtime
from ipandora.core.schedule.session import SessionManager

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0
"""Seconds allowed for all threads to get ready, and again for all to finish."""

SOURCE = 'concurrency'
"""Check.src of overlap_check(): it judges the test's own setup, not the product."""


class NotConcurrent(RuntimeError):
    """The burst never started, so nothing about concurrency was tested."""


@dataclass
class Outcome:
    """What one of the concurrent operations did."""
    index: int
    value: Any = None
    error: Optional[BaseException] = None
    """The exception it raised, if any. Never re-raised: it is for judging."""
    start: float = 0.0
    """Seconds after the first operation of the burst started."""
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def end(self) -> float:
        return self.start + self.duration

    def __repr__(self):
        _what = 'error={!r}'.format(self.error) if self.error is not None \
            else 'value={!r}'.format(self.value)
        return 'Outcome(#{}, {}, start=+{:.1f}ms, {:.1f}ms)'.format(
            self.index, _what, self.start * 1000, self.duration * 1000)


class Results(list):
    """The outcomes of one burst, in the order the operations were given."""

    @property
    def values(self) -> List[Any]:
        return [_o.value for _o in self]

    @property
    def errors(self) -> List[Outcome]:
        return [_o for _o in self if not _o.ok]

    @property
    def start_skew(self) -> float:
        """Seconds between the first and the last operation starting."""
        return max(_o.start for _o in self) - min(_o.start for _o in self) if self else 0.0

    @property
    def overlapped(self) -> bool:
        """
        Whether every operation was in flight at the same moment: the last
        one started before the first one finished. False means the burst was,
        at least in part, a sequence -- and a race it was meant to provoke may
        simply not have had the chance to happen.
        """
        if len(self) < 2:
            return False
        return max(_o.start for _o in self) < min(_o.end for _o in self)

    @property
    def warning(self) -> str:
        if self.overlapped or not self:
            return ''
        return ('并发没有完全发生：最后一个操作在 +{:.1f}ms 才开始，而最早的一个在 +{:.1f}ms '
                '已经结束。操作太快或起跑偏差太大时会这样，这次的结论不能说明并发下的行为'
                ).format(max(_o.start for _o in self) * 1000,
                         min(_o.end for _o in self) * 1000)

    def overlap_check(self) -> Check:
        """
        The burst's own validity as a judgement, for assert_all.

        A concurrency test that ran sequentially passes vacuously: one request
        at a time never double-charges. Put this first among the checks and
        such a run fails instead of reporting a guarantee it never tested.
        """
        _claim = 'concurrently: {} operations in flight together'.format(len(self))
        _expr = ('starts within {:.1f}ms; last start +{:.1f}ms, first end +{:.1f}ms'.format(
            self.start_skew * 1000, max((_o.start for _o in self), default=0) * 1000,
            min((_o.end for _o in self), default=0) * 1000))
        return Check(name='{} 个操作同时进行'.format(len(self)), ok=self.overlapped,
                     expr=_expr if self.overlapped else self.warning + ' | ' + _expr,
                     src=SOURCE, claim=_claim)


def concurrently(operation: Union[Callable[[], Any], Sequence[Callable[[], Any]]],
                 n: Optional[int] = None, timeout: float = DEFAULT_TIMEOUT) -> Results:
    """
    Run operations at the same moment and return what each one did.

    :param operation: a callable to run `n` times, or a list of different
                      callables to run once each -- `[pay, refund]` to race
                      two things against each other.
    :param n:         how many copies of `operation`; ignored for a list.
    :param timeout:   seconds for every thread to get ready, and separately
                      for every operation to finish. An operation still
                      running after that is reported as a TimeoutError; its
                      thread cannot be stopped and is left to finish alone.
    :raises NotConcurrent: a thread failed, or was too slow, before the start.
                      Nothing was run.

    Exceptions raised by the operations are not re-raised. Each is on its
    Outcome, so the test judges them like any other result -- under
    concurrency an error is often the expected answer for all but one.
    """
    _calls = _operations(operation, n)
    _session = SessionManager.getSession()
    _evidence = recorder.current()
    _case_state = Runtime.Case.share()
    _barrier = threading.Barrier(len(_calls))
    # One deadline for the whole start. A per-wait timeout restarts with each
    # thread that arrives, so threads that were all equally slow still started
    # -- late, and as if nothing had happened.
    _ready_by = time.monotonic() + timeout
    _outcomes = [None] * len(_calls)  # type: List[Optional[Outcome]]
    _starts = [None] * len(_calls)  # type: List[Optional[float]]
    _not_ready = {}
    # Each thread records into its own evidence, merged into the case's once
    # the thread has finished. Binding them straight to the case's evidence let
    # a timed-out thread -- which cannot be stopped -- keep adding requests to
    # the case after concurrently() returned, or to a case that had ended. And
    # merged in operation order, the report reads the same on every run.
    _own = [CaseEvidence(nodeid=_evidence.nodeid, context=dict(_evidence.context))
            if _evidence is not None else None for _ in _calls]

    def _worker(index: int, call: Callable[[], Any]):
        try:
            SessionManager.setSession(SessionManager.clone(_session))
            recorder.bind(_own[index])
            Runtime.Case.adopt(_case_state)
        except BaseException as exc:  # noqa: BLE001 -- reported as NotConcurrent below
            _not_ready[index] = exc
            _barrier.abort()
            SessionManager.forget()
            return
        try:
            _left = _ready_by - time.monotonic()
            if _left <= 0:
                _barrier.abort()
            _barrier.wait(timeout=max(_left, 0))
        except threading.BrokenBarrierError:
            recorder.bind(None)
            SessionManager.forget()
            return
        _start = time.perf_counter()
        _starts[index] = _start
        try:
            _value, _error = call(), None
        except BaseException as exc:  # noqa: BLE001 -- pytest.fail and skip are BaseException
            _value, _error = None, exc
        _outcomes[index] = Outcome(index=index, value=_value, error=_error,
                                   start=_start, duration=time.perf_counter() - _start)
        recorder.bind(None)
        SessionManager.forget()

    _threads = [threading.Thread(target=_worker, args=(_i, _c), daemon=True,
                                 name='ipandora-concurrently-{}'.format(_i))
                for _i, _c in enumerate(_calls)]
    for _thread in _threads:
        _thread.start()

    _deadline = None
    for _index, _thread in enumerate(_threads):
        if _deadline is None:
            # wait for the start (or its failure), then give the burst `timeout`
            while _thread.is_alive() and _starts[_index] is None and not _barrier.broken:
                _thread.join(0.01)
            _deadline = time.monotonic() + timeout
        _thread.join(max(0.0, _deadline - time.monotonic()))

    if _barrier.broken or _not_ready:
        raise NotConcurrent(_why_not_started(len(_calls), _not_ready, timeout))

    # one snapshot for both the evidence and the results: a thread finishing
    # between two reads would otherwise be a timeout with its requests merged
    _done = list(_outcomes)
    for _index, _outcome in enumerate(_done):
        if _outcome is not None:    # still running: what it records from now on is dropped
            recorder.merge(_evidence, _own[_index])

    _first = min(_s for _s in _starts if _s is not None)
    _results = Results()
    for _index, _outcome in enumerate(_done):
        if _outcome is None:
            _outcome = Outcome(index=_index, error=TimeoutError(
                'still running {:g}s after the start; its thread was left to finish on its '
                'own'.format(timeout)), start=_starts[_index] or _first, duration=timeout)
        _outcome.start -= _first
        _results.append(_outcome)
    if _results.warning:
        logger.warning(_results.warning)
    return _results


def _operations(operation, n) -> List[Callable[[], Any]]:
    if isinstance(operation, (list, tuple)):
        _calls = list(operation)
    else:
        if n is None:
            raise TypeError('concurrently(operation, n): say how many -- n=20')
        _calls = [operation] * int(n)
    if len(_calls) < 2:
        raise ValueError('concurrency needs at least two operations, got {}'.format(len(_calls)))
    if not all(callable(_c) for _c in _calls):
        raise TypeError('every operation must be callable; wrap a call in a lambda')
    return _calls


def _why_not_started(count: int, not_ready: dict, timeout: float) -> str:
    if not_ready:
        _index, _exc = sorted(not_ready.items())[0]
        return ('concurrency did not happen: operation #{} of {} failed while getting ready '
                '({}: {}), so none of them was run'.format(
                    _index, count, type(_exc).__name__, _exc))
    return ('concurrency did not happen: the {} threads were not all ready within {:g}s, '
            'so none of them was run'.format(count, timeout))
