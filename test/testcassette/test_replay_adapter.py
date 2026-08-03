# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_replay_adapter.py
@Time  : 2026-08-02

The adapter, driven against a real local HTTP server.

Loopback rather than mocks, deliberately: the whole point of recording at the
adapter is that it sees the finished PreparedRequest and a real Response, and a
fake session would skip exactly the layer under test -- which is how the read
timeout defect survived its own unit tests (see docs/design/05).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests
from requests.adapters import HTTPAdapter

from ipandora.core.cassette import Cassette, Mode, OnExhausted
from ipandora.core.cassette.cassette import CassetteMiss
from ipandora.core.protocol.http import replay
from ipandora.core.protocol.http.transport import mount


class _Handler(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's naming
        type(self).hits += 1
        _body = json.dumps({'path': self.path, 'hit': type(self).hits,
                            'token': 'sk-live-abcdef1234567890'}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(_body)))
        self.end_headers()
        self.wfile.write(_body)

    def log_message(self, *_args):
        pass


@pytest.fixture
def server():
    _Handler.hits = 0
    _server = HTTPServer(('127.0.0.1', 0), _Handler)
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    yield 'http://127.0.0.1:{}'.format(_server.server_port)
    _server.shutdown()
    _server.server_close()


@pytest.fixture
def session():
    _session = mount(requests.Session())
    _session.trust_env = False
    yield _session
    replay.session.deactivate()


def tape(tmp_path, name='t', **kwargs):
    return Cassette(name, directory=str(tmp_path), **kwargs)


class TestOffByDefault:
    def test_a_run_with_no_cassette_behaves_as_before(self, server, session):
        assert replay.session.active is False
        assert session.get(server + '/v1/a').json()['path'] == '/v1/a'
        assert _Handler.hits == 1


class TestRecording:
    def test_a_call_is_recorded(self, server, session, tmp_path):
        _tape = tape(tmp_path).start_recording()
        replay.session.activate(Mode.RECORD, _tape)
        session.get(server + '/v1/a')
        _tape.finish_recording()

        [record] = list(_tape.store.read())
        assert record.method == 'GET' and record.status == 200
        assert json.loads(record.response_body)['path'] == '/v1/a'

    def test_recording_does_not_change_what_the_caller_gets(self, server, session,
                                                            tmp_path):
        replay.session.activate(Mode.RECORD, tape(tmp_path).start_recording())
        assert session.get(server + '/v1/a').json()['path'] == '/v1/a'

    def test_a_secret_in_the_body_is_redacted_before_it_lands(self, server, session,
                                                              tmp_path):
        _tape = tape(tmp_path).start_recording()
        replay.session.activate(Mode.RECORD, _tape)
        session.get(server + '/v1/a')
        _tape.finish_recording()
        assert 'sk-live-abcdef1234567890' not in open(
            _tape.store.exchanges_path, encoding='utf-8').read()

    def test_a_failure_to_write_does_not_fail_the_call(self, server, session, tmp_path):
        """Recording is an observation. If the tape cannot be written the call
        still happened and still succeeded."""
        class _Broken:
            def record(self, **_kwargs):
                raise OSError('disk full')

        replay.session.activate(Mode.RECORD, _Broken())
        assert session.get(server + '/v1/a').status_code == 200


