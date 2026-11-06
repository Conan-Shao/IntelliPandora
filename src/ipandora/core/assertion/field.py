# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : field.py
@Time  : 2026-11-05

A value under test that compares with plain Python operators and yields a
Check instead of a bool:

    items = field(r, 'data.items')
    assert_all(
        status_ok(r),
        field(r, 'data.status').is_in(['ok', 'pending']),
        field(r, 'data.amount').decimal() > 0,         # "100.50" -> Decimal
        items.len() > 0,
        items.each('price').decimal() > 0,             # every element
        field(r, 'data.total').decimal() == items.map(
            lambda xs: sum(Decimal(x['price']) for x in xs), 'sum(price)'),
        that(db_row['state'], 'db.state') == 'PAID',   # any Python value
    )

Tests here are Python, and Python already has operators. What a bare
`assert` lacks is the rest of a Check -- it stops at the first failure, a
missing field raises instead of failing, and the evidence is whatever
pytest's rewriter prints. Field keeps the operators and the Check.

Comparisons are strict, because a test framework that guesses hides bugs:

- A value is compared as what it is. The JSON string "12" is not greater than
  9 -- an API that started returning numbers as strings changed its contract.
  Where strings are the contract (money often is), say so: `.decimal()`.
- bool is not a number. Python says True == 1; an API returning `true` where
  `1` was expected (or the reverse) changed its contract too.
- Anything that cannot be judged -- a missing field, mismatched types, an
  invalid regex, a `.map()` function that raised -- is a failed Check that
  says why. Never an exception: one raising judgement would hide every other
  judgement in the same assert_all.

