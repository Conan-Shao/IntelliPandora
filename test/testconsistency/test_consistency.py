# -*- coding: utf-8 -*-
"""
@File  : test_consistency.py
@Time  : 2026-11-06

Consistency checks on an operation history (docs/design/decisions/18, D3a).
Acceptance: a counter with a read-modify-write race, driven by
concurrently(), is judged inconsistent with a counterexample; the fixed one
is judged consistent.

The checker tests need Java 21 and elle-cli (ELLE_CLI_JAR); CI provides
both and sets IPANDORA_REQUIRE_CHECKER, which turns a skip into a failure.
"""
import os
import subprocess
import threading
import time

import pytest

from ipandora.core import consistency
from ipandora.core.concurrency import concurrently
from ipandora.core.consistency import K, History


def _checker_or_skip():
    try:
        return consistency.checker()
    except BaseException as exc:          # require() skips via pytest's own exception
        if os.environ.get('IPANDORA_REQUIRE_CHECKER'):
            pytest.fail('the consistency checker is required here: {}'.format(exc))
        pytest.skip('no consistency checker: {}'.format(exc))


needs_checker = pytest.fixture(_checker_or_skip)


class TestEdn:

    def test_values(self):
        assert consistency.edn({'process': 1, 'type': K('ok'), 'f': K('read'), 'value': None}) == \
            '{:process 1, :type :ok, :f :read, :value nil}'
        assert consistency.edn([consistency.append(3, 8), consistency.read(4, [1, 2])]) == '[[:append 3 8] [:r 4 [1 2]]]'
        assert consistency.edn('a "q"') == '"a \\"q\\""' and consistency.edn(True) == 'true'
        assert consistency.edn(2.5) == '2.5'
        with pytest.raises(TypeError, match='EDN'):
            consistency.edn(object())


class TestHistory:

    def test_ok_fail_info_and_a_new_process_after_info(self):
        _h = History()
        _h.call('write', 1, lambda: 200, ok=lambda r: r == 200)
        _h.call('cas', [1, 2], lambda: 409, fail=lambda r: r == 409)
        _h.call('write', 3, lambda: 503, ok=lambda r: r == 200)          # unknown: info
        with pytest.raises(TimeoutError):
            _h.call('write', 4, lambda: (_ for _ in ()).throw(TimeoutError('slow')))
        _h.call('read', None, lambda: {'v': 1}, result=lambda r: r['v'])
        assert [(_o['process'], str(_o['type']), str(_o['f'])) for _o in _h.ops] == [
            (0, 'invoke', 'write'), (0, 'ok', 'write'), (0, 'invoke', 'cas'), (0, 'fail', 'cas'),
            (0, 'invoke', 'write'), (0, 'info', 'write'),
            (1, 'invoke', 'write'), (1, 'info', 'write'),
            (2, 'invoke', 'read'), (2, 'ok', 'read')]
        assert _h.ops[-1]['value'] == 1 and 'TimeoutError: slow' in _h.ops[7]['error']
        assert all(_a['time'] <= _b['time'] for _a, _b in zip(_h.ops, _h.ops[1:]))
        assert _h.to_edn().count('\n') == 10

    def test_threads_are_processes(self):
        _h = History()
        concurrently([lambda: _h.call('add', 1, lambda: time.sleep(0.01))] * 3)
        assert len({_o['process'] for _o in _h.ops}) == 3

    def test_mistakes(self):
        with pytest.raises(ValueError, match='unknown model'):
            History().check('linearizable')
        assert not History().check('counter').ok          # an empty history proves nothing


class TestChecker:

    def test_missing_java_or_jar_skips_and_says_why(self, monkeypatch):
        monkeypatch.setattr(consistency, '_settings', lambda: {'elle_cli': '/nowhere.jar'})
        with pytest.raises(BaseException, match='elle-cli'):
            consistency.checker()

    def test_a_jar_with_another_hash_is_refused(self, tmp_path, monkeypatch):
        _java, _ = _checker_or_skip()
        _fake = tmp_path / 'elle-cli.jar'
        _fake.write_bytes(b'not the admitted build')
        monkeypatch.setattr(consistency, '_settings', lambda: {'elle_cli': str(_fake), 'java': _java})
        with pytest.raises(RuntimeError, match='refusing to run it'):
            consistency.checker()
        monkeypatch.setattr(consistency, '_settings', lambda: {
            'elle_cli': str(_fake), 'java': _java,
            'elle_cli_sha256': __import__('hashlib').sha256(b'not the admitted build').hexdigest()})
        assert consistency.checker()[1] == str(_fake)        # admitted by the project itself

    def test_unknown_is_no_verdict_and_counterexamples_read_well(self, monkeypatch):
        _h = History()
        _h.call('add', 1, lambda: None)
        monkeypatch.setattr(consistency, 'checker', lambda: ('java', 'x.jar'))
        monkeypatch.setattr(consistency.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, '{"valid?": "unknown"}', ''))
        _c = _h.check('counter')
        assert _c.is_gap and '无法判定' in _c.expr
        assert consistency.counterexample({'valid?': False, 'errors': [[8, 1, 8]]}) == \
            '读到 1，按已确认的操作应在 8 到 8 之间'
        assert consistency.counterexample({'valid?': False, 'anomaly-types': ['G1c'], 'not': ['read-committed']}) \
            == '异常：G1c；不满足 read-committed'


