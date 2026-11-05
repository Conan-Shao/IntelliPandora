# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_assertion.py
@Time  : 2026-08-01
"""
from decimal import Decimal

import pytest

from ipandora.core.assertion import (MISSING, Check, Source, assert_all, header_is, that,
                                     field, json_equals, json_has, json_value,
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
    "The test account was never provisioned" and "the code is wrong" must not look the
    same on a dashboard.
    """

    def test_unmet_precondition_skips(self):
        with pytest.raises(pytest.skip.Exception):
            require(Check(name='测试账号已开通', ok=False, expr='provisioned = false'))

    def test_met_precondition_continues(self):
        assert len(require(Check(name='测试账号已开通', ok=True))) == 1


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


class TestPathFormsRealApisRequire:
    """
    Both of these came out of driving the layer at pypi.org and
    registry.npmjs.org -- neither is hypothetical.
    """

    def test_bare_number_indexes_a_list(self, make_response):
        # `items.0.id` is how most people write it, and it used to be read as
        # the string key '0', failing with "expected an object, found list" --
        # a message that points away from the actual mistake.
        resp = make_response(body={'items': [{'id': 1}, {'id': 2}]})
        assert json_equals(resp, 'items.0.id', 1).ok
        assert json_equals(resp, 'items.-1.id', 2).ok

    def test_bare_number_still_reads_as_a_key_on_an_object(self, make_response):
        # Numeric-looking keys are ordinary in real documents, so the bare form
        # has to mean whichever the node actually supports.
        resp = make_response(body={'counts': {'0': 'zero', '1': 'one'}})
        assert json_equals(resp, 'counts.0', 'zero').ok

    def test_quoted_key_reaches_a_key_containing_dots(self, make_response):
        # PyPI keys its releases by version string, so `releases.2.32.0` cannot
        # work -- without a quoted form the field is unreachable at all.
        resp = make_response(body={'releases': {'2.32.0': [{'filename': 'x.whl'}]}})
        assert json_equals(resp, "releases['2.32.0'][0].filename", 'x.whl').ok
        assert json_equals(resp, 'releases["2.32.0"].0.filename', 'x.whl').ok

    def test_quoted_key_is_not_split_on_its_dots(self, make_response):
        resp = make_response(body={'a.b': {'c': 1}, 'a': {'b': {'c': 2}}})
        assert json_equals(resp, "['a.b'].c", 1).ok
        assert json_equals(resp, 'a.b.c', 2).ok

    def test_entering_a_list_by_name_says_what_would_work(self, make_response):
        resp = make_response(body={'items': [{'id': 1}]})
        check = json_has(resp, 'items.name')
        assert not check.ok
        assert '[0]' in check.expr, check.expr

    def test_key_listing_stays_bounded_on_a_wide_object(self, make_response):
        # PyPI's releases map has 163 keys; naming all of them helps nobody.
        resp = make_response(body={'m': {'k{:03d}'.format(i): i for i in range(200)}})
        check = json_has(resp, 'm.nope')
        assert not check.ok
        assert '200 keys' in check.expr
        assert len(check.expr) < 300, 'key listing is unbounded: {}'.format(len(check.expr))


