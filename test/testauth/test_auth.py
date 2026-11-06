# -*- coding: utf-8 -*-
"""
@File  : test_auth.py
@Time  : 2026-11-06

Identities and providers (docs/design/decisions/17 §2, plan A1), against a
local service that logs in, expires tokens and allows one session per user.

Acceptance: two identities in one case never mix; concurrently() carries the
identity; a credential the case wrote itself -- an expired token on purpose --
is never "fixed" by a refresh.
"""
import json
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ipandora.core import api, auth
from ipandora.core.assertion.http import json_body, status_code
from ipandora.core.concurrency import concurrently
from ipandora.core.evidence import recorder
from ipandora.core.runner import plugin, run
from ipandora.core.schedule.session import SessionManager
from ipandora.core.triage import Category, classify

PASSWORDS = {'buyer': 'b-pass', 'seller': 's-pass'}


class Service:
    """Tokens per user; a new login revokes the user's older tokens (single session)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.tokens = {}            # token -> user
        self.logins = {}            # user -> count
        self.sessions = {}          # cookie sid -> user
        self.posts = 0
        self.url = ''

    def login(self, user, password):
        if PASSWORDS.get(user) != password:
            return None
        with self.lock:
            self.logins[user] = self.logins.get(user, 0) + 1
            for _t in [_t for _t, _u in self.tokens.items() if _u == user]:
                del self.tokens[_t]         # single session: the old token stops working
            _token = 'tok-{}-{}'.format(user, self.logins[user])
            self.tokens[_token] = user
            return _token

    def expire(self, user):
        with self.lock:
            for _t in [_t for _t, _u in self.tokens.items() if _u == user]:
                del self.tokens[_t]


def _handler(svc):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, code, body=None, headers=None):
            _data = json.dumps(body or {}).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            for _k, _v in (headers or {}).items():
                self.send_header(_k, _v)
            self.send_header('Content-Length', str(len(_data)))
            self.end_headers()
            self.wfile.write(_data)

        def _user(self):
            _auth = self.headers.get('Authorization') or ''
            if _auth.startswith('Bearer '):
                return svc.tokens.get(_auth[7:])
            _cookie = self.headers.get('Cookie') or ''
            for _part in _cookie.split(';'):
                _k, _, _v = _part.strip().partition('=')
                if _k == 'sid' and _v in svc.sessions:
                    return svc.sessions[_v]
            if self.headers.get('X-Api-Key') == 'key-1':
                return 'robot'
            return None

        def do_POST(self):
            _len = int(self.headers.get('Content-Length') or 0)
            _raw = self.rfile.read(_len) if _len else b''
            try:
                _body = json.loads(_raw or b'{}')
            except ValueError:
                _body = {}              # a multipart upload
            if self.path == '/login':
                _token = svc.login(_body.get('user'), _body.get('password'))
                return self._reply(200, {'token': _token}) if _token else self._reply(403, {'error': 'bad password'})
            if self.path == '/cookie-login':
                _token = svc.login(_body.get('user'), _body.get('password'))
                if not _token:
                    return self._reply(403)
                svc.sessions['sid-' + _token] = _body.get('user')
                return self._reply(200, {}, {'Set-Cookie': 'sid=sid-{}; Path=/'.format(_token)})
            if self.path == '/orders':
                svc.posts += 1
                _user = self._user()
                return self._reply(201, {'by': _user}) if _user else self._reply(401)
            return self._reply(404)

        def do_GET(self):
            if self.path == '/me':
                _user = self._user()
                return self._reply(200, {'user': _user}) if _user else self._reply(401, {'error': 'login'})
            if self.path == '/me-code':
                _user = self._user()
                return self._reply(200, {'code': 0, 'user': _user} if _user else {'code': 401})
            return self._reply(404)

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


@pytest.fixture(autouse=True)
def clean():
    auth.reset()
    SessionManager.forget()
    yield
    auth.reset()
    SessionManager.forget()


def client(svc):
    class ShopApi:
        @api.http.get(svc.url + '/me')
        def me(self, headers=None):
            return {'headers': headers} if headers else {}

        @api.http.get(svc.url + '/me-code')
        def me_code(self):
            return {}

        @api.http.post(svc.url + '/orders')
        def order(self, files=None):
            return {'json': {'sku': 1}} if files is None else {'files': files}

        @api.http.post(svc.url + '/login')
        def login(self, user, password):
            return {'json': {'user': user, 'password': password}}
    return ShopApi()


class TokenLogin(auth.Provider):
    """Logs in through a framework API class, so the login is in the evidence."""

    def __init__(self, svc, expires_in=3600):
        self.svc, self.expires_in, self.calls = svc, expires_in, []

    def login(self, name, session):
        self.calls.append(name)
        _r = client(self.svc).login(name, PASSWORDS.get(name, '?'))
        if status_code(_r) != 200:
            raise RuntimeError('login returned {}'.format(status_code(_r)))
        return auth.Bearer(json_body(_r)[0]['token'], expires_in=self.expires_in)


def who(response):
    return json_body(response)[0].get('user') if status_code(response) == 200 else status_code(response)


class TestIdentities:
    def test_two_identities_in_one_case_do_not_mix(self, svc):
        auth.provider(TokenLogin(svc))
        _api = client(svc)
        with auth.identity('buyer'):
            _buyer = who(_api.me())
            with auth.identity('seller'):
                _seller = who(_api.me())
            _buyer_again = who(_api.me())
        assert (_buyer, _seller, _buyer_again) == ('buyer', 'seller', 'buyer')
        assert who(_api.me()) == 401            # the default session carries nothing

    def test_each_identity_logs_in_once(self, svc):
        _p = auth.provider(TokenLogin(svc))
        _api = client(svc)
        with auth.identity('buyer'):
            for _ in range(3):
                assert who(_api.me()) == 'buyer'
        # once per identity: logging in on every request would, on a single-
        # session system, kick out every other session of the same user
        assert _p.calls == ['buyer'] and svc.logins == {'buyer': 1}

    def test_anonymous_sends_no_credential(self, svc):
        auth.provider(TokenLogin(svc))
        with auth.identity('anonymous'):
            assert who(client(svc).me()) == 401

    def test_a_plain_function_is_a_provider(self, svc):
        def _login(name, session):
            _r = session.post(svc.url + '/login', json={'user': name, 'password': PASSWORDS[name]})
            return auth.Bearer(_r.json()['token'])
        auth.provider(_login)
        with auth.identity('seller'):
            assert who(client(svc).me()) == 'seller'

    def test_api_key(self, svc):
        auth.provider(lambda name, session: auth.ApiKey('key-1'))
        with auth.identity('robot'):
            assert who(client(svc).me()) == 'robot'

    def test_a_cookie_login_needs_no_credential_returned(self, svc):
        def _login(name, session):
            session.post(svc.url + '/cookie-login', json={'user': name, 'password': PASSWORDS[name]})
        auth.provider(_login)
        with auth.identity('buyer'):
            assert who(client(svc).me()) == 'buyer'
            # a thread that is not a copy of this one gets the cookies too
            _seen = []
            _t = threading.Thread(target=lambda: (auth.adopt('buyer'), _seen.append(who(client(svc).me()))))
            _t.start()
            _t.join()
        assert _seen == ['buyer']


class TestRefresh:
    def test_a_token_close_to_expiry_is_renewed_before_use(self, svc):
        _p = auth.provider(TokenLogin(svc, expires_in=0.05))
        _api = client(svc)
        with auth.identity('buyer'):
            assert who(_api.me()) == 'buyer'
            time.sleep(0.06)
            assert who(_api.me()) == 'buyer'
        assert _p.calls == ['buyer', 'buyer']

    def test_rejected_as_not_logged_in_logs_in_again_and_replays_once(self, svc):
        auth.provider(TokenLogin(svc))
        _api = client(svc)
        recorder.begin('case')
        try:
            with auth.identity('buyer'):
                assert who(_api.me()) == 'buyer'
                svc.expire('buyer')                 # the server forgets the token
                assert who(_api.me()) == 'buyer'
        finally:
            _evidence = recorder.end('case')
        _calls = [(_e['url'].rsplit('/', 1)[-1], _e['status'], _e['role'], _e['identity'])
                  for _e in _evidence.exchanges]
        assert _calls == [('login', 200, 'login', 'buyer'), ('me', 200, '', 'buyer'),
                          ('me', 401, '', 'buyer'), ('login', 200, 'login', 'buyer'),
                          ('me', 200, 'replayed', 'buyer')]

    def test_a_token_the_case_wrote_itself_is_never_fixed(self, svc):
        _p = auth.provider(TokenLogin(svc))
        with auth.identity('buyer'):
            _r = client(svc).me(headers={'Authorization': 'Bearer expired-on-purpose'})
        assert status_code(_r) == 401
        assert _p.calls == []                       # not even logged in for it

    def test_a_business_code_can_mean_not_logged_in(self, svc):
        class CodeLogin(TokenLogin):
            def unauthenticated(self, response):
                return json.loads(response.text).get('code') == 401
        _p = auth.provider(CodeLogin(svc))
        with auth.identity('buyer'):
            client(svc).me_code()
            svc.expire('buyer')
            assert json_body(client(svc).me_code())[0]['user'] == 'buyer'
        assert len(_p.calls) == 2

    def test_a_file_upload_is_not_replayed(self, svc):
        auth.provider(TokenLogin(svc))
        with auth.identity('buyer'):
            client(svc).me()
            svc.expire('buyer')
            _before = svc.posts
            _r = client(svc).order(files={'f': ('a.txt', b'x')})
        assert status_code(_r) == 401 and svc.posts - _before == 1

    def test_replay_can_be_turned_off(self, svc):
        class NoReplay(TokenLogin):
            refresh_on_401 = False
        auth.provider(NoReplay(svc))
        with auth.identity('buyer'):
            client(svc).me()
            svc.expire('buyer')
            assert status_code(client(svc).me()) == 401

    def test_expiry_rule(self):
        _c = auth.Credential(issued_at=0, expires_at=1000)
        assert not _c.due(now=900) and _c.due(now=941)          # 60 s before
        _short = auth.Credential(issued_at=0, expires_at=30)
        assert not _short.due(now=23) and _short.due(now=24.5)  # a fifth of 30 s
        assert not auth.Credential().due()

    def test_a_jwt_says_when_it_expires(self):
        import base64
        _payload = base64.urlsafe_b64encode(json.dumps({'exp': 2000000000}).encode()).decode().rstrip('=')
        assert auth.Bearer('eyJhbGciOiJub25lIn0.{}.sig'.format(_payload)).expires_at == 2000000000


class TestConcurrency:
    def test_concurrent_operations_go_out_as_the_callers_identity(self, svc):
        _p = auth.provider(TokenLogin(svc))
        _api = client(svc)
        with auth.identity('buyer'):
            _results = concurrently(lambda: who(_api.me()), n=4)
        assert _results.values == ['buyer'] * 4
        assert _p.calls == ['buyer']

    def test_threads_can_each_take_an_identity(self, svc):
        auth.provider(TokenLogin(svc))
        _api = client(svc)

        def _as(name):
            def _go():
                with auth.identity(name):
                    return who(_api.me())
            return _go
        assert concurrently([_as('buyer'), _as('seller')]).values == ['buyer', 'seller']


class TestFailuresAndLifetime:
    def test_a_wrong_password_is_a_data_problem_not_a_defect(self, svc):
        auth.provider(TokenLogin(svc))
        with auth.identity('nobody'), pytest.raises(auth.LoginFailed) as _exc:
            client(svc).me()
        assert classify('t::a', 'failed', str(_exc.value)).category == Category.DATA

    def test_an_unreachable_login_is_the_environment(self):
        def _login(name, session):
            from ipandora.core.protocol.http.transport import translate_error
            import requests
            raise translate_error(requests.ConnectionError('refused'), url='http://x/login',
                                  method='post', elapsed=0.0)
        auth.provider(_login)
        with auth.identity('buyer'), pytest.raises(auth.LoginFailed) as _exc:
            auth.credential()
        assert classify('t::a', 'failed', str(_exc.value)).category == Category.ENVIRONMENT

    def test_reset_forgets_provider_credentials_and_sessions(self, svc):
        auth.provider(TokenLogin(svc))
        with auth.identity('buyer'):
            client(svc).me()
        auth.reset()
        assert auth.provider() is None
        assert not any(SessionManager.SEP in _k for _k in SessionManager._session_map)

    def test_a_run_forgets_its_provider(self, svc, tmp_path, monkeypatch):
        monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'no-conf'))
        monkeypatch.setenv(plugin.LOCK_DIR_VAR, str(tmp_path / 'locks'))
        monkeypatch.setenv('SHOP_URL', svc.url)
        (tmp_path / 'conftest.py').write_text(textwrap.dedent('''
            import os
            from ipandora.core import auth

            from ipandora.core import api
            from ipandora.core.assertion.http import json_body

            class LoginApi:
                @api.http.post(os.environ['SHOP_URL'] + '/login')
                def login(self, user):
                    return {'json': {'user': user, 'password': 'b-pass'}}  # pragma: allowlist secret

            def _login(name, session):
                return auth.Bearer(json_body(LoginApi().login(name))[0]['token'])

            auth.provider(_login)
        '''), encoding='utf-8')
        (tmp_path / 'test_shop.py').write_text(textwrap.dedent('''
            import json, os
            from ipandora.core import api, auth
            from ipandora.core.assertion import assert_all, field, status_ok

            class Shop:
                @api.http.get(os.environ['SHOP_URL'] + '/me')
                def me(self):
                    return {}

            def test_buyer():
                with auth.identity('buyer'):
                    r = Shop().me()
                assert_all(status_ok(r), field(r, 'user') == 'buyer')
        '''), encoding='utf-8')
        _result = run(str(tmp_path), persist=False, quiet=True, baseline='')
        assert _result.ok, _result.cases[0].message if _result.cases else _result.collect_error
        _exchanges = _result.cases[0].exchanges
        assert [_e['role'] for _e in _exchanges] == ['login', '']
        assert all(_e['identity'] == 'buyer' for _e in _exchanges)
        assert auth.provider() is None