class Counter:
    def __init__(self, racy):
        self.n, self.racy, self.lock = 0, racy, threading.Lock()

    def incr(self):
        if self.racy:
            _v = self.n
            time.sleep(0.01)                  # read, think, write: the classic lost update
            self.n = _v + 1
        else:
            with self.lock:
                self.n += 1
        return 200


class TestAcceptance:

    def _history(self, counter):
        _h = History()
        concurrently([lambda: _h.call('add', 1, counter.incr, ok=lambda r: r == 200)] * 8)
        _h.call('read', None, lambda: counter.n, result=lambda r: r)
        return _h

    def test_a_racy_counter_is_inconsistent_with_a_counterexample(self, needs_checker):
        _c = self._history(Counter(racy=True)).check('counter')
        assert not _c.ok and _c.src == consistency.CONSISTENCY
        assert '按已确认的操作应在 8 到 8 之间' in _c.expr

    def test_the_fixed_counter_is_consistent(self, needs_checker):
        _c = self._history(Counter(racy=False)).check('counter')
        assert _c.ok and '9 个操作' in _c.expr

    def test_a_register_read_no_order_explains(self, needs_checker):
        _h = History()
        _h.call('write', 1, lambda: None)
        _h.call('read', None, lambda: 2, result=lambda r: r)
        _c = _h.check('cas-register')
        assert not _c.ok and "can't read 2" in _c.expr


def test_the_admitted_hash_is_the_one_registered_and_the_one_ci_checks():
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _registry = open(os.path.join(_root, 'docs', 'security', 'components.md'), encoding='utf-8').read()
    _ci = open(os.path.join(_root, '.github', 'workflows', 'ci.yml'), encoding='utf-8').read()
    assert consistency.ELLE_CLI_SHA256 in _registry and consistency.ELLE_CLI_SHA256 in _ci
    assert consistency.ELLE_CLI_URL in _ci and consistency.ELLE_CLI_VERSION in _registry


class TestCr8:
    """Found in code review CR8 (docs/design/reviews/08-CR8.md)."""

    def test_a_base_exception_still_completes_the_operation(self):
        class Stop(BaseException):
            pass

        def stop():
            raise Stop()
        _h = History()
        with pytest.raises(Stop):
            _h.call('write', 1, stop)
        _h.call('write', 2, lambda: None)
        assert [(_o['process'], str(_o['type'])) for _o in _h.ops] == [
            (0, 'invoke'), (0, 'info'), (1, 'invoke'), (1, 'ok')]

    def test_a_name_that_is_not_a_keyword_is_refused_before_running(self):
        _ran = []
        with pytest.raises(ValueError, match='EDN keyword'):
            History().call('add one', 1, lambda: _ran.append(1))
        assert _ran == []
        assert K('read') == 'read' and K('cas-op?') == 'cas-op?'

    def test_a_value_that_is_not_finite_is_refused(self):
        with pytest.raises(ValueError, match='finite'):
            History().call('add', float('nan'), lambda: None)
        with pytest.raises(ValueError, match='finite'):
            consistency.edn([float('inf')])

    def test_a_jar_swapped_after_it_was_checked_is_checked_again(self, tmp_path, monkeypatch):
        _java, _ = _checker_or_skip()
        _jar = tmp_path / 'elle-cli.jar'
        _jar.write_bytes(b'admitted')
        _hash = __import__('hashlib').sha256(b'admitted').hexdigest()
        monkeypatch.setattr(consistency, '_settings', lambda: {'elle_cli': str(_jar), 'java': _java,
                                                               'elle_cli_sha256': _hash})
        assert consistency.checker()[1] == str(_jar)
        time.sleep(0.01)
        _jar.write_bytes(b'swapped!')
        with pytest.raises(RuntimeError, match='refusing'):
            consistency.checker()
