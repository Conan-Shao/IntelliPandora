# -*- coding: utf-8 -*-
"""
@File  : test_faults.py
@Time  : 2026-11-06

Fault injection through Toxiproxy (docs/design/decisions/18, D4a), against a
stand-in Toxiproxy that really forwards TCP: the fault takes effect, is undone
whatever happens, is written into the evidence, and triage tells an injected
fault from a real outage.

With TOXIPROXY_URL set, the same API tests also run against a real Toxiproxy.
"""
import os
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from ipandora.core import faults
from ipandora.core.evidence import recorder

from .fake_toxiproxy import FakeToxiproxy

NO_PROXY = {'http': None, 'https': None}


class _Ok(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')


@pytest.fixture
def upstream():
    _s = ThreadingHTTPServer(('127.0.0.1', 0), _Ok)
    _s.daemon_threads = True
    threading.Thread(target=_s.serve_forever, daemon=True).start()
    yield '127.0.0.1:{}'.format(_s.server_address[1])
    _s.shutdown()
    _s.server_close()


@pytest.fixture
def toxi():
    _t = FakeToxiproxy()
    yield _t
    _t.close()


@pytest.fixture
def allowed(monkeypatch, toxi, tmp_path):
    monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True, 'toxiproxy': toxi.url})
    monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
    return toxi


@pytest.fixture
def db(allowed, upstream):
    """A proxy `db` in front of the upstream; returns its URL."""
    _p = faults.proxy('db', '127.0.0.1:0', upstream)
    return 'http://{}/'.format(_p['listen'])


def get(url, timeout=3):
    return requests.get(url, timeout=timeout, proxies=NO_PROXY)


class TestSafety:

    def test_off_unless_allowed(self, monkeypatch):
        monkeypatch.setattr(faults, '_settings', lambda: {})
        assert not faults.allowed()
        with pytest.raises(faults.FaultsNotAllowed, match='allowed: true'):
            with faults.injected(faults.latency('db', 100)):
                pass

    def test_never_in_production(self, monkeypatch):
        monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True})
        monkeypatch.setattr(faults, '_env_name', lambda: 'prod')
        assert not faults.allowed()
        with pytest.raises(faults.FaultsNotAllowed, match='never allowed'):
            with faults.injected(faults.latency('db', 100)):
                pass

    def test_toxiproxy_not_running_is_a_message(self, monkeypatch, tmp_path):
        monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True, 'toxiproxy': 'http://127.0.0.1:9'})
        monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
        with pytest.raises(faults.ToxiproxyError, match='not reachable'):
            with faults.injected(faults.latency('db', 100)):
                pass