class TestEvidenceStaysReadable:
    """
    Asserting against a field that holds a large object produced a 195,000-char
    failure message at pypi.org. That message is not only printed -- it is
    stored in the report and sent to the failure-triage model, which is billed
    per token.
    """

    @staticmethod
    def _big_body():
        return {'releases': {'v{}'.format(i): {'files': list(range(50))}
                             for i in range(200)}}

    def test_a_large_actual_value_is_truncated(self, make_response):
        check = json_equals(make_response(body=self._big_body()), 'releases', 'nope')
        assert not check.ok
        assert len(check.expr) < 600, 'evidence is {} chars'.format(len(check.expr))

    def test_truncation_says_what_was_cut(self, make_response):
        check = json_equals(make_response(body=self._big_body()), 'releases', 'nope')
        # "was the field empty or huge?" must still be answerable
        assert 'truncated' in check.expr
        assert 'dict of 200' in check.expr

    def test_a_large_expected_value_is_truncated_too(self, make_response):
        resp = make_response(body={'x': 1})
        check = json_equals(resp, 'x', list(range(5000)))
        assert not check.ok and len(check.expr) < 800

    def test_small_values_are_shown_in_full(self, make_response):
        resp = make_response(body={'name': 'alice'})
        check = json_equals(resp, 'name', 'bob')
        assert "'alice'" in check.expr and "'bob'" in check.expr
        assert 'truncated' not in check.expr

    def test_truncation_cannot_undo_redaction(self, make_response):
        """
        Report redaction matches whole credential shapes. Cutting a value in
        half stops it matching, so a naive truncation publishes the surviving
        prefix of a key that used to come out as ***REDACTED***.

        Every cut offset is swept, because the bug only appears when the
        boundary happens to land inside the secret.
        """
        from ipandora.core.assertion.check import brief
        from ipandora.core.report.redact import redact_text

        secret = '0x' + 'a1b2c3d4' * 8  # 32-byte hex key, 66 chars
        for pad in range(0, 300):
            evidence = 'field = ' + brief({'pad': 'x' * pad, 'key': secret})
            published = redact_text(evidence)
            for length in range(len(secret), 7, -1):
                assert secret[:length] not in published, (
                    'pad={}: {} chars of the key survived redaction'.format(pad, length))

    def test_the_whole_assert_all_message_stays_bounded(self, make_response):
        resp = make_response(body=self._big_body())
        with pytest.raises(AssertionError) as exc:
            assert_all(json_equals(resp, 'releases', 'a'),
                       json_equals(resp, 'releases', 'b'),
                       field(resp, 'releases') == 'c')
        assert len(str(exc.value)) < 2500, len(str(exc.value))


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


class TestFieldOperators:
    """Plain Python operators; each one yields a Check, not a bool."""

    @pytest.mark.parametrize('expr,expected', [
        (lambda f: f > 5, True), (lambda f: f > 10, False),
        (lambda f: f >= 10, True), (lambda f: f >= 11, False),
        (lambda f: f < 11, True), (lambda f: f < 10, False),
        (lambda f: f <= 10, True), (lambda f: f <= 9, False),
        (lambda f: f == 10, True), (lambda f: f == 11, False),
        (lambda f: f != 11, True), (lambda f: f != 10, False),
    ])
    def test_operators(self, make_response, expr, expected):
        check = expr(field(make_response(body={'n': 10}), 'n'))
        assert isinstance(check, Check) and check.ok is expected

    def test_reflected_operand_order(self, make_response):
        f = field(make_response(body={'n': 10}), 'n')
        assert (5 < f).ok and (10 == f).ok and not (11 <= f).ok

    def test_chained_comparison_gives_the_right_verdict(self, make_response):
        # a Check is truthy exactly when it passed, so Python's `a <= b <= c`
        # short-circuits on the failing bound
        for fee, ok in ((0, True), (100, True), (-1, False), (100.01, False)):
            f = field(make_response(body={'fee': fee}), 'fee')
            assert bool(0 <= f <= 100) is ok, fee

    def test_failure_names_the_values(self, make_response):
        check = field(make_response(body={'data': {'fee': 150}}), 'data.fee') <= 100
        assert not check.ok
        assert check.name == 'data.fee <= 100'
        assert '150' in check.expr and '<= 100' in check.expr

    def test_custom_name(self, make_response):
        check = field(make_response(body={'fee': 1}), 'fee', name='手续费非负') >= 0
        assert check.ok and check.name == '手续费非负'

    def test_missing_field_is_a_failed_check_with_the_path_walk(self, make_response):
        check = field(make_response(body={'data': {'a': 1}}), 'data.fee') > 0
        assert not check.ok and 'fee' in check.expr and 'a' in check.expr

    def test_non_json_body_is_a_failed_check(self, make_response):
        check = field(make_response(raw='<html>502</html>'), 'data') == 1
        assert not check.ok and 'not JSON' in check.expr

    def test_a_field_alone_is_not_a_judgement(self, make_response):
        # `if field(...)` or `assert field(...)` would otherwise be always-true
        with pytest.raises(TypeError, match='compare it'):
            bool(field(make_response(body={'n': 0}), 'n'))

    def test_decimal_and_float_compare(self, make_response):
        assert (field(make_response(body={'n': 0.1}), 'n') < Decimal('0.2')).ok


