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

    # -- lifecycle ---------------------------------------------------------

    def begin(self, nodeid: str) -> None:
        self._local.current = CaseEvidence(nodeid=nodeid)

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
        self._local.current = None
        return _current

    def reset(self) -> None:
        self._local.current = None

    @property
    def active(self) -> bool:
        return getattr(self._local, 'current', None) is not None

    # -- capture -----------------------------------------------------------

    def add_checks(self, checks) -> None:
        _current = getattr(self._local, 'current', None)
        if _current is None:
            return
        for _check in checks or ():
            _current.checks.append({
                'name': getattr(_check, 'name', ''),
                'ok': bool(getattr(_check, 'ok', False)),
                'kind': getattr(_check, 'kind', 'assert'),
                'expr': getattr(_check, 'expr', ''),
                'src': getattr(_check, 'src', ''),
            })

    def add_exchange(self, exchange: Exchange) -> None:
        _current = getattr(self._local, 'current', None)
        if _current is None:
            return
        exchange.request_body = _clip(_readable(exchange.request_body))
        exchange.response_body = _clip(_readable(exchange.response_body))
        _current.exchanges.append(exchange.to_dict())


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
    except Exception:  # noqa: BLE001 - see docstring
        pass


def add_exchange(**kwargs) -> None:
    """Record one HTTP call. Never raises, for the same reason."""
    try:
        recorder.add_exchange(Exchange(**kwargs))
    except Exception:  # noqa: BLE001
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