class TestReplayDoesNotTouchTheNetwork:
    """
    The guarantee people actually rely on. Asserting "it returned the recorded
    body" is not enough -- a live server that happens to answer the same way
    would pass that.
    """

    def _recorded(self, server, session, tmp_path, path='/v1/a'):
        _tape = tape(tmp_path).start_recording()
        replay.session.activate(Mode.RECORD, _tape)
        session.get(server + path)
        _tape.finish_recording()
        replay.session.deactivate()
        return _tape

    def test_no_request_reaches_the_server(self, server, session, tmp_path):
        self._recorded(server, session, tmp_path)
        assert _Handler.hits == 1

        replay.session.activate(Mode.REPLAY, tape(tmp_path).load())
        for _ in range(1):
            session.get(server + '/v1/a')
        assert _Handler.hits == 1, 'replay reached the server'

    def test_the_underlying_adapter_is_never_called(self, server, session, tmp_path,
                                                    monkeypatch):
        # belt and braces: even a server that never notices would be caught
        self._recorded(server, session, tmp_path)

        def _explode(*_args, **_kwargs):
            raise AssertionError('ReplayAdapter fell through to the network')

        monkeypatch.setattr(HTTPAdapter, 'send', _explode)
        replay.session.activate(Mode.REPLAY, tape(tmp_path).load())
        assert session.get(server + '/v1/a').status_code == 200

    def test_the_response_is_a_usable_requests_response(self, server, session, tmp_path):
        """Built through urllib3 rather than by setting attributes, so
        everything downstream behaves -- a hand-assembled Response works until
        the first caller touches something that was never set."""
        self._recorded(server, session, tmp_path)
        replay.session.activate(Mode.REPLAY, tape(tmp_path).load())

        response = session.get(server + '/v1/a')
        assert response.status_code == 200
        assert response.json()['path'] == '/v1/a'
        assert response.text
        assert response.headers['Content-Type'] == 'application/json'
        assert response.ok
        response.raise_for_status()

    def test_a_recorded_error_status_replays_as_that_status(self, tmp_path, session):
        _tape = tape(tmp_path).start_recording()
        _tape.record(method='GET', url='http://127.0.0.1:1/v1/missing',
                     request_headers={}, request_body=None, status=404,
                     reason='Not Found', response_headers={}, response_body='{}',
                     ms=1)
        _tape.finish_recording()

        replay.session.activate(Mode.REPLAY, tape(tmp_path).load())
        response = session.get('http://127.0.0.1:1/v1/missing')
        assert response.status_code == 404 and response.ok is False

    def test_an_unrecorded_request_raises_rather_than_going_out(self, server, session,
                                                                tmp_path):
        self._recorded(server, session, tmp_path)
        replay.session.activate(Mode.REPLAY, tape(tmp_path).load())
        with pytest.raises(CassetteMiss):
            session.get(server + '/v1/never-recorded')
        assert _Handler.hits == 1

    def test_passthrough_is_the_only_way_out(self, server, session, tmp_path):
        self._recorded(server, session, tmp_path)
        replay.session.activate(
            Mode.REPLAY, tape(tmp_path, on_exhausted=OnExhausted.PASSTHROUGH).load())
        session.get(server + '/v1/never-recorded')
        assert _Handler.hits == 2


class TestRoundTrip:
    def test_what_was_recorded_is_what_comes_back(self, server, session, tmp_path):
        _tape = tape(tmp_path).start_recording()
        replay.session.activate(Mode.RECORD, _tape)
        live = [session.get(server + '/v1/{}'.format(i)).json() for i in range(3)]
        _tape.finish_recording()
        replay.session.deactivate()

        replay.session.activate(Mode.REPLAY, tape(tmp_path).load())
        played = [session.get(server + '/v1/{}'.format(i)).json() for i in range(3)]
        assert [p['path'] for p in played] == [l['path'] for l in live]
        assert _Handler.hits == 3

    def test_the_same_url_replays_in_recorded_order(self, server, session, tmp_path):
        # the handler counts hits, so each call to the same path differs
        _tape = tape(tmp_path).start_recording()
        replay.session.activate(Mode.RECORD, _tape)
        live = [session.get(server + '/v1/a').json()['hit'] for _ in range(3)]
        _tape.finish_recording()
        replay.session.deactivate()

        replay.session.activate(Mode.REPLAY, tape(tmp_path).load())
        played = [session.get(server + '/v1/a').json()['hit'] for _ in range(3)]
        assert played == live == [1, 2, 3]
