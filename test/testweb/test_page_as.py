# -*- coding: utf-8 -*-
"""
@File  : test_page_as.py
@Time  : 2026-11-06

Web login state: page_as(identity) (docs/design/decisions/17 §2.5, plan A3).

Acceptance: both ways of getting a browser logged in work in a real browser --
the API login moved into the browser, and a page login saved and reused --; one
case holds two roles; an application keeping its token in sessionStorage is
served by writing it back before the page opens.
"""
import json
import os
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest

from ipandora.core import auth, web
from ipandora.core.runner import run
from ipandora.core.schedule.runtime import Runtime
from ipandora.core.triage import Category, triage

pytest.importorskip('playwright', reason='web tests need the `web` extra')
pytest.importorskip('pytest_playwright', reason='web tests need the `web` extra')

from test.testweb.test_web import _browser_or_skip  # noqa: E402


@pytest.fixture(scope='module', autouse=True)
def browser_available():
    _browser_or_skip()


class App:
    def __init__(self):
        self.sessions = {}          # sid -> user
        self.page_logins = 0
        self.lock = threading.Lock()

    def start(self, user):
        with self.lock:
            _sid = 'sid-{}-{}'.format(user, len(self.sessions) + 1)
            self.sessions[_sid] = user
            return _sid


def _handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body='', ctype='text/html; charset=utf-8', headers=None):
            _data = body.encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            for _k, _v in (headers or {}).items():
                self.send_header(_k, _v)
            self.send_header('Content-Length', str(len(_data)))
            self.end_headers()
            self.wfile.write(_data)

        def _user(self):
            for _part in (self.headers.get('Cookie') or '').split(';'):
                _k, _, _v = _part.strip().partition('=')
                if _k == 'sid':
                    return app.sessions.get(_v)
            return None

        def do_POST(self):
            _raw = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode()
            if self.path == '/api/login':
                _body = json.loads(_raw or '{}')
                if _body.get('password') != 'pw':
                    return self._send(403, '{}', 'application/json')
                _sid = app.start(_body['user'])
                return self._send(200, json.dumps({'token': 'tok-' + _body['user']}), 'application/json',
                                  {'Set-Cookie': 'sid={}; Path=/; HttpOnly'.format(_sid)})
            if self.path == '/login':
                _form = {_k: _v[0] for _k, _v in parse_qs(_raw).items()}
                if _form.get('password') != 'pw':
                    return self._send(200, '<p id="error">密码错误</p>')
                app.page_logins += 1
                _sid = app.start(_form['user'])
                return self._send(302, '', headers={'Location': '/app',
                                                    'Set-Cookie': 'sid={}; Path=/'.format(_sid)})
            if self.path == '/expire-all':
                app.sessions.clear()
                return self._send(200, 'ok')
            return self._send(404)

        def do_GET(self):
            if self.path == '/login':
                return self._send(200, '<form method="post" action="/login">'
                                       '<label>用户 <input name="user"></label>'
                                       '<label>密码 <input name="password" type="password"></label>'
                                       '<button type="submit">登录</button></form>')
            if self.path == '/app':
                _user = self._user()
                if not _user:
                    return self._send(302, '', headers={'Location': '/login'})
                return self._send(200, '<h1 id="who">{}</h1>'.format(_user))
            if self.path == '/spa':
                return self._send(200, '<p id="token"></p><script>document.getElementById("token")'
                                       '.textContent = sessionStorage.getItem("token") || "none"</script>')
            return self._send(404)

    return Handler


@pytest.fixture
def app():
    _app = App()
    _server = ThreadingHTTPServer(('127.0.0.1', 0), _handler(_app))
    _server.daemon_threads = True
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    _app.url = 'http://127.0.0.1:{}'.format(_server.server_address[1])
    yield _app
    _server.shutdown()
    _server.server_close()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, app):
    monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'no-conf'))
    monkeypatch.setenv('IPANDORA_RUNS_DIR', str(tmp_path / 'home' / 'runs'))
    monkeypatch.setenv(web.MEMORY_VAR, str(tmp_path / 'home' / 'locators.json'))
    monkeypatch.setenv('APP', app.url)
    auth.reset()
    yield
    auth.reset()


def suite(tmp_path, conftest, body):
    _dir = tmp_path / 'suite'
    _dir.mkdir(exist_ok=True)
    (_dir / 'conftest.py').write_text(textwrap.dedent(conftest), encoding='utf-8')
    (_dir / 'test_login_state.py').write_text(textwrap.dedent(body), encoding='utf-8')
    return str(_dir)


def go(target):
    return run(target, persist=False, quiet=True, baseline='')


API_LOGIN = '''
    import os
    from ipandora.core import auth

    class ApiLogin(auth.Provider):
        login_url = r'/login$'

        def login(self, name, session):
            r = session.post(os.environ['APP'] + '/api/login', json={'user': name, 'password': 'pw'})
            r.raise_for_status()          # the session now holds the cookie: return nothing

    auth.provider(ApiLogin())
'''

