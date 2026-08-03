# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : matcher.py
@Time  : 2026-08-02

Deciding whether a request is the one that was recorded.

This is where replay is easiest to get wrong. Real requests are full of noise
that changes on every call -- cache-busting timestamps, nonces, signatures,
generated request ids, rotating tokens -- and any of it left in the key makes
every lookup miss. So the ignore lists are not a convenience: without them the
feature does not work at all.

The rules live in the cassette's manifest rather than in code, because they
describe the recorded system.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlsplit

# Present on nearly every API and never stable. Callers can replace the list;
# starting from zero means everyone rediscovers the same four names.
DEFAULT_IGNORE_QUERY = ('_', '_t', 'ts', 'timestamp', 'nonce', 'sign', 'signature')
DEFAULT_IGNORE_HEADERS = ('authorization', 'cookie', 'date', 'user-agent',
                          'x-trace-id', 'x-request-id', 'content-length')
DEFAULT_IGNORE_BODY_PATHS = ('requestId', 'timestamp', 'nonce', 'sign')

BODY_DIGEST_CHARS = 12


@dataclass
class MatchRules:
    """
    What counts as the same request.

    `on` selects the parts that participate. The ignore lists then subtract the
    noise inside those parts.
    """
    on: Tuple[str, ...] = ('method', 'path', 'query', 'body')
    ignore_query: Tuple[str, ...] = DEFAULT_IGNORE_QUERY
    ignore_headers: Tuple[str, ...] = DEFAULT_IGNORE_HEADERS
    ignore_body_paths: Tuple[str, ...] = DEFAULT_IGNORE_BODY_PATHS
    match_host: bool = False
    """
    Off by default: the same cassette should replay against staging and against
    a local port. Turn it on when a cassette deliberately spans several hosts
    and the host is what tells them apart.
    """

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MatchRules':
        _data = data or {}
        return cls(
            on=tuple(_data.get('on') or cls.on),
            ignore_query=tuple(_data.get('ignore_query', DEFAULT_IGNORE_QUERY)),
            ignore_headers=tuple(_l.lower() for _l in
                                 _data.get('ignore_headers', DEFAULT_IGNORE_HEADERS)),
            ignore_body_paths=tuple(_data.get('ignore_body_paths',
                                              DEFAULT_IGNORE_BODY_PATHS)),
            match_host=bool(_data.get('match_host', False)))

    def to_dict(self) -> Dict[str, Any]:
        return {'on': list(self.on),
                'ignore_query': list(self.ignore_query),
                'ignore_headers': list(self.ignore_headers),
                'ignore_body_paths': list(self.ignore_body_paths),
                'match_host': self.match_host}


def _strip_paths(value: Any, paths: Tuple[str, ...], _prefix: str = '') -> Any:
    """Drop the noisy fields from a decoded body, at any depth."""
    if isinstance(value, dict):
        _out = {}
        for _key, _item in value.items():
            _full = '{}.{}'.format(_prefix, _key) if _prefix else _key
            if _key in paths or _full in paths:
                continue
            _out[_key] = _strip_paths(_item, paths, _full)
        return _out
    if isinstance(value, list):
        return [_strip_paths(_item, paths, _prefix) for _item in value]
    return value


def body_digest(body: Any, rules: MatchRules) -> str:
    """
    A stable fingerprint of a request body.

    JSON is normalised before hashing -- sorted keys, no incidental whitespace
    -- so that two encoders producing the same object agree. Anything that is
    not JSON is hashed as bytes, which is the honest thing to do: we cannot
    normalise what we cannot parse.
    """
    if body is None or body == '':
        return '-'
    if isinstance(body, bytes):
        try:
            body = body.decode('utf-8')
        except UnicodeDecodeError:
            return hashlib.sha256(body).hexdigest()[:BODY_DIGEST_CHARS]
    if isinstance(body, str):
        try:
            _decoded = json.loads(body)
        except (TypeError, ValueError):
            return hashlib.sha256(body.encode('utf-8')).hexdigest()[:BODY_DIGEST_CHARS]
    else:
        _decoded = body

    _stripped = _strip_paths(_decoded, rules.ignore_body_paths)
    _canonical = json.dumps(_stripped, sort_keys=True, separators=(',', ':'),
                            ensure_ascii=False)
    return hashlib.sha256(_canonical.encode('utf-8')).hexdigest()[:BODY_DIGEST_CHARS]


