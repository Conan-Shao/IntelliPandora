# -*- coding: utf-8 -*-
"""
Assertion, evidence, Web and triage defects found in code review CR1
(docs/design/reviews/01-CR1.md, F3). Each test fails on the code before the fix.
"""
import io
import json
import os
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ipandora.core import web
from ipandora.core.assertion import visual
from ipandora.core.assertion.field import that
from ipandora.core.assertion.http import json_body
from ipandora.core.assertion.jsonpath import MISSING, resolve
from ipandora.core.runner.result import CaseResult, RunResult
from ipandora.core.triage import Category, classify, failed_check_sources


class TestDecimal:
    def test_decimal_equals_the_float_as_written(self):
        assert that('0.1', 'fee').decimal() == 0.1
        assert that('100.50', 'amount').decimal() == 100.5

    def test_ordering_uses_the_float_as_written(self):
        # Decimal('0.1') < 0.1 is True by binary value
        assert not (that('0.1', 'fee').decimal() < 0.1)
        assert that('0.1', 'fee').decimal() <= 0.1

    def test_python_literal_underscores_are_not_numbers(self):
        _check = that('1_000', 'amount').decimal() == 1000
        assert not _check
        assert 'not a number' in _check.expr

    def test_is_in_compares_the_same_way(self):
        assert that('0.3', 'rate').decimal().is_in([0.1, 0.3])


class TestJsonPath:
    BODY = {'data': {'items': [{'name': 'a'}], 'x': 1}, 'a': {'x': 2}}

    @pytest.mark.parametrize('path', ['data..items', 'data.items[0', 'a[x]', 'data.items[0]name',
                                      '.data', 'data.'])
    def test_a_malformed_path_is_not_read_as_another(self, path):
        _value, _reason = resolve(self.BODY, path)
        assert _value is MISSING
        assert 'bad path' in _reason

    def test_valid_forms_still_work(self):
        assert resolve(self.BODY, 'data.items[0].name') == ('a', '')
        assert resolve(self.BODY, "data['items'][0]['name']") == ('a', '')
        assert resolve(self.BODY, 'data.items.0.name') == ('a', '')

    def test_json_body_with_a_byte_order_mark(self):
        _response = SimpleNamespace(content='﻿{"ok": true}'.encode('utf-8'))
        assert json_body(_response) == ({'ok': True}, '')
        assert json_body(SimpleNamespace(content='﻿{"ok": true}')) == ({'ok': True}, '')


