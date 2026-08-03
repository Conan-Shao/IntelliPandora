# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_cassette_cli.py
@Time  : 2026-08-03

`ipandora cassette` as a command. Subprocess, because the exit codes are what
a pipeline branches on and sys.exit is not observable from a library call.
"""
import json
import os
import subprocess
import sys

import pytest


def har(tmp_path, count=3, body='{"ok": 1}', name='capture.har'):
    _entries = [{
        'startedDateTime': '2026-08-03T10:00:00.000Z', 'time': 100,
        'request': {'method': 'GET',
                    'url': 'https://api.test/v1/item?id={}'.format(_i),
                    'headers': [{'name': 'Authorization',
                                 'value': 'Bearer sk-live-abcdef1234567890'}]},
        'response': {'status': 200, 'statusText': 'OK', 'headers': [],
                     'content': {'size': len(body), 'text': body,
                                 'mimeType': 'application/json'}}}
        for _i in range(count)]
    _file = tmp_path / name
    _file.write_text(json.dumps({'log': {'version': '1.2', 'entries': _entries}}),
                     encoding='utf-8')
    return str(_file)


def access_log(tmp_path, count=5, with_body=False):
    _rows = []
    for _i in range(count):
        _row = {'time_iso8601': '2026-08-03T10:00:00+08:00', 'request_method': 'GET',
                'request_uri': '/v1/item?id={}'.format(_i), 'host': 'api.test',
                'status': 200, 'request_time': 0.1}
        if with_body:
            _row['response_body'] = '{"id": %d}' % _i
        _rows.append(_row)
    _file = tmp_path / 'access.log'
    _file.write_text('\n'.join(json.dumps(_r) for _r in _rows) + '\n', encoding='utf-8')
    return str(_file)


def ipandora(*args, tmp_path):
    _env = dict(os.environ)
    _env['IPANDORA_CASSETTES_DIR'] = str(tmp_path / 'tapes')
    return subprocess.run([sys.executable, '-m', 'ipandora.run', 'cassette']
                          + list(args), capture_output=True, text=True,
                          env=_env, timeout=120)


class TestImport:
    def test_a_har_import_succeeds_and_reports_what_it_did(self, tmp_path):
        done = ipandora('import', 't', har(tmp_path), tmp_path=tmp_path)
        assert done.returncode == 0, done.stdout + done.stderr
        assert '导入 3 条' in done.stdout and '含响应体 3/3' in done.stdout
        assert (tmp_path / 'tapes' / 't' / 'exchanges.jsonl').is_file()

    def test_a_bodyless_log_fails_and_writes_nothing(self, tmp_path):
        done = ipandora('import', 't', access_log(tmp_path), tmp_path=tmp_path)
        assert done.returncode != 0
        # the finding goes to stdout, the refusal to stderr -- a pipeline that
        # captures one and not the other still sees the half it needs
        assert '响应体覆盖率过低' in done.stdout
        assert '未写入' in done.stderr
        assert not (tmp_path / 'tapes' / 't').exists()

    def test_the_failure_says_how_to_proceed(self, tmp_path):
        done = ipandora('import', 't', access_log(tmp_path), tmp_path=tmp_path)
        assert '--force' in done.stderr
        assert 'body' in done.stdout + done.stderr

    def test_force_accepts_it(self, tmp_path):
        done = ipandora('import', 't', access_log(tmp_path), '--force',
                        tmp_path=tmp_path)
        assert done.returncode == 0
        assert (tmp_path / 'tapes' / 't' / 'exchanges.jsonl').is_file()

    def test_a_log_with_bodies_needs_no_force(self, tmp_path):
        assert ipandora('import', 't', access_log(tmp_path, with_body=True),
                        tmp_path=tmp_path).returncode == 0

    def test_field_overrides_are_parsed(self, tmp_path):
        _file = tmp_path / 'odd.log'
        _file.write_text(json.dumps({'verb': 'POST', 'uri': '/v1/a', 'code': 201,
                                     'resp': '{"ok": 1}'}) + '\n', encoding='utf-8')
        done = ipandora('import', 't', str(_file), '-f', 'nginx',
                        '--field', 'method=verb', '--field', 'url=uri',
                        '--field', 'status=code', '--field', 'response_body=resp',
                        tmp_path=tmp_path)
        assert done.returncode == 0, done.stdout + done.stderr

    def test_a_malformed_field_override_is_refused(self, tmp_path):
        done = ipandora('import', 't', har(tmp_path), '--field', 'nonsense',
                        tmp_path=tmp_path)
        assert done.returncode != 0
        assert 'name=value' in (done.stdout + done.stderr)

    def test_the_credential_never_reaches_disk(self, tmp_path):
        ipandora('import', 't', har(tmp_path), tmp_path=tmp_path)
        _raw = (tmp_path / 'tapes' / 't' / 'exchanges.jsonl').read_text(
            encoding='utf-8')
        assert 'sk-live-abcdef1234567890' not in _raw


class TestListAndShow:
    def test_an_empty_directory_says_how_to_start(self, tmp_path):
        out = ipandora('list', tmp_path=tmp_path).stdout
        assert '还没有磁带' in out and '--record' in out

    def test_list_shows_each_tape_with_its_age(self, tmp_path):
        ipandora('import', 'alpha', har(tmp_path), tmp_path=tmp_path)
        out = ipandora('list', tmp_path=tmp_path).stdout
        assert 'alpha' in out and 'import:har' in out and '天前' in out

    def test_show_lists_the_keys(self, tmp_path):
        ipandora('import', 't', har(tmp_path), tmp_path=tmp_path)
        out = ipandora('show', 't', tmp_path=tmp_path).stdout
        assert 'GET|/v1/item' in out and '3 条' in out

    def test_show_verbose_names_the_request(self, tmp_path):
        ipandora('import', 't', har(tmp_path), tmp_path=tmp_path)
        out = ipandora('show', 't', '-v', tmp_path=tmp_path).stdout
        assert 'https://api.test/v1/item' in out and '200' in out

    def test_showing_a_missing_tape_fails(self, tmp_path):
        done = ipandora('show', 'nope', tmp_path=tmp_path)
        assert done.returncode != 0


class TestExport:
    def test_export_writes_har(self, tmp_path):
        ipandora('import', 't', har(tmp_path), tmp_path=tmp_path)
        _out = tmp_path / 'out.har'
        done = ipandora('export', 't', '-o', str(_out), tmp_path=tmp_path)
        assert done.returncode == 0
        _data = json.loads(_out.read_text(encoding='utf-8'))
        assert len(_data['log']['entries']) == 3

    def test_export_to_stdout(self, tmp_path):
        ipandora('import', 't', har(tmp_path), tmp_path=tmp_path)
        out = ipandora('export', 't', tmp_path=tmp_path).stdout
        assert json.loads(out)['log']['version'] == '1.2'

    def test_exporting_a_missing_tape_fails(self, tmp_path):
        assert ipandora('export', 'nope', tmp_path=tmp_path).returncode != 0

    def test_the_export_does_not_re_expose_a_redacted_secret(self, tmp_path):
        """Redaction happened on the way in; export must not somehow undo it."""
        ipandora('import', 't', har(tmp_path), tmp_path=tmp_path)
        assert 'sk-live-abcdef1234567890' not in ipandora(
            'export', 't', tmp_path=tmp_path).stdout


class TestImportedTapesReplay:
    def test_an_imported_cassette_can_be_replayed(self, tmp_path):
        """The point of importing: the tape has to work in the same runner as
        a recorded one, or the format is only decorative."""
        import textwrap

        ipandora('import', 'imported', har(tmp_path), tmp_path=tmp_path)

        _suite = tmp_path / 'test_imported.py'
        _suite.write_text(textwrap.dedent('''
            from ipandora.core import api
            from ipandora.core.assertion import assert_all, json_equals, status_ok
            from ipandora.core.base.data.markdata import MarkData
            from ipandora.core.plugin.interface.endpointsinterface import (
                EndPointsInterface)
            from ipandora.core.plugin.pluginmanager import PluginManager

            class _N(EndPointsInterface):
                def endpoints(self, mark: MarkData) -> dict:
                    return {}

            PluginManager.endpoints(reg=_N())

            class C:
                @api.http.get("https://api.test/v1/item?id=0")
                def item(self):
                    return {}

            def test_item():
                """import 来的磁带也能回放"""
                r = C().item()
                assert_all(status_ok(r), json_equals(r, 'ok', 1))
        '''), encoding='utf-8')

        _env = dict(os.environ)
        _env.update({'IPANDORA_CASSETTES_DIR': str(tmp_path / 'tapes'),
                     'IPANDORA_REPORTS_DIR': str(tmp_path / 'reports')})
        done = subprocess.run(
            [sys.executable, '-m', 'ipandora.run', 'run', str(_suite),
             '--replay', '--cassette', 'imported'],
            capture_output=True, text=True, env=_env, timeout=180)
        # api.test does not resolve, so a pass proves the tape answered
        assert done.returncode == 0, done.stdout + done.stderr
        assert 'PASS' in done.stdout
