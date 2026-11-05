# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_redact.py
@Time  : 2026-08-01
"""
import pytest

from ipandora.core.report.redact import MASK, redact, redact_text

SECRET = 'sk-abcdefghij0123456789'  # pragma: allowlist secret
ETH_KEY = '0x' + 'a' * 64
JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijkl'
MNEMONIC = ('abandon ability able about above absent absorb abstract '
            'absurd abuse access accident')


def leaks(value, secret):
    """Whether the secret survives redaction anywhere in the structure."""
    return secret in repr(redact(value))


class TestSecretsByFieldName:
    @pytest.mark.parametrize('key', [
        'password', 'passwd', 'pwd', 'secret', 'token', 'api_key', 'apiKey',
        'api-key', 'access_key', 'private_key', 'privateKey', 'mnemonic',
        'credential', 'signature', 'signedTx', 'refresh_token', 'session_id'])
    def test_named_fields_are_masked(self, key):
        assert redact({key: 'whatever-it-holds'})[key] == MASK

    @pytest.mark.parametrize('header', [
        'Authorization', 'authorization', 'Cookie', 'Set-Cookie',
        'X-API-Key', 'Proxy-Authorization', 'X-Auth-Token'])
    def test_credential_headers_are_masked(self, header):
        assert redact({header: 'Bearer something'})[header] == MASK

    def test_masking_is_case_insensitive(self):
        assert redact({'PASSWORD': 'x'})['PASSWORD'] == MASK

    def test_benign_fields_survive(self):
        payload = {'id': 1, 'name': 'alice', 'total': 3.5, 'ok': True, 'nil': None}
        assert redact(payload) == payload


class TestSecretsByValueShape:
    """
    Name-based masking alone is not enough: a key pasted into an error message
    has no field name at all.
    """

    @pytest.mark.parametrize('secret', [
        ETH_KEY, 'a' * 64, JWT, SECRET, 'AKIA1234567890ABCDEF',
        'Bearer abcdefghijklmnop', 'Basic dXNlcjpwYXNz1234'])
    def test_shapes_are_masked_in_free_text(self, secret):
        assert not leaks({'log': 'value was {} here'.format(secret)}, secret)

    def test_mnemonic_is_masked(self):
        assert not leaks({'note': MNEMONIC}, MNEMONIC)

    def test_pem_private_key_is_masked(self):
        pem = ('-----BEGIN RSA PRIVATE KEY-----\n'  # pragma: allowlist secret
               'MIIEowIBAAKCAQEA1234\n'
               '-----END RSA PRIVATE KEY-----')
        assert not leaks({'key': pem}, 'MIIEowIBAAKCAQEA1234')

    def test_ordinary_hex_is_not_over_masked(self):
        # a transaction hash or short id is not a key
        assert redact({'tx': '0xabc123'}) == {'tx': '0xabc123'}

    def test_ordinary_prose_survives(self):
        text = 'the server returned 500 and the response body was empty'
        assert redact_text(text) == text


class TestNestedStructures:
    def test_nested_dicts(self):
        assert not leaks({'a': {'b': {'c': {'token': SECRET}}}}, SECRET)

    def test_inside_lists(self):
        assert not leaks({'items': [{'ok': 1}, {'password': SECRET}]}, SECRET)

    def test_list_of_strings(self):
        assert not leaks({'lines': ['fine', 'key={}'.format(ETH_KEY)]}, ETH_KEY)

    def test_tuples_keep_their_type(self):
        assert isinstance(redact(('a', 'b')), tuple)

    def test_deeply_nested_does_not_recurse_forever(self):
        deep = {}
        node = deep
        for _ in range(50):
            node['n'] = {}
            node = node['n']
        redact(deep)  # must return rather than hit the recursion limit

    def test_non_string_scalars_pass_through(self):
        assert redact([1, 2.5, True, None]) == [1, 2.5, True, None]


class TestKeyValuePairs:
    """
    Form bodies, query strings, cookie lines: `password=hunter2` has no shape,
    only a name. Found while reviewing login support (decisions/17 §7): a
    form-encoded login body reached the report exactly as it was sent.
    """

    @pytest.mark.parametrize('text,secret', [
        ('username=alice&password=hunter2&grant_type=password', 'hunter2'),
        ('client_id=app&client_secret=s3cr3t-value', 's3cr3t-value'),
        ('grant_type=refresh_token&refresh_token=r-1234567', 'r-1234567'),
        ('https://api.example.com/orders?page=2&access_token=abc123', 'abc123'),
        ('sid=1; session_id=zz-99; path=/', 'zz-99'),
        ('login with password=hunter2 failed', 'hunter2'),
        ('pass%77ord=encoded-key', 'encoded-key'),
        ('api_key=k&q=1', '=k&'),
        ('sent body=password=hunter2', 'hunter2'),
        ('token=abc123==', 'abc123'),
    ])
    def test_the_value_of_a_credential_named_pair_is_masked(self, text, secret):
        _out = redact_text(text)
        assert secret not in _out and MASK in _out

    def test_everything_else_is_left_byte_for_byte(self):
        _text = 'username=alice&password=hunter2&grant_type=password&scope=read%20write'
        assert redact_text(_text) == ('username=alice&password={}&grant_type=password'
                                      '&scope=read%20write'.format(MASK))

    @pytest.mark.parametrize('text', [
        "data.status = 'PAID' (expected 'PAID'); fee=120",
        'page=2&size=20',
        'token=',                          # nothing to hide
        'token==',                         # nor here
        'a==b',
    ])
    def test_ordinary_text_is_untouched(self, text):
        assert redact_text(text) == text

    def test_a_pair_inside_a_value_keeps_its_key(self):
        assert redact_text('sent body=password=hunter2') == 'sent body=password={}'.format(MASK)

    def test_a_form_body_is_redacted_as_a_body(self):
        from ipandora.core.report.redact import redact_body
        assert 'hunter2' not in redact_body('username=alice&password=hunter2')

    def test_through_the_report(self):
        from ipandora.core.report.builder import _redact_exchange
        from ipandora.core.report.render import to_curl
        _ex = _redact_exchange({'method': 'POST', 'url': 'https://x/login?otp_token=777777',
                                'request_body': 'username=alice&password=hunter2',
                                'request_headers': {'Content-Type': 'application/x-www-form-urlencoded'}})
        _text = repr(_ex) + to_curl(_ex)
        assert 'hunter2' not in _text and '777777' not in _text


class TestWhatLeavesForAnAgent:
    """explain_failure / run_tests output goes to an agent, and usually on to a model provider."""

    def test_summary_and_explain_are_masked(self, monkeypatch):
        from ipandora.core.runner import api, store
        from ipandora.core.runner.result import CaseResult, RunResult
        _message = ('AssertionError: login failed\n  [FAIL] token is valid | '
                    "data.token = '{}' body=password=hunter2".format(JWT))
        _run = RunResult(run_id='run-x', cases=[CaseResult(
            nodeid='t.py::test_login', outcome='failed', message=_message, detail=_message)])
        _summary = repr(_run.summary())
        assert JWT not in _summary and 'hunter2' not in _summary
        monkeypatch.setattr(store, 'load', lambda run_id: _run)
        _explained = repr(api.explain('run-x'))
        assert JWT not in _explained and 'hunter2' not in _explained
