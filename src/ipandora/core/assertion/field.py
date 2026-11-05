# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : field.py
@Time  : 2026-11-05

A value under test that compares with plain Python operators and yields a
Check instead of a bool:

    assert_all(
        status_ok(r),
        field(r, 'data.fee') >= 0,
        field(r, 'data.fee') <= 100,
        field(r, 'data.status').is_in(['ok', 'pending']),
        field(r, 'data.version').matches(r'^\\d+\\.\\d+\\.\\d+$'),
        field(r, 'data.items').len() > 0,
    )

This replaced `json_matches(r, 'data.fee', {'$gte': 0})`, a MongoDB-style
operator dict inherited from ResponseHandler.filter. Tests here are Python;
Python already has operators. What a bare `assert` lacks is not operators but
the rest of a Check -- it stops at the first failure, a missing field raises
instead of failing, and the evidence is whatever pytest's rewriter prints.
Field keeps the operators and the Check.

Comparisons are strict, because a test framework that guesses hides bugs:

- A value is compared as what it is. The JSON string "12" is not greater than
  9 -- an API that started returning numbers as strings changed its contract,
  and that is a finding, not something to coerce away.
- bool is not a number. Python says True == 1; an API returning `true` where
  `1` was expected (or the reverse) changed its contract too.
- Anything that cannot be compared -- a missing field, mismatched types, an
  invalid regex -- is a failed Check that says why. Never an exception: one
  raising judgement would hide every other judgement in the same assert_all.

Chained comparison works: `0 <= field(r, 'x') <= 100` gives the right
verdict, because a Check is truthy exactly when it passed. It reports only
the bound that failed (or, when both hold, the upper one); write two checks
when you want both in the evidence.
"""
import operator
import re
from decimal import Decimal
from typing import Any, Iterable

from ipandora.core.assertion.check import Check, Source, brief
from ipandora.core.assertion.jsonpath import MISSING
from ipandora.utils.match import same

_SYMBOL = {operator.lt: '<', operator.le: '<=', operator.gt: '>', operator.ge: '>='}


def _is_number(value) -> bool:
    # bool is an int subclass; it is excluded on purpose, see the module doc
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


class Field:
    """
    One value read out of a response, waiting to be judged.

    Every operator and method returns a Check. Build one with `field()`.
    """

    __hash__ = None  # __eq__ returns a Check, so a Field cannot be a dict key

    def __init__(self, label: str, value: Any, reason: str = '', name: str = None,
                 src: str = Source.API):
        self._label = label
        self._value = value
        self._reason = reason
        self._name = name
        self._src = src

    # -- plumbing ---------------------------------------------------------

    def _check(self, claim: str, ok: bool, expr: str) -> Check:
        return Check(name=self._name or '{} {}'.format(self._label, claim),
                     ok=ok, expr=expr, src=self._src)

    def _judge(self, claim: str, test, expected_text: str) -> Check:
        """Run `test(value)`; turn a missing value or a TypeError into a failure."""
        if self._value is MISSING:
            return self._check(claim, False, self._reason)
        try:
            _ok = bool(test(self._value))
        except (TypeError, ValueError, re.error) as exc:
            return self._check(claim, False, '{} = {}: {}'.format(
                self._label, brief(self._value), exc))
        return self._check(claim, _ok, '{} = {} (expected {})'.format(
            self._label, brief(self._value), expected_text))

    def _order(self, op, operand) -> Check:
        _claim = '{} {}'.format(_SYMBOL[op], brief(operand, 60))

        def _test(value):
            if _is_number(operand):
                if not _is_number(value):
                    raise TypeError('expected a number, got {}'.format(type(value).__name__))
            elif isinstance(operand, str):
                if not isinstance(value, str):
                    raise TypeError('expected a string, got {}'.format(type(value).__name__))
            else:
                raise TypeError('cannot order by a {}'.format(type(operand).__name__))
            return op(value, operand)
        return self._judge(_claim, _test, _claim)

    def __bool__(self):
        raise TypeError(
            'a field is not a judgement by itself: compare it -- '
            'field(r, path) > 0 -- or use json_has() to check it exists')

    # -- operators --------------------------------------------------------

    def __eq__(self, other) -> Check:
        _claim = '== {}'.format(brief(other, 60))
        return self._judge(_claim, lambda v: same(v, other), brief(other))

    def __ne__(self, other) -> Check:
        _claim = '!= {}'.format(brief(other, 60))
        return self._judge(_claim, lambda v: not same(v, other), _claim)

    def __lt__(self, other) -> Check:
        return self._order(operator.lt, other)

    def __le__(self, other) -> Check:
        return self._order(operator.le, other)

    def __gt__(self, other) -> Check:
        return self._order(operator.gt, other)

    def __ge__(self, other) -> Check:
        return self._order(operator.ge, other)

    # -- named checks -----------------------------------------------------

    def is_in(self, options: Iterable) -> Check:
        _options = list(options)
        _claim = 'in {}'.format(brief(_options, 60))
        return self._judge(_claim, lambda v: any(same(v, _o) for _o in _options), _claim)

    def not_in(self, options: Iterable) -> Check:
        _options = list(options)
        _claim = 'not in {}'.format(brief(_options, 60))
        return self._judge(_claim, lambda v: not any(same(v, _o) for _o in _options), _claim)

    def contains(self, item) -> Check:
        """Substring for a string, element for a list, key for an object."""
        _claim = 'contains {}'.format(brief(item, 60))

        def _test(value):
            if isinstance(value, str):
                if not isinstance(item, str):
                    raise TypeError('a string can only contain a string')
                return item in value
            if isinstance(value, (list, tuple)):
                return any(same(_e, item) for _e in value)
            if isinstance(value, dict):
                return item in value
            raise TypeError('{} has no members'.format(type(value).__name__))
        return self._judge(_claim, _test, _claim)

    def startswith(self, prefix: str) -> Check:
        _claim = 'starts with {}'.format(brief(prefix, 60))

        def _test(value):
            if not isinstance(value, str):
                raise TypeError('expected a string, got {}'.format(type(value).__name__))
            return value.startswith(prefix)
        return self._judge(_claim, _test, _claim)

    def matches(self, pattern: str) -> Check:
        """re.search -- anchor with ^...$ for a whole-value match. Strings only."""
        _claim = 'matches {}'.format(brief(pattern, 60))

        def _test(value):
            if not isinstance(value, str):
                raise TypeError('expected a string, got {}'.format(type(value).__name__))
            return re.search(pattern, value) is not None
        return self._judge(_claim, _test, _claim)

    def len(self) -> 'Field':
        """The length, as a new field: `field(r, 'data.items').len() > 0`."""
        _label = 'len({})'.format(self._label)
        if self._value is MISSING:
            return Field(_label, MISSING, self._reason, self._name, self._src)
        try:
            return Field(_label, len(self._value), '', self._name, self._src)
        except TypeError:
            return Field(_label, MISSING, '{} = {} has no length'.format(
                self._label, brief(self._value)), self._name, self._src)

    def __repr__(self):
        return 'Field({}={})'.format(self._label, brief(self._value, 60))
