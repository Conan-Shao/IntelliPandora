# -*- coding: utf-8 -*-
"""
@File  : test_under_faults.py
@Time  : 2026-11-06

Histories under injected faults (docs/design/decisions/18, D3b). Acceptance:
with replication latency injected, an eventually consistent KV service is
judged not linearizable by the register model; the same read, declared
eventually consistent and judged with eventually(), passes.

The service is a primary that acknowledges a write at once and replicates
it, in order, to a replica through a Toxiproxy proxy `replication`; reads go
to the replica. The proxy is the test double in test/testfaults.
"""
import http.client
import json
import os
import queue
import subprocess
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from ipandora.core import consistency, faults
from ipandora.core.assertion import eventually, that
from ipandora.core.consistency import History
from ipandora.core.evidence import recorder
from ipandora.core.report.builder import _artifact

from ..testfaults.fake_toxiproxy import FakeToxiproxy


def _server(handler):
    _s = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    _s.daemon_threads = True
    threading.Thread(target=_s.serve_forever, daemon=True).start()
    return _s


class Store(BaseHTTPRequestHandler):
    """GET / -> {"value": v}; PUT / {"value": v} stores it. `server.value` is the state."""

    def log_message(self, *args):
        pass

    def _reply(self, body):
        _data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(_data)))
        self.end_headers()
        self.wfile.write(_data)

    def do_GET(self):
        self._reply({'value': self.server.value})

    def do_PUT(self):
        _v = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['value']
        self.server.value = _v
        self.server.written(_v)
        self._reply({'value': _v})


class KV:
    """Writes to the primary, reads from the replica: eventually consistent, by design."""

    def __init__(self, toxi):
        self.replica = _server(Store)
        self.replica.value, self.replica.written = None, lambda v: None
        _proxy = faults.proxy('replication', '127.0.0.1:0', '127.0.0.1:{}'.format(self.replica.server_address[1]))
        _host, _port = _proxy['listen'].rsplit(':', 1)
        self._log = queue.Queue()

        def replicate():                      # one stream, in order, like a replication log
            while True:
                _v = self._log.get()
                if _v is StopIteration:
                    return
                _c = http.client.HTTPConnection(_host, int(_port), timeout=10)
                _c.request('PUT', '/', json.dumps({'value': _v}), {'Content-Type': 'application/json'})
                _c.getresponse().read()
                _c.close()
        threading.Thread(target=replicate, daemon=True).start()
        self.primary = _server(Store)
        self.primary.value, self.primary.written = None, self._log.put
        self._session = requests.Session()
        self._session.trust_env = False

    def put(self, v):
        return self._session.put('http://127.0.0.1:{}/'.format(self.primary.server_address[1]),
                                 json={'value': v}, timeout=10).status_code

    def get(self):
        return self._session.get('http://127.0.0.1:{}/'.format(self.replica.server_address[1]),
                                 timeout=10).json()['value']

    def close(self):
        self._log.put(StopIteration)
        for _s in (self.primary, self.replica):
            _s.shutdown()
            _s.server_close()


@pytest.fixture
def allowed(monkeypatch, tmp_path):
    _toxi = FakeToxiproxy()
    monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True, 'toxiproxy': _toxi.url})
    monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
    yield _toxi
    _toxi.close()


@pytest.fixture
def kv(allowed):
    _kv = KV(allowed)
    yield _kv
    _kv.close()


class TestAcceptance:

    def test_a_replica_read_under_replication_lag_is_not_linearizable(self, kv, needs_checker):
        _h = History()

        def write(v):
            return _h.call('write', v, lambda: kv.put(v), ok=lambda r: r == 200)

        def read():
            return _h.call('read', None, kv.get, result=lambda r: r)

        write(0)                                   # the initial value, in the history: a read of nil judges nothing
        assert eventually(lambda: that(kv.get(), '副本上的值') == 0, within=5).ok
        read()
        # a second of lag: the read below must come before the write reaches
        # the replica, and a loaded CI machine can stall for a few hundred ms
        with faults.injected(faults.latency('replication', 1000, stream='upstream')):
            write(1)
            assert read() == 0                     # the write is acknowledged; the replica has not seen it
            _strict = _h.check('cas-register')
            _eventual = eventually(lambda: that(kv.get(), '副本上的值') == 1, within=5)
        assert not _strict.ok
        assert "can't read 0 from register 1" in _strict.expr
        assert '它完成时故障正在生效：latency(replication, jitter=0, latency=1000, upstream)' in _strict.expr
        assert '其中 2 个操作发生在注入的故障期间' in _strict.expr
        assert _eventual.ok                        # declared eventually consistent: it converges

    def test_without_the_lag_the_same_history_is_linearizable(self, kv, needs_checker):
        _h = History()
        _h.call('write', 0, lambda: kv.put(0), ok=lambda r: r == 200)
        assert eventually(lambda: that(kv.get()) == 0, within=5).ok
        _h.call('read', None, kv.get, result=lambda r: r)
        _c = _h.check('cas-register')
        assert _c.ok and '故障' not in _c.expr


