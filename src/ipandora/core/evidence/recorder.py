# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : recorder.py
@Time  : 2026-08-02

What actually happened during a case, kept so the report can show it.

A run already produces every fact worth reporting -- each `Check` carries its
own name, verdict, evidence and dimension, and every HTTP call knows its
request and response. Until now all of it was thrown away and rebuilt from the
one string pytest hands back, so a report could say "this test failed" and
almost nothing else.

This collects those facts as they are produced. It is deliberately passive:
nothing here decides an outcome, and a run with no recorder attached behaves
exactly as before -- reporting must never be able to change a verdict.

Thread-local by construction. Cases run in parallel, and evidence attributed to
the wrong case is worse than no evidence.
"""
import json
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

MAX_BODY_CHARS = 8000
"""
A body larger than this is stored truncated.

Reports get archived as CI artifacts and opened on phones, and the cost is per
exchange: a 200-case suite holds hundreds of them. 8000 characters is roughly
200 lines -- past the point anyone reads, and still enough to see the shape of
whatever came back.
"""


def _readable(text: Any):
    """
    Re-indent JSON before storing it.

    Order matters, and getting it wrong is invisible until you look at a
    report: truncating first leaves a fragment that no longer parses, so the
    renderer falls back to printing one enormous line. Indenting first also
    means the cut lands between lines instead of mid-token.
    """
    if not isinstance(text, str) or not text.strip():
        return text
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return text


def _clip(text: Any, limit: int = MAX_BODY_CHARS):
    if not isinstance(text, str) or len(text) <= limit:
        return text
    _head = text[:limit]
    # keep whole lines; a half-line of JSON reads as corruption
    _break = _head.rfind('\n')
    if _break > limit // 2:
        _head = _head[:_break]
    return _head + '\n… (truncated, {} chars total)'.format(len(text))


@dataclass
class Exchange:
    """One request and its response, as the report needs them."""
    method: str = ''
    url: str = ''
    status: int = 0
    reason: str = ''
    ms: float = 0.0
    request_headers: Dict[str, str] = field(default_factory=dict)
    request_body: Any = None
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_body: Any = None
    error: str = ''
    """Set when no response came back at all."""
    identity: str = ''
    """Who it was sent as (core/auth.py); '' for the default session. Never the credential."""
    role: str = ''
    """'login': made by the provider to log in, not by the case. 'replayed': the
    first attempt was rejected as not logged in and was sent again after a
    fresh login. '' otherwise."""

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 400

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CaseEvidence:
    nodeid: str = ''
    checks: List[Dict[str, Any]] = field(default_factory=list)
    exchanges: List[Dict[str, Any]] = field(default_factory=list)
    locators: Dict[str, Dict[str, str]] = field(default_factory=dict)
    """Web: selector -> what it pointed at (role, accessible name). See core/web.py."""
    locator_failures: List[Dict[str, Any]] = field(default_factory=list)
    """Web: selectors that found nothing, with the stale / missing verdict."""
    artifacts: List[Dict[str, str]] = field(default_factory=list)
    """Files the case produced for the report: golden / actual / diff images."""
    context: Dict[str, str] = field(default_factory=dict)
    """Where the case lives: its file, and the browser it ran in (core/runner/plugin.py)."""
    faults: List[Dict[str, Any]] = field(default_factory=list)
    """Faults the case injected (core/faults.py): what, where, from when to when. Read by triage."""

    def to_dict(self) -> Dict[str, Any]:
        return {'checks': list(self.checks), 'exchanges': list(self.exchanges)}


class Recorder:
    """
    Per-thread evidence, keyed by the case that produced it.

    `begin_case` marks the thread as belonging to a case; anything recorded
    afterwards lands there. Outside a case -- a helper script, an interactive
    session -- recording is a no-op rather than an error, because the calling
    code has no business knowing whether a report is being built.
    """

    def __init__(self):
        self._local = threading.local()
        # Several threads write into one case's evidence during concurrently();
        # appends are guarded so that holds on interpreters without a GIL too.
        self._write = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def begin(self, nodeid: str, **context) -> None:
        # Cases nest when a test calls run() itself: the inner session's case
        # opens while the outer one is still recording. The outer evidence is
        # set aside and comes back at end(); replacing it lost everything the
        # outer case judged after the inner run.
        _stack = getattr(self._local, 'stack', None)
        if _stack is None:
            _stack = self._local.stack = []
        _stack.append(getattr(self._local, 'current', None))
        self._local.current = CaseEvidence(
            nodeid=nodeid, context={_k: str(_v) for _k, _v in context.items() if _v})

    def end(self, nodeid: str) -> Optional[CaseEvidence]:
        """
        Hand the evidence over and forget it.

        A hand-off, deliberately, rather than an archive keyed by nodeid. The
        recorder holding onto finished cases looks harmless until you notice
        that pytest nodeids are relative to rootdir, so two runs of the same
        file produce the same key -- and this process serves many runs. The MCP
        server is the case that matters: it stays up across every `run_tests`
        call, so an archive would have made each report repeat the last one's
        checks, growing without bound. The caller owns what it is given.
        """
        _current = getattr(self._local, 'current', None)
        if _current is None or _current.nodeid != nodeid:
            # not this case's slot -- a case skipped by its marker never began
            # one, and must not take the enclosing case's evidence with it
            return None
        _stack = getattr(self._local, 'stack', None) or []
        self._local.current = _stack.pop() if _stack else None
        return _current

    def current(self) -> Optional[CaseEvidence]:
        """This thread's case evidence, for handing to another thread; None outside a case."""
        return getattr(self._local, 'current', None)

    def bind(self, evidence: Optional[CaseEvidence]) -> None:
        """
        Make this thread record into a case another thread opened.

        For core/concurrency.py: the threads it starts belong to the case that
        started them, and without this every request they made was dropped --
        the evidence is per-thread and a new thread has no case.
        """
        self._local.current = evidence

    def reset(self) -> None:
        self._local.current = None
        self._local.stack = []

    def merge(self, target: Optional[CaseEvidence], source: Optional[CaseEvidence]) -> None:
        """Append what `source` recorded to `target`. For concurrently(): see there."""
        if target is None or source is None:
            return
        with self._write:
            target.checks.extend(source.checks)
            target.exchanges.extend(source.exchanges)
            target.locators.update(source.locators)
            target.locator_failures.extend(source.locator_failures)
            target.faults.extend(_f for _f in source.faults if _f not in target.faults)
            for _artifact in source.artifacts:
                if _artifact not in target.artifacts:
                    target.artifacts.append(_artifact)

    @property
    def active(self) -> bool:
        return getattr(self._local, 'current', None) is not None

    # -- capture -----------------------------------------------------------

    @contextmanager
    def checks_withheld(self):
        """
        Record no judgements on this thread for the duration; requests still are.

        For eventually(): each read of its probe judges, and a probe that uses
        assert_all records those judgements. The reads that did not hold yet
        are observations of a system still converging, not failed judgements
        -- yet they landed in the case's evidence, and a case whose wait
        succeeded showed red checks in its report. eventually() returns its own
        single Check instead. The requests each read made stay: they are what
        someone debugging a slow convergence wants to see.
        """
        _before = getattr(self._local, 'withheld', False)
        self._local.withheld = True
        try:
            yield
        finally:
            self._local.withheld = _before

    def add_checks(self, checks) -> None:
        _current = getattr(self._local, 'current', None)
        if _current is None or getattr(self._local, 'withheld', False):
            return
        for _check in checks or ():
            _entry = {
                'name': getattr(_check, 'name', ''),
                'ok': bool(getattr(_check, 'ok', False)),
                'kind': getattr(_check, 'kind', 'assert'),
                'expr': getattr(_check, 'expr', ''),
                'src': getattr(_check, 'src', ''),
                'claim': getattr(_check, 'claim', '') or getattr(_check, 'name', ''),
            }
            with self._write:
                _current.checks.append(_entry)

    def current_checks(self) -> List[Dict[str, Any]]:
        """The checks recorded so far for this thread's case; [] outside one."""
        _current = getattr(self._local, 'current', None)
        if _current is None:
            return []
        with self._write:
            return list(_current.checks)

    def add_fault(self, record: Dict[str, Any]) -> None:
        """
        A fault injected while this case ran. The record itself, not a copy:
        core/faults.py fills in when the fault ended after the block exits.
        """
        _current = self.current()
        if _current is None:
            return
        with self._write:
            _current.faults.append(record)

    def add_artifact(self, entry: Dict[str, str]) -> None:
        """A file the case produced for the report: kind, path, group (and a command that opens it)."""
        _current = self.current()
        if _current is None:
            return
        with self._write:
            if entry not in _current.artifacts:
                _current.artifacts.append(dict(entry))

    def add_exchange(self, exchange: Exchange) -> None:
        _current = getattr(self._local, 'current', None)
        if _current is None:
            return
        exchange.request_body = _clip(_readable(exchange.request_body))
        exchange.response_body = _clip(_readable(exchange.response_body))
        _entry = exchange.to_dict()
        with self._write:
            _current.exchanges.append(_entry)


recorder = Recorder()
"""Process-wide instance. Its state is per-thread; only the index is shared."""


def begin_case(nodeid: str) -> None:
    recorder.begin(nodeid)


def end_case(nodeid: str):
    return recorder.end(nodeid)


def add_checks(checks) -> None:
    """
    Record judgements. Never raises: a reporting failure must not turn a
    passing test red.
    """
    try:
        recorder.add_checks(checks)
    # bandit B110: reporting must never fail a test
    except Exception:  # noqa: BLE001 - see docstring  # nosec B110
        pass


def add_fault(record: Dict[str, Any]) -> None:
    recorder.add_fault(record)


def add_exchange(**kwargs) -> None:
    """Record one HTTP call. Never raises, for the same reason."""
    try:
        recorder.add_exchange(Exchange(**kwargs))
    # bandit B110: reporting must never fail a test
    except Exception:  # noqa: BLE001  # nosec B110
        pass


class Timer:
    """Elapsed milliseconds, for exchange timing."""

    def __enter__(self):
        self._start = time.perf_counter()
        self.ms = 0.0
        return self

    def __exit__(self, *_exc):
        self.ms = (time.perf_counter() - self._start) * 1000.0
        return False
