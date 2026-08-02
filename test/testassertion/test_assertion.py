# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_assertion.py
@Time  : 2026-08-01
"""
from decimal import Decimal

import pytest

from ipandora.core.assertion import (MISSING, Check, Source, assert_all, header_is,
                                     json_equals, json_has, json_matches, json_value,
                                     require, schema_conforms, status_is, status_ok)


class TestTheGapThisLayerCloses:
    """
    The framework had no assertion layer at all: status_code was only ever
    read to colour a log line, so a 500 passed silently. These are the tests
    that would have caught that.
    """

    def test_server_error_fails(self, make_response):
        resp = make_response(status_code=500, body={'error': 'boom'})
        assert not status_ok(resp).ok

    def test_server_error_raises_through_assert_all(self, make_response):
        resp = make_response(status_code=500, body={'error': 'boom'})
        with pytest.raises(AssertionError, match='500'):
            assert_all(status_ok(resp))

    @pytest.mark.parametrize('code', [200, 201, 204, 299])
    def test_2xx_passes(self, make_response, code):
        assert status_ok(make_response(status_code=code, body={})).ok

    @pytest.mark.parametrize('code', [199, 300, 301, 400, 404, 500, 503])
    def test_non_2xx_fails(self, make_response, code):
        assert not status_ok(make_response(status_code=code, body={})).ok


class TestCheckIsAValue:
    def test_building_a_failing_check_does_not_raise(self, make_response):
        resp = make_response(status_code=500, body={})
        check = status_ok(resp)
        assert check.ok is False
        assert '500' in check.expr

    def test_check_is_falsy_when_failed(self, make_response):
        assert not bool(status_ok(make_response(status_code=500, body={})))

    def test_str_carries_evidence(self, make_response):
        rendered = str(status_is(make_response(status_code=404, body={}), 200))
        assert 'FAIL' in rendered and '404' in rendered


class TestAssertAllReportsEverything:
    def test_all_failures_reported_not_just_first(self, make_response):
        resp = make_response(status_code=500, body={'data': {'id': 9}})
        with pytest.raises(AssertionError) as exc:
            assert_all(
                status_ok(resp),
                json_equals(resp, 'data.id', 1),
                json_has(resp, 'data.missing'),
            )
        message = str(exc.value)
        assert '3/3 checks failed' in message
        # every failure must be visible in one run
        assert '500' in message and 'data.id' in message and 'data.missing' in message

    def test_passes_are_listed_too(self, make_response):
        resp = make_response(status_code=200, body={'data': {'id': 1}})
        with pytest.raises(AssertionError) as exc:
            assert_all(status_ok(resp), json_equals(resp, 'data.id', 2))
        assert 'passed:' in str(exc.value)

    def test_returns_checks_when_all_pass(self, make_response):
        resp = make_response(body={'data': {'id': 1}})
        result = assert_all(status_ok(resp), json_equals(resp, 'data.id', 1))
        assert len(result) == 2

    def test_accepts_lists(self, make_response):
        resp = make_response(body={'data': {'id': 1}})
        assert_all([status_ok(resp), json_equals(resp, 'data.id', 1)])

    def test_rejects_bare_bool(self):
        # A check function returning True/False instead of a Check would
        # silently always pass. Fail loudly instead.
        with pytest.raises(TypeError, match='must return a Check'):
            assert_all(True)


class TestRequireSkipsRatherThanFails:
    """
    "The account had no balance" and "the code is wrong" must not look the
    same on a dashboard.
    """

    def test_unmet_precondition_skips(self):
        with pytest.raises(pytest.skip.Exception):
            require(Check(name='账号有余额', ok=False, expr='balance = 0'))

    def test_met_precondition_continues(self):
        assert len(require(Check(name='账号有余额', ok=True))) == 1


class TestJsonPath:
    def test_nested(self, make_response):
        resp = make_response(body={'data': {'user': {'name': 'alice'}}})
        assert json_equals(resp, 'data.user.name', 'alice').ok

    def test_array_index(self, make_response):
        resp = make_response(body={'items': [{'id': 1}, {'id': 2}]})
        assert json_equals(resp, 'items[1].id', 2).ok

    def test_negative_index(self, make_response):
        resp = make_response(body={'items': [{'id': 1}, {'id': 2}]})
        assert json_equals(resp, 'items[-1].id', 2).ok

    def test_missing_key_names_available_keys(self, make_response):
        resp = make_response(body={'data': {'id': 1, 'name': 'a'}})
        check = json_has(resp, 'data.nope')
        assert not check.ok
        assert 'nope' in check.expr and 'present:' in check.expr

    def test_index_out_of_range_is_explicit(self, make_response):
        resp = make_response(body={'items': [1]})
        check = json_has(resp, 'items[5]')
        assert not check.ok and 'out of range' in check.expr

    def test_present_but_null_counts_as_present(self, make_response):
        resp = make_response(body={'data': None})
        assert json_has(resp, 'data').ok
        assert json_equals(resp, 'data', None).ok


class TestPayloadShapesThatBrokeTheOldHandler:
    """
    ResponseHandler.fetch_all() returns ['code','data'] -- the key names --
    for a single-object payload, and raises TypeError on null/scalar data.
    The assertion layer reads the raw body instead, so these all work.
    """

    def test_single_object_payload(self, make_response):
        resp = make_response(body={'code': 0, 'data': {'id': 1, 'name': 'alice'}})
        assert_all(status_ok(resp),
                   json_equals(resp, 'code', 0),
                   json_equals(resp, 'data.name', 'alice'))

    def test_null_data(self, make_response):
        resp = make_response(body={'code': 0, 'data': None})
        assert_all(json_equals(resp, 'data', None))

    def test_scalar_data(self, make_response):
        resp = make_response(body={'code': 0, 'data': 5})
        assert_all(json_equals(resp, 'data', 5))

    def test_key_with_dash(self, make_response):
        # a key a namedtuple could never have held
        resp = make_response(body={'x-request-id': 'abc'})
        assert json_equals(resp, 'x-request-id', 'abc').ok

    def test_python_keyword_key(self, make_response):
        resp = make_response(body={'class': 'premium'})
        assert json_equals(resp, 'class', 'premium').ok

    def test_non_json_body_fails_clearly(self, make_response):
        resp = make_response(raw='<html>nope</html>')
        check = json_has(resp, 'data')
        assert not check.ok and 'not JSON' in check.expr

    def test_binary_body_fails_clearly(self, make_response):
        resp = make_response(raw=b'\x89PNG\r\n\x1a\n\xff\xfe')
        check = json_has(resp, 'data')
        assert not check.ok


class TestComparators:
    def test_gt(self, make_response):
        resp = make_response(body={'total': 10})
        assert json_matches(resp, 'total', {'$gt': 5}).ok
        assert not json_matches(resp, 'total', {'$gt': 50}).ok

    def test_in(self, make_response):
        resp = make_response(body={'status': 'ok'})
        assert json_matches(resp, 'status', {'$in': ['ok', 'pending']}).ok

    def test_contains(self, make_response):
        resp = make_response(body={'msg': 'operation succeeded'})
        assert json_matches(resp, 'msg', {'$contains': 'succeed'}).ok

    def test_unknown_operator_fails_loudly(self, make_response):
        resp = make_response(body={'total': 10})
        check = json_matches(resp, 'total', {'$nope': 1})
        assert not check.ok and 'unknown operator' in check.expr

    def test_comparator_exception_becomes_failed_check(self, make_response):
        # comparing a dict with $gt raises inside Compare; must not escape
        resp = make_response(body={'obj': {'a': 1}})
        check = json_matches(resp, 'obj', {'$gt': 5})
        assert not check.ok


class TestJsonValueForCustomChecks:
    """
    Custom checks must be able to read a field without risking an exception --
    one raising check would abort the run and hide every other failure.
    """

    def test_returns_value(self, make_response):
        value, err = json_value(make_response(body={'data': {'fee': '0.10'}}), 'data.fee')
        assert value == '0.10' and err == ''

    def test_missing_field_returns_reason_not_raise(self, make_response):
        value, err = json_value(make_response(body={'data': {}}), 'data.fee')
        assert value is MISSING and 'no key' in err

    def test_unparseable_body_returns_reason_not_raise(self, make_response):
        value, err = json_value(make_response(raw='<html/>'), 'data.fee')
        assert value is MISSING and 'not JSON' in err

    def test_custom_check_pattern_from_the_docs(self, make_response):
        def fee_within_cap(resp, cap):
            fee_raw, err = json_value(resp, 'data.fee')
            if err:
                return Check(name='手续费在上限内', ok=False, expr=err, src=Source.DERIVED)
            return Check(name='手续费在上限内', ok=Decimal(str(fee_raw)) <= cap,
                         expr='fee {} <= cap {}'.format(fee_raw, cap), src=Source.DERIVED)

        cap = Decimal('0.15')
        assert fee_within_cap(make_response(body={'data': {'fee': '0.10'}}), cap).ok
        assert not fee_within_cap(make_response(body={'data': {'fee': '0.99'}}), cap).ok
        # the shape that would have raised with body['fee']
        assert not fee_within_cap(make_response(body={'data': {}}), cap).ok


class TestHeadersAndSchema:
    def test_header(self, make_response):
        resp = make_response(body={}, headers={'Content-Type': 'application/json'})
        assert header_is(resp, 'Content-Type', 'application/json').ok
        assert not header_is(resp, 'Content-Type', 'text/html').ok

    def test_schema_conforms(self, make_response):
        schema = {'type': 'object',
                  'properties': {'id': {'type': 'integer'}},
                  'required': ['id']}
        assert schema_conforms(make_response(body={'id': 1}), schema).ok

    def test_schema_violation_points_at_the_field(self, make_response):
        schema = {'type': 'object',
                  'properties': {'id': {'type': 'integer'}},
                  'required': ['id']}
        check = schema_conforms(make_response(body={'id': 'not-an-int'}), schema)
        assert not check.ok and 'id' in check.expr

    def test_source_is_tagged(self, make_response):
        resp = make_response(body={'id': 1})
        assert status_ok(resp).src == Source.API
        assert json_has(resp, 'id').src == Source.SCHEMA


class TestWorksWithResponseHandler:
    """Checks must accept the object real tests actually hold."""

    def test_accepts_response_handler(self, make_response):
        from ipandora.core.protocol.http.model.handler.responsehandler import ResponseHandler
        raw = make_response(body={'code': 0, 'data': {'id': 7}})
        handler = ResponseHandler().inject(response=raw, content=raw.text)
        assert_all(status_ok(handler), json_equals(handler, 'data.id', 7))
