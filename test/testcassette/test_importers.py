# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_importers.py
@Time  : 2026-08-03
"""
import base64
import json

import pytest

from ipandora.core.cassette.importers import (MIN_BODY_RATIO, import_into, sniff,
                                              to_har)
from ipandora.core.cassette.store import CassetteStore
from ipandora.core.report.redact import MASK


def har_file(tmp_path, entries=None, name='capture.har'):
    _entries = entries if entries is not None else [har_entry()]
    _file = tmp_path / name
    _file.write_text(json.dumps({'log': {'version': '1.2', 'entries': _entries}}),
                     encoding='utf-8')
    return str(_file)


def har_entry(url='https://api.test/v1/item?id=1', body='{"ok": 1}',
              encoding=None, headers=None, status=200, request_body=None):
    _content = {'size': len(body or ''), 'mimeType': 'application/json'}
    if body is not None:
        _content['text'] = (base64.b64encode(body.encode()).decode()
                            if encoding == 'base64' else body)
        if encoding:
            _content['encoding'] = encoding
    _entry = {
        'startedDateTime': '2026-08-03T10:00:00.000Z', 'time': 120,
        'request': {'method': 'GET', 'url': url,
                    'headers': [{'name': _k, 'value': _v}
                                for _k, _v in (headers or {}).items()]},
        'response': {'status': status, 'statusText': 'OK',
                     'headers': [{'name': 'Content-Type', 'value': 'application/json'}],
                     'content': _content}}
    if request_body is not None:
        _entry['request']['postData'] = {'mimeType': 'application/json',
                                         'text': request_body}
    return _entry


def nginx_file(tmp_path, rows, name='access.log'):
    _file = tmp_path / name
    _file.write_text('\n'.join(json.dumps(_r) for _r in rows) + '\n', encoding='utf-8')
    return str(_file)


def nginx_row(i=0, with_body=True, **extra):
    _row = {'time_iso8601': '2026-08-03T10:00:0{}+08:00'.format(i),
            'request_method': 'GET', 'request_uri': '/v1/item?id={}'.format(i),
            'host': 'api.test', 'status': 200, 'request_time': 0.187}
    if with_body:
        _row['response_body'] = json.dumps({'id': i})
    _row.update(extra)
    return _row


def envoy_file(tmp_path, traces, name='tap.jsonl'):
    _file = tmp_path / name
    _file.write_text('\n'.join(json.dumps(_t) for _t in traces) + '\n', encoding='utf-8')
    return str(_file)


def envoy_trace(path='/v1/pay', request_body=None, response_body='{"ok": 1}',
                headers=None, status='200'):
    _request = {'headers': [{'key': ':method', 'value': 'POST'},
                            {'key': ':path', 'value': path},
                            {'key': ':authority', 'value': 'api.internal'},
                            {'key': ':scheme', 'value': 'https'}]
                + [{'key': _k, 'value': _v} for _k, _v in (headers or {}).items()]}
    if request_body is not None:
        _request['body'] = {'as_bytes': base64.b64encode(request_body.encode()).decode()}
    return {'http_buffered_trace': {
        'request': _request,
        'response': {'headers': [{'key': ':status', 'value': status}],
                     'body': {'as_string': response_body}}}}


def records(name, tmp_path):
    return list(CassetteStore(name, directory=str(tmp_path / 'tapes')).read())


def do_import(name, path, tmp_path, **kwargs):
    return import_into(name, path, directory=str(tmp_path / 'tapes'), **kwargs)


class TestHar:
    def test_a_capture_becomes_a_cassette(self, tmp_path):
        report = do_import('t', har_file(tmp_path), tmp_path)
        assert report.imported == 1 and report.usable
        [record] = records('t', tmp_path)
        assert record.method == 'GET' and record.status == 200
        assert record.url == 'https://api.test/v1/item?id=1'
        assert record.source == 'import:har'

    def test_a_base64_body_is_decoded(self, tmp_path):
        path = har_file(tmp_path, [har_entry(body='{"decoded": true}',
                                             encoding='base64')])
        do_import('t', path, tmp_path)
        assert records('t', tmp_path)[0].response_body == '{"decoded": true}'

    def test_a_request_body_is_kept(self, tmp_path):
        path = har_file(tmp_path, [har_entry(request_body='{"amount": 5}')])
        do_import('t', path, tmp_path)
        assert records('t', tmp_path)[0].request_body == '{"amount": 5}'

    def test_binary_is_described_rather_than_mangled(self, tmp_path):
        """A cassette full of replacement characters is worse than one that
        admits the body was not text."""
        entry = har_entry(body='')
        entry['response']['content'] = {
            'text': base64.b64encode(b'\x89PNG\r\n\x1a\n\xff\xfe').decode(),
            'encoding': 'base64', 'size': 10, 'mimeType': 'image/png'}
        do_import('t', har_file(tmp_path, [entry]), tmp_path)
        assert 'binary bytes' in records('t', tmp_path)[0].response_body

    def test_an_entry_without_a_url_is_skipped_not_fatal(self, tmp_path):
        broken = har_entry()
        broken['request']['url'] = ''
        path = har_file(tmp_path, [broken, har_entry()])
        report = do_import('t', path, tmp_path)
        assert report.read == 2 and report.imported == 1 and report.skipped

    def test_order_is_preserved(self, tmp_path):
        path = har_file(tmp_path, [har_entry(body='{"n": %d}' % i) for i in range(3)])
        do_import('t', path, tmp_path)
        assert [json.loads(r.response_body)['n'] for r in records('t', tmp_path)] == [0, 1, 2]


class TestNginx:
    def test_a_json_log_becomes_a_cassette(self, tmp_path):
        path = nginx_file(tmp_path, [nginx_row(i) for i in range(3)])
        report = do_import('t', path, tmp_path)
        assert report.imported == 3
        assert records('t', tmp_path)[0].url == 'https://api.test/v1/item?id=0'

    def test_seconds_become_milliseconds(self, tmp_path):
        """nginx reports request_time in seconds; a cassette stores ms. Getting
        this wrong makes every timing in the report a thousand times off."""
        path = nginx_file(tmp_path, [nginx_row(0)])
        do_import('t', path, tmp_path)
        assert records('t', tmp_path)[0].ms == 187.0

    def test_field_names_can_be_overridden(self, tmp_path):
        """No two sites name these the same, which is why the map is data."""
        path = nginx_file(tmp_path, [{'verb': 'POST', 'uri': '/v1/a',
                                      'code': 201, 'resp': '{"ok": 1}'}])
        report = do_import('t', path, tmp_path, fields={
            'method': 'verb', 'url': 'uri', 'status': 'code',
            'response_body': 'resp'})
        assert report.imported == 1
        [record] = records('t', tmp_path)
        assert record.method == 'POST' and record.status == 201

    def test_a_malformed_line_is_skipped_not_fatal(self, tmp_path):
        path = tmp_path / 'access.log'
        path.write_text(json.dumps(nginx_row(0)) + '\nnot json\n'
                        + json.dumps(nginx_row(1)) + '\n', encoding='utf-8')
        report = do_import('t', str(path), tmp_path)
        assert report.imported == 2 and len(report.skipped) == 1

    def test_a_relative_url_still_parses(self, tmp_path):
        path = nginx_file(tmp_path, [nginx_row(0, host=None)])
        do_import('t', path, tmp_path)
        assert records('t', tmp_path)[0].url.startswith('https://')


class TestEnvoy:
    def test_a_tap_trace_becomes_a_cassette(self, tmp_path):
        path = envoy_file(tmp_path, [envoy_trace()])
        report = do_import('t', path, tmp_path)
        assert report.imported == 1
        [record] = records('t', tmp_path)
        assert record.method == 'POST' and record.status == 200
        assert record.url == 'https://api.internal/v1/pay'

    def test_pseudo_headers_are_lifted_out_not_left_as_headers(self, tmp_path):
        """`:method` and friends are structure wearing a header's clothes;
        leaving them in would put them into matching and diffing."""
        do_import('t', envoy_file(tmp_path, [envoy_trace()]), tmp_path)
        [record] = records('t', tmp_path)
        assert not any(_k.startswith(':') for _k in record.request_headers)

    def test_a_base64_request_body_is_decoded(self, tmp_path):
        path = envoy_file(tmp_path, [envoy_trace(request_body='{"n": 7}')])
        do_import('t', path, tmp_path)
        assert records('t', tmp_path)[0].request_body == '{"n": 7}'

    def test_a_single_trace_object_works_too(self, tmp_path):
        path = tmp_path / 'tap.json'
        path.write_text(json.dumps(envoy_trace()), encoding='utf-8')
        assert do_import('t', str(path), tmp_path, fmt='envoy').imported == 1


class TestAnUnusableTapeIsRefused:
    """
    The guard that matters most. Most access logs carry no response body, and a
    cassette without them cannot be replayed and cannot be diffed -- while
    looking exactly like a good one: right count, right URLs, green import. It
    only fails later, somewhere else, for reasons nobody connects back here.
    """

    def test_a_log_with_no_response_bodies_writes_nothing(self, tmp_path):
        path = nginx_file(tmp_path, [nginx_row(i, with_body=False)
                                     for i in range(5)])
        report = do_import('t', path, tmp_path)
        assert report.imported == 5
        assert not report.usable
        assert not (tmp_path / 'tapes' / 't').exists(), 'an unusable tape was written'

    def test_the_report_says_why(self, tmp_path):
        path = nginx_file(tmp_path, [nginx_row(i, with_body=False) for i in range(5)])
        assert '响应体' in do_import('t', path, tmp_path).describe()

    def test_force_writes_it_anyway(self, tmp_path):
        path = nginx_file(tmp_path, [nginx_row(i, with_body=False) for i in range(5)])
        do_import('t', path, tmp_path, force=True)
        assert len(records('t', tmp_path)) == 5

    def test_a_mostly_bodied_capture_is_accepted(self, tmp_path):
        """A 204 or a redirect legitimately has no body, so the bar is a
        majority rather than every single one."""
        rows = [nginx_row(i) for i in range(9)] + [nginx_row(9, with_body=False)]
        report = do_import('t', nginx_file(tmp_path, rows), tmp_path)
        assert report.usable and report.body_ratio > MIN_BODY_RATIO

    def test_an_empty_capture_is_not_silently_fine(self, tmp_path):
        report = do_import('t', har_file(tmp_path, []), tmp_path)
        assert report.imported == 0 and not report.usable


class TestRedactionOnTheWayIn:
    """
    Imported traffic is real users. This is the input that makes redaction at
    write time non-negotiable rather than a nicety.
    """

    def test_a_credential_header_never_lands(self, tmp_path):
        path = har_file(tmp_path, [har_entry(
            headers={'Authorization': 'Bearer sk-live-abcdef1234567890'})])
        do_import('t', path, tmp_path)
        _raw = (tmp_path / 'tapes' / 't' / 'exchanges.jsonl').read_text(encoding='utf-8')
        assert 'sk-live-abcdef1234567890' not in _raw and MASK in _raw

    def test_a_credential_named_only_by_its_field_never_lands(self, tmp_path):
        path = har_file(tmp_path, [har_entry(
            body=json.dumps({'password': 'correcthorsebattery'}))])
        do_import('t', path, tmp_path)
        _raw = (tmp_path / 'tapes' / 't' / 'exchanges.jsonl').read_text(encoding='utf-8')
        assert 'correcthorsebattery' not in _raw

    def test_a_secret_inside_a_base64_body_is_decoded_then_redacted(self, tmp_path):
        """Decoding first is what makes redaction able to see it at all -- a
        base64 blob matches no rule."""
        path = har_file(tmp_path, [har_entry(
            body=json.dumps({'token': 'sk-live-abcdef1234567890'}),
            encoding='base64')])
        do_import('t', path, tmp_path)
        _raw = (tmp_path / 'tapes' / 't' / 'exchanges.jsonl').read_text(encoding='utf-8')
        assert 'sk-live-abcdef1234567890' not in _raw

    def test_an_envoy_header_is_redacted_too(self, tmp_path):
        path = envoy_file(tmp_path, [envoy_trace(
            headers={'x-token': 'sk-live-abcdef1234567890'})])
        do_import('t', path, tmp_path)
        _raw = (tmp_path / 'tapes' / 't' / 'exchanges.jsonl').read_text(encoding='utf-8')
        assert 'sk-live-abcdef1234567890' not in _raw


class TestFormatDetection:
    def test_har_is_recognised_by_extension(self, tmp_path):
        assert sniff(har_file(tmp_path, name='x.har')) == 'har'

    def test_har_is_recognised_by_content(self, tmp_path):
        assert sniff(har_file(tmp_path, name='x.json')) == 'har'

    def test_envoy_is_recognised_by_content(self, tmp_path):
        assert sniff(envoy_file(tmp_path, [envoy_trace()])) == 'envoy'

    def test_a_json_log_falls_through_to_nginx(self, tmp_path):
        assert sniff(nginx_file(tmp_path, [nginx_row(0)])) == 'nginx'

    def test_an_unknown_format_is_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            do_import('t', har_file(tmp_path), tmp_path, fmt='carrier-pigeon')


class TestHarExport:
    def test_a_cassette_round_trips_through_har(self, tmp_path):
        """The reason the internal format is not HAR is streaming, not
        tooling -- so the tooling has to still work."""
        do_import('a', har_file(tmp_path, [har_entry(body='{"n": 1}'),
                                           har_entry(body='{"n": 2}')]), tmp_path)
        _har = to_har('a', directory=str(tmp_path / 'tapes'))

        _out = tmp_path / 'out.har'
        _out.write_text(json.dumps(_har), encoding='utf-8')
        do_import('b', str(_out), tmp_path)

        _before = [(r.method, r.url, r.status, r.response_body)
                   for r in records('a', tmp_path)]
        _after = [(r.method, r.url, r.status, r.response_body)
                  for r in records('b', tmp_path)]
        assert _before == _after

    def test_the_export_is_valid_har_shape(self, tmp_path):
        do_import('a', har_file(tmp_path), tmp_path)
        _har = to_har('a', directory=str(tmp_path / 'tapes'))
        assert _har['log']['version'] == '1.2'
        [entry] = _har['log']['entries']
        assert entry['request']['method'] and entry['response']['status']
        assert 'content' in entry['response']