class TestFaults:

    def test_latency_takes_effect_and_is_undone(self, db, allowed):
        _start = time.monotonic()
        assert get(db).text == 'ok'
        _clean = time.monotonic() - _start
        with faults.injected(faults.latency('db', 400)):
            _start = time.monotonic()
            assert get(db).text == 'ok'
            assert time.monotonic() - _start >= 0.4
        assert allowed.proxies['db'].toxics == []
        _start = time.monotonic()
        get(db)
        assert time.monotonic() - _start < max(0.3, _clean * 5)

    def test_reset_peer(self, db):
        with faults.injected(faults.reset_peer('db')):
            with pytest.raises(requests.ConnectionError):
                get(db)
        assert get(db).text == 'ok'

    def test_down_and_back(self, db, allowed):
        with faults.injected(faults.down('db')):
            assert allowed.proxies['db'].enabled is False
            with pytest.raises(requests.ConnectionError):
                get(db)
        assert allowed.proxies['db'].enabled is True and allowed.proxies['db'].toxics == []
        assert get(db).text == 'ok'

    def test_undone_when_the_case_raises(self, db, allowed):
        with pytest.raises(ZeroDivisionError):
            with faults.injected(faults.latency('db', 50), faults.timeout('db', 100)):
                assert len(allowed.proxies['db'].toxics) == 2
                1 / 0
        assert allowed.proxies['db'].toxics == []

    def test_names_carry_the_prefix_and_describe_themselves(self, db, allowed):
        with faults.injected(faults.latency('db', 200, jitter=50, toxicity=0.5)) as _records:
            assert allowed.proxies['db'].toxics[0]['name'].startswith(faults.PREFIX)
        assert _records[0]['description'] == 'latency(db, jitter=50, latency=200, toxicity=0.5)'
        assert _records[0]['ended'] >= _records[0]['started']

    def test_the_evidence_holds_what_was_injected_and_when(self, db):
        recorder.begin('t::fault')
        try:
            with faults.injected(faults.latency('db', 10)):
                assert [_f['kind'] for _f in faults.active()] == ['latency']
            assert faults.active() == []
        finally:
            _evidence = recorder.end('t::fault')
        assert len(_evidence.faults) == 1
        _f = _evidence.faults[0]
        assert (_f['kind'], _f['proxy']) == ('latency', 'db') and _f['ended'] >= _f['started']

    def test_one_injector_per_proxy(self, db, monkeypatch):
        from ipandora.core.runner.plugin import ResourceLock, lock_path
        monkeypatch.setenv('IPANDORA_RESOURCE_TIMEOUT', '0.5')
        _held = ResourceLock(lock_path('fault:db'))
        assert _held.acquire(0)
        try:
            with pytest.raises(TimeoutError, match='gave up waiting for resource fault:db'):
                with faults.injected(faults.latency('db', 10)):
                    pass
        finally:
            _held.release()

    def test_clean_removes_only_ours_and_enables_what_we_disabled(self, db, allowed):
        _client = faults.Toxiproxy()
        _client.add_toxic(faults.Fault('db', 'latency', {'latency': 0}, name='ipandora-999-1'))
        _client.add_toxic(faults.Fault('db', 'latency', {'latency': 0}, name='someone-elses'))
        _client.enable('db', False)
        assert faults.clean() == ['db/ipandora-999-1']
        assert [_t['name'] for _t in allowed.proxies['db'].toxics] == ['someone-elses']
        assert allowed.proxies['db'].enabled is True

    def test_proxy_is_idempotent(self, allowed, upstream):
        _a = faults.proxy('x', '127.0.0.1:0', upstream)
        assert faults.proxy('x', _a['listen'], upstream)['listen'] == _a['listen']
        assert len(allowed.proxies) == 1


class TestTriage:
    """Acceptance: an injected fault is told apart from a real outage."""

    @pytest.mark.parametrize('workers', [None, 2], ids=['serial', 'parallel'])
    def test_a_run(self, toxi, upstream, tmp_path, monkeypatch, workers):
        if workers:
            pytest.importorskip('xdist', reason='parallel runs need the `parallel` extra')
        from ipandora.core.runner import run
        from ipandora.core.triage import triage
        _proxy = faults.Toxiproxy(toxi.url).proxy('db', '127.0.0.1:0', upstream)
        from ipandora.core.schedule import config
        from ipandora.core.schedule.runtime import Runtime
        # settings are read once per process; a project's conf/config.yaml is the usual place
        monkeypatch.setattr(Runtime, 'settings', config.deep_merge(
            Runtime.settings, {'faults': {'allowed': True, 'toxiproxy': toxi.url}}))
        monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
        monkeypatch.setenv('DB_URL', 'http://{}/'.format(_proxy['listen']))
        _suite = tmp_path / 'suite'
        _suite.mkdir()
        (_suite / 'test_resilience.py').write_text(textwrap.dedent('''
            import os
            from ipandora.core import api, faults
            from ipandora.core.assertion import assert_all, status_ok

            class Db:
                @api.http.get(os.environ['DB_URL'])
                def read(self):
                    return {'timeout': 3}

            class Gone:
                @api.http.get('http://127.0.0.1:9/')
                def read(self):
                    return {'timeout': 3}

            def test_survives_latency():
                with faults.injected(faults.latency('db', 100)):
                    assert_all(status_ok(Db().read()))

            def test_no_retry_under_reset():
                with faults.injected(faults.reset_peer('db')):
                    assert_all(status_ok(Db().read()))

            def test_real_outage():
                assert_all(status_ok(Gone().read()))

            def test_outage_after_the_fault():
                with faults.injected(faults.latency('db', 10)):
                    assert_all(status_ok(Db().read()))
                assert_all(status_ok(Gone().read()))
        '''), encoding='utf-8')
        if workers:
            # the workers read their settings from conf/, not from this process
            _conf = tmp_path / 'conf'
            _conf.mkdir()
            (_conf / 'config.yaml').write_text('faults:\n  allowed: true\n  toxiproxy: {}\n'.format(toxi.url),
                                               encoding='utf-8')
            monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(_conf))
        _result = run(str(_suite), persist=False, quiet=True, baseline='', workers=workers)
        _by = {_c.nodeid.split('::')[-1]: _c for _c in _result.cases}
        assert _by['test_survives_latency'].outcome == 'passed', _by['test_survives_latency'].message
        assert [_f['kind'] for _f in _by['test_survives_latency'].faults] == ['latency']
        _triage = {_f.nodeid.split('::')[-1]: _f for _f in triage(_result).findings}
        assert _triage['test_no_retry_under_reset'].category == 'injected'
        assert 'reset_peer(db' in _triage['test_no_retry_under_reset'].reason
        assert _triage['test_real_outage'].category == 'environment'
        assert _triage['test_outage_after_the_fault'].category == 'environment'
        assert toxi.proxies['db'].toxics == []              # nothing left behind


