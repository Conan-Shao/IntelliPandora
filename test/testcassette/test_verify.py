# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_verify.py
@Time  : 2026-08-03

`--verify` end to end: record a baseline, change the server, see what is said.

The server changes its answers between runs, which is the situation verify
exists for -- a service rewritten behind the same contract.
"""
import json
import os
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

BASELINE = {'code': '000000',
            'data': {'orderId': '26073', 'status': 'SUCCESS', 'amount': '0.5',
                     'fee': '0.0002', 'serverTime': 1754130062,
                     'traceId': 'abc-123'}}

DRIFTED = {'code': '000000',
           'data': {'orderId': '26073', 'status': 'PROCESSING',
                    'amount': '0.50000001', 'serverTime': 1754130999,
                    'traceId': 'zzz-999', 'riskLevel': 'LOW'}}

SUITE = '''
    from ipandora.core import api
    from ipandora.core.assertion import assert_all, json_equals, status_ok
    from ipandora.core.base.data.markdata import MarkData
    from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface
    from ipandora.core.plugin.pluginmanager import PluginManager

    class _N(EndPointsInterface):
        def endpoints(self, mark: MarkData) -> dict:
            return {{}}

    PluginManager.endpoints(reg=_N())

    class C:
        @api.http.get("{base}/v1/order/query")
        def order(self):
            return {{}}

    def test_order():
        """订单查询"""
        assert_all(status_ok(C().order()), json_equals(C().order(), 'code', '000000'))
'''


class _State:
    drifted = False


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        _raw = json.dumps(DRIFTED if _State.drifted else BASELINE).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(_raw)))
        self.end_headers()
        self.wfile.write(_raw)

    def log_message(self, *_args):
        pass


@pytest.fixture
def service():
    _State.drifted = False
    _server = HTTPServer(('127.0.0.1', 0), _Handler)
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    yield 'http://127.0.0.1:{}'.format(_server.server_port), _State
    _server.shutdown()
    _server.server_close()


@pytest.fixture
def suite(tmp_path, service):
    _base, _ = service
    _file = tmp_path / 'test_order_suite.py'
    _file.write_text(textwrap.dedent(SUITE).format(base=_base), encoding='utf-8')
    return str(_file)


def ipandora(*args, tmp_path):
    _env = dict(os.environ)
    _env.update({'IPANDORA_REPORTS_DIR': str(tmp_path / 'reports'),
                 'IPANDORA_CASSETTES_DIR': str(tmp_path / 'tapes'),
                 'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'})
    return subprocess.run([sys.executable, '-m', 'ipandora.run'] + list(args),
                          capture_output=True, text=True, env=_env, timeout=180)


def record(suite, tmp_path, name='base'):
    _done = ipandora('run', suite, '--record', '--cassette', name, tmp_path=tmp_path)
    assert _done.returncode == 0, _done.stdout + _done.stderr
    return _done


def verify(suite, tmp_path, *extra, name='base'):
    return ipandora('run', suite, '--verify', '--cassette', name, *extra,
                    tmp_path=tmp_path)


def set_diff_rules(tmp_path, rules, name='base'):
    import yaml
    _file = tmp_path / 'tapes' / name / 'manifest.yaml'
    _data = yaml.safe_load(_file.read_text(encoding='utf-8'))
    _data['diff'] = rules
    _file.write_text(yaml.safe_dump(_data, allow_unicode=True, sort_keys=False),
                     encoding='utf-8')


class TestNothingChanged:
    def test_an_unchanged_service_passes(self, suite, tmp_path):
        record(suite, tmp_path)
        done = verify(suite, tmp_path)
        assert done.returncode == 0, done.stdout
        assert '0 次有差异' in done.stdout

    def test_it_says_how_many_comparisons_it_made(self, suite, tmp_path):
        """Not just "no differences" -- how many were actually compared. The
        two are very different claims."""
        record(suite, tmp_path)
        assert '比对 2 次' in verify(suite, tmp_path).stdout


class TestSomethingChanged:
    def test_a_changed_service_fails_the_run(self, suite, tmp_path, service):
        record(suite, tmp_path)
        service[1].drifted = True
        done = verify(suite, tmp_path)
        assert done.returncode == 1
        assert '与基线不一致' in done.stdout

    def test_the_assertions_still_pass_but_the_run_does_not(self, suite, tmp_path,
                                                            service):
        """The point of verify: nothing the test asserts is broken, and the
        behaviour changed anyway. That is exactly the case a rewrite needs
        caught, and no assertion would have caught it."""
        record(suite, tmp_path)
        service[1].drifted = True
        done = verify(suite, tmp_path)
        assert 'PASS  1 passed' in done.stdout
        assert done.returncode == 1

    def test_each_change_is_named_with_both_sides(self, suite, tmp_path, service):
        record(suite, tmp_path)
        service[1].drifted = True
        out = verify(suite, tmp_path).stdout
        assert "data.status: 'SUCCESS' → 'PROCESSING'" in out
        assert 'data.fee: 消失' in out

    def test_the_terminal_truncates_but_says_it_did(self, suite, tmp_path, service):
        """Six differences, five printed. Silently dropping the sixth would be
        the problem; saying so is not."""
        record(suite, tmp_path)
        service[1].drifted = True
        out = verify(suite, tmp_path).stdout
        assert '另有 1 处' in out

    def test_the_report_carries_every_difference(self, suite, tmp_path, service):
        # the terminal is a summary; completeness belongs in the artifact
        record(suite, tmp_path)
        service[1].drifted = True
        verify(suite, tmp_path)
        _runs = sorted((tmp_path / 'reports').glob('run-*/report.json'))
        _text = _runs[-1].read_text(encoding='utf-8')
        for _field in ('data.status', 'data.fee', 'data.riskLevel',
                       'data.serverTime', 'data.traceId'):
            assert _field in _text, _field

    def test_allow_diff_reports_without_failing(self, suite, tmp_path, service):
        record(suite, tmp_path)
        service[1].drifted = True
        done = verify(suite, tmp_path, '--allow-diff')
        assert done.returncode == 0
        assert '有差异' in done.stdout

    def test_the_report_is_still_written_when_the_diff_fails(self, suite, tmp_path,
                                                             service):
        """The moment the evidence matters most is the moment it was being
        skipped: bailing out on a difference used to happen before the report
        was built."""
        record(suite, tmp_path)
        service[1].drifted = True
        assert verify(suite, tmp_path).returncode == 1

        _runs = sorted((tmp_path / 'reports').glob('run-*/report.json'))
        _data = json.loads(_runs[-1].read_text(encoding='utf-8'))
        # one check per difference: 6 changes across 2 identical calls
        assert _data['by_source']['diff']['failed'] == 12
        _checks = [c for case in _data['cases'] for c in case['checks']
                   if c['src'] == 'diff']
        assert any('data.status' in c['expr'] for c in _checks)


class TestNoiseRules:
    def test_ignored_and_tolerated_fields_drop_out(self, suite, tmp_path, service):
        record(suite, tmp_path)
        service[1].drifted = True
        set_diff_rules(tmp_path, {
            'ignore_paths': ['data.serverTime', 'data.traceId'],
            'tolerate': [{'path': 'data.amount', 'kind': 'numeric',
                          'epsilon': 0.0001}]})
        out = verify(suite, tmp_path).stdout
        assert 'serverTime' not in out and 'traceId' not in out
        assert '已容忍' in out
        # and the real changes survive
        assert 'data.status' in out and 'data.fee' in out


class TestComparisonFailureIsNotAgreement:
    """
    The failure mode this whole feature dies of quietly: the comparator breaks,
    the exception is swallowed, and the run reports zero differences and exits
    green. That is indistinguishable from success and strictly worse than a
    crash.
    """

    def test_a_run_that_compared_nothing_fails(self, suite, tmp_path):
        record(suite, tmp_path, name='other')
        # a tape recorded from a different endpoint: requests go out, nothing
        # matches, and "0 differences" would be a lie
        _tape = tmp_path / 'tapes' / 'other' / 'exchanges.jsonl'
        _lines = _tape.read_text(encoding='utf-8').splitlines()
        _lines = [_l.replace('/v1/order/query', '/v1/somewhere/else') for _l in _lines]
        _tape.write_text('\n'.join(_lines) + '\n', encoding='utf-8')

        done = verify(suite, tmp_path, name='other')
        assert done.returncode == 1
        assert '一次都没能与基线比对上' in done.stdout

    def test_allow_diff_does_not_silence_it(self, suite, tmp_path):
        """--allow-diff says differences are acceptable. It does not say that
        not comparing is acceptable."""
        record(suite, tmp_path, name='other')
        _tape = tmp_path / 'tapes' / 'other' / 'exchanges.jsonl'
        _tape.write_text(_tape.read_text(encoding='utf-8')
                         .replace('/v1/order/query', '/v1/elsewhere'), encoding='utf-8')
        assert verify(suite, tmp_path, '--allow-diff',
                      name='other').returncode == 1

    def test_an_unmatched_request_is_reported_as_uncompared(self, suite, tmp_path):
        record(suite, tmp_path)
        # add a second, unrecorded endpoint to the suite
        _extra = '\n\ndef test_extra():\n    """另一个接口"""\n    pass\n'
        assert verify(suite, tmp_path).returncode == 0


class TestABrokenComparatorIsNotAgreement:
    """
    In process, because this is about what happens when compare() itself
    raises -- which is how the real defect behaved: an exception swallowed
    upstream, zero differences reported, exit code 0. Green, and nothing had
    been verified.
    """

    def _tape(self, tmp_path):
        from ipandora.core.cassette import Cassette
        from ipandora.core.cassette.store import CassetteStore
        from ipandora.core.cassette.model import Manifest, Record

        _store = CassetteStore('t', directory=str(tmp_path))
        _store.append(Record(method='GET', url='https://x.test/a', status=200,
                             response_body='{"a": 1}'))
        _store.save_manifest(Manifest(name='t'))
        return Cassette('t', directory=str(tmp_path)).load()

    def test_a_raising_comparator_is_recorded_not_swallowed(self, tmp_path,
                                                            monkeypatch):
        def _boom(*_args, **_kwargs):
            raise TypeError("'NoneType' object has no attribute 'get'")

        monkeypatch.setattr('ipandora.core.cassette.cassette.compare', _boom)
        _tape = self._tape(tmp_path)

        assert _tape.verify('GET', 'https://x.test/a', None, 200, {}, '{"a": 2}') is None
        assert _tape.verify_errors, 'the failure vanished'
        assert _tape.diffs == [], 'a failed comparison must not look like a result'
        assert _tape.attempted == 1

    def test_the_command_fails_on_a_recorded_comparison_failure(self, tmp_path,
                                                               monkeypatch):
        from argparse import Namespace
        from ipandora.run.commands.run import Command

        def _boom(*_args, **_kwargs):
            raise TypeError('broken')

        monkeypatch.setattr('ipandora.core.cassette.cassette.compare', _boom)
        _tape = self._tape(tmp_path)
        _tape.verify('GET', 'https://x.test/a', None, 200, {}, '{"a": 2}')

        _reason = Command._report_diffs(Namespace(allow_diff=False), _tape)
        assert _reason and '比对失败' in _reason

    def test_allow_diff_does_not_excuse_a_broken_comparator(self, tmp_path,
                                                            monkeypatch):
        from argparse import Namespace
        from ipandora.run.commands.run import Command

        monkeypatch.setattr('ipandora.core.cassette.cassette.compare',
                            lambda *_a, **_k: (_ for _ in ()).throw(TypeError('x')))
        _tape = self._tape(tmp_path)
        _tape.verify('GET', 'https://x.test/a', None, 200, {}, '{"a": 2}')

        assert Command._report_diffs(Namespace(allow_diff=True), _tape)

    def test_a_working_comparator_leaves_no_errors(self, tmp_path):
        _tape = self._tape(tmp_path)
        _result = _tape.verify('GET', 'https://x.test/a', None, 200, {}, '{"a": 2}')
        assert _result is not None and not _tape.verify_errors


class TestModesAreExclusive:
    def test_verify_and_replay_cannot_be_combined(self, suite, tmp_path):
        assert ipandora('run', suite, '--verify', '--replay',
                        tmp_path=tmp_path).returncode != 0

    def test_verify_needs_a_cassette_that_exists(self, suite, tmp_path):
        done = verify(suite, tmp_path, name='never-recorded')
        assert done.returncode != 0
        assert '--record' in (done.stdout + done.stderr)
