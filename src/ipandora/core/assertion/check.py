# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : check.py
@Time  : 2026-08-01
"""
import re
from dataclasses import dataclass


class Source:
    """
    Where a judgement came from. Lets a report group failures by kind, and
    makes it obvious when a suite only ever checks one dimension.

    These are the dimensions any system has. `Check.src` is a plain string and
    is never validated against this list, so a business suite can tag its own
    -- `src='onchain'`, `src='ledger'` -- and the report groups by it all the
    same. That is where domain dimensions belong: in the suite that knows the
    domain, not in the framework. ONCHAIN used to live here, a Web3 concept
    hardcoded into a general-purpose assertion layer.
    """
    API = 'api'
    """The interface answered as expected: status, envelope."""
    SCHEMA = 'schema'
    """The response has the agreed shape."""
    DERIVED = 'derived'
    """The business result is right -- the value, not just its presence."""
    AUTHZ = 'authz'
    """Who may do what: the request was allowed or refused correctly."""
    ASSERT = 'assert'
    """
    A plain pytest `assert` (or pytest.raises / pytest.warns), recorded by the
    runner. What it checks is not known beyond its source text, so it gets
    a dimension of its own rather than being guessed into one of the above.
    """


class Kind:
    """
    What a Check is claiming.

    ASSERT is a judgement the run actually made. GAP is the opposite: a
    judgement the run *should* make and does not -- declared by hand against a
    requirement, because no run can report an assertion nobody wrote.

    Keeping gaps in the same list as real checks is the point. A case showing
    "5 passed" reads as thorough; the same case showing "5 passed, 3 not
    covered" reads as what it is. Gaps never fail a run -- they are a statement
    about the suite, not about the system.
    """
    ASSERT = 'assert'
    GAP = 'gap'


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
    claim: what is being asserted, in a stable form -- `data.fee <= 100`.
          Unlike `name` it does not change when someone gives the check a
          friendlier label, so it is what the judgement inventory compares
          between runs (core/runner/inventory.py). Empty means "same as name",
          which is right for a hand-built Check whose name is the claim.
    """
    name: str
    ok: bool
    expr: str = ''
    src: str = Source.DERIVED
    kind: str = Kind.ASSERT
    claim: str = ''

    @property
    def is_gap(self) -> bool:
        return self.kind == Kind.GAP

    @property
    def subject(self) -> str:
        """The claim, falling back to the name."""
        return self.claim or self.name

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        _mark = 'GAP' if self.is_gap else ('PASS' if self.ok else 'FAIL')
        _detail = ' | {}'.format(self.expr) if self.expr else ''
        return '[{}] {} ({}){}'.format(_mark, self.name, self.src, _detail)


MAX_VALUE_CHARS = 240
"""
How much of a value may appear in a Check's evidence.

Without a cap this is not a cosmetic issue. Asserting against a field that
happens to hold a large object -- PyPI's `releases` map, a search result page,
an embedded document -- produced a 195,000-character assertion message, which
then flows verbatim into the console, the HTML report and the failure-triage
prompt. The last of those is billed per token.

240 is enough to see a short value in full and to recognise the shape of a
large one.
"""


_TRAILING_TOKEN = re.compile(r'[A-Za-z0-9+/=_-]+$')


def brief(value, limit: int = MAX_VALUE_CHARS) -> str:
    """
    A value rendered for a failure message: complete when small, and honest
    about what was cut when not.

    The suffix carries the size, so a truncated value still answers "was this
    empty, or huge?" -- which is usually the question being asked.

    The cut never lands inside an opaque token. Report redaction matches whole
    credential shapes (a 64-char hex string, a JWT), so a value sliced through
    the middle stops matching and the surviving prefix is published in the
    clear -- turning a `***REDACTED***` into 20 real characters of somebody's
    key. Backing the cut off to the start of the run is what keeps truncation
    from quietly undoing redaction.
    """
    _text = repr(value)
    if len(_text) <= limit:
        return _text

    _head = _text[:limit]
    _next = _text[limit:limit + 1]
    if _next and _TRAILING_TOKEN.search(_next):
        # the boundary is inside a run -- drop the part of it we kept
        _head = _TRAILING_TOKEN.sub('', _head)

    _shape = type(value).__name__
    if isinstance(value, (dict, list, tuple, set, str, bytes)):
        _shape = '{} of {}'.format(_shape, len(value))
    return '{}… (truncated; {}, {} chars)'.format(_head, _shape, len(_text))


def passed(name: str, expr: str = '', src: str = Source.DERIVED) -> Check:
    """Shorthand for a check that holds."""
    return Check(name=name, ok=True, expr=expr, src=src)


def failed(name: str, expr: str = '', src: str = Source.DERIVED) -> Check:
    """Shorthand for a check that does not hold."""
    return Check(name=name, ok=False, expr=expr, src=src)


def gap(name: str, expr: str = '', src: str = Source.DERIVED) -> Check:
    """
    Declare a judgement this test *ought* to make and does not.

        assert_all(
            status_ok(r),
            json_equals(r, 'data.status', 'SUCCESS'),
            gap('订单实际落库', '只校验了接口返回，没有查数据库里的记录'),
        )

    Passing a gap to assert_all is safe: it cannot fail the run. It exists so
    the report can say what this test does not cover, next to what it does --
    which is the only place anyone will actually read it.
    """
    return Check(name=name, ok=True, expr=expr, src=src, kind=Kind.GAP)