@pytest.mark.skipif(not os.environ.get('TOXIPROXY_URL'), reason='set TOXIPROXY_URL to run against a real Toxiproxy')
def test_against_a_real_toxiproxy(upstream, monkeypatch, tmp_path):
    monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True})
    monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
    _p = faults.proxy('ipandora-selftest', '127.0.0.1:26379', upstream)
    try:
        with faults.injected(faults.reset_peer('ipandora-selftest')):
            with pytest.raises(requests.ConnectionError):
                get('http://{}/'.format(_p['listen']))
        assert get('http://{}/'.format(_p['listen'])).text == 'ok'
    finally:
        faults.Toxiproxy().delete_proxy('ipandora-selftest')


class TestCr7:
    """Found in code review CR7 (docs/design/reviews/07-CR7.md)."""

    def test_a_real_outage_after_the_fault_is_the_environment(self):
        from ipandora.core.triage.rules import classify
        _faults = [{'kind': 'latency', 'description': 'latency(db, latency=10)', 'started': 1.0, 'ended': 2.0}]
        _later = 'ipandora.utils.error.HttpConnectionError: GET http://127.0.0.1:9/ could not connect'
        assert classify('t', 'failed', _later, faults=_faults).category == 'environment'
        _during = _later + ' ({}: latency(db, latency=10))'.format(faults.INJECTED_MARKER)
        _f = classify('t', 'failed', _during, faults=_faults)
        assert _f.category == 'injected' and 'latency(db, latency=10)' in _f.reason

    def test_a_transport_error_says_when_a_fault_is_in_effect_in_any_thread(self, db):
        from ipandora.core.concurrency import concurrently
        from ipandora.core.protocol.http.transport import translate_error
        _exc = requests.exceptions.ConnectionError('reset')
        assert faults.INJECTED_MARKER not in str(translate_error(_exc, 'http://x/', 'GET'))
        with faults.injected(faults.reset_peer('db')):
            _results = concurrently(lambda: str(translate_error(_exc, 'http://x/', 'GET')), n=2)
        assert all(faults.INJECTED_MARKER in _r.value and 'reset_peer(db' in _r.value for _r in _results)
        assert faults.during() == ''

    def test_nested_blocks_on_one_proxy_do_not_wait_for_each_other(self, db, allowed, monkeypatch):
        monkeypatch.setenv('IPANDORA_RESOURCE_TIMEOUT', '2')
        _start = time.monotonic()
        with faults.injected(faults.latency('db', 10)):
            with faults.injected(faults.reset_peer('db')):
                assert len(allowed.proxies['db'].toxics) == 2
            assert len(allowed.proxies['db'].toxics) == 1
        assert time.monotonic() - _start < 1.5 and allowed.proxies['db'].toxics == []
        from ipandora.core.runner.plugin import ResourceLock, lock_path
        _lock = ResourceLock(lock_path('fault:db'))
        assert _lock.acquire(0)                             # released after the outer block
        _lock.release()

    def test_a_run_inside_a_case_leaves_the_case_faults_alone(self, db, allowed, tmp_path, monkeypatch):
        from ipandora.core.runner import run
        from ipandora.core.schedule import config
        from ipandora.core.schedule.runtime import Runtime
        monkeypatch.setattr(Runtime, 'settings', config.deep_merge(
            Runtime.settings, {'faults': {'allowed': True, 'toxiproxy': allowed.url}}))
        (tmp_path / 's').mkdir()
        (tmp_path / 's' / 'test_x.py').write_text('def test_x():\n    assert 1\n', encoding='utf-8')
        with faults.injected(faults.latency('db', 10)):
            run(str(tmp_path / 's'), persist=False, quiet=True, baseline='')
            assert len(allowed.proxies['db'].toxics) == 1