Chained comparison works: `0 <= field(r, 'x') <= 100` gives the right
verdict, because a Check is truthy exactly when it passed. It reports only
the bound that failed (or, when both hold, the upper one); write two checks
when you want both in the evidence.
"""
import operator
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, List

from ipandora.core.assertion.check import Check, Source, brief
from ipandora.core.assertion.jsonpath import MISSING, resolve
from ipandora.utils.match import aligned, same

_SYMBOL = {operator.lt: '<', operator.le: '<=', operator.gt: '>', operator.ge: '>='}

# what a judgement or a transform may raise and still be "a failed check"
_UNJUDGEABLE = (TypeError, ValueError, ArithmeticError, re.error)

# how many failing elements an each() check spells out before summarising
_EACH_SHOWN = 3


def _is_number(value) -> bool:
    # bool is an int subclass; it is excluded on purpose, see the module doc
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _to_decimal(value) -> Decimal:
    if isinstance(value, bool):
        raise TypeError('expected a number, got bool')
    if isinstance(value, Decimal):
        _d = value
    elif isinstance(value, (int, float)):
        _d = Decimal(str(value))      # str(): 0.1 -> Decimal('0.1'), not 0.1000000000000000055
    elif isinstance(value, str):
        if '_' in value:
            # Decimal('1_000') is 1000 -- Python literal syntax, not a number
            # any API sends. Accepting it would let a malformed amount pass.
            raise ValueError('not a number: {!r}'.format(value))
        try:
            _d = Decimal(value.strip())
        except InvalidOperation:
            raise ValueError('not a number: {!r}'.format(value)) from None
    else:
        raise TypeError('expected a number or numeric string, got {}'.format(
            type(value).__name__))
    if not _d.is_finite():
        raise ValueError('not a finite number: {!r}'.format(value))
    return _d


class Field:
    """
    One value waiting to be judged. Build one with `field()` or `that()`.

    Every operator and named check returns a Check. `.decimal()`, `.len()`,
    `.map()` and `.each()` return another Field.
    """

    __hash__ = None  # __eq__ returns a Check, so a Field cannot be a dict key

    def __init__(self, label: str, value: Any, reason: str = '', name: str = None,
                 src: str = Source.API):
        self._label = label
        self._value = value
        self._reason = reason
        self._name = name
        self._src = src

    def _like(self, label: str, value: Any, reason: str = '') -> 'Field':
        return Field(label, value, reason, self._name, self._src)

    # -- the two primitives everything else goes through ------------------

    def _judge(self, claim: str, test: Callable, expected: str, blocked: str = '') -> Check:
        """
        Apply `test` to the value. `blocked` is why the *expected* side could
        not be read (a Field operand that is itself missing).
        """
        _claim = '{} {}'.format(self._label, claim)
        _ok, _expr = self._verdict(test, expected, blocked)
        return Check(name=self._name or _claim, ok=_ok, expr=_expr, src=self._src,
                     claim=_claim)

    def _verdict(self, test, expected, blocked):
        if self._value is MISSING:
            return False, self._reason
        if blocked:
            return False, 'cannot compare {}: {}'.format(self._label, blocked)
        try:
            _ok = bool(test(self._value))
        except _UNJUDGEABLE as exc:
            return False, '{} = {}: {}'.format(self._label, brief(self._value), exc)
        return _ok, '{} = {} (expected {})'.format(self._label, brief(self._value), expected)

    def _derive(self, label: str, transform: Callable, catch=_UNJUDGEABLE) -> 'Field':
        """A new Field holding transform(value); a raise becomes a missing value."""
        if self._value is MISSING:
            return self._like(label, MISSING, self._reason)
        try:
            return self._like(label, transform(self._value))
        except catch as exc:
            return self._like(label, MISSING, '{} = {}: {}: {}'.format(
                self._label, brief(self._value), type(exc).__name__, exc))

    # -- operators --------------------------------------------------------

    @staticmethod
    def _operand(other):
        """(value, how to show it, why it is unavailable) -- unwraps a Field."""
        if isinstance(other, Field):
            if other._value is MISSING:
                return MISSING, other._label, other._reason
            return other._value, '{} = {}'.format(other._label, brief(other._value)), ''
        return other, brief(other), ''

    @staticmethod
    def _claim_text(other) -> str:
        return other._label if isinstance(other, Field) else brief(other, 60)

    def __eq__(self, other) -> Check:
        _value, _shown, _blocked = self._operand(other)
        return self._judge('== {}'.format(self._claim_text(other)),
                           lambda v: same(v, _value), _shown, _blocked)

    def __ne__(self, other) -> Check:
        _value, _shown, _blocked = self._operand(other)
        return self._judge('!= {}'.format(self._claim_text(other)),
                           lambda v: not same(v, _value), '!= {}'.format(_shown), _blocked)

    def _order(self, op, other) -> Check:
        _value, _shown, _blocked = self._operand(other)
        _claim = '{} {}'.format(_SYMBOL[op], self._claim_text(other))

        def _test(value):
            if _is_number(_value):
                if not _is_number(value):
                    raise TypeError('expected a number, got {}'.format(type(value).__name__))
            elif isinstance(_value, str):
                if not isinstance(value, str):
                    raise TypeError('expected a string, got {}'.format(type(value).__name__))
            else:
                raise TypeError('cannot order by a {}'.format(type(_value).__name__))
            return op(*aligned(value, _value))
        return self._judge(_claim, _test, '{} {}'.format(_SYMBOL[op], _shown), _blocked)

    def __lt__(self, other) -> Check:
        return self._order(operator.lt, other)

    def __le__(self, other) -> Check:
        return self._order(operator.le, other)

    def __gt__(self, other) -> Check:
        return self._order(operator.gt, other)

    def __ge__(self, other) -> Check:
        return self._order(operator.ge, other)

    def __bool__(self):
        raise TypeError(
            'a field is not a judgement by itself: compare it -- '
            'field(r, path) > 0 -- or use json_has() to check it exists')

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

    def matches_golden(self, name: str, tolerance: float = 0.0, mask=(), threshold: float = 0.1,
                       noise: str = 'edges') -> Check:
        """
        This image looks like its golden image: `that(page.screenshot(), '结算页')
        .matches_golden('checkout')`. The value is PNG bytes, a path or a PIL
        image. See core/assertion/visual.py for what it can and cannot see.
        """
        from ipandora.core.assertion import visual
        if self._value is MISSING:
            return Check(name=self._name or '{} matches golden {!r}'.format(self._label, name),
                         ok=False, expr=self._reason, src=Source.VISUAL,
                         claim='{} matches golden {!r}'.format(self._label, name))
        return visual.matches_golden(self._value, name, label=self._label, tolerance=tolerance,
                                     mask=mask, threshold=threshold, noise=noise,
                                     check_name=self._name)

    # -- transforms: each returns a new Field -----------------------------

    def len(self) -> 'Field':
        """The length: `field(r, 'data.items').len() > 0`."""
        return self._derive('len({})'.format(self._label), len)

    def decimal(self) -> 'Field':
        """
        The value as an exact Decimal, from a number or a numeric string.

        Comparison is strict, so "100.50" > 0 fails as a type mismatch. Where
        the API sends numbers as strings on purpose -- money, mostly -- this
        is how a test says so. A value that is not a number fails the check.
        """
        return self._derive(self._label, _to_decimal)

    def map(self, fn: Callable, label: str = None) -> 'Field':
        """
        Any computation over the value, as a new Field:

            items.map(lambda xs: sum(x['qty'] for x in xs), 'total qty') == 3

        Whatever `fn` raises -- a KeyError on an item missing a key included
        -- becomes a failed check carrying the exception, not a crash.
        """
        return self._derive(label or '{}({})'.format(
            getattr(fn, '__name__', 'f').replace('<lambda>', 'f'), self._label),
            fn, catch=Exception)

    def each(self, path: str = None, allow_empty: bool = False) -> 'Each':
        """
        Every element of a list, judged together:

            field(r, 'data.items').each('price') > 0
            field(r, 'data.tags').each().matches(r'^[a-z]+$')

        One Check comes out, naming the elements that failed. An empty list
        fails unless `allow_empty=True`: "every item is valid" holding over
        zero items is the vacuous pass that hides a broken query.
        """
        _label = '{}[*]{}'.format(self._label, '.' + path if path else '')
        if self._value is MISSING:
            return Each(_label, [], self._reason, self._name, self._src, allow_empty)
        if not isinstance(self._value, (list, tuple)):
            return Each(_label, [], '{} = {} is not a list'.format(
                self._label, brief(self._value)), self._name, self._src, allow_empty)
        _items = []
        for _i, _element in enumerate(self._value):
            _item_label = '{}[{}]{}'.format(self._label, _i, '.' + path if path else '')
            if path:
                _v, _why = resolve(_element, path)
                _items.append(Field(_item_label, _v, '{}: {}'.format(_item_label, _why)
                                    if _why else '', None, self._src))
            else:
                _items.append(Field(_item_label, _element, '', None, self._src))
        return Each(_label, _items, '', self._name, self._src, allow_empty)

    def __repr__(self):
        return 'Field({}={})'.format(self._label, brief(self._value, 60))


class Each(Field):
    """
    A Field standing for every element of a list. Judgements apply to each
    element and fold into one Check; transforms apply to each element and
    return another Each.
    """

    def __init__(self, label: str, items: List[Field], reason: str = '', name: str = None,
                 src: str = Source.API, allow_empty: bool = False):
        super().__init__(label, MISSING if reason else items, reason, name, src)
        self._items = items
        self._allow_empty = allow_empty

    def _judge(self, claim, test, expected, blocked=''):
        _claim = '{} {}'.format(self._label, claim)
        _name = self._name or _claim
        if self._reason:
            return Check(name=_name, ok=False, expr=self._reason, src=self._src, claim=_claim)
        if not self._items:
            return Check(name=_name, ok=self._allow_empty, claim=_claim,
                         expr='no items' + ('' if self._allow_empty else
                                            ' -- nothing was checked (allow_empty=True if '
                                            'an empty list is valid)'),
                         src=self._src)
        _failures = []
        for _item in self._items:
            _ok, _expr = _item._verdict(test, expected, blocked)
            if not _ok:
                _failures.append(_expr)
        _total = len(self._items)
        if not _failures:
            return Check(name=_name, ok=True, claim=_claim,
                         expr='all {} items {}'.format(_total, claim), src=self._src)
        _shown = '; '.join(_failures[:_EACH_SHOWN])
        _more = ' (+{} more)'.format(len(_failures) - _EACH_SHOWN) \
            if len(_failures) > _EACH_SHOWN else ''
        return Check(name=_name, ok=False, src=self._src, claim=_claim,
                     expr='{} of {} items failed: {}{}'.format(
                         len(_failures), _total, _shown, _more))

    def _derive(self, label, transform, catch=_UNJUDGEABLE):
        if self._reason:
            return Each(label, [], self._reason, self._name, self._src, self._allow_empty)
        return Each(label, [_i._derive(self._item_label(_i, label), transform, catch)
                            for _i in self._items],
                    '', self._name, self._src, self._allow_empty)

    def _item_label(self, item: Field, new_label: str) -> str:
        # carry the element's own index into the transformed label:
        # len(items[*].tags) -> len(items[2].tags)
        return new_label.replace(self._label, item._label, 1)

    def each(self, path=None, allow_empty=False):
        raise TypeError('each() of each() is not supported; use .map() on the element')

    def __repr__(self):
        return 'Each({}, {} items)'.format(self._label, len(self._items))


def that(value: Any, label: str = 'value', name: str = None,
         src: str = Source.DERIVED) -> Field:
    """
    Judge any Python value the same way as a response field:

        that(db_row['state'], 'db.state') == 'PAID'
        that(len(page_rows), 'rendered rows') == field(r, 'data.total')

    For values the test computed or fetched itself -- a database row, a
    second API, text read off a page.
    """
    return Field(label, value, '', name=name, src=src)