class TestAnnotations:

    def test_operations_carry_the_faults_in_effect(self, kv):
        _h = History()
        _h.call('read', None, kv.get, result=lambda r: r)
        with faults.injected(faults.latency('replication', 5, stream='upstream')):
            _h.call('write', 1, lambda: kv.put(1))
        _h.call('read', None, kv.get, result=lambda r: r)
        assert [bool(_o.get('faults')) for _o in _h.ops] == [False, False, True, True, False, False]
        assert _h.ops[2]['faults'] == ['latency(replication, jitter=0, latency=5, upstream)']
        assert ':faults ["latency(replication' in _h.to_edn()

    def test_an_operation_that_began_before_a_fault_counts_as_under_it(self, kv):
        _h = History()
        _started, _go = threading.Event(), threading.Event()

        def slow():
            _started.set()
            _go.wait(5)
        _t = threading.Thread(target=lambda: _h.call('write', 1, slow))
        _t.start()
        _started.wait(5)
        with faults.injected(faults.latency('replication', 1)):
            _go.set()
            _t.join(5)
        assert 'faults' not in _h.ops[0] and _h.ops[1]['faults']
        assert _h._under_faults() == '；其中 1 个操作发生在注入的故障期间（latency(replication, jitter=0, latency=1)）'
        assert History()._under_faults() == ''


def _answer(monkeypatch, result):
    monkeypatch.setattr(consistency, 'checker', lambda: ('java', 'x.jar'))
    monkeypatch.setattr(consistency.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, json.dumps(result), ''))


class TestVerdicts:

    def test_a_pass_says_how_many_reads_of_nil_it_could_not_judge(self, monkeypatch):
        _answer(monkeypatch, {'valid?': True})
        _h = History()
        _h.call('write', 1, lambda: None)
        _h.call('read', None, lambda: None, result=lambda r: r)
        assert '1 个读到空值（None），检查器不据此判定' in _h.check('cas-register').expr
        assert '空值' not in _h.check('counter').expr      # a counter's nil read is not a register's

    def test_a_knossos_counterexample_names_the_fault(self):
        _final = [[{'op': {'process': 1, 'f': 'read', 'value': 0, 'faults': ['latency(db, latency=9)']},
                    'model': {'msg': "can't read 0 from register 1"}}]]
        assert consistency.counterexample({'valid?': False, 'final-paths': _final}).endswith(
            '它完成时故障正在生效：latency(db, latency=9)')
        del _final[0][0]['op']['faults']
        assert '故障' not in consistency.counterexample({'valid?': False, 'final-paths': _final})


class TestEvidence:

    def test_the_history_and_the_verdict_are_kept_for_the_case(self, monkeypatch, tmp_path):
        monkeypatch.setenv('IPANDORA_ARTIFACTS_DIR', str(tmp_path))
        _answer(monkeypatch, {'valid?': False, 'errors': [[1, 0, 1]]})
        _h = History()
        _h.call('write', 'token=s3cr3t-value', lambda: None)
        recorder.begin('test_x.py::test_kv')
        try:
            _h.check('cas-register', consistency_models=['strict-serializable'])
        finally:
            _evidence = recorder.end('test_x.py::test_kv')
        _history, _result = _evidence.artifacts
        assert (_history['kind'], _history['group'], _result['kind']) == ('history', 'cas-register', 'checker-result')
        _text = open(_history['path'], encoding='utf-8').read()
        assert _text.startswith('{:process 0, :type :invoke, :f :write, :value "token=')
        assert 's3cr3t-value' not in _text                 # the file sits next to the report, which CI uploads
        assert json.load(open(_result['path'], encoding='utf-8'))['valid?'] is False
        assert _history['command'].startswith('java -jar elle-cli-0.1.11-standalone.jar --model cas-register '
                                              '--consistency-models strict-serializable "')
        assert _artifact(_history)['command'] == _history['command']
        assert os.path.dirname(_history['path']) == str(tmp_path)

    def test_outside_a_case_nothing_is_written(self, monkeypatch, tmp_path):
        monkeypatch.setenv('IPANDORA_ARTIFACTS_DIR', str(tmp_path))
        _answer(monkeypatch, {'valid?': True})
        _h = History()
        _h.call('write', 1, lambda: None)
        _h.check('cas-register')
        assert os.listdir(str(tmp_path)) == []


