# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : model.py
@Time  : 2026-08-02

What sits on disk: one record per exchange, one manifest per cassette.

See docs/design/07-流量录制回放.md for why the format is what it is. The short
version: JSON Lines so recording can append and a person can grep and diff it,
content-addressed blobs for large bodies because real traffic repeats the same
response constantly, and a manifest carrying the rules -- because "which fields
differ every time" is a fact about the system under test, not about a test.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

FORMAT_VERSION = 1

INLINE_BODY_CHARS = 8000
"""
Bodies longer than this move to a blob.

Two reasons, neither of them tidiness. Real traffic repeats the same response
body constantly -- config endpoints, dictionaries, first pages -- and content
addressing stores each distinct one once. And a jsonl line with 200KB of JSON
embedded in it cannot be read, diffed or reviewed, which loses the main reason
for choosing jsonl in the first place.
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@dataclass
class Record:
    """One request and its response, as stored."""
    seq: int = 0
    at: str = field(default_factory=_now)
    key: str = ''
    method: str = ''
    url: str = ''
    request_headers: Dict[str, str] = field(default_factory=dict)
    request_body: Optional[str] = None
    request_body_ref: str = ''
    status: int = 0
    reason: str = ''
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_body: Optional[str] = None
    response_body_ref: str = ''
    ms: float = 0.0
    source: str = 'record'
    """Where it came from: record, or import:<tool> once P6.3 exists."""

    def to_dict(self) -> Dict[str, Any]:
        # Empty refs and null bodies are dropped: a cassette is read by people,
        # and a line full of `"request_body_ref": ""` is noise.
        return {_k: _v for _k, _v in asdict(self).items()
                if _v not in ('', None, {}) or _k in ('method', 'url', 'status')}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Record':
        _fields = {_f for _f in cls.__dataclass_fields__}
        return cls(**{_k: _v for _k, _v in (data or {}).items() if _k in _fields})


@dataclass
class Manifest:
    """
    The cassette's metadata and its rules.

    `match` and `diff` live here rather than in a test because they describe
    the recorded system: `data.serverTime` differs on every call no matter
    which test asks for it. Stating that once per cassette is correct; stating
    it once per test is a rule everyone forgets exactly once, and the symptom
    is a permanently red assertion nobody trusts.
    """
    name: str = ''
    version: int = FORMAT_VERSION
    recorded_at: str = field(default_factory=_now)
    recorded_from: str = ''
    ipandora: str = ''
    count: int = 0
    blobs: int = 0
    match: Dict[str, Any] = field(default_factory=dict)
    diff: Dict[str, Any] = field(default_factory=dict)
    redaction: Dict[str, Any] = field(default_factory=lambda: {
        'applied_at': 'record', 'rules': 'default'})

    def age_days(self) -> Optional[float]:
        """
        How stale the cassette is.

        A cassette that stopped being re-recorded keeps a suite green while it
        tests an assumption nobody holds anymore, and it does so silently.
        Reporting the age is what makes that visible; see docs/design/07.
        """
        try:
            _then = datetime.strptime(self.recorded_at, '%Y-%m-%dT%H:%M:%SZ')
        except (TypeError, ValueError):
            return None
        return (datetime.utcnow() - _then).total_seconds() / 86400.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Manifest':
        _fields = {_f for _f in cls.__dataclass_fields__}
        return cls(**{_k: _v for _k, _v in (data or {}).items() if _k in _fields})


@dataclass
class Miss:
    """Why a request found nothing, with enough detail to fix the rules."""
    method: str = ''
    url: str = ''
    key: str = ''
    nearest_key: str = ''
    nearest_reason: str = ''
    exhausted: bool = False
    """True when the key matched but every recording of it was already used."""
    total: int = 0
    keys: List[str] = field(default_factory=list)
