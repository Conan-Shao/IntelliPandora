# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_eventually.py
@Time  : 2026-11-05

eventually(): judging something that becomes true later, without sleep().
Timing is driven by a fake clock, so the counts are exact and the suite does
not wait; one test uses the real clock to make sure the defaults are wired.
"""
import textwrap
import time

import pytest

from ipandora.core.assertion import Check, assert_all, eventually, gap, that, wait
from ipandora.core.runner import inventory, run


class Clock:
    def __init__(self):
        self.now = 1000.0       # not 0: elapsed must be a difference, not the reading
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    _clock = Clock()
    monkeypatch.setattr(wait, '_clock', _clock)
    monkeypatch.setattr(wait, '_sleep', _clock.sleep)
    return _clock


def reads(*values):
    """A probe that reads the next value each call, then keeps the last one."""
    _values = list(values)
    _calls = []

    def _probe():
        _calls.append(1)
        _value = _values[min(len(_calls), len(_values)) - 1]
        if isinstance(_value, Exception):
            raise _value
        return that(_value, 'order.status') == 'PAID'
    _probe.calls = _calls
    return _probe


class TestWaiting:

    def test_it_holds_once_the_value_arrives(self, clock):
        _probe = reads('CREATED', 'PENDING', 'PAID')
        _check = eventually(_probe, within=10, every=0.5)
        assert _check.ok and len(_probe.calls) == 3
        assert _check.expr.startswith('第 3 次读到成立，用时 1 s（上限 10 s）')
        assert _check.expr.endswith("；之前读到：order.status = 'CREATED' (expected 'PAID') → "
                                    "order.status = 'PENDING' (expected 'PAID')")
        assert _check.name == "最终成立：order.status == 'PAID'"
        assert _check.src == 'derived'

    def test_elapsed_time_is_measured_and_rounded(self, clock):
        _check = eventually(reads('PENDING', 'PAID'), within=10, every=0.1234567)
        assert '用时 0.123 s' in _check.expr

    def test_holding_at_once_reads_once_and_never_sleeps(self, clock):
        _check = eventually(reads('PAID'), within=10)
        assert _check.ok and clock.sleeps == []
        assert '之前读到' not in _check.expr

    def test_it_gives_up_at_the_deadline_and_says_what_it_saw(self, clock):
        _probe = reads('CREATED', 'PENDING')
        _check = eventually(_probe, within=1, every=0.4)
        assert not _check.ok
        # reads at 0, 0.4, 0.8 and one last at the deadline, never after it
        assert len(_probe.calls) == 4 and clock.sleeps == [0.4, 0.4, 0.2]
        assert _check.expr.startswith('1 s 内读了 4 次都不成立')
        # consecutive identical reads are shown once, in the order seen
        assert _check.expr.index("'CREATED'") < _check.expr.index("'PENDING'")
        assert _check.expr.count("'PENDING'") == 1

    def test_within_zero_is_one_read(self, clock):
        _probe = reads('PENDING')
        assert not eventually(_probe, within=0).ok
        assert len(_probe.calls) == 1 and clock.sleeps == []

    def test_every_check_of_a_read_must_hold(self, clock):
        _n = []

        def _probe():
            _n.append(1)
            return [that(len(_n), 'replicas') >= 2, that('PAID', 'status') == 'PAID']
        _check = eventually(_probe, within=5, every=1)
        assert _check.ok and len(_n) == 2
        assert _check.claim == "eventually replicas >= 2 and status == 'PAID' (within 5 s)"
        assert _check.name == "最终成立：replicas >= 2, status == 'PAID'"
        assert eventually(_probe, within=1, name='副本追上主节点').name == '最终成立：副本追上主节点'

    def test_only_the_failing_checks_are_shown(self, clock):
        _check = eventually(lambda: [that(1, 'a') == 1, that(2, 'b') == 3,
                                     that(4, 'c') == 5], within=0)
        assert _check.expr.endswith('b = 2 (expected 3); c = 4 (expected 5)')
        assert 'a = 1' not in _check.expr

    def test_it_takes_the_dimension_of_what_it_judges(self, clock):
        from ipandora.core.assertion import Source, field  # noqa: F401
        _check = eventually(lambda: Check('replica in sync', True, src='ledger'), within=1)
        assert _check.src == 'ledger' 

    def test_the_last_ones_are_kept_when_it_saw_many(self, clock):
        _seen = iter(range(100))
        _check = eventually(lambda: that(next(_seen), 'n') < 0, within=20, every=1)
        assert not _check.ok
        assert _check.expr.endswith(
            'n = 0 (expected < 0) → n = 1 (expected < 0) → n = 2 (expected < 0) → …（另有 15 种） → '
            'n = 18 (expected < 0) → n = 19 (expected < 0) → n = 20 (expected < 0)')

    def test_six_observations_are_all_shown(self, clock):
        _seen = iter(range(100))
        _check = eventually(lambda: that(next(_seen), 'n') < 0, within=5, every=1)
        assert '另有' not in _check.expr and _check.expr.count(' → ') == 5


class TestWhatAReadCanDo:

    def test_a_read_that_raises_is_an_observation_not_the_end(self, clock):
        _probe = reads(ConnectionError('node-2 refused'), 'PAID')
        _check = eventually(_probe, within=5)
        assert _check.ok and _check.expr.endswith('之前读到：ConnectionError: node-2 refused')

    def test_raising_until_the_deadline_fails_with_the_error(self, clock):
        _check = eventually(reads(TimeoutError('read timed out')), within=1, every=0.5)
        assert not _check.ok and _check.expr.endswith('：TimeoutError: read timed out')
        assert _check.claim == 'eventually probe (within 1 s)'
        assert _check.name == '最终成立：probe' and _check.src == 'derived'

    def test_an_assert_all_inside_the_probe_is_a_read_that_did_not_hold(self, clock):
        _n = []

        def _probe():
            _n.append(1)
            assert_all(that(len(_n), 'n') >= 2)
            return that(True, 'done') == True  # noqa: E712
        assert eventually(_probe, within=5).ok and len(_n) == 2

    def test_a_failing_assert_all_in_the_probe_shows_its_first_line(self, clock):
        def _probe():
            assert_all(that(1, 'n') >= 2)
        _check = eventually(_probe, within=0)
        assert _check.expr.endswith('：Assertion failed (1/1 checks failed)')

    def test_a_bare_assertion_error_is_named(self, clock):
        def _probe():
            raise AssertionError()
        assert eventually(_probe, within=0).expr.endswith('：AssertionError')

    @pytest.mark.parametrize('result', [True, None, [], [gap('not judged')]])
    def test_a_probe_that_judges_nothing_is_a_bug_reported_at_once(self, clock, result):
        with pytest.raises(TypeError, match=r'eventually\(\)|Check'):
            eventually(lambda: result, within=60)
        assert clock.sleeps == []

    @pytest.mark.parametrize('within,every', [(-1, 0.5), (1, 0), (1, -1)])
    def test_bad_timing_is_refused(self, within, every):
        with pytest.raises(ValueError, match=r'eventually\(\): within must be >= 0 and every > 0'):
            eventually(reads('PAID'), within=within, every=every)


class TestAsAJudgement:

    def test_it_fails_assert_all_with_its_evidence(self, clock):
        with pytest.raises(AssertionError) as exc:
            assert_all(eventually(reads('PENDING'), within=2))
        assert "最终成立：order.status == 'PAID'" in str(exc.value)
        assert '2 s 内读了 5 次都不成立' in str(exc.value)

    def test_waiting_longer_is_a_changed_judgement(self, clock):
        _short = eventually(reads('PAID'), within=10).claim
        _long = eventually(reads('PAID'), within=60).claim
        assert _short != _long
        assert inventory.classify(_short, _long) in inventory.WEAKENING

    def test_the_real_clock(self):
        _start = time.monotonic()
        _check = eventually(lambda: that(time.monotonic() - _start, 'elapsed') >= 0.1,
                            within=2, every=0.02)
        assert _check.ok and time.monotonic() - _start < 1.5

    def test_a_run_records_one_judgement_not_every_read(self, tmp_path):
        _suite = tmp_path / 'test_replica.py'
        _suite.write_text(textwrap.dedent('''
            import itertools
            from ipandora.core.assertion import assert_all, eventually, that

            reads = itertools.count()

            def test_replica_catches_up():
                assert_all(eventually(lambda: that(next(reads), 'replica.version') >= 3,
                                      within=5, every=0.01))
        '''), encoding='utf-8')
        _result = run(str(_suite), persist=False, quiet=True, baseline='')
        _case = _result.cases[0]
        assert _case.outcome == 'passed', _case.message
        assert len(_case.checks) == 1
        assert _case.checks[0]['claim'] == 'eventually replica.version >= 3 (within 5 s)'
        assert '第 4 次读到成立' in _case.checks[0]['expr']


def test_a_long_error_is_cut_with_its_size(clock):
    _check = eventually(reads(ConnectionError('x' * 500)), within=0)
    assert 'truncated; str of 500' in _check.expr and len(_check.expr) < 400