class TestFieldIsStrict:
    """A test framework that coerces hides contract changes."""

    def test_number_as_string_does_not_compare_as_a_number(self, make_response):
        # the old $gt converted '12' to 12.0 and passed
        check = field(make_response(body={'n': '12'}), 'n') > 9
        assert not check.ok and 'expected a number, got str' in check.expr

    def test_number_as_string_is_not_equal(self, make_response):
        check = field(make_response(body={'id': '5'}), 'id') == 5
        assert not check.ok and "'5'" in check.expr

    @pytest.mark.parametrize('value', [5.9, 5.1])
    def test_no_truncation(self, make_response, value):
        # the old $eq truncated the value with int(float(v)) first
        assert not (field(make_response(body={'v': value}), 'v') == 5).ok
        assert (field(make_response(body={'v': value}), 'v') > 5).ok

    def test_true_is_not_one(self, make_response):
        assert not (field(make_response(body={'v': True}), 'v') == 1).ok
        assert not (field(make_response(body={'v': 1}), 'v') == True).ok  # noqa: E712
        assert (field(make_response(body={'v': 1}), 'v') != True).ok  # noqa: E712

    def test_bool_is_not_ordered_as_a_number(self, make_response):
        check = field(make_response(body={'v': True}), 'v') > 0
        assert not check.ok and 'expected a number, got bool' in check.expr

    def test_strings_order_as_strings(self, make_response):
        # ISO dates are the common case
        assert (field(make_response(body={'d': '2026-11-05'}), 'd') > '2026-01-01').ok

    def test_string_against_number_is_a_failed_check(self, make_response):
        check = field(make_response(body={'v': 'abc'}), 'v') < 5
        assert not check.ok and 'expected a number' in check.expr

    def test_unorderable_operand(self, make_response):
        check = field(make_response(body={'v': [1]}), 'v') > [0]
        assert not check.ok and 'cannot order' in check.expr


