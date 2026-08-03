# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_record_replay_cli.py
@Time  : 2026-08-02

`ipandora run --record` / `--replay` end to end.

A local HTTP server stands in for the system under test, so recording is real
without the suite needing egress. The server is then stopped before replay --
which is the only honest way to show a tape is being played: if anything still
reached the network the run would fail, not quietly succeed.
"""
import json
import os
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

SUITE = '''
    from ipandora.core import api
    from ipandora.core.assertion import assert_all, json_equals, status_ok
    from ipandora.core.base.data.markdata import MarkData
    from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface
    from ipandora.core.plugin.pluginmanager import PluginManager
    import os

    class _N(EndPointsInterface):
        def endpoints(self, mark: MarkData) -> dict:
            return {{}}

    PluginManager.endpoints(reg=_N())

    BASE = "{base}"

    class C:
        @api.http.get(BASE + "/v1/thing")
        def thing(self):
            return {{'headers': {{'Authorization': 'Bearer sk-live-abcdef1234567890'}}}}

    def test_thing():
        """读一个东西"""
        r = C().thing()
        assert_all(status_ok(r), json_equals(r, 'name', 'widget'))
'''


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        _body = json.dumps({'name': 'widget', 'secret': 'hunter2hunter2'}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(_body)))
        self.end_headers()
        self.wfile.write(_body)

    def log_message(self, *_args):
        pass


@pytest.fixture
def stoppable_server():
    _server = HTTPServer(('127.0.0.1', 0), _Handler)
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    _base = 'http://127.0.0.1:{}'.format(_server.server_port)

    def _stop():
        _server.shutdown()
        _server.server_close()

    yield _base, _stop
    try:
        _stop()
    except Exception:  # noqa: BLE001 - already stopped by the test
        pass


def ipandora(*args, tmp_path, extra_env=None):
    _env = dict(os.environ)
    _env.update({'IPANDORA_REPORTS_DIR': str(tmp_path / 'reports'),
                 'IPANDORA_CASSETTES_DIR': str(tmp_path / 'tapes'),
                 'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'})
    _env.update(extra_env or {})
    return subprocess.run([sys.executable, '-m', 'ipandora.run'] + list(args),
                          capture_output=True, text=True, env=_env, timeout=180)


@pytest.fixture
def suite(tmp_path, stoppable_server):
    _base, _stop = stoppable_server
    _file = tmp_path / 'test_tape_suite.py'
    _file.write_text(textwrap.dedent(SUITE).format(base=_base), encoding='utf-8')
    return str(_file), _stop


class TestRecordThenReplay:
    def test_the_suite_passes_and_a_tape_appears(self, tmp_path, suite):
        _file, _stop = suite
        done = ipandora('run', _file, '--record', '--cassette', 'demo',
                        tmp_path=tmp_path)
        assert done.returncode == 0, done.stdout + done.stderr
        tape = tmp_path / 'tapes' / 'demo'
        assert (tape / 'exchanges.jsonl').is_file()
        assert (tape / 'manifest.yaml').is_file()

    def test_replay_works_after_the_server_is_gone(self, tmp_path, suite):
        """The proof. With the server stopped, a run that still reached the
        network would fail rather than quietly pass."""
        _file, _stop = suite
        assert ipandora('run', _file, '--record', '--cassette', 'demo',
                        tmp_path=tmp_path).returncode == 0
        _stop()

        done = ipandora('run', _file, '--replay', '--cassette', 'demo',
                        tmp_path=tmp_path)
        assert done.returncode == 0, done.stdout + done.stderr
        assert '磁带' in done.stdout

    def test_without_the_tape_the_same_run_fails_once_the_server_is_gone(
            self, tmp_path, suite):
        """The control. Without it, the test above proves only that the suite
        passes -- not that the tape is what made it pass."""
        _file, _stop = suite
        _stop()
        assert ipandora('run', _file, tmp_path=tmp_path).returncode == 1

    def test_the_recorded_secret_is_not_in_the_tape(self, tmp_path, suite):
        _file, _stop = suite
        ipandora('run', _file, '--record', '--cassette', 'demo', tmp_path=tmp_path)
        raw = (tmp_path / 'tapes' / 'demo' / 'exchanges.jsonl').read_text(
            encoding='utf-8')
        assert 'sk-live-abcdef1234567890' not in raw
        assert 'hunter2hunter2' not in raw, 'a body field named secret survived'

    def test_replaying_a_cassette_that_does_not_exist_says_how_to_make_one(
            self, tmp_path, suite):
        _file, _stop = suite
        done = ipandora('run', _file, '--replay', '--cassette', 'nope',
                        tmp_path=tmp_path)
        assert done.returncode != 0
        assert '--record' in (done.stdout + done.stderr)

    def test_a_cassette_name_is_derived_when_not_given(self, tmp_path, suite):
        _file, _stop = suite
        assert ipandora('run', _file, '--record', tmp_path=tmp_path).returncode == 0
        assert (tmp_path / 'tapes' / 'test_tape_suite').is_dir()

    def test_an_expired_cassette_fails_the_run(self, tmp_path, suite):
        """A tape nobody re-records keeps a suite green while it tests an
        assumption nobody holds anymore, and it does so silently."""
        _file, _stop = suite
        ipandora('run', _file, '--record', '--cassette', 'demo', tmp_path=tmp_path)
        manifest = tmp_path / 'tapes' / 'demo' / 'manifest.yaml'
        manifest.write_text(
            manifest.read_text(encoding='utf-8').replace(
                manifest.read_text(encoding='utf-8').split('recorded_at: ')[1]
                .splitlines()[0], "'2020-01-01T00:00:00Z'"),
            encoding='utf-8')
        _stop()

        done = ipandora('run', _file, '--replay', '--cassette', 'demo',
                        '--max-cassette-age', '30', tmp_path=tmp_path)
        assert done.returncode != 0
        assert '过期' in (done.stdout + done.stderr)

    def test_record_and_replay_cannot_be_combined(self, tmp_path, suite):
        _file, _stop = suite
        done = ipandora('run', _file, '--record', '--replay', tmp_path=tmp_path)
        assert done.returncode != 0
