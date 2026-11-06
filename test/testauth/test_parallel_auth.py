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
            if self.path == '/expire':
                with srv.lock:
                    srv.tokens.clear()
                return self._reply(200, {})
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
        _out = tmp_path / 'seen.json'
        monkeypatch.setenv('SEEN', str(_out))
        _dir = tmp_path / 'suite'
        _dir.mkdir()
        (_dir / 'conftest.py').write_text(textwrap.dedent(SINGLE), encoding='utf-8')
        (_dir / 'test_seen.py').write_text(textwrap.dedent('''
            import json, os, stat
            from ipandora.core import api, auth

            class Me:
                @api.http.get(os.environ['SRV'] + '/me')
                def me(self):
                    return {}

            def test_seen():
                with auth.identity('buyer'):
                    Me().me()
                _dir = os.environ[auth.AUTH_DIR_VAR]
                _file = auth._shared_path('buyer', _dir) + '.json'
                with open(os.environ['SEEN'], 'w') as _f:
                    json.dump({'dir': _dir, 'mode_dir': stat.S_IMODE(os.stat(_dir).st_mode),
                               'mode_file': stat.S_IMODE(os.stat(_file).st_mode)}, _f)
        '''), encoding='utf-8')
        assert run(str(_dir), workers=2, persist=False, quiet=True, baseline='').ok
        _seen = json.loads(_out.read_text())
        assert _seen['mode_dir'] == 0o700 and _seen['mode_file'] == 0o600
        assert not os.path.exists(_seen['dir'])
        assert auth.AUTH_DIR_VAR not in os.environ

    def test_a_serial_run_keeps_the_login_in_memory(self, srv, tmp_path):
        # one process has nobody to share with: nothing is written
        assert run(project(tmp_path, SINGLE), persist=False, quiet=True, baseline='').ok
        assert srv.logins == {'buyer': 1}


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


class TestCr3:
    """Found in code review CR3 (docs/design/reviews/03-CR3.md)."""

    def test_a_rejected_shared_login_is_renewed_by_one_worker_only(self, srv, tmp_path):
        _dir = tmp_path / 'suite'
        _dir.mkdir()
        (_dir / 'conftest.py').write_text(textwrap.dedent(SINGLE), encoding='utf-8')
        (_dir / 'test_expire.py').write_text(textwrap.dedent(CASES + '''
    import requests

    def test_the_server_forgets_every_token():
        _case()
        requests.post(os.environ['SRV'] + '/expire', json={}, proxies={'http': None})
        _case()
'''), encoding='utf-8')
        _result = run(str(_dir), workers=4, persist=False, quiet=True, baseline='')
        assert _result.ok, [_c.message for _c in _result.cases if _c.message][:3]
        assert srv.logins == {'buyer': 2}

    def test_forget_logs_in_afresh_even_when_shared(self, srv, tmp_path):
        _dir = tmp_path / 'suite'
        _dir.mkdir()
        (_dir / 'conftest.py').write_text(textwrap.dedent(SINGLE), encoding='utf-8')
        (_dir / 'test_forget.py').write_text(textwrap.dedent('''
            import os
            from ipandora.core import api, auth
            from ipandora.core.assertion import assert_all, status_ok

            class Me:
                @api.http.get(os.environ['SRV'] + '/me')
                def me(self):
                    return {}

            def test_forget():
                with auth.identity('buyer'):
                    assert_all(status_ok(Me().me()))
                    auth.forget('buyer')
                    assert_all(status_ok(Me().me()))
        '''), encoding='utf-8')
        assert run(str(_dir), workers=2, persist=False, quiet=True, baseline='').ok
        assert srv.logins == {'buyer': 2}

    def test_a_pool_smaller_than_the_workers_says_so_at_once(self, srv, tmp_path):
        _small = POOL.replace("['buyer01', 'buyer02', 'buyer03', 'buyer04']", "['buyer01']")
        _result = run(project(tmp_path, _small), workers=2, persist=False, quiet=True, baseline='')
        assert not _result.ok
        assert any('add accounts' in (_c.message or '') for _c in _result.cases)

    def test_a_lease_does_not_take_the_resource_of_the_same_name(self, srv):
        from ipandora.core.runner.plugin import ResourceLock, lock_path
        auth.reset()

        class P(auth.Provider):
            accounts = {'buyer': ['vip']}
        auth.provider(P())
        try:
            assert auth.account('buyer') == 'vip'
            _lock = ResourceLock(lock_path('account:vip'))
            assert _lock.acquire(0)             # @pytest.mark.resource('account:vip') still runs
            _lock.release()
        finally:
            auth.reset()

    def test_store_writes_a_shared_login_for_every_worker(self, tmp_path, monkeypatch):
        monkeypatch.setenv(auth.AUTH_DIR_VAR, str(tmp_path))
        monkeypatch.setenv('PYTEST_XDIST_WORKER', 'gw0')
        auth.reset()

        class P(auth.Provider):
            single_session = 'buyer'

            def login(self, name, session):
                raise AssertionError('not called: the stored login is used')
        auth.provider(P())
        try:
            auth.store('buyer', auth.Bearer('from-the-browser'))
            _version, _cred = auth._read_shared('buyer', str(tmp_path))
            assert _cred.headers == {'Authorization': 'Bearer from-the-browser'}
            auth._CACHE.clear()                 # another worker
            assert auth.credential('buyer', session=None)[0] == _version
        finally:
            auth.reset()

    def test_a_single_session_name_is_not_a_set_of_letters(self):
        class P(auth.Provider):
            single_session = 'admin'
        assert P().shares('admin') and not P().shares('ad') and not P().shares('min')

    def test_a_pooled_identity_is_never_shared(self, tmp_path, monkeypatch):
        # sharing would put every worker on the first worker's account
        monkeypatch.setenv(auth.AUTH_DIR_VAR, str(tmp_path))
        monkeypatch.setenv('PYTEST_XDIST_WORKER', 'gw0')
        auth.reset()

        class P(auth.Provider):
            single_session = True
            accounts = {'buyer': ['b1', 'b2']}
        auth.provider(P())
        try:
            assert auth._shared_dir('buyer') == ''
            assert auth._shared_dir('seller') == str(tmp_path)
        finally:
            auth.reset()

    def test_plain_pytest_with_workers_shares_the_login_too(self, srv, tmp_path):
        # the directory is made by the plugin, not only by `ipandora run`
        import subprocess
        import sys
        _env = dict(os.environ)
        _env.pop(auth.AUTH_DIR_VAR, None)
        _proc = subprocess.run(
            [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-p', 'ipandora.core.runner.plugin',
             '-n', '3', project(tmp_path, SINGLE)],
            cwd=str(tmp_path), env=_env, capture_output=True, text=True, timeout=300)
        assert _proc.returncode == 0, _proc.stdout[-2000:] + _proc.stderr[-2000:]
        assert srv.logins == {'buyer': 1}