class TestCr9:
    """Found in code review CR9 (docs/design/reviews/09-CR9.md)."""

    @pytest.mark.parametrize('workers', [None, 2], ids=['serial', 'parallel'])
    def test_a_run_triages_it_as_a_defect_and_reports_the_history(self, allowed, needs_checker, tmp_path,
                                                                    monkeypatch, workers):
        if workers:
            pytest.importorskip('xdist', reason='parallel runs need the `parallel` extra')
        from ipandora.core.report.builder import build_from_run
        from ipandora.core.report.render import to_html
        from ipandora.core.runner import run
        from ipandora.core.schedule import config
        from ipandora.core.schedule.runtime import Runtime
        from ipandora.core.triage import triage
        faults.Toxiproxy(allowed.url).proxy('db', '127.0.0.1:0', '127.0.0.1:9')
        monkeypatch.setattr(Runtime, 'settings', config.deep_merge(
            Runtime.settings, {'faults': {'allowed': True, 'toxiproxy': allowed.url}}))
        _conf = tmp_path / 'conf'
        _conf.mkdir()
        (_conf / 'config.yaml').write_text('faults:\n  allowed: true\n  toxiproxy: {}\n'.format(allowed.url),
                                           encoding='utf-8')
        monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(_conf))
        _suite = tmp_path / 'suite'
        _suite.mkdir()
        (_suite / 'test_kv.py').write_text(textwrap.dedent('''
            from ipandora.core import consistency, faults
            from ipandora.core.assertion import assert_all

            def test_stale_read_under_lag():
                history, replica = consistency.History(), {'v': 0}
                history.call('write', 0, lambda: None)
                with faults.injected(faults.latency('db', 50)):
                    history.call('write', 1, lambda: None)           # acknowledged, not yet replicated
                    history.call('read', None, lambda: replica['v'], result=lambda r: r)
                    assert_all(history.check('cas-register'))
        '''), encoding='utf-8')
        _result = run(str(_suite), persist=False, quiet=True, baseline='', workers=workers)
        _case = _result.cases[0]
        assert _case.outcome == 'failed'
        assert sorted(_a['kind'] for _a in _case.artifacts) == ['checker-result', 'history']
        assert [_f.category for _f in triage(_result).findings] == ['defect']     # the fault is the condition
        _html = to_html(build_from_run(_result))
        assert '操作历史' in _html and '--model cas-register' in _html

    def test_a_value_under_a_secret_field_name_is_masked_in_the_kept_files(self, monkeypatch, tmp_path):
        monkeypatch.setenv('IPANDORA_ARTIFACTS_DIR', str(tmp_path))
        _answer(monkeypatch, {'valid?': False, 'op': {'value': {'token': 'plain-looking-1', 'n': 1}}})  # pragma: allowlist secret
        _h = History()
        _h.call('write', {'token': 'plain-looking-1', 'n': 1}, lambda: None)  # pragma: allowlist secret
        recorder.begin('t::kv')
        try:
            _h.check('cas-register')
        finally:
            _evidence = recorder.end('t::kv')
        for _a in _evidence.artifacts:
            _text = open(_a['path'], encoding='utf-8').read()
            assert 'plain-looking-1' not in _text and '***REDACTED***' in _text, _a['kind']
        assert ':n 1' in open(_evidence.artifacts[0]['path'], encoding='utf-8').read()
        assert _h.ops[0]['value']['token'] == 'plain-looking-1'          # the checker still sees the real history

    def test_evidence_that_cannot_be_written_does_not_cost_the_verdict(self, monkeypatch, tmp_path, caplog):
        _blocked = tmp_path / 'a-file'
        _blocked.write_text('')
        monkeypatch.setenv('IPANDORA_ARTIFACTS_DIR', str(_blocked / 'artifacts'))     # cannot be created
        _answer(monkeypatch, {'valid?': True})
        _h = History()
        _h.call('write', 1, lambda: None)
        recorder.begin('t::kv')
        try:
            _c = _h.check('cas-register')
        finally:
            _evidence = recorder.end('t::kv')
        assert _c.ok and _evidence.artifacts == []
        assert 'could not keep the history of t::kv' in caplog.text
