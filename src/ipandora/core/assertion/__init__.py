# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __init__.py
@Time  : 2026-08-01

Assertion layer.

A check is a value, not an exception. Test code builds every judgement it
cares about, then hands them to `assert_all`, which fails once and lists
everything that is wrong:

    from ipandora.core.assertion import assert_all, status_ok, json_equals

    resp = SomeApi().get_user(uid=1)
    assert_all(
        status_ok(resp),
        json_equals(resp, 'data.id', 1),
        json_equals(resp, 'data.name', 'alice'),
    )

Preconditions use `require` instead, which skips rather than fails -- "the
fixture had no data" must not look like "the code is broken".
"""
from ipandora.core.assertion.check import (Check, Kind, Source, brief, failed, gap,
                                           passed)
from ipandora.core.assertion.collector import assert_all, require
from ipandora.core.assertion.http import (header_is, json_body, json_equals, json_has,
                                          json_matches, json_value, raw_response,
                                          schema_conforms, status_code, status_is, status_ok)
from ipandora.core.assertion.jsonpath import MISSING, resolve

__all__ = [
    'Kind', 'gap', 'brief',
    'Check', 'Source', 'passed', 'failed',
    'assert_all', 'require',
    'status_ok', 'status_is', 'header_is',
    'json_has', 'json_equals', 'json_matches', 'schema_conforms',
    # building blocks for custom checks
    'json_value', 'json_body', 'status_code', 'raw_response',
    'resolve', 'MISSING',
]
