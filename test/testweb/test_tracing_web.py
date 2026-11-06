# -*- coding: utf-8 -*-
"""
@File  : test_tracing_web.py
@Time  : 2026-11-06

Browser requests carry the case's trace (docs/guide/tracing.md, D7b): to the
application only, a span each, cookies untouched; the report shows the case's
trace even when it made no API request.
"""
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ipandora.core import tracing
from ipandora.core.runner import run

pytest.importorskip('playwright', reason='web tests need the `web` extra')
pytest.importorskip('pytest_playwright', reason='web tests need the `web` extra')

from test.testweb.test_web import _browser_or_skip  # noqa: E402


@pytest.fixture(scope='module', autouse=True)
def browser_available():
    _browser_or_skip()


def _server(seen, page=''):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append((self.path, self.headers.get('traceparent'), self.headers.get('Cookie')))
            _body, _type, _extra = b'', 'text/plain', {}
            if self.path == '/page':
                _body, _type = page.encode(), 'text/html; charset=utf-8'
                _extra = {'Set-Cookie': 'sid=s1; Path=/'}
            elif self.path == '/pixel.png':
                _type = 'image/png'
            else:
                _body = b'{"ok": true}'
            self.send_response(200)
            self.send_header('Content-Type', _type)
            for _k, _v in _extra.items():
                self.send_header(_k, _v)
            self.send_header('Content-Length', str(len(_body)))
            self.end_headers()
            self.wfile.write(_body)
    _s = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    _s.daemon_threads = True
    threading.Thread(target=_s.serve_forever, daemon=True).start()
    return _s


@pytest.fixture
def servers():
    _app_seen, _other_seen = [], []
    _other = _server(_other_seen)
    _page = ('<img src="http://127.0.0.1:{}/pixel.png"><p id="out"></p><script>'
             'fetch("/api/data").then(r => r.json()).then(j => document.getElementById("out").textContent = "done")'
             '</script>').format(_other.server_address[1])
    _app = _server(_app_seen, _page)
    yield 'http://127.0.0.1:{}'.format(_app.server_address[1]), _app_seen, _other_seen
    for _s in (_app, _other):
        _s.shutdown()
        _s.server_close()


@pytest.mark.parametrize('workers', [None, 2], ids=['serial', 'parallel'])
def test_pages_send_the_case_trace_to_the_application_only(servers, tmp_path, monkeypatch, workers):
    if workers:
        pytest.importorskip('xdist', reason='parallel runs need the `parallel` extra')
    _url, _app_seen, _other_seen = servers
    _conf = tmp_path / 'conf'
    _conf.mkdir()
    (_conf / 'config.yaml').write_text(textwrap.dedent('''
        web:
          base_url: {}
        tracing:
          enabled: true
          link: http://jaeger.test/trace/{{trace_id}}
    '''.format(_url)), encoding='utf-8')
    monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(_conf))
    monkeypatch.setenv('IPANDORA_RUNS_DIR', str(tmp_path / 'runs'))
    from ipandora.core.schedule import config
    from ipandora.core.schedule.runtime import Runtime
    monkeypatch.setattr(Runtime, 'settings', config.deep_merge(Runtime.settings, {
        'web': {'base_url': _url}, 'tracing': {'enabled': True, 'link': 'http://jaeger.test/trace/{trace_id}'}}))
    monkeypatch.setattr(Runtime.Web, '_base_url', _url)       # read once per process, like every setting
    _suite = tmp_path / 'suite'
    _suite.mkdir()
    (_suite / 'test_shop.py').write_text(textwrap.dedent('''
        from playwright.sync_api import expect

        def test_page(page):
            page.goto('/page')
            expect(page.locator('#out')).to_have_text('done')
    '''), encoding='utf-8')
    _result = run(str(_suite), persist=False, quiet=True, baseline='', workers=workers)
    assert _result.ok, [_c.message for _c in _result.cases]

    _sent = {_path: (tracing.parse(_tp), _cookie) for _path, _tp, _cookie in _app_seen}
    assert set(_sent) >= {'/page', '/api/data'}
    _page, _api = _sent['/page'][0], _sent['/api/data'][0]
    assert _page and _api and _page['trace_id'] == _api['trace_id'] and _page['span_id'] != _api['span_id']
    assert _sent['/api/data'][1] == 'sid=s1'                     # the cookie still goes with the request
    assert _other_seen and all(_tp is None for _, _tp, _ in _other_seen)   # nothing for a third party

    _case = _result.cases[0]
    assert _case.trace_id == _page['trace_id'] and not _case.exchanges
    from ipandora.core.report.builder import build_from_run
    from ipandora.core.report.render import to_html
    assert '<a href="http://jaeger.test/trace/{}"'.format(_page['trace_id']) in to_html(build_from_run(_result))