class TestVisualNames:
    def test_non_ascii_golden_names_do_not_collide(self):
        assert visual.golden_path('价格区') != visual.golden_path('总价')

    def test_long_names_sharing_a_prefix_do_not_collide(self):
        _prefix = 'test/testapi/test_orders.py::TestCheckout::test_' + 'x' * 60
        assert visual._slug(_prefix + 'a') != visual._slug(_prefix + 'b')

    def test_ascii_names_keep_their_paths(self):
        assert visual._slug('price box') == 'price-box'

    def test_unreadable_image_is_a_failed_check(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _check = visual.matches_golden(b'not a png', 'x')
        assert not _check.ok
        assert '无法读取' in _check.expr

    def test_unreadable_golden_is_a_failed_check(self, tmp_path, monkeypatch):
        from PIL import Image
        monkeypatch.chdir(tmp_path)
        _golden = visual.golden_path('broken')
        os.makedirs(os.path.dirname(_golden))
        with open(_golden, 'wb') as _f:
            _f.write(b'garbage')
        _buf = io.BytesIO()
        Image.new('RGBA', (4, 4)).save(_buf, format='PNG')
        _check = visual.matches_golden(_buf.getvalue(), 'broken')
        assert not _check.ok and '基准图' in _check.expr


class _Locator:
    def __init__(self, line):
        self._line = line

    def count(self):
        return 1

    def aria_snapshot(self, timeout=None):
        return self._line


class TestWeb:
    @pytest.mark.parametrize('line, expected', [
        ('- heading "价格" [level=2]', {'role': 'heading', 'name': '价格'}),
        ('- checkbox "同意条款" [checked]', {'role': 'checkbox', 'name': '同意条款'}),
        ('- button "付款"', {'role': 'button', 'name': '付款'}),
    ])
    def test_identity_reads_lines_with_attributes(self, line, expected):
        assert web.identity_of(_Locator(line)) == expected

    def test_two_responses_get_different_claims(self):
        class APIResponseAssertions:
            pass
        _a, _b = APIResponseAssertions(), APIResponseAssertions()
        setattr(_a, web._ACTUAL, SimpleNamespace(url='http://h/api/orders?ts=1'))
        setattr(_b, web._ACTUAL, SimpleNamespace(url='http://h/api/users?ts=2'))
        assert web._target(_a) == 'response(/api/orders)'
        assert web._target(_a) != web._target(_b)

    def test_remember_merges_with_what_is_on_disk(self, tmp_path, monkeypatch):
        _path = tmp_path / 'locators.json'
        monkeypatch.setenv(web.MEMORY_VAR, str(_path))
        _path.write_text(json.dumps({'t::other': {'#x': {'role': 'button', 'name': 'X'}}}))
        web.remember(RunResult(run_id='r', cases=[CaseResult(
            nodeid='t::a', outcome='passed', locators={'#a': {'role': 'link', 'name': 'A'}})]))
        _data = json.loads(_path.read_text())
        assert set(_data) == {'t::other', 't::a'}
        assert not [_p for _p in os.listdir(tmp_path) if _p.endswith('.tmp')]


FAILED = 'AssertionError: Assertion failed (1/2 checks failed)\n\n  [FAIL] {}'


class TestTriage:
    def test_timed_out_inside_a_judgement_is_a_defect(self):
        _message = FAILED.format("网关返回 (api) | data.error = 'upstream timed out' (expected None)")
        assert classify('t::a', 'failed', _message).category == Category.DEFECT

    def test_a_raised_transport_error_is_still_the_environment(self):
        _message = FAILED.format('x (api) | y') + '\nHttpTimeoutError: GET http://h timed out'
        assert classify('t::a', 'failed', _message).category == Category.ENVIRONMENT

    def test_eventually_that_never_got_an_answer_is_the_environment(self):
        _message = FAILED.format('最终成立：status (api) | 10 s 内读了 5 次都不成立；'
                                 '读到的依次是：HttpConnectionError: refused')
        assert classify('t::a', 'failed', _message).category == Category.ENVIRONMENT

    def test_a_caught_locator_error_does_not_decide_the_verdict(self):
        _caught = [{'selector': '#cookie-banner', 'verdict': 'stale_selector',
                    'identity': {'role': 'button', 'name': '同意'}}]
        _message = FAILED.format('总价 (api) | total = 90 (expected 100)')
        assert classify('t::a', 'failed', _message, _caught).category == Category.DEFECT

    def test_the_locator_the_failure_names_decides(self):
        _failures = [{'selector': '#cookie-banner', 'verdict': 'missing',
                      'identity': {'role': 'button', 'name': '同意'}},
                     {'selector': '#pay', 'verdict': 'stale_selector',
                      'identity': {'role': 'button', 'name': '付款'}}]
        _message = "TimeoutError: Locator.click: Timeout 30000ms exceeded.\nwaiting for locator('#pay')"
        _finding = classify('t::a', 'failed', _message, _failures)
        assert _finding.category == Category.HARNESS and '#pay' in _finding.reason

    def test_check_line_with_no_expr_does_not_take_the_next_line(self):
        _message = '  [FAIL] 签名 (derived)\n  [FAIL] 金额 (schema) | amount missing'
        assert failed_check_sources(_message) == ['derived', 'schema']
