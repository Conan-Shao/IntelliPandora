# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : diff.py
@Time  : 2026-08-03

Comparing a live response against the one on the tape.

This is the half of record/replay the original plan called the highest-ROI
piece: rewrite a service, then point the same traffic at both versions and ask
what changed. Replay answers "can I run offline"; this answers "did I break
anything", which is a different and more valuable question.

The whole difficulty is that real responses differ on every call for reasons
nobody cares about -- server timestamps, trace ids, generated ids, floats that
wobble in the last digit. Reporting those as changes produces a diff nobody
reads, which is the same as no diff at all. So the tolerance list is not a
nicety; it is what separates a usable guardrail from noise, and it belongs in
the cassette's manifest because "this field always differs" is a fact about the
recorded system rather than about any one test.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ipandora.core.assertion.check import brief

DEFAULT_IGNORE_HEADERS = ('date', 'content-length', 'set-cookie', 'x-request-id',
                          'x-trace-id', 'etag', 'age', 'server', 'connection',
                          'keep-alive', 'x-served-by', 'cf-ray', 'report-to')
"""
Response headers that differ on every call by design.

Comparing them produces a difference on every single exchange, which trains
whoever reads the report to skip the whole section.
"""

MAX_DIFFERENCES = 50
"""
How many differences one exchange reports.

A renamed top-level field can produce thousands. Past the first few dozen the
list has stopped being a list of problems and become one problem printed many
times; the count is still reported in full.
"""


class Kind:
    STATUS = 'status'
    HEADER = 'header'
    BODY = 'body'
    SHAPE = 'shape'
    """The body stopped being JSON, or started being it."""


class Change:
    CHANGED = 'changed'
    ADDED = 'added'
    REMOVED = 'removed'


@dataclass
class Difference:
    path: str = ''
    kind: str = Kind.BODY
    change: str = Change.CHANGED
    baseline: Any = None
    actual: Any = None
    tolerated: bool = False
    reason: str = ''
    """Why it was tolerated, when it was. Empty otherwise."""

    def describe(self) -> str:
        if self.change == Change.ADDED:
            return '{}: 新增 {}'.format(self.path, brief(self.actual, 80))
        if self.change == Change.REMOVED:
            return '{}: 消失（基线为 {}）'.format(self.path, brief(self.baseline, 80))
        return '{}: {} → {}'.format(self.path, brief(self.baseline, 80),
                                    brief(self.actual, 80))

    def to_dict(self) -> Dict[str, Any]:
        return {'path': self.path, 'kind': self.kind, 'change': self.change,
                'baseline': brief(self.baseline, 200), 'actual': brief(self.actual, 200),
                'tolerated': self.tolerated, 'reason': self.reason}


@dataclass
class DiffRules:
    """
    What may differ without counting as a change.

    Read from the cassette's manifest. Two knobs beyond a plain ignore list,
    because a plain ignore list forces a false choice between "compare this
    field exactly" and "do not look at it at all":

    - `tolerate` accepts a numeric wobble, so a rounding change of 1e-9 is
      quiet while a real change of 0.01 is not.
    - `unordered` compares a list as a bag, for endpoints that return the same
      items in whatever order the database felt like.
    """
    ignore_paths: Tuple[str, ...] = ()
    ignore_headers: Tuple[str, ...] = DEFAULT_IGNORE_HEADERS
    unordered_paths: Tuple[str, ...] = ()
    tolerate: Tuple[Dict[str, Any], ...] = ()
    compare_headers: bool = False
    """
    Off by default. Headers carry far more incidental variation than bodies,
    and a diff that is 90% header noise gets ignored wholesale -- taking the
    body differences with it.
    """

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DiffRules':
        _data = data or {}
        return cls(
            ignore_paths=tuple(_data.get('ignore_paths') or ()),
            ignore_headers=tuple(_h.lower() for _h in _data.get(
                'ignore_headers', DEFAULT_IGNORE_HEADERS)),
            unordered_paths=tuple(_data.get('unordered_paths') or ()),
            tolerate=tuple(_data.get('tolerate') or ()),
            compare_headers=bool(_data.get('compare_headers', False)))

    def to_dict(self) -> Dict[str, Any]:
        return {'ignore_paths': list(self.ignore_paths),
                'ignore_headers': list(self.ignore_headers),
                'unordered_paths': list(self.unordered_paths),
                'tolerate': [dict(_t) for _t in self.tolerate],
                'compare_headers': self.compare_headers}