class TestR1:
    """Gaps mutation testing found (R1): each test fails on a mutant that survived before."""

    @pytest.mark.parametrize('how', ['option', 'variable'])
    @pytest.mark.parametrize('name', ['prod', 'Production'])
    def test_production_is_recognised_however_it_is_named(self, monkeypatch, how, name):
        # the old test replaced _env_name itself: the real detection was never run
        from ipandora.core.schedule.runtime import Runtime
        monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True})
        monkeypatch.setattr(Runtime.Option, 'env', name if how == 'option' else '', raising=False)
        monkeypatch.setenv('IPANDORA_ENV', name if how == 'variable' else '')
        assert faults._env_name() == name
        assert not faults.allowed()
        with pytest.raises(faults.FaultsNotAllowed, match="never allowed in the '{}' environment".format(name)):
            with faults.injected(faults.latency('db', 1)):
                pass

    def test_the_run_option_wins_over_the_variable(self, monkeypatch):
        from ipandora.core.schedule.runtime import Runtime
        monkeypatch.setattr(Runtime.Option, 'env', 'ci', raising=False)
        monkeypatch.setenv('IPANDORA_ENV', 'prod')
        assert faults._env_name() == 'ci'
        monkeypatch.setattr(Runtime.Option, 'env', '', raising=False)
        monkeypatch.delenv('IPANDORA_ENV')
        assert faults._env_name() == ''

    def test_allowed_reads_the_config_and_takes_only_true(self, monkeypatch):
        from ipandora.core.schedule import config
        from ipandora.core.schedule.runtime import Runtime
        monkeypatch.setattr(Runtime.Option, 'env', 'ci', raising=False)
        for _value, _expected in ((True, True), ('yes', False), (1, False), (None, False)):
            monkeypatch.setattr(Runtime, 'settings', config.deep_merge(Runtime.settings, {'faults': {'allowed': _value}}))
            assert faults.allowed() is _expected, _value
        with pytest.raises(faults.FaultsNotAllowed, match=r"off in this environment \(ci\).*local and CI environments only"):
            faults._require_allowed()

    def test_constructors_say_what_toxiproxy_needs(self):
        assert (faults.latency('db', 10).attributes, faults.latency('db', 10).stream) == (
            {'latency': 10, 'jitter': 0}, 'downstream')
        assert faults.timeout('db').attributes == {'timeout': 0} and faults.timeout('db', 5).attributes == {'timeout': 5}
        _r = faults.reset_peer('db', after_ms=20, stream='upstream', toxicity=0.5)
        assert (_r.kind, _r.attributes, _r.stream, _r.toxicity) == ('reset_peer', {'timeout': 20}, 'upstream', 0.5)
        assert faults.reset_peer('db').attributes == {'timeout': 0} and faults.reset_peer('db').toxicity == 1.0
        assert faults.latency('db', 10, jitter=3, stream='upstream', toxicity=0.25).describe() == \
            'latency(db, jitter=3, latency=10, upstream, toxicity=0.25)'
        assert faults.down('db').describe() == 'down(db)'

    def test_down_leaves_a_marker_toxiproxy_accepts(self, db, allowed):
        with faults.injected(faults.down('db')) as _records:
            _marker = allowed.proxies['db'].toxics[0]
            assert (_marker['type'], _marker['attributes']) == ('latency', {'latency': 0, 'jitter': 0})
            assert _marker['name'] == _records[0]['name'] and _marker['name'].startswith(faults.PREFIX)
            assert not allowed.proxies['db'].enabled
        _r = _records[0]
        assert set(_r) >= {'kind', 'proxy', 'stream', 'toxicity', 'attributes', 'name', 'description', 'started',
                           'ended', 'via'}
        assert (_r['stream'], _r['toxicity'], _r['via']) == ('downstream', 1.0, allowed.url)

    def test_the_client_finds_toxiproxy_and_says_what_went_wrong(self, monkeypatch, allowed):
        monkeypatch.setattr(faults, '_settings', lambda: {})
        monkeypatch.delenv('TOXIPROXY_URL', raising=False)
        assert faults.Toxiproxy().url == faults.DEFAULT_URL
        monkeypatch.setenv('TOXIPROXY_URL', 'http://toxi.test:8474/')
        assert faults.Toxiproxy().url == 'http://toxi.test:8474'
        monkeypatch.setattr(faults, '_settings', lambda: {'toxiproxy': allowed.url + '/'})
        assert faults.Toxiproxy().url == allowed.url                    # the config wins over the variable
        assert faults.Toxiproxy('http://explicit.test').url == 'http://explicit.test'
        monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')            # never through a proxy
        _client = faults.Toxiproxy(allowed.url)
        assert _client.version() == 'fake-2.0' and _client.proxies() == {}
        with pytest.raises(faults.ToxiproxyError, match=r'POST /proxies/nope/toxics answered 404: .*proxy not found'):
            _client.add_toxic(faults.Fault('nope', 'latency', name='x'))
        _client.remove_toxic('nope', 'x')                               # 404 on removal: already gone, fine

    def test_proxy_is_updated_only_when_it_points_elsewhere(self, allowed, upstream):
        _client = faults.Toxiproxy(allowed.url)
        _created = _client.proxy('svc', '127.0.0.1:0', upstream)
        allowed.calls.clear()
        _client.proxy('svc', _created['listen'], upstream)
        assert [_c[0] for _c in allowed.calls] == ['GET']                # nothing to change: only looked
        _moved = _client.proxy('svc', _created['listen'], '127.0.0.1:9')
        assert _moved['upstream'] == '127.0.0.1:9' and allowed.calls[-1][:2] == ('POST', '/proxies/svc')

    def test_clean_leaves_proxies_alone_that_we_did_not_disable(self, db, allowed):
        _client = faults.Toxiproxy(allowed.url)
        allowed.proxies['db'].toxics.append({'name': 'someone-else', 'type': 'latency', 'attributes': {}})
        allowed.proxies['db'].enabled = False                             # disabled, but not by us
        assert faults.clean(_client) == []
        assert not allowed.proxies['db'].enabled and len(allowed.proxies['db'].toxics) == 1

    def test_during_names_every_fault_in_effect(self, db, allowed):
        assert faults.during() == ''
        with faults.injected(faults.latency('db', 1), faults.timeout('db', 5)):
            assert faults.during() == ' ({}: latency(db, jitter=0, latency=1), timeout(db, timeout=5))'.format(
                faults.INJECTED_MARKER)

    def test_a_held_proxy_says_who_has_it_and_for_how_long(self, db, monkeypatch, tmp_path):
        from ipandora.core.runner.plugin import ResourceLock, lock_path
        monkeypatch.setenv('IPANDORA_RESOURCE_TIMEOUT', '0.2')
        _other = ResourceLock(lock_path('fault:db'))
        assert _other.acquire(1)
        try:
            with pytest.raises(TimeoutError, match=r'resource fault:db after 0\.2s'):
                with faults.injected(faults.latency('db', 1)):
                    pass
        finally:
            _other.release()
        monkeypatch.setenv('IPANDORA_RESOURCE_TIMEOUT', 'soon')            # unreadable: the default, not a crash
        with faults.injected(faults.latency('db', 1)):
            assert 'db' in faults._HELD
        assert 'db' not in faults._HELD
