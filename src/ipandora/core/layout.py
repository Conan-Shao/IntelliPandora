# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : layout.py
@Time  : 2026-11-06

The layering rules of a case library, checked (docs/design/decisions/17 §3.3,
plan L3). `ipandora check layout` runs it; CI can too.

| layer   | does not                                                          |
|---------|-------------------------------------------------------------------|
| apis/   | judge; hard-code an address                                       |
| pages/  | judge; sleep                                                      |
| flows/  | judge (require() is fine: a step that cannot set up says so); sleep |
| tests/  | call requests directly; sleep (eventually() waits for a condition)  |

Judgements belong in tests/ so that reading a case says what it verifies,
and a reviewer reads one directory's diff to see what changed in them. The
judgement inventory records them wherever they are -- this is about where a
person finds them, not whether the runner does.

Static, from the syntax tree: nothing is imported or run. A directory the
project does not have is not checked.
"""
import ast
import os
import re
from dataclasses import dataclass
from typing import List

LAYERS = ('apis', 'pages', 'flows', 'tests')
NO_JUDGEMENTS = ('apis', 'pages', 'flows')
NO_SLEEP = ('pages', 'flows', 'tests')

JUDGING_CALLS = {'assert_all'}
"""Calls that judge, by their last name. require() is not one: it states a precondition."""

SLEEPS = {'sleep', 'wait_for_timeout'}
"""Fixed waits, by their last name: time.sleep, t.sleep, asyncio.sleep, self.page.wait_for_timeout."""

_URL = re.compile(r'^https?://[^\s{}]+', re.IGNORECASE)


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    message: str

    def __str__(self):
        return '{}:{}: [{}] {}'.format(self.path, self.line, self.rule, self.message)


def _name(node) -> str:
    """`assert_all`, `expect`, `time.sleep`, `pytest.raises` for a call's function."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        _base = _name(node.value)
        return '{}.{}'.format(_base, node.attr) if _base else node.attr
    return ''


def _layer(rel: str) -> str:
    _top = rel.replace('\\', '/').split('/', 1)[0]
    return _top if _top in LAYERS else ''


def check_file(path: str, rel: str) -> List[Finding]:
    _layer_name = _layer(rel)
    if not _layer_name:
        return []
    try:
        with open(path, encoding='utf-8') as _f:
            _tree = ast.parse(_f.read(), filename=path)
    except (OSError, SyntaxError, ValueError) as exc:
        return [Finding(rel, getattr(exc, 'lineno', 0) or 0, 'unreadable', str(exc))]
    _out = []

    def _add(node, rule, message):
        _out.append(Finding(rel, getattr(node, 'lineno', 0), rule, message))

    for _node in ast.walk(_tree):
        if _layer_name in NO_JUDGEMENTS:
            if isinstance(_node, ast.Assert):
                _add(_node, 'judgement', 'assert in {}/: judgements belong in tests/'.format(_layer_name))
            elif isinstance(_node, ast.Call):
                _fn = _name(_node.func)
                _last = _fn.rsplit('.', 1)[-1]
                # expect() only as Playwright's bare function: pexpect's
                # child.expect(...) is not a judgement
                _bare_expect = isinstance(_node.func, ast.Name) and _node.func.id == 'expect'
                if _last in JUDGING_CALLS or _bare_expect or _fn in ('pytest.raises', 'pytest.warns') \
                        or _last == 'matches_golden':
                    _add(_node, 'judgement', '{}() in {}/: judgements belong in tests/'.format(
                        _fn, _layer_name))
        if isinstance(_node, ast.Call) and _layer_name in NO_SLEEP \
                and _name(_node.func).rsplit('.', 1)[-1] in SLEEPS:
            _add(_node, 'sleep', 'a fixed wait in {}/: wait for the condition instead -- '
                                 'eventually() in a case, locator.wait_for() or '
                                 'page.wait_for_url() in a page'.format(_layer_name))
        # conftest.py is where a login provider lives, and it may use requests
        if _layer_name == 'tests' and os.path.basename(rel) != 'conftest.py':
            if isinstance(_node, ast.Import) and any(_a.name.split('.')[0] == 'requests' for _a in _node.names):
                _add(_node, 'requests', 'tests/ imports requests: call the API classes in apis/, '
                                        'so the request is recorded and authenticated')
            elif isinstance(_node, ast.ImportFrom) and not _node.level \
                    and (_node.module or '').split('.')[0] == 'requests':
                _add(_node, 'requests', 'tests/ imports from requests: call the API classes in apis/')
        if _layer_name == 'apis' and isinstance(_node, ast.Constant) and isinstance(_node.value, str) \
                and _URL.match(_node.value.strip()):
            _add(_node, 'address', 'a fixed address in apis/ ({}): take it from conf/<env>.yaml or a '
                                   'constructor argument'.format(_node.value.strip()[:60]))
    return _out


def check(root: str = '.') -> List[Finding]:
    """Every finding under the project at `root`, in path and line order."""
    _root = os.path.abspath(root)
    _out = []
    for _layer_name in LAYERS:
        _dir = os.path.join(_root, _layer_name)
        if not os.path.isdir(_dir):
            continue
        for _base, _dirs, _files in os.walk(_dir):
            _dirs[:] = sorted(_d for _d in _dirs if _d != '__pycache__' and not _d.startswith('.'))
            for _file in sorted(_files):
                if _file.endswith('.py'):
                    _path = os.path.join(_base, _file)
                    _out.extend(check_file(_path, os.path.relpath(_path, _root)))
    return sorted(_out, key=lambda _f: (_f.path, _f.line, _f.rule))
