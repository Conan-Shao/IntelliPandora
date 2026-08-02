# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : jsonpath.py
@Time  : 2026-08-01
"""
import re
from typing import Any, List, Tuple

MISSING = object()
"""Sentinel: distinguishes "field absent" from "field present and None"."""

# Ordered: bracket forms first, so a quoted key is never split on its dots.
_TOKEN = re.compile(r"""
      \[\s*'([^']*)'\s*\]      # ['any.key']
    | \[\s*"([^"]*)"\s*\]      # ["any.key"]
    | \[\s*(-?\d+)\s*\]        # [0], [-1]
    | ([^.\[\]]+)              # bare segment
""", re.VERBOSE)

_KEY, _INDEX, _EITHER = 'key', 'index', 'either'

_MAX_KEYS_LISTED = 8
_MAX_KEY_CHARS = 160


def _segments(path: str) -> List[Tuple[str, Any]]:
    """
    'data.items[0].name'      -> [(key,'data'), (key,'items'), (index,0), (key,'name')]
    "releases['2.32.0'].url"  -> [(key,'releases'), (key,'2.32.0'), (key,'url')]
    'data.items.0.name'       -> [(key,'data'), (key,'items'), (either,'0'), (key,'name')]

    A bare numeric segment stays undecided until the walk sees what it is
    standing on. `data.items.0` is how most people write an index, but `0` is
    also a perfectly ordinary object key -- npm and PyPI both have documents
    with numeric-looking keys. Resolving it against the actual node means both
    readings work and neither has to be guessed at parse time.
    """
    _out = []
    for _sq, _dq, _idx, _bare in _TOKEN.findall(path):
        if _sq:
            _out.append((_KEY, _sq))
        elif _dq:
            _out.append((_KEY, _dq))
        elif _idx:
            _out.append((_INDEX, int(_idx)))
        elif _bare:
            _kind = _EITHER if re.fullmatch(r'-?\d+', _bare) else _KEY
            _out.append((_kind, _bare))
    return _out


def _keys_of(node: dict) -> str:
    _names = sorted(map(str, node.keys()))
    if not _names:
        return '<empty>'
    _shown = ', '.join(_names[:_MAX_KEYS_LISTED])
    if len(_shown) > _MAX_KEY_CHARS:
        _shown = _shown[:_MAX_KEY_CHARS] + '…'
    if len(_names) > _MAX_KEYS_LISTED:
        _shown += ', … ({} keys)'.format(len(_names))
    return _shown


def resolve(body: Any, path: str) -> Tuple[Any, str]:
    """
    Walk a dotted/indexed path through plain JSON data.

    Returns (value, reason). On success reason is ''. On failure the value is
    MISSING and reason says exactly where the walk stopped -- that string goes
    straight into a Check's evidence, so a failure is readable without
    re-running anything.

    Accepted forms::

        data.items[0].name        bracket index
        data.items.0.name         bare index, same thing
        releases['2.32.0'].url    quoted key, for keys containing dots
        headers["x-request-id"]   either quote style

    Works on plain dicts and lists only, deliberately: judging correctness
    should not depend on another layer's parsing conventions. ResponseHandler
    now yields JsonObject, which is a dict, so this reads it either way.
    """
    if not path:
        return body, ''

    _current = body
    _walked = []

    def _where():
        return '.'.join(_walked) or '<root>'

    for _kind, _segment in _segments(path):
        # An undecided numeric segment takes the reading the node supports.
        if _kind is _EITHER:
            _kind = _INDEX if isinstance(_current, (list, tuple)) else _KEY

        if _kind is _INDEX:
            _index = int(_segment)
            if not isinstance(_current, (list, tuple)):
                return MISSING, 'at {!r}: expected a list, found {}'.format(
                    _where(), type(_current).__name__)
            if not -len(_current) <= _index < len(_current):
                return MISSING, 'at {!r}: index {} out of range (len={})'.format(
                    _where(), _index, len(_current))
            _current = _current[_index]
            _walked.append('[{}]'.format(_index))
        else:
            _key = str(_segment)
            if not isinstance(_current, dict):
                # Reaching a list with a non-numeric segment is the common
                # version of this: say what would have worked.
                _hint = (" (use an index like [0] to enter a list)"
                         if isinstance(_current, (list, tuple)) else '')
                return MISSING, 'at {!r}: expected an object, found {}{}'.format(
                    _where(), type(_current).__name__, _hint)
            if _key not in _current:
                return MISSING, 'at {!r}: no key {!r} (present: {})'.format(
                    _where(), _key, _keys_of(_current))
            _current = _current[_key]
            _walked.append(_key)

    return _current, ''