def key_for(method: str, url: str, body: Any = None,
            rules: MatchRules = None) -> str:
    """
    The match key, as it appears in the cassette and in a miss message.

    Deliberately readable rather than a bare hash: when a lookup misses, the
    first thing anyone needs to see is which part differs, and
    `GET|/v1/order|q:orderId,page|b:a1b2c3` answers that at a glance where
    `sha256:9f2c…` does not.
    """
    _rules = rules or MatchRules()
    _parts = []

    if 'method' in _rules.on:
        _parts.append(str(method or 'GET').upper())

    _split = urlsplit(url or '')
    if 'path' in _rules.on:
        _path = _split.path or '/'
        if _rules.match_host and _split.netloc:
            _path = '{}{}'.format(_split.netloc, _path)
        _parts.append(_path)

    if 'query' in _rules.on:
        _pairs = [(_k, _v) for _k, _v in parse_qsl(_split.query, keep_blank_values=True)
                  if _k not in _rules.ignore_query]
        # sorted: ?a=1&b=2 and ?b=2&a=1 are the same request
        _parts.append('q:' + ','.join('{}={}'.format(_k, _v)
                                      for _k, _v in sorted(_pairs)) if _pairs else 'q:-')

    if 'body' in _rules.on:
        _parts.append('b:' + body_digest(body, _rules))

    return '|'.join(_parts)


_SEGMENT = re.compile(r'^(?P<label>[a-z]+):(?P<value>.*)$')


def explain(key_a: str, key_b: str) -> str:
    """
    How two keys differ, in a sentence.

    Nine misses out of ten are one ignore rule that was never configured, so
    naming the differing part is what turns a dead end into a fix.
    """
    _a, _b = key_a.split('|'), key_b.split('|')
    if len(_a) != len(_b):
        return 'different key shape'

    _diffs = []
    for _left, _right in zip(_a, _b):
        if _left == _right:
            continue
        _match = _SEGMENT.match(_left)
        if _match and _match.group('label') == 'q':
            _lk = {_p.split('=')[0] for _p in _match.group('value').split(',') if _p}
            _rm = _SEGMENT.match(_right)
            _rk = {_p.split('=')[0] for _p in (_rm.group('value') if _rm else '').split(',') if _p}
            if _lk != _rk:
                _extra = sorted(_lk - _rk) or sorted(_rk - _lk)
                _diffs.append('query 参数不同（{}）'.format(', '.join(_extra)))
            else:
                _diffs.append('query 取值不同')
        elif _match and _match.group('label') == 'b':
            _diffs.append('请求体不同')
        elif _left.startswith('/') or _right.startswith('/'):
            _diffs.append('路径不同')
        else:
            _diffs.append('方法不同')
    return '，'.join(_diffs) or 'identical'


def nearest(key: str, candidates: List[str]) -> Tuple[Optional[str], str]:
    """
    The recorded key closest to the one being looked up, and how it differs.

    Similarity is counted over the key's own segments rather than characters:
    two keys that agree on method and path but differ on query are far more
    useful to show than one that happens to share a long URL prefix.
    """
    if not candidates:
        return None, ''

    _target = key.split('|')
    _best, _score = None, -1
    for _candidate in candidates:
        _parts = _candidate.split('|')
        _shared = sum(1 for _l, _r in zip(_target, _parts) if _l == _r)
        if _shared > _score:
            _best, _score = _candidate, _shared
    return _best, explain(key, _best) if _best else ''