class TestFieldMethods:
    def test_is_in(self, make_response):
        f = field(make_response(body={'s': 'ok'}), 's')
        assert f.is_in(['ok', 'pending']).ok and not f.is_in(['failed']).ok
        assert f.not_in(['failed']).ok and not f.not_in(['ok']).ok

    def test_is_in_is_strict_about_bool(self, make_response):
        assert not field(make_response(body={'v': True}), 'v').is_in([1, 2]).ok

    def test_contains(self, make_response):
        r = make_response(body={'msg': 'Operation succeeded', 'tags': ['a', 'b'],
                                'obj': {'k': 1}, 'n': 5})
        assert field(r, 'msg').contains('succeed').ok
        assert not field(r, 'msg').contains('SUCCEED').ok      # case-sensitive
        assert field(r, 'tags').contains('a').ok and not field(r, 'tags').contains('c').ok
        assert field(r, 'obj').contains('k').ok
        check = field(r, 'n').contains(5)
        assert not check.ok and 'no members' in check.expr
        check = field(r, 'msg').contains(5)
        assert not check.ok and 'can only contain a string' in check.expr

    def test_startswith(self, make_response):
        r = make_response(body={'code': 'ORD-1', 'n': 300})
        assert field(r, 'code').startswith('ORD-').ok
        check = field(r, 'n').startswith('3')
        assert not check.ok and 'expected a string' in check.expr

    def test_matches_is_search(self, make_response):
        r = make_response(body={'v': 'v1.11.0-rc'})
        assert field(r, 'v').matches(r'\d+\.\d+\.\d+').ok
        assert not field(r, 'v').matches(r'^\d+\.\d+\.\d+$').ok

    def test_matches_does_not_stringify_numbers(self, make_response):
        check = field(make_response(body={'v': 59}), 'v').matches('^5')
        assert not check.ok and 'expected a string' in check.expr

    def test_invalid_pattern_is_a_failed_check(self, make_response):
        check = field(make_response(body={'v': 'abc'}), 'v').matches('(')
        assert not check.ok and 'abc' in check.expr

    def test_len(self, make_response):
        r = make_response(body={'items': [1, 2, 3], 'n': 5})
        check = field(r, 'items').len() > 0
        assert check.ok and check.name == 'len(items) > 0'
        assert (field(r, 'items').len() == 3).ok
        check = field(r, 'n').len() > 0
        assert not check.ok and 'has no len' in check.expr
        check = field(r, 'missing').len() > 0
        assert not check.ok and 'missing' in check.expr

    def test_every_judgement_in_one_run(self, make_response):
        r = make_response(body={'fee': 150, 'status': 'done', 'items': []})
        with pytest.raises(AssertionError) as exc:
            assert_all(field(r, 'fee') <= 100,
                       field(r, 'status').is_in(['ok']),
                       field(r, 'items').len() > 0)
        assert '3/3 checks failed' in str(exc.value)


ORDER = {'data': {'amount': '100.50', 'total': '30.00', 'n': 'abc',
                  'items': [{'price': '10.00', 'tags': ['a']},
                            {'price': '-1', 'tags': []},
                            {'price': '21.00'}]}}


class TestDecimal:
    """Strict comparison plus an explicit way out for string-encoded numbers."""

    def test_numeric_string(self, make_response):
        r = make_response(body=ORDER)
        assert not (field(r, 'data.amount') > 0).ok             # strict by default
        check = field(r, 'data.amount').decimal() > 0
        assert check.ok and check.name == 'data.amount > 0'

    def test_exact(self, make_response):
        r = make_response(body={'a': '0.1', 'b': 0.1})
        assert (field(r, 'a').decimal() == Decimal('0.1')).ok
        assert (field(r, 'b').decimal() == Decimal('0.1')).ok   # via str(), not binary float
        assert (field(r, 'a').decimal() == field(r, 'b').decimal()).ok

    @pytest.mark.parametrize('value,reason', [
        ('abc', 'not a number'), (True, 'got bool'), ('NaN', 'not a finite'),
        ([1], 'got list'), ('', 'not a number'),
    ])
    def test_not_a_number_is_a_failed_check(self, make_response, value, reason):
        check = field(make_response(body={'v': value}), 'v').decimal() > 0
        assert not check.ok and reason in check.expr

    def test_missing_stays_missing(self, make_response):
        check = field(make_response(body={}), 'v').decimal() > 0
        assert not check.ok and "no key 'v'" in check.expr


class TestFieldAsOperand:
    def test_compare_two_fields(self, make_response):
        r = make_response(body={'a': 3, 'b': 3, 'c': 4})
        check = field(r, 'a') == field(r, 'b')
        assert check.ok and check.name == 'a == b' and 'b = 3' in check.expr
        assert (field(r, 'a') < field(r, 'c')).ok
        assert not (field(r, 'a') != field(r, 'b')).ok

    def test_missing_operand_fails_and_says_which(self, make_response):
        check = field(make_response(body={'a': 3}), 'a') == field(
            make_response(body={'a': 3}), 'nope')
        assert not check.ok and 'cannot compare a' in check.expr and 'nope' in check.expr


