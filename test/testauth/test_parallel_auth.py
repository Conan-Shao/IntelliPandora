# -*- coding: utf-8 -*-
"""
@File  : test_parallel_auth.py
@Time  : 2026-11-06

Logins under parallel runs (docs/design/decisions/17 §2.3, plan A2).

Acceptance: with 4 workers, a single-session account no longer knocks the
other workers out -- one login for the whole run; with an account pool, each
worker uses one account of its own.
"""
import json
import os
import stat
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ipandora.core import auth
from ipandora.core.runner import plugin, run

pytest.importorskip('xdist', reason='parallel runs need the `parallel` extra')


class Server:
    """One session per user: a new login revokes the user's older token."""

    def __init__(self):
        self.lock = threading.Lock()
        self.tokens = {}
        self.logins = {}
        self.seen = []          # (worker, account) per request

    def login(self, user):
        with self.lock:
            self.logins[user] = self.logins.get(user, 0) + 1
            for _t in [_t for _t, _u in self.tokens.items() if _u == user]:
                del self.tokens[_t]
            _token = 'tok-{}-{}'.format(user, self.logins[user])
            self.tokens[_token] = user
            return _token


def _handler(srv):
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

        def do_POST(self):
            _body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            return self._reply(200, {'token': srv.login(_body['user'])})

        def do_GET(self):
            _auth = self.headers.get('Authorization') or ''
            _user = srv.tokens.get(_auth[7:]) if _auth.startswith('Bearer ') else None
            if not _user:
                return self._reply(401, {})
            with srv.lock:
                srv.seen.append((self.headers.get('X-Worker'), _user))
            return self._reply(200, {'user': _user})

    return Handler


@pytest.fixture
def srv(monkeypatch, tmp_path):
    _srv = Server()
    _server = ThreadingHTTPServer(('127.0.0.1', 0), _handler(_srv))
    _server.daemon_threads = True
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    monkeypatch.setenv('SRV', 'http://127.0.0.1:{}'.format(_server.server_address[1]))
    monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'no-conf'))
    monkeypatch.setenv(plugin.LOCK_DIR_VAR, str(tmp_path / 'locks'))
    yield _srv
    _server.shutdown()
    _server.server_close()


CASES = '''
    import os, time
    from ipandora.core import api, auth
    from ipandora.core.assertion import assert_all, status_ok

    class Me:
        @api.http.get(os.environ['SRV'] + '/me')
        def me(self):
            return {'headers': {'X-Worker': os.environ.get('PYTEST_XDIST_WORKER', 'main')}}

    def _case():
        with auth.identity('buyer'):
            for _ in range(3):
                assert_all(status_ok(Me().me()))
                time.sleep(0.02)

''' + ''.join('''
    def test_{0}():
        _case()
'''.format(_i) for _i in range(12))


def project(tmp_path, provider):
    _dir = tmp_path / 'suite'
    _dir.mkdir()
    (_dir / 'conftest.py').write_text(textwrap.dedent(provider), encoding='utf-8')
    (_dir / 'test_shared.py').write_text(textwrap.dedent(CASES), encoding='utf-8')
    return str(_dir)


SINGLE = '''
    import os, requests
    from ipandora.core import auth

    class Login(auth.Provider):
        single_session = True

        def login(self, name, session):
            r = requests.post(os.environ['SRV'] + '/login', json={'user': auth.account(name)},
                              proxies={'http': None})
            return auth.Bearer(r.json()['token'])

    auth.provider(Login())
'''


class TestSingleSession:
    def test_four_workers_share_one_login(self, srv, tmp_path):
        _result = run(project(tmp_path, SINGLE), workers=4, persist=False, quiet=True, baseline='')
        assert _result.ok, [_c.message for _c in _result.cases if _c.message][:3]
        assert srv.logins == {'buyer': 1}
        assert len({_w for _w, _ in srv.seen}) > 1          # it really ran on several workers

    def test_without_sharing_workers_log_each_other_out(self, srv, tmp_path):
        # the failure the shared login removes: every worker logs in, and
        # each login revokes the others' tokens
        _result = run(project(tmp_path, SINGLE.replace('single_session = True', 'single_session = False')),
                      workers=4, persist=False, quiet=True, baseline='')
        assert srv.logins['buyer'] > 1

    def test_the_shared_directory_is_private_and_removed(self, srv, tmp_path, monkeypatch):
        _seen = {}
        _real = auth._write_shared

        def _spy(name, entry):
            _real(name, entry)
            _dir = os.environ[auth.AUTH_DIR_VAR]
            _seen['dir'] = _dir
            _seen['mode_dir'] = stat.S_IMODE(os.stat(_dir).st_mode)
            _seen['mode_file'] = stat.S_IMODE(os.stat(auth._shared_path(name) + '.json').st_mode)
        monkeypatch.setattr(auth, '_write_shared', _spy)
        assert run(project(tmp_path, SINGLE), persist=False, quiet=True, baseline='').ok
        assert _seen['mode_dir'] == 0o700 and _seen['mode_file'] == 0o600
        assert not os.path.exists(_seen['dir'])


POOL = '''
    import os, requests
    from ipandora.core import auth

    class Login(auth.Provider):
        accounts = {'buyer': ['buyer01', 'buyer02', 'buyer03', 'buyer04']}

        def login(self, name, session):
            r = requests.post(os.environ['SRV'] + '/login', json={'user': auth.account(name)},
                              proxies={'http': None})
            return auth.Bearer(r.json()['token'])

    auth.provider(Login())
'''


class TestAccountPool:
    def test_each_worker_has_an_account_of_its_own(self, srv, tmp_path):
        _result = run(project(tmp_path, POOL), workers=4, persist=False, quiet=True, baseline='')
        assert _result.ok, [_c.message for _c in _result.cases if _c.message][:3]
        _by_worker = {}
        for _worker, _account in srv.seen:
            _by_worker.setdefault(_worker, set()).add(_account)
        assert all(len(_a) == 1 for _a in _by_worker.values()), _by_worker
        _accounts = [next(iter(_a)) for _a in _by_worker.values()]
        assert len(set(_accounts)) == len(_accounts)            # never two workers on one account
        assert all(_n == 1 for _n in srv.logins.values())

    def test_without_a_pool_the_name_is_the_account(self):
        auth.reset()
        auth.provider(lambda name, session: auth.Bearer('t'))
        try:
            assert auth.account('buyer') == 'buyer'
        finally:
            auth.reset()

    def test_a_credential_survives_the_round_trip_through_the_shared_file(self):
        import requests
        _jar = requests.cookies.RequestsCookieJar()
        _jar.set('sid', 'x', domain='a.example', path='/p')
        _c = auth.Credential(headers={'Authorization': 'Bearer t'}, cookies=_jar,
                             params={'k': 'v'}, expires_at=123.0, issued_at=100.0, data={'r': 1})
        _back = auth._load(json.loads(json.dumps(auth._dump(_c))))
        assert _back.headers == _c.headers and _back.params == _c.params
        assert (_back.expires_at, _back.issued_at, _back.data) == (123.0, 100.0, {'r': 1})
        assert [(_x.name, _x.value, _x.domain, _x.path) for _x in _back.cookies] == [('sid', 'x', 'a.example', '/p')]
