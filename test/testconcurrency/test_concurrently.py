# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_concurrently.py
@Time  : 2026-11-05

concurrently(): N operations at once from inside one test.

Acceptance from docs/design/decisions/14 §2, against a real HTTP server in this process:

- a charge endpoint with a check-then-act race: concurrently() reproduces the
  double charge every time, and the locked implementation passes;
- concurrent requests carry the caller's login (the server checks a cookie);
- every concurrent request is in the case's evidence, and so in the report.

Plus the ways the primitive itself could quietly mislead: a start that did not
happen, operations that never overlapped, exceptions, a hang.
"""
import json
import os
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ipandora.core import api
from ipandora.core.assertion import assert_all
from ipandora.core.assertion.field import that
from ipandora.core.assertion.http import status_code
from ipandora.core.concurrency import NotConcurrent, Outcome, Results, concurrently
from ipandora.core.evidence import recorder
from ipandora.core.runner import run
from ipandora.core.schedule.runtime import Runtime
from ipandora.core.schedule.session import SessionManager

SID = 'sid=s3cret'


class Shop:
    """A payment service with one bug on purpose: /pay/racy checks, then acts."""

    WINDOW = 0.05   # the gap between "is it paid?" and "mark it paid"

    def __init__(self):
        self.lock = threading.Lock()
        self.paid = {}
        self.charges = {}

    def pay(self, order: str, locked: bool) -> int:
        if locked:
            with self.lock:
                return self._pay(order)
        return self._pay(order)

    def _pay(self, order):
        if self.paid.get(order):
            return 409
        time.sleep(self.WINDOW)
        self.paid[order] = True
        self.charges[order] = self.charges.get(order, 0) + 1
        return 200


def _handler(shop):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, code, body=None, cookie=None):
            _data = json.dumps(body or {}).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(_data)))
            if cookie:
                self.send_header('Set-Cookie', cookie + '; Path=/')
            self.end_headers()
            self.wfile.write(_data)

        def do_POST(self):
            _len = int(self.headers.get('Content-Length') or 0)
            if _len:
                self.rfile.read(_len)
            if self.path == '/login':
                return self._reply(200, {'ok': True}, cookie=SID)
            if SID not in (self.headers.get('Cookie') or ''):
                return self._reply(401, {'error': 'not logged in'})
            if self.path.startswith('/pay/'):
                _kind, _, _order = self.path[len('/pay/'):].partition('/')
                return self._reply(shop.pay(_order, locked=_kind == 'locked'))
            if self.path == '/echo':
                return self._reply(200, {'tenant': self.headers.get('X-Tenant')})
            return self._reply(404)

        do_GET = do_POST

    return Handler


@pytest.fixture
def shop():
    _shop = Shop()
    _server = ThreadingHTTPServer(('127.0.0.1', 0), _handler(_shop))
    _server.daemon_threads = True
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    _shop.url = 'http://127.0.0.1:{}'.format(_server.server_address[1])
    yield _shop
    _server.shutdown()
    _server.server_close()


@pytest.fixture(autouse=True)
def fresh_session():
    # this thread's session starts empty and ignores HTTP(S)_PROXY, which
    # would otherwise route 127.0.0.1 through the environment's proxy
    SessionManager.forget()
    SessionManager.getSession().trust_env = False
    yield
    SessionManager.forget()


def client(shop):
    class ShopApi:
        @api.http.post(shop.url + '/login')
        def login(self):
            return {}

        @api.http.post(shop.url + '/pay/racy/{order}')
        def pay_racy(self, order):
            return dict(other_params={'order': order})

        @api.http.post(shop.url + '/pay/locked/{order}')
        def pay_locked(self, order):
            return dict(other_params={'order': order})

        @api.http.post(shop.url + '/echo')
        def echo(self):
            return {}
    return ShopApi()


class TestAcceptance:

    @pytest.mark.parametrize('attempt', range(3))
    def test_the_race_is_reproduced_every_time(self, shop, attempt):
        _api = client(shop)
        _api.login()
        _results = concurrently(lambda: _api.pay_racy('A{}'.format(attempt)), n=10)
        _codes = [status_code(_r.value) for _r in _results]
        assert _results.overlapped, _results.warning
        # the bug: more than one request got through the check
        assert _codes.count(200) > 1
        assert shop.charges['A{}'.format(attempt)] > 1

    def test_the_locked_implementation_passes(self, shop):
        _api = client(shop)
        _api.login()
        _results = concurrently(lambda: _api.pay_locked('B1'), n=10)
        _codes = [status_code(_r.value) for _r in _results]
        assert_all(
            _results.overlap_check(),
            that(_codes, '各请求状态').each().is_in([200, 409]),
            that(_codes.count(200), '成功扣款次数') == 1,
        )
        assert shop.charges['B1'] == 1

    def test_the_same_judgement_fails_on_the_racy_one(self, shop):
        _api = client(shop)
        _api.login()
        _results = concurrently(lambda: _api.pay_racy('C1'), n=10)
        _codes = [status_code(_r.value) for _r in _results]
        with pytest.raises(AssertionError, match='成功扣款次数'):
            assert_all(_results.overlap_check(),
                       that(_codes.count(200), '成功扣款次数') == 1)

    def test_concurrent_requests_are_logged_in(self, shop):
        _api = client(shop)
        _api.login()
        _results = concurrently(lambda: _api.pay_locked('D1'), n=8)
        assert 401 not in [status_code(_r.value) for _r in _results]

    def test_a_plain_thread_is_not_logged_in(self, shop):
        # the pitfall itself, so the test above is known to be testing something
        _api = client(shop)
        _api.login()
        _seen = {}

        def _plain():
            SessionManager.getSession().trust_env = False
            _seen['code'] = status_code(_api.pay_locked('E1'))
            SessionManager.forget()
        _t = threading.Thread(target=_plain)
        _t.start()
        _t.join()
        assert _seen['code'] == 401

    def test_headers_set_on_the_session_reach_every_request(self, shop):
        _api = client(shop)
        _api.login()
        SessionManager.setHeaders({'X-Tenant': 'tenant-7'})
        _results = concurrently(_api.echo, n=5)
        assert {_r.value.data['tenant'] for _r in _results} == {'tenant-7'}

    def test_every_concurrent_request_is_in_the_report(self, shop, tmp_path, monkeypatch):
        monkeypatch.setenv('SHOP_URL', shop.url)
        monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'no-conf'))
        _suite = tmp_path / 'test_shop.py'
        _suite.write_text(textwrap.dedent('''
            import os
            from ipandora.core import api
            from ipandora.core.assertion import assert_all
            from ipandora.core.assertion.field import that
            from ipandora.core.assertion.http import status_code
            from ipandora.core.concurrency import concurrently
            from ipandora.core.schedule.session import SessionManager

            URL = os.environ['SHOP_URL']

            class ShopApi:
                @api.http.post(URL + '/login')
                def login(self):
                    return {}

                @api.http.post(URL + '/pay/locked/{order}')
                def pay(self, order):
                    return dict(other_params={'order': order})

            def test_pay_exactly_once():
                SessionManager.getSession().trust_env = False
                shop = ShopApi()
                shop.login()
                results = concurrently(lambda: shop.pay('R1'), n=12)
                codes = [status_code(r.value) for r in results]
                assert_all(results.overlap_check(),
                           that(codes.count(200), '成功扣款次数') == 1)
        '''), encoding='utf-8')
        _result = run(str(_suite), persist=False, quiet=True, baseline='')
        assert _result.ok, [(_c.outcome, _c.message) for _c in _result.cases]
        _case = _result.cases[0]
        _urls = [_e['url'] for _e in _case.exchanges]
        assert _urls.count(shop.url + '/pay/locked/R1') == 12
        assert sorted(_e['status'] for _e in _case.exchanges
                      if _e['url'].endswith('/R1')) == [200] + [409] * 11
        assert {_c['claim'] for _c in _case.checks} >= {
            'concurrently: 12 operations in flight together'}


class TestTheStart:

    def test_a_thread_failing_before_the_start_aborts_the_burst(self, monkeypatch):
        _real = SessionManager.clone
        _calls = {'n': 0}
        _ran = []

        def _clone(session):
            _calls['n'] += 1
            if _calls['n'] == 3:
                raise RuntimeError('cannot copy session')
            return _real(session)
        monkeypatch.setattr(SessionManager, 'clone', _clone)
        _start = time.perf_counter()
        with pytest.raises(NotConcurrent, match='failed while getting ready.*none of them was run'):
            concurrently(lambda: _ran.append(1), n=6)
        # at once, not after the others have waited out the whole timeout
        assert time.perf_counter() - _start < 5
        time.sleep(0.1)
        assert _ran == []

    def test_threads_not_ready_in_time_abort_the_burst(self, monkeypatch):
        _real = SessionManager.clone
        _ran = []

        def _slow(session):
            time.sleep(1)
            return _real(session)
        monkeypatch.setattr(SessionManager, 'clone', _slow)
        with pytest.raises(NotConcurrent, match='not all ready'):
            concurrently(lambda: _ran.append(1), n=3, timeout=0.3)
        time.sleep(1.2)
        assert _ran == []

    @pytest.mark.parametrize('args, error', [
        ((lambda: 1,), TypeError),          # no n
        ((lambda: 1, 1), ValueError),        # one is not concurrency
        (([lambda: 1],), ValueError),
        (([lambda: 1, 'x'],), TypeError),
    ])
    def test_bad_arguments(self, args, error):
        with pytest.raises(error):
            concurrently(*args)


class TestOutcomes:

    def test_exceptions_are_results_not_raised(self):
        def _boom():
            raise ValueError('nope')
        _results = concurrently([lambda: 1, _boom, lambda: pytest.fail('in a thread')])
        assert _results[0].ok and _results[0].value == 1
        assert isinstance(_results[1].error, ValueError)
        assert 'in a thread' in str(_results[2].error)
        assert [_o.index for _o in _results.errors] == [1, 2]

    def test_different_operations_run_once_each_in_order_given(self):
        _results = concurrently([lambda: 'pay', lambda: 'refund', lambda: 'cancel'])
        assert _results.values == ['pay', 'refund', 'cancel']

    def test_a_hanging_operation_is_reported_not_waited_for(self):
        _start = time.perf_counter()
        _results = concurrently([lambda: time.sleep(5), lambda: 'quick'], timeout=0.5)
        assert time.perf_counter() - _start < 3
        assert isinstance(_results[0].error, TimeoutError)
        assert _results[1].value == 'quick'

    def test_starts_are_measured_from_the_first(self):
        _results = concurrently(lambda: time.sleep(0.2), n=4)
        assert min(_o.start for _o in _results) == 0
        assert _results.start_skew < 0.2
        assert _results.overlapped


class TestOverlap:

    @staticmethod
    def results(*spans):
        return Results(Outcome(index=_i, start=_s, duration=_d) for _i, (_s, _d) in enumerate(spans))

    def test_all_in_flight_together(self):
        _r = self.results((0, 0.1), (0.01, 0.1), (0.02, 0.1))
        assert _r.overlapped and not _r.warning
        assert _r.overlap_check().ok

    def test_one_finished_before_the_last_started(self):
        # this is a sequence, and a race needs overlap to happen at all
        _r = self.results((0, 0.001), (0.01, 0.1))
        assert not _r.overlapped
        assert '并发没有完全发生' in _r.warning
        _check = _r.overlap_check()
        assert not _check.ok and _check.src == 'concurrency'
        assert _check.claim == 'concurrently: 2 operations in flight together'


class TestWhatThreadsInherit:

    def test_evidence_goes_to_the_case_that_started_them(self):
        recorder.begin('case-x')
        try:
            from ipandora.core.assertion.check import Check
            concurrently(lambda: recorder.add_checks([Check(name='c', ok=True)]), n=5)
            assert len(recorder.current_checks()) == 5
        finally:
            recorder.end('case-x')

    def test_steps_go_to_the_case_that_started_them(self):
        Runtime.Case.cur_case_name = 'checkout'
        try:
            _results = concurrently(lambda: Runtime.Case.cur_case_name, n=3)
            assert _results.values == ['checkout'] * 3
        finally:
            Runtime.Case.cur_case_name = None

    def test_no_thread_session_is_left_behind(self):
        # idents are reused: a session left behind would be inherited, cookies
        # and all, by whatever thread next gets the same name and ident
        _before = set(SessionManager._session_map)
        concurrently(lambda: SessionManager.getSession(), n=5)
        assert set(SessionManager._session_map) <= _before
