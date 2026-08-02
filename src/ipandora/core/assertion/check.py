# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : check.py
@Time  : 2026-08-01
"""
from dataclasses import dataclass


class Source:
    """
    Where a judgement came from. Lets a report group failures by kind, and
    makes it obvious when a suite only ever checks one dimension.
    """
    API = 'api'
    SCHEMA = 'schema'
    DERIVED = 'derived'
    AUTHZ = 'authz'
    ONCHAIN = 'onchain'


@dataclass(frozen=True)
class Check:
    """
    One judgement about the system under test.

    A check is a *value*, not an exception. Building it never raises, so a
    test can evaluate every judgement and report all failures at once instead
    of stopping at the first one. `assert_all` is what turns checks into a
    test failure.

    name: human-readable, shown as-is in reports. Write it for the person
          reading a red build, not for the code.
    ok:   whether the judgement holds.
    expr: the evidence. On failure this has to be enough to understand what
          went wrong without opening the logs -- put the actual and expected
          values in it.
    src:  which dimension this judgement covers, see `Source`.
    """
    name: str
    ok: bool
    expr: str = ''
    src: str = Source.DERIVED

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        _mark = 'PASS' if self.ok else 'FAIL'
        _detail = ' | {}'.format(self.expr) if self.expr else ''
        return '[{}] {} ({}){}'.format(_mark, self.name, self.src, _detail)


def passed(name: str, expr: str = '', src: str = Source.DERIVED) -> Check:
    """Shorthand for a check that holds."""
    return Check(name=name, ok=True, expr=expr, src=src)


def failed(name: str, expr: str = '', src: str = Source.DERIVED) -> Check:
    """Shorthand for a check that does not hold."""
    return Check(name=name, ok=False, expr=expr, src=src)
