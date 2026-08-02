# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_redact.py
@Time  : 2026-08-01
"""
import pytest

from ipandora.core.report.redact import MASK, redact, redact_text

SECRET = 'sk-abcdefghij0123456789'
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
        pem = ('-----BEGIN RSA PRIVATE KEY-----\n'
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
