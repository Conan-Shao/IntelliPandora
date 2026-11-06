# -*- coding: utf-8 -*-
"""
@File  : test_tracing.py
@Time  : 2026-11-06

Cross-service trace evidence (docs/design/decisions/14 §12, D7): requests
carry a W3C traceparent, one trace per case; the evidence and the report
show the trace each request went out under.
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ipandora.core import api, auth, tracing
from ipandora.core.concurrency import concurrently
from ipandora.core.evidence import recorder
from ipandora.core.report.builder import _redact_exchange
from ipandora.core.report.model import ReportCase
from ipandora.core.report.render import to_html
from ipandora.core.schedule.session import SessionManager

LINK = 'http://jaeger.test:16686/trace/{trace_id}'


class Service:
    """Echoes the traceparent it received; /me accepts only the newest token."""

    def __init__(self):
        self.seen, self.token, self.url = [], 0, ''


def _handler(svc):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, code, body):
            _data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(_data)))
            self.end_headers()
            self.wfile.write(_data)

        def do_GET(self):
            svc.seen.append(self.headers.get('traceparent'))
            if self.path == '/me' and self.headers.get('Authorization') != 'Bearer tok-{}'.format(svc.token):
                return self._reply(401, {})
            self._reply(200, {'traceparent': self.headers.get('traceparent')})

        def do_POST(self):
            svc.token += 1
            self._reply(200, {'token': 'tok-{}'.format(svc.token)})  # pragma: allowlist secret
    return Handler


@pytest.fixture
def svc():
    _svc = Service()
    _server = ThreadingHTTPServer(('127.0.0.1', 0), _handler(_svc))
    _server.daemon_threads = True
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    _svc.url = 'http://127.0.0.1:{}'.format(_server.server_address[1])
    yield _svc
    _server.shutdown()
    _server.server_close()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(tracing, '_settings', lambda: {'enabled': True, 'link': LINK})


@pytest.fixture(autouse=True)
def clean():
    auth.reset()
    SessionManager.forget()
    yield
    auth.reset()
    SessionManager.forget()


def client(svc):
    class Api:
        @api.http.get(svc.url + '/echo')
        def echo(self, headers=None):
            return {'headers': headers} if headers else {}

        @api.http.get(svc.url + '/me')
        def me(self):
            return {}

        @api.http.get('http://127.0.0.1:9/')
        def gone(self):
            return {'timeout': 2}
    return Api()


class _Case:
    def __init__(self, name='t::case'):
        self.name = name

    def __enter__(self):
        recorder.begin(self.name)
        return self

    def __exit__(self, *exc):
        self.evidence = recorder.end(self.name)


class TestHeader:

    def test_parse(self):
        _ok = '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01'
        assert tracing.parse(_ok) == {'trace_id': '4bf92f3577b34da6a3ce929d0e0e4736', 'span_id': '00f067aa0ba902b7'}
        assert tracing.parse(_ok.upper()) is not None
        for _bad in ('', None, 'nonsense', _ok[:-1], 'ff' + _ok[2:],
                     '00-' + '0' * 32 + '-00f067aa0ba902b7-01', '00-4bf92f3577b34da6a3ce929d0e0e4736-' + '0' * 16 + '-01'):
            assert tracing.parse(_bad) is None, _bad
        assert tracing.of_headers({'TraceParent': _ok}) == '4bf92f3577b34da6a3ce929d0e0e4736'
        assert tracing.of_headers({'traceparent': 'junk'}) == tracing.of_headers(None) == ''

    def test_one_trace_per_case_and_a_new_span_per_request(self):
        with _Case('t::a'):
            _a1, _a2 = tracing.parse(tracing.traceparent()), tracing.parse(tracing.traceparent())
        with _Case('t::b'):
            _b = tracing.parse(tracing.traceparent())
        assert _a1['trace_id'] == _a2['trace_id'] != _b['trace_id']
        assert _a1['span_id'] != _a2['span_id']
        assert tracing.trace_id() != tracing.trace_id()           # outside a case, each request its own

    def test_link_only_for_a_web_page(self, monkeypatch):
        for _template, _expected in ((LINK, 'http://jaeger.test:16686/trace/ab'), ('', ''),
                                     ('http://tempo.test/explore', ''), ('javascript:alert({trace_id})', '')):
            monkeypatch.setattr(tracing, '_settings', lambda t=_template: {'link': t})
            assert tracing.link('ab') == _expected


class TestRequests:

    def test_off_by_default(self, svc):
        with _Case():
            client(svc).echo()
        assert svc.seen == [None]

    def test_every_request_of_a_case_shares_its_trace(self, svc, on):
        _api = client(svc)
        with _Case() as _c:
            _api.echo()
            _api.echo()
        _sent = [tracing.parse(_h) for _h in svc.seen]
        assert _sent[0]['trace_id'] == _sent[1]['trace_id'] and _sent[0]['span_id'] != _sent[1]['span_id']
        assert [_e['trace_id'] for _e in _c.evidence.exchanges] == [_sent[0]['trace_id']] * 2
        assert _c.evidence.trace_id == _sent[0]['trace_id']

    def test_a_traceparent_the_case_set_is_left_alone(self, svc, on):
        _own = '00-11111111111111111111111111111111-2222222222222222-01'
        with _Case() as _c:
            client(svc).echo(headers={'TraceParent': _own})
        assert svc.seen == [_own]
        assert _c.evidence.exchanges[0]['trace_id'] == '1' * 32       # what went out, not what we meant to send

    def test_concurrent_requests_are_in_the_case_trace(self, svc, on):
        _api = client(svc)
        with _Case() as _c:
            concurrently([_api.echo] * 3)
        assert {tracing.parse(_h)['trace_id'] for _h in svc.seen} == {_c.evidence.trace_id}
        assert len({tracing.parse(_h)['span_id'] for _h in svc.seen}) == 3

    def test_a_request_that_never_got_an_answer_keeps_its_trace(self, svc, on):
        with _Case() as _c:
            with pytest.raises(Exception):
                client(svc).gone()
        assert _c.evidence.exchanges[0]['error'] and _c.evidence.exchanges[0]['trace_id'] == _c.evidence.trace_id

    def test_signing_covers_it_and_a_replay_is_a_span_of_its_own(self, svc, on):
        _signed = []

        class Login(auth.Provider):
            def login(self, name, session):
                return auth.Bearer(session.post(svc.url + '/login', json={}).json()['token'])

            def sign(self, name, credential, request):
                _signed.append(dict(request.kwargs['headers']).get('traceparent'))
        auth.provider(Login())
        _api = client(svc)
        with _Case() as _c, auth.identity('buyer'):
            _api.me()
            svc.token += 1                         # the token is revoked: the next call is rejected and replayed
            _api.me()
        _me = [_h for _h in svc.seen if _h]
        assert len(_me) == 3 and _signed == _me    # every traceparent sent was there when sign() ran
        _spans = [tracing.parse(_h) for _h in _me]
        assert len({_s['trace_id'] for _s in _spans}) == 1 and len({_s['span_id'] for _s in _spans}) == 3
        assert [_e['role'] for _e in _c.evidence.exchanges if '/me' in _e['url']] == ['', '', 'replayed']


class TestReport:

    def test_each_trace_is_linked(self, on):
        _trace = 'a' * 32
        _ex = _redact_exchange({'method': 'GET', 'url': 'http://svc/x', 'status': 500, 'trace_id': _trace,
                                'request_headers': {'traceparent': '00-{}-{}-01'.format(_trace, 'b' * 16)}})
        assert _ex['trace_url'] == 'http://jaeger.test:16686/trace/' + _trace
        _case = ReportCase(name='t', nodeid='t::t', exchanges=[_ex, dict(_ex), {'url': 'http://svc/y'}])
        assert _case.traces == [{'id': _trace, 'url': _ex['trace_url']}]
        from ipandora.core.report.model import ReportData
        _html = to_html(ReportData(cases=[_case]))
        assert '<a href="http://jaeger.test:16686/trace/{}"'.format(_trace) in _html


class TestCr10:
    """Found in code review CR10 (docs/design/reviews/10-CR10.md)."""

    def test_a_traceparent_on_the_session_is_the_cases_own(self, svc, on):
        _own = '00-33333333333333333333333333333333-4444444444444444-01'
        SessionManager.getSession().headers['traceparent'] = _own
        with _Case():
            client(svc).echo(headers={'Content-Type': 'text/plain'})     # the session's headers are not copied in
            client(svc).echo()
        assert svc.seen == [_own, _own]

    def test_a_report_rebuilt_from_json_links_only_web_pages(self):
        from ipandora.core.report.builder import build_from_dict
        _trace = 'c' * 32
        _report = build_from_dict({'cases': [{'name': 't', 'nodeid': 't::t', 'exchanges': [
            {'url': 'http://svc/a', 'trace_id': _trace, 'trace_url': 'javascript:alert(document.cookie)'},
            {'url': 'http://svc/b', 'trace_id': 'd' * 32, 'trace_url': 'https://tempo.test/t/' + 'd' * 32}]}]})
        _html = to_html(_report)
        assert 'javascript:' not in _html
        assert '<code>{}</code>'.format(_trace) in _html                  # still shown, just not as a link
        assert '<a href="https://tempo.test/t/{}"'.format('d' * 32) in _html


class TestR1:
    """Gaps mutation testing found (R1): each test fails on a mutant that survived before."""

    @staticmethod
    def _request(**headers):
        from types import SimpleNamespace
        return SimpleNamespace(kwargs={'headers': dict(headers)} if headers else {})

    def test_injecting_twice_keeps_one_header_and_a_renewal_keeps_the_rest(self, on):
        _r = self._request(Authorization='Bearer x', Accept='text/csv')
        tracing.inject(_r)
        _first = _r.kwargs['headers']['traceparent']
        tracing.inject(_r)                                   # not a renewal: the same span
        assert _r.kwargs['headers']['traceparent'] == _first
        tracing.inject(_r, renew=True)                       # a replay: a new span, every other header kept
        assert _r.kwargs['headers']['traceparent'] != _first
        assert _r.kwargs['headers']['Authorization'] == 'Bearer x' and _r.kwargs['headers']['Accept'] == 'text/csv'

    def test_a_replay_never_replaces_the_cases_own(self, on):
        _own = '00-' + '5' * 32 + '-' + '6' * 16 + '-01'
        _r = self._request(traceparent=_own)
        tracing.inject(_r, renew=True)
        assert _r.kwargs['headers'] == {'traceparent': _own}

    def test_a_request_without_headers_or_a_session_gets_one(self, on):
        _r = self._request()                                 # no headers, no option, no session
        tracing.inject(_r)
        assert tracing.parse(_r.kwargs['headers']['traceparent'])

    def test_ids_are_w3c_shaped_outside_a_case_and_never_all_zeros(self, monkeypatch):
        assert re.fullmatch(r'[0-9a-f]{32}', tracing.trace_id())
        _given = iter(['0' * 32, 'ab' * 16])
        monkeypatch.setattr(tracing.secrets, 'token_hex', lambda n: next(_given))
        assert tracing._hex(16) == 'ab' * 16                 # an all-zero id is invalid: drawn again

    def test_the_settings_are_read_from_the_config(self, monkeypatch):
        from ipandora.core.schedule import config
        from ipandora.core.schedule.runtime import Runtime
        monkeypatch.setattr(Runtime, 'settings', config.deep_merge(Runtime.settings, {
            'tracing': {'enabled': True, 'link': 'https://tempo.test/{trace_id}'}}))
        assert tracing.enabled() and tracing.link('ab') == 'https://tempo.test/ab'
        monkeypatch.setattr(Runtime, 'settings', config.deep_merge(Runtime.settings, {'tracing': None}))
        assert not tracing.enabled() and tracing.link('ab') == ''

    def test_hosts_are_compared_by_name_and_port(self):
        _n = tracing._netloc
        assert _n('http://Shop.TEST:8080/orders?x=1') == 'shop.test:8080'
        assert _n('api.shop.test') == _n('http://api.shop.test') == 'api.shop.test:80'
        assert _n('https://shop.test/') == 'shop.test:443' != _n('http://shop.test/')
        assert _n('shop.test:8443') == 'shop.test:8443'
        assert _n('') == _n(None) == '' and _n('http://') == ''

    @staticmethod
    def _routed(monkeypatch, settings, base_url):
        from types import SimpleNamespace
        monkeypatch.setattr(tracing, '_settings', lambda: settings)
        _installed = []
        _context = SimpleNamespace(route=lambda pattern, handler: _installed.append((pattern, handler)))
        _ok = tracing.browser(_context, base_url)

        def _send(url, **headers):
            _out = {}
            _route = SimpleNamespace(request=SimpleNamespace(url=url, headers=dict(headers)),
                                     fallback=lambda headers=None: _out.update(sent=headers))
            _installed[0][1](_route)
            return _out['sent']
        return _ok, _installed, _send

    def test_the_browser_route_sends_to_the_application_only(self, monkeypatch):
        _ok, _installed, _send = self._routed(
            monkeypatch, {'enabled': True, 'hosts': ['api.shop.test:8443']}, 'https://shop.test/app')
        assert _ok and [_p for _p, _ in _installed] == ['**/*']
        assert tracing.parse(_send('https://shop.test/orders', accept='*/*')['traceparent'])
        assert _send('https://shop.test/orders', accept='*/*')['accept'] == '*/*'
        assert tracing.parse(_send('https://api.shop.test:8443/v1')['traceparent'])      # listed in tracing.hosts
        assert _send('https://cdn.example/lib.js') is None                              # not the application
        assert _send('https://api.shop.test/v1') is None                                # another port is another host
        _own = '00-' + '7' * 32 + '-' + '8' * 16 + '-01'
        assert _send('https://shop.test/x', Traceparent=_own) is None                   # the page's own, any case

    def test_the_browser_route_is_not_installed_off_or_without_an_application(self, monkeypatch):
        assert self._routed(monkeypatch, {'enabled': False}, 'https://shop.test')[:2] == (False, [])
        assert self._routed(monkeypatch, {'enabled': True}, '')[:2] == (False, [])
        assert self._routed(monkeypatch, {'enabled': True, 'hosts': None}, '')[:2] == (False, [])
