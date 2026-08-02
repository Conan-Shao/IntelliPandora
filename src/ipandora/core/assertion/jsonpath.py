# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : jsonpath.py
@Time  : 2026-08-01
"""
import re
from typing import Any, Tuple

_SEGMENT = re.compile(r'([^.\[\]]+)|\[(-?\d+)\]')

MISSING = object()
"""Sentinel: distinguishes "field absent" from "field present and None"."""


def _segments(path: str):
    """'data.items[0].name' -> ['data', 'items', 0, 'name']"""
    _out = []
    for _key, _index in _SEGMENT.findall(path):
        _out.append(_key if _key else int(_index))
    return _out


def resolve(body: Any, path: str) -> Tuple[Any, str]:
    """
    Walk a dotted/indexed path through plain JSON data.

    Returns (value, reason). On success reason is ''. On failure the value is
    MISSING and reason says exactly where the walk stopped -- that string goes
    straight into a Check's evidence, so a failure is readable without
    re-running anything.

    Works on plain dicts and lists only. It deliberately does not understand
    namedtuples: ResponseHandler.json_to_obj silently degrades to a dict when
    a JSON key is a Python keyword or contains a dash, which would make the
    accessor's behaviour depend on the payload's key names.
    """
    if not path:
        return body, ''

    _current = body
    _walked = []
    for _segment in _segments(path):
        _shown = '[{}]'.format(_segment) if isinstance(_segment, int) else _segment
        if isinstance(_segment, int):
            if not isinstance(_current, (list, tuple)):
                return MISSING, 'at {!r}: expected a list, found {}'.format(
                    '.'.join(_walked) or '<root>', type(_current).__name__)
            if not -len(_current) <= _segment < len(_current):
                return MISSING, 'at {!r}: index {} out of range (len={})'.format(
                    '.'.join(_walked) or '<root>', _segment, len(_current))
            _current = _current[_segment]
        else:
            if not isinstance(_current, dict):
                return MISSING, 'at {!r}: expected an object, found {}'.format(
                    '.'.join(_walked) or '<root>', type(_current).__name__)
            if _segment not in _current:
                _available = ', '.join(sorted(map(str, _current.keys()))[:8]) or '<empty>'
                return MISSING, 'at {!r}: no key {!r} (present: {})'.format(
                    '.'.join(_walked) or '<root>', _segment, _available)
            _current = _current[_segment]
        _walked.append(_shown)

    return _current, ''