PAGE_LOGIN = '''
    import os
    from ipandora.core import auth

    class PageLogin(auth.Provider):
        login_url = r'/login$'

        def login(self, name, session):
            raise AssertionError('the page login is used, not this')

        def web_login(self, name, page):
            page.goto(os.environ['APP'] + '/login')
            page.get_by_label('用户').fill(name)
            page.get_by_label('密码').fill(os.environ.get('PW', 'pw'))
            page.get_by_role('button', name='登录').click()
            page.wait_for_url('**/app')

    auth.provider(PageLogin())
'''

TWO_ROLES = '''
    import os
    from playwright.sync_api import expect

    APP = os.environ['APP']

    def test_buyer_and_seller_side_by_side(page_as):
        buyer, seller = page_as('buyer', APP + '/app'), page_as('seller', APP + '/app')
        expect(buyer.locator('#who')).to_have_text('buyer')
        expect(seller.locator('#who')).to_have_text('seller')
        assert buyer.context is not seller.context
'''


class TestApiLogin:
    def test_the_api_login_is_moved_into_the_browser(self, tmp_path, app):
        _result = go(suite(tmp_path, API_LOGIN, TWO_ROLES))
        assert _result.ok, [_c.message for _c in _result.cases]
        assert app.page_logins == 0                   # no login page was ever opened

    def test_a_bearer_token_alone_is_refused_with_a_way_out(self, tmp_path):
        _result = go(suite(tmp_path, '''
            from ipandora.core import auth
            auth.provider(lambda name, session: auth.Bearer('t'))
        ''', '''
            def test_x(page_as):
                page_as('buyer')
        '''))
        assert not _result.ok and 'web_headers' in _result.cases[0].message


class TestPageLogin:
    def test_a_page_login_is_saved_and_reused(self, tmp_path, app):
        _result = go(suite(tmp_path, PAGE_LOGIN, TWO_ROLES + '''

    def test_buyer_again(page_as):
        expect(page_as('buyer', APP + '/app').locator('#who')).to_have_text('buyer')
'''))
        assert _result.ok, [_c.message for _c in _result.cases]
        assert app.page_logins == 2                   # buyer and seller, once each

    def test_sent_back_to_the_login_page_logs_in_again_once(self, tmp_path, app):
        _result = go(suite(tmp_path, PAGE_LOGIN, '''
            import os, requests
            from playwright.sync_api import expect

            APP = os.environ['APP']

            def test_first(page_as):
                expect(page_as('buyer', APP + '/app').locator('#who')).to_have_text('buyer')

            def test_after_the_server_forgot_every_session(page_as):
                requests.post(APP + '/expire-all', proxies={'http': None})
                expect(page_as('buyer', APP + '/app').locator('#who')).to_have_text('buyer')
        '''))
        assert _result.ok, [_c.message for _c in _result.cases]
        assert app.page_logins == 2

    def test_a_login_that_never_works_is_test_data_not_a_defect(self, tmp_path, monkeypatch):
        monkeypatch.setenv('PW', 'wrong')
        _result = go(suite(tmp_path, PAGE_LOGIN, '''
            import os

            def test_x(page_as):
                page_as('buyer', os.environ['APP'] + '/app')
        '''))
        assert not _result.ok
        assert triage(_result).findings[0].category == Category.DATA


class TestSessionStorage:
    def test_a_token_in_session_storage_is_written_back(self, tmp_path):
        _result = go(suite(tmp_path, API_LOGIN + '''

    class SpaLogin(ApiLogin):
        def web_prepare(self, name, credential, context):
            context.add_init_script("sessionStorage.setItem('token', 'tok-%s')" % name)

    auth.provider(SpaLogin())
''', '''
            import os
            from playwright.sync_api import expect

            def test_spa(page_as):
                page = page_as('buyer', os.environ['APP'] + '/spa')
                expect(page.locator('#token')).to_have_text('tok-buyer')
        '''))
        assert _result.ok, [_c.message for _c in _result.cases]


class TestPieces:
    def test_dict_cookies_take_the_base_url_host(self):
        assert web.browser_cookies({'sid': 'x'}, 'https://shop.example/app') == [
            {'name': 'sid', 'value': 'x', 'domain': 'shop.example', 'path': '/'}]
        with pytest.raises(ValueError, match='web.base_url'):
            web.browser_cookies({'sid': 'x'})

    def test_trace_can_be_turned_off(self, monkeypatch):
        monkeypatch.setattr(Runtime.Web, 'trace', 'off')
        _args = web.pytest_args([], '')
        assert _args[_args.index('--tracing') + 1] == 'off'

    def test_yaml_off_reads_as_off(self, monkeypatch):
        monkeypatch.setattr(Runtime, 'settings', dict(Runtime.settings, web={'trace': False}))
        Runtime.reset('Web')
        try:
            assert Runtime.Web.trace == 'off'
        finally:
            Runtime.reset('Web')
