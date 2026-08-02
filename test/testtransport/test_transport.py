# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_transport.py
@Time  : 2026-08-01
"""
import contextlib
import json
import socket
import threading

import pytest
import requests

from ipandora.core import api
from ipandora.core.base.data.markdata import MarkData
from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface
from ipandora.core.plugin.pluginmanager import PluginManager
from ipandora.core.protocol.http.transport import (IDEMPOTENT_METHODS, RETRY_STATUS,
                                                   TransportPolicy, build_adapter, mount,
                                                   translate_error)
from ipandora.core.schedule.runtime import Runtime
from ipandora.core.schedule.session import SessionManager
from ipandora.utils.error import HttpConnectionError, HttpTimeoutError, TransportError


class _EndPointPlugin(EndPointsInterface):
    def endpoints(self, mark: MarkData) -> dict:
        return {}


PluginManager.endpoints(reg=_EndPointPlugin())


def _fake_response(status=200, body=None):
    resp = requests.Response()
    resp.status_code = status
    resp._content = json.dumps(body if body is not None else {'ok': True}).encode()
    resp.url = 'https://example.test/thing'
    resp.request = requests.Request(method='GET', url=resp.url).prepare()
    return resp


class RecordingSession(requests.Session):
    """Captures the kwargs that actually reach requests."""

    def __init__(self, raises=None):
        super().__init__()
        self.calls = []
        self._raises = raises

    def _record(self, method, args, kwargs):
        self.calls.append({'method': method, 'args': args, 'kwargs': kwargs})
        if self._raises:
            raise self._raises
        return _fake_response()

    def get(self, *args, **kwargs):
        return self._record('get', args, kwargs)

    def post(self, *args, **kwargs):
        return self._record('post', args, kwargs)


@pytest.fixture
def reset_runtime():
    """Undo config overrides. Runtime memoises process-wide, so without this an
    override leaks into every test that follows."""
    yield
    Runtime.reset()


@pytest.fixture
def recording(request):
    """Install a recording session for the current thread, then restore."""
    session = RecordingSession(raises=getattr(request, 'param', None))
    SessionManager.setSession(session)
    yield session
    SessionManager._session_map.pop(SessionManager.name(), None)


class Client:
    @api.http.get('https://example.test/thing')
    def fetch(self):
        return {}

    @api.http.get('https://example.test/thing')
    def fetch_insecure(self):
        return dict(verify=False)

    @api.http.get('https://example.test/thing')
    def fetch_slow(self):
        return dict(timeout=99)

    @api.http.post('https://example.test/thing')
    def submit(self):
        return dict(json={'a': 1})


class TestTlsVerification:
    """
    Every https request used to get verify=False injected, so the suite could
    never catch an expired or misconfigured certificate.
    """

    def test_verify_is_on_by_default(self, recording):
        Client().fetch()
        assert recording.calls[0]['kwargs']['verify'] is True

    def test_caller_can_still_opt_out(self, recording):
        Client().fetch_insecure()
        assert recording.calls[0]['kwargs']['verify'] is False

    def test_follows_config(self, recording, reset_runtime):
        Runtime.Http.verify = False
        Client().fetch()
        assert recording.calls[0]['kwargs']['verify'] is False


class TestTimeout:
    """
    ApiOption defaulted timeout to 0 and nothing called set_timeout, so every
    request waited forever -- one hung endpoint hung the whole suite.
    """

    def test_timeout_is_applied_by_default(self, recording):
        Client().fetch()
        assert recording.calls[0]['kwargs']['timeout'] == (
            Runtime.Http.connect_timeout, Runtime.Http.read_timeout)

    def test_connect_and_read_are_separate(self):
        policy = TransportPolicy(connect_timeout=3, read_timeout=17)
        assert policy.timeout == (3, 17)

    def test_caller_override_wins(self, recording):
        Client().fetch_slow()
        assert recording.calls[0]['kwargs']['timeout'] == 99

    def test_no_request_is_unbounded(self, recording):
        Client().fetch()
        Client().submit()
        assert all(c['kwargs'].get('timeout') for c in recording.calls)


class TestRetryPolicy:
    def test_adapter_carries_retry_config(self):
        retry = build_adapter(TransportPolicy(max_retries=5, backoff_factor=0.5)).max_retries
        assert retry.total == 5
        assert retry.backoff_factor == 0.5

    def test_only_transient_statuses_retried(self):
        assert set(build_adapter().max_retries.status_forcelist) == set(RETRY_STATUS)
        # a 500 is a real defect; retrying it just hides a flaky-looking failure
        assert 500 not in RETRY_STATUS
        assert 404 not in RETRY_STATUS

    def test_non_idempotent_methods_are_not_retried(self):
        # replaying a POST can double-submit
        assert 'POST' not in IDEMPOTENT_METHODS
        assert 'PATCH' not in IDEMPOTENT_METHODS
        assert IDEMPOTENT_METHODS >= {'GET', 'HEAD', 'PUT', 'DELETE'}
        assert set(build_adapter().max_retries.allowed_methods) == set(IDEMPOTENT_METHODS)

    def test_status_does_not_raise_inside_urllib3(self):
        # the response must reach our assertion layer, not blow up in the adapter
        assert build_adapter().max_retries.raise_on_status is False

    def test_mount_covers_both_schemes(self):
        session = mount(requests.Session(), TransportPolicy(max_retries=4))
        assert session.get_adapter('https://x.test').max_retries.total == 4
        assert session.get_adapter('http://x.test').max_retries.total == 4

    def test_new_sessions_get_the_adapter(self):
        # A bare requests.Session already carries a Retry object (total=0), so
        # this has to compare the configured value, not just the type.
        assert requests.Session().get_adapter('https://x.test').max_retries.total == 0

        SessionManager._session_map.pop(SessionManager.name(), None)
        try:
            retry = SessionManager.getSession().get_adapter('https://x.test').max_retries
            assert retry.total == Runtime.Http.max_retries
            assert set(retry.status_forcelist) == set(RETRY_STATUS)
        finally:
            SessionManager._session_map.pop(SessionManager.name(), None)


class TestErrorSemantics:
    """
    A transport failure produces no response, so there is nothing to assert
    on. It must be distinguishable from a response the test dislikes.
    """

    @pytest.mark.parametrize('recording', [requests.exceptions.ConnectTimeout('slow')],
                             indirect=True)
    def test_timeout_becomes_framework_error(self, recording):
        with pytest.raises(HttpTimeoutError) as exc:
            Client().fetch()
        assert 'example.test' in str(exc.value)
        assert exc.value.method == 'GET'
        assert exc.value.elapsed is not None

    @pytest.mark.parametrize('recording', [requests.exceptions.ConnectionError('refused')],
                             indirect=True)
    def test_connection_error_becomes_framework_error(self, recording):
        with pytest.raises(HttpConnectionError):
            Client().fetch()

    @pytest.mark.parametrize('recording', [requests.exceptions.ConnectTimeout('slow')],
                             indirect=True)
    def test_original_exception_is_preserved_as_cause(self, recording):
        with pytest.raises(HttpTimeoutError) as exc:
            Client().fetch()
        assert isinstance(exc.value.__cause__, requests.exceptions.Timeout)

    @pytest.mark.parametrize('recording', [ValueError('not a transport problem')],
                             indirect=True)
    def test_unrelated_exceptions_propagate_untouched(self, recording):
        with pytest.raises(ValueError):
            Client().fetch()

    def test_both_subtypes_share_a_base(self):
        assert issubclass(HttpTimeoutError, TransportError)
        assert issubclass(HttpConnectionError, TransportError)

    def test_existing_requests_handlers_still_catch_these(self):
        # ConnectionError already surfaced before this change, so code that
        # catches the requests exception must keep working.
        assert issubclass(HttpConnectionError, requests.exceptions.ConnectionError)
        assert issubclass(HttpTimeoutError, requests.exceptions.Timeout)

    def test_context_survives_the_mro(self):
        # multiple inheritance must not eat the attributes TransportError sets
        exc = HttpTimeoutError('boom', details='d', url='https://x.test',
                               method='GET', elapsed=1.5)
        assert (exc.url, exc.method, exc.elapsed, exc.message) == (
            'https://x.test', 'GET', 1.5, 'boom')

    @pytest.mark.parametrize('recording', [requests.exceptions.ConnectionError('refused')],
                             indirect=True)
    def test_caught_by_requests_except_clause(self, recording):
        with pytest.raises(requests.exceptions.ConnectionError):
            Client().fetch()

    def test_translate_returns_none_for_unrelated(self):
        assert translate_error(ValueError('nope'), url='u', method='get') is None


@contextlib.contextmanager
def _blackhole_server():
    """
    A listener that completes the TCP handshake and then says nothing.

    The connection succeeds, so this is unambiguously a *read* timeout rather
    than a connect failure -- which is the distinction the framework has to get
    right. Loopback only: no network access is involved.
    """
    _srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _srv.bind(('127.0.0.1', 0))
    _srv.listen(8)
    _srv.settimeout(0.2)
    _held, _stop = [], threading.Event()

    def _accept_loop():
        while not _stop.is_set():
            try:
                _conn, _ = _srv.accept()
            except OSError:
                continue
            _held.append(_conn)  # keep it open, send nothing

    _thread = threading.Thread(target=_accept_loop, daemon=True)
    _thread.start()
    try:
        yield 'http://127.0.0.1:{}/hang'.format(_srv.getsockname()[1])
    finally:
        _stop.set()
        _thread.join(timeout=2)
        for _conn in _held:
            _conn.close()
        _srv.close()


class TestTimeoutThroughTheRealAdapter:
    """
    Regression: a read timeout used to surface as HttpConnectionError.

    Mounting a Retry adapter -- which this framework does for every session --
    makes urllib3 wrap the read timeout as MaxRetryError(reason=ReadTimeoutError),
    and requests then maps that to ConnectionError instead of ReadTimeout. So
    `isinstance(exc, Timeout)` quietly stopped being true.

    The tests above missed it because they inject a ConnectTimeout straight into
    a fake session, which never touches the adapter. These go through the real
    adapter, real urllib3 and a real socket, so the wrapping actually happens.
    """

    @staticmethod
    def _raise_through_adapter(url, retries):
        session = mount(requests.Session(), TransportPolicy(max_retries=retries))
        session.trust_env = False  # an ambient proxy would answer, defeating the point
        with pytest.raises(requests.exceptions.RequestException) as exc:
            session.get(url, timeout=(5, 0.25))
        return exc.value

    @pytest.mark.parametrize('retries', [0, 2])
    def test_read_timeout_is_reported_as_a_timeout(self, retries):
        with _blackhole_server() as url:
            raw = self._raise_through_adapter(url, retries)
            translated = translate_error(raw, url=url, method='GET', elapsed=0.3)
        assert isinstance(translated, HttpTimeoutError), (
            'a read timeout reported as {}'.format(type(translated).__name__))

    def test_the_wrapping_this_guards_against_is_real(self):
        # Control. If requests ever starts raising a plain ReadTimeout through a
        # mounted adapter, the unwrapping below becomes dead code and this test
        # says so instead of leaving it there forever.
        with _blackhole_server() as url:
            raw = self._raise_through_adapter(url, retries=2)
        assert not isinstance(raw, requests.exceptions.Timeout)
        assert isinstance(raw, requests.exceptions.ConnectionError)

    def test_a_genuine_connection_failure_is_still_a_connection_error(self):
        # The fix must not turn every ConnectionError into a timeout. Port 1 on
        # loopback refuses immediately -- no timeout anywhere in the chain.
        session = mount(requests.Session(), TransportPolicy(max_retries=0))
        session.trust_env = False
        with pytest.raises(requests.exceptions.RequestException) as exc:
            session.get('http://127.0.0.1:1/nope', timeout=(2, 2))
        translated = translate_error(exc.value, url='http://127.0.0.1:1/nope', method='GET')
        assert isinstance(translated, HttpConnectionError)
        assert not isinstance(translated, HttpTimeoutError)

    def test_end_to_end_through_the_decorator(self, monkeypatch):
        monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
        SessionManager._session_map.pop(SessionManager.name(), None)
        try:
            with _blackhole_server() as url:
                class Hanging:
                    @api.http.get(url)
                    def fetch(self):
                        return dict(timeout=(5, 0.25))

                with pytest.raises(HttpTimeoutError) as exc:
                    Hanging().fetch()
            assert exc.value.method == 'GET'
            assert exc.value.elapsed is not None
        finally:
            SessionManager._session_map.pop(SessionManager.name(), None)


class TestSessionLocking:
    def test_lock_is_released_after_an_exception(self):
        # acquire/release without try/finally used to leave the RLock held
        # forever if anything in between raised.
        try:
            with SessionManager._lock:
                raise RuntimeError('boom')
        except RuntimeError:
            pass
        assert SessionManager._lock.acquire(timeout=1)
        SessionManager._lock.release()

    def test_concurrent_access_yields_one_session_per_thread(self):
        seen = {}

        def grab(idx):
            seen[idx] = id(SessionManager.getSession())

        threads = [threading.Thread(target=grab, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(set(seen.values())) == len(threads)

    def test_repeated_calls_reuse_one_session(self):
        SessionManager._session_map.pop(SessionManager.name(), None)
        try:
            assert SessionManager.getSession() is SessionManager.getSession()
        finally:
            SessionManager._session_map.pop(SessionManager.name(), None)
