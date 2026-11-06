# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : match.py
# @Time  : 2024-04-17
"""
Equality as a test framework needs it.

This module used to hold Compare and DictMatcher: a MongoDB-style operator
language (`{'$gt': 5}`, `{'$in': [...]}`) behind json_matches and
ResponseHandler.filter. Tests here are Python, so both now take Python
instead -- `field(r, 'x') > 5` and `filter(lambda x: x['i'] > 5)` -- and the
operator language is gone. What is left is the one rule both still share.
"""


def same(a, b) -> bool:
    """
    `a == b`, except that a bool only ever equals a bool.

    Python says True == 1 and False == 0.0. An API that returns `true` where
    it used to return `1` has changed its contract, and a check that says
    "equal" there hides it.
    """
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    a, b = aligned(a, b)
    return a == b


def aligned(a, b):
    """
    A Decimal and a float made comparable: the float read the way it is written.

    Python compares Decimal('0.1') with the float 0.1 by the float's binary
    value, 0.1000000000000000055..., so `that(x).decimal() == 0.1` could never
    hold, and `<= 0.1` held for the wrong reason. Decimal(str(f)) is what the
    test author typed.
    """
    from decimal import Decimal
    if isinstance(a, Decimal) and isinstance(b, float):
        return a, Decimal(repr(b))
    if isinstance(b, Decimal) and isinstance(a, float):
        return Decimal(repr(a)), b
    return a, b