def _to_regex(pattern: str) -> 're.Pattern':
    """
    `data.list[*].updatedAt` -> a matcher for concrete paths.

    `[*]` stands for any index, `*` inside a segment for any name. Built once
    per pattern; a run compares thousands of paths against a handful of rules.
    """
    _out, _i = [], 0
    while _i < len(pattern):
        if pattern.startswith('[*]', _i):
            _out.append(r'\[\d+\]')
            _i += 3
        elif pattern[_i] == '*':
            _out.append(r'[^.\[\]]*')
            _i += 1
        else:
            _out.append(re.escape(pattern[_i]))
            _i += 1
    return re.compile('^' + ''.join(_out) + '$')


class _Matcher:
    def __init__(self, patterns):
        self._exact = {_p for _p in patterns if '*' not in _p}
        self._globs = [_to_regex(_p) for _p in patterns if '*' in _p]

    def matches(self, path: str) -> bool:
        if path in self._exact:
            return True
        return any(_glob.match(path) for _glob in self._globs)

    def prefix_matches(self, path: str) -> bool:
        """True when the path or any ancestor of it matches."""
        _parts = path
        while _parts:
            if self.matches(_parts):
                return True
            _cut = max(_parts.rfind('.'), _parts.rfind('['))
            if _cut <= 0:
                return False
            _parts = _parts[:_cut]
        return False


def _tolerance_for(path: str, rules: DiffRules) -> Optional[Dict[str, Any]]:
    for _rule in rules.tolerate:
        _pattern = _rule.get('path') or ''
        if _pattern and _to_regex(_pattern).match(path):
            return _rule
    return None


def _within_tolerance(baseline, actual, rule) -> Tuple[bool, str]:
    if not rule or rule.get('kind', 'numeric') != 'numeric':
        return False, ''
    try:
        _a, _b = float(baseline), float(actual)
    except (TypeError, ValueError):
        return False, ''
    _epsilon = float(rule.get('epsilon', 0))
    if abs(_a - _b) <= _epsilon:
        return True, '数值差 {:g} ≤ 容差 {:g}'.format(abs(_a - _b), _epsilon)
    return False, ''


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      default=str)


def _walk(baseline: Any, actual: Any, path: str, rules: DiffRules,
          ignore: _Matcher, unordered: _Matcher, out: List[Difference]) -> None:
    if len(out) >= MAX_DIFFERENCES:
        return
    if path and ignore.matches(path):
        return

    if isinstance(baseline, dict) and isinstance(actual, dict):
        for _key in baseline:
            _child = '{}.{}'.format(path, _key) if path else _key
            if ignore.matches(_child):
                continue
            if _key not in actual:
                out.append(Difference(path=_child, change=Change.REMOVED,
                                      baseline=baseline[_key]))
            else:
                _walk(baseline[_key], actual[_key], _child, rules, ignore, unordered, out)
        for _key in actual:
            if _key in baseline:
                continue
            _child = '{}.{}'.format(path, _key) if path else _key
            if not ignore.matches(_child):
                out.append(Difference(path=_child, change=Change.ADDED,
                                      actual=actual[_key]))
        return

    if isinstance(baseline, list) and isinstance(actual, list):
        if unordered.matches(path):
            _left = sorted(_canonical(_i) for _i in baseline)
            _right = sorted(_canonical(_i) for _i in actual)
            if _left != _right:
                out.append(Difference(path=path, baseline='{} 项'.format(len(baseline)),
                                      actual='{} 项'.format(len(actual)),
                                      reason='按无序集合比较，内容不同'))
            return
        if len(baseline) != len(actual):
            out.append(Difference(path=path, baseline='{} 项'.format(len(baseline)),
                                  actual='{} 项'.format(len(actual))))
        for _index in range(min(len(baseline), len(actual))):
            _walk(baseline[_index], actual[_index], '{}[{}]'.format(path, _index),
                  rules, ignore, unordered, out)
        return

    if baseline == actual:
        return

    _tolerated, _reason = _within_tolerance(baseline, actual, _tolerance_for(path, rules))
    out.append(Difference(path=path or '<root>', baseline=baseline, actual=actual,
                          tolerated=_tolerated, reason=_reason))


def _parse(body) -> Tuple[Any, bool]:
    """(value, is_json). Non-JSON comes back as its text."""
    if body is None:
        return None, False
    if not isinstance(body, str):
        return body, True
    try:
        return json.loads(body), True
    except (TypeError, ValueError):
        return body, False


@dataclass
class DiffResult:
    """One exchange compared. `differences` excludes nothing; `real` is what counts."""
    method: str = ''
    url: str = ''
    differences: List[Difference] = field(default_factory=list)
    truncated: bool = False

    @property
    def real(self) -> List[Difference]:
        return [_d for _d in self.differences if not _d.tolerated]

    @property
    def tolerated(self) -> List[Difference]:
        return [_d for _d in self.differences if _d.tolerated]

    @property
    def identical(self) -> bool:
        return not self.real

    def summary(self) -> str:
        if self.identical:
            _count = len(self.tolerated)
            return '与基线一致{}'.format(
                '（{} 处差异已容忍）'.format(_count) if _count else '')
        _lines = [_d.describe() for _d in self.real[:5]]
        _more = len(self.real) - len(_lines)
        if _more > 0:
            _lines.append('… 另有 {} 处'.format(_more))
        if self.tolerated:
            _lines.append('（{} 处差异已容忍）'.format(len(self.tolerated)))
        return '{} 处差异：{}'.format(len(self.real), '；'.join(_lines))

    def to_dict(self) -> Dict[str, Any]:
        return {'method': self.method, 'url': self.url,
                'identical': self.identical,
                'differences': [_d.to_dict() for _d in self.differences],
                'truncated': self.truncated}


def compare(record, status: int, headers, body, rules: DiffRules = None,
            method: str = '', url: str = '') -> DiffResult:
    """
    Compare a live response against a recorded one.

    Status first, and on its own: when a 200 becomes a 500 the body differences
    that follow are noise about an error page, and burying the status line
    among them is how a reader misses the only thing that mattered.
    """
    _rules = rules or DiffRules()
    _result = DiffResult(method=method or record.method, url=url or record.url)
    _ignore = _Matcher(_rules.ignore_paths)
    _unordered = _Matcher(_rules.unordered_paths)

    if record.status != status:
        _result.differences.append(Difference(
            path='<status>', kind=Kind.STATUS,
            baseline=record.status, actual=status))

    if _rules.compare_headers:
        _base_headers = {_k.lower(): _v for _k, _v in (record.response_headers or {}).items()}
        _live_headers = {_k.lower(): _v for _k, _v in (headers or {}).items()}
        for _name in sorted(set(_base_headers) | set(_live_headers)):
            if _name in _rules.ignore_headers:
                continue
            if _base_headers.get(_name) != _live_headers.get(_name):
                _result.differences.append(Difference(
                    path='<header>.{}'.format(_name), kind=Kind.HEADER,
                    change=(Change.ADDED if _name not in _base_headers else
                            Change.REMOVED if _name not in _live_headers else
                            Change.CHANGED),
                    baseline=_base_headers.get(_name), actual=_live_headers.get(_name)))

    _base_body, _base_json = _parse(record.response_body)
    _live_body, _live_json = _parse(body)

    if _base_json != _live_json:
        _result.differences.append(Difference(
            path='<body>', kind=Kind.SHAPE,
            baseline='JSON' if _base_json else '非 JSON',
            actual='JSON' if _live_json else '非 JSON'))
    elif not _base_json:
        if _base_body != _live_body:
            _result.differences.append(Difference(
                path='<body>', kind=Kind.SHAPE, baseline=_base_body, actual=_live_body))
    else:
        _body_diffs = []  # type: List[Difference]
        _walk(_base_body, _live_body, '', _rules, _ignore, _unordered, _body_diffs)
        _result.truncated = len(_body_diffs) >= MAX_DIFFERENCES
        _result.differences.extend(_body_diffs)

    return _result