class TestMap:
    def test_cross_field(self, make_response):
        r = make_response(body=ORDER)
        total = field(r, 'data.items').map(
            lambda xs: sum(Decimal(x['price']) for x in xs), 'sum(price)')
        check = field(r, 'data.total').decimal() == total
        assert check.ok and check.name == 'data.total == sum(price)'

    def test_a_raising_function_is_a_failed_check(self, make_response):
        r = make_response(body=ORDER)
        check = field(r, 'data.items').map(lambda xs: xs[0]['nope']) == 1
        assert not check.ok and 'KeyError' in check.expr

    def test_default_label(self, make_response):
        check = field(make_response(body={'s': 'ab'}), 's').map(str.upper) == 'AB'
        assert check.ok and check.name == "upper(s) == 'AB'"


class TestEach:
    def test_names_the_failing_element(self, make_response):
        check = field(make_response(body=ORDER), 'data.items').each('price').decimal() > 0
        assert not check.ok
        assert check.name == 'data.items[*].price > 0'
        assert '1 of 3 items failed' in check.expr and 'data.items[1].price' in check.expr

    def test_all_pass(self, make_response):
        check = field(make_response(body=ORDER), 'data.items').each('price').decimal() > -5
        assert check.ok and 'all 3 items' in check.expr

    def test_element_missing_the_key(self, make_response):
        check = field(make_response(body=ORDER), 'data.items').each('tags').len() >= 0
        assert not check.ok and 'data.items[2].tags' in check.expr and "no key 'tags'" in check.expr

    def test_transform_keeps_the_index(self, make_response):
        check = field(make_response(body=ORDER), 'data.items').each('tags').len() > 0
        assert 'len(data.items[1].tags) = 0' in check.expr

    def test_without_a_path(self, make_response):
        r = make_response(body={'tags': ['ab', 'cd', 'E']})
        check = field(r, 'tags').each().matches('^[a-z]+$')
        assert not check.ok and 'tags[2]' in check.expr

    def test_empty_list_fails_unless_allowed(self, make_response):
        r = make_response(body={'items': []})
        check = field(r, 'items').each('price') > 0
        assert not check.ok and 'nothing was checked' in check.expr
        assert (field(r, 'items').each('price', allow_empty=True) > 0).ok

    def test_not_a_list(self, make_response):
        check = field(make_response(body={'v': 'x'}), 'v').each() == 'x'
        assert not check.ok and 'is not a list' in check.expr

    def test_missing_list(self, make_response):
        check = field(make_response(body={}), 'v').each() == 'x'
        assert not check.ok and "no key 'v'" in check.expr

    def test_long_failure_lists_are_summarised(self, make_response):
        check = field(make_response(body={'v': list(range(10))}), 'v').each() > 100
        assert '10 of 10 items failed' in check.expr and '(+7 more)' in check.expr

    def test_methods_work_per_element(self, make_response):
        r = make_response(body={'s': ['ok', 'ok', 'bad']})
        check = field(r, 's').each().is_in(['ok'])
        assert not check.ok and 's[2]' in check.expr

    def test_nested_each_is_refused(self, make_response):
        with pytest.raises(TypeError, match='each'):
            field(make_response(body={'v': [[1]]}), 'v').each().each()


class TestThat:
    def test_any_value(self):
        check = that('PAID', 'db.state') == 'PAID'
        assert check.ok and check.name == "db.state == 'PAID'"

    def test_against_a_field(self, make_response):
        r = make_response(body={'data': {'total': 3}})
        check = that(3, 'rendered rows') == field(r, 'data.total')
        assert check.ok and 'data.total = 3' in check.expr

    def test_src_defaults_to_derived(self):
        assert (that(1) == 1).src == Source.DERIVED

    def test_list_value_supports_each(self):
        assert not (that([1, -1], 'rows').each() > 0).ok


class TestJsonEqualsIsStrictToo:
    def test_true_is_not_one(self, make_response):
        assert not json_equals(make_response(body={'v': True}), 'v', 1).ok
        assert json_equals(make_response(body={'v': 1}), 'v', 1.0).ok


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
