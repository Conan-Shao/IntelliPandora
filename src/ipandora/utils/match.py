# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : match.py
# @Time  : 2024-04-17
import logging
import re
from abc import ABCMeta, abstractmethod

logger = logging.getLogger(__name__)
basetype = int, float, bytes, bytearray, str, bool


class Compare(object):
    """
    The comparators behind json_matches and ResponseHandler.filter.

    `a` is the value found in the response, `b` the operand the test wrote.
    A comparator that cannot apply -- a non-numeric value under `$gt`, a
    non-string under `$regex`, an invalid pattern -- raises, and the assertion
    layer turns that into a failed check carrying the reason. It never quietly
    answers True or False on input it could not interpret.
    """

    def __init__(self, a=None, b=None):
        self._b = b
        self._a = a

    @staticmethod
    def method_for(operator) -> str:
        """
        The comparator method name for `$op`, or '' if there is none.

        Both callers used to do `op.replace('$', 'cmp_')` and check hasattr.
        A key without a `$` therefore became an attribute name verbatim:
        `{'__class__': 5}` constructed a new Compare, which is truthy, and the
        check passed on any value -- an unknown operator succeeding silently.
        `{'_coerced': 5}` would do the same through the helper below. Only `$`
        keys that name a real `cmp_` method are operators.
        """
        _op = str(operator)
        if not _op.startswith('$') or len(_op) < 2:
            return ''
        _method = 'cmp_' + _op[1:]
        return _method if callable(getattr(Compare, _method, None)) else ''

    def _coerced(self):
        """
        (a, b) made comparable, by the operand's type.

        A numeric operand compares the value as a number, so a JSON string "5"
        still matches 5. It used to be `int(float(a))` whenever the operand was
        an int -- which truncated the value before comparing: `{'$eq': 5}`
        passed on 5.9, `{'$eq': 0}` passed on -0.5, and `{'$gt': 0}` failed on
        0.9, so a check that an amount was positive rejected a valid one. The
        value is converted with float(), never truncated.

        Booleans are not numbers here, in either direction. bool is an int
        subclass, so float(True) would make `{'$eq': 1}` match `true`; and a
        bool operand used to convert with bool(), under which every non-empty
        value is True -- `{'$eq': True}` matched 1, 'yes' and the string
        'false'. Each now raises, so the check fails and says why.

        Any other operand type converts the value to that type, as before.
        """
        _a, _b = self._a, self._b
        if isinstance(_b, bool):
            if not isinstance(_a, bool):
                raise TypeError('expected a boolean, got {} {!r}'.format(
                    type(_a).__name__, _a))
            return _a, _b
        if isinstance(_b, (int, float)):
            if isinstance(_a, bool):
                raise TypeError('expected a number, got boolean {!r}'.format(_a))
            return float(_a), _b
        return type(_b)(_a), _b

    def cmp_in(self):
        return self._a in self._b

    def cmp_notIn(self):
        return self._a not in self._b

    def cmp_eq(self):
        _a, _b = self._coerced()
        return _a == _b

    def cmp_gt(self):
        _a, _b = self._coerced()
        return _a > _b

    def cmp_gte(self):
        _a, _b = self._coerced()
        return _a >= _b

    def cmp_lt(self):
        _a, _b = self._coerced()
        return _a < _b

    def cmp_lte(self):
        _a, _b = self._coerced()
        return _a <= _b

    def cmp_startWith(self):
        return str(self._a).startswith(str(self._b))

    def cmp_contains(self):
        return str(self._b).lower() in str(self._a).lower()

    def cmp_regex(self):
        """
        True when the pattern is found anywhere in the value (re.search).

        Anchor it yourself for a whole-value match: `^\\d+\\.\\d+$`. Only
        strings are matched -- a number is not silently stringified, because
        `{'$regex': '^5'}` matching 5.9 would be the same kind of quiet
        coercion the ordering comparators just stopped doing.
        """
        if not isinstance(self._a, str):
            raise TypeError('$regex only applies to strings, got {}'.format(
                type(self._a).__name__))
        return re.search(str(self._b), self._a) is not None

    # NOTE: comparators here must stay deterministic and offline.
    # An LLM-backed `cmp_semantic` was removed deliberately -- calling a model
    # from the assertion path makes every assertion a paid, latent, non-
    # reproducible network call. See docs/design/03-LLM接入边界.md.


class Matcher(metaclass=ABCMeta):
    def __init__(self, superset: dict = None):
        self._super_dict = superset
        self._condition = None

    def condition(self, condition=None):
        self._condition = condition
        return self

    @abstractmethod
    def match(self) -> bool:
        pass


class DictMatcher(Matcher):

    def match(self) -> bool:
        if self._condition is None:
            return True

        if not isinstance(self._condition, dict):
            raise ValueError(
                'condition must be dict {}'.format(self._condition))

        for _k, _v in self._condition.items():
            if _k not in self._super_dict:
                return False

            if isinstance(_v, basetype):
                if str(_v) != str(self._super_dict.get(_k, '')):
                    return False

            elif isinstance(_v, dict):
                for _e_k, _e_v in _v.items():
                    _method = Compare.method_for(_e_k)
                    if not _method:
                        return False
                    if not getattr(Compare(a=self._super_dict.get(_k), b=_e_v),
                                   _method)():
                        return False

            else:
                raise ValueError(
                    u'compare value must be basetype or dict, {}/{}'.format(
                        type(_v), _v))

        return True