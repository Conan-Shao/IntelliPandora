# -*- coding: utf-8 -*-
"""
@File  : test_bench.py
@Time  : 2026-11-07

scripts/bench_android.py (M5c): the measuring, checking and reporting, with
fake clients and a fake clock. The real run is .github/workflows/android-bench.yml.
"""
import itertools
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))
import bench_android as bench  # noqa: E402

HIERARCHY = '''<hierarchy rotation="0">
  <node package="com.android.settings" text="Settings"/>
  <node package="com.android.settings" text="Network &amp; internet"/>
  <node package="com.android.settings" text="Settings"/>
  <node package="com.android.systemui" text="Battery"/>
</hierarchy>'''


class Clock:
    """Each call advances by the next step (seconds)."""

    def __init__(self, steps):
        self.now, self.steps = 0.0, itertools.cycle(steps)

    def __call__(self):
        self.now += next(self.steps)
        return self.now


def test_percentile_is_nearest_rank():
    assert bench.percentile([5, 1, 4, 2, 3], 90) == 5
    assert bench.percentile(list(range(1, 11)), 90) == 9
    assert bench.percentile(list(range(1, 11)), 50) == 5
    assert bench.percentile([7], 0) == 7
    with pytest.raises(ValueError):
        bench.percentile([], 50)


def test_stats():
    assert bench.stats([1.0, 2.0, 3.0, 10.04]) == {
        'n': 4, 'median': 2.5, 'p90': 10.0, 'mean': 4.0, 'min': 1.0, 'max': 10.0}
    with pytest.raises(ValueError):
        bench.stats([])


def test_timed_measures_milliseconds_and_refuses_a_wrong_answer():
    _ms, _r = bench.timed(lambda: 'ok', lambda r: r == 'ok', clock=Clock([0.25]))
    assert (_ms, _r) == (pytest.approx(250.0), 'ok')
    with pytest.raises(bench.BenchError, match='wrong answer'):
        bench.timed(lambda: 'no', lambda r: r == 'ok', clock=Clock([0.25]))


def test_measure_drops_the_warmup_and_checks_it_too():
    _calls = []
    _samples = bench.measure(lambda: _calls.append(1) or True, bool, reps=4, warmup=2, clock=Clock([0.001]))
    assert len(_calls) == 6 and len(_samples) == 4
    assert _samples == [pytest.approx(1.0)] * 4
    _answers = iter([False, True, True])
    with pytest.raises(bench.BenchError):
        bench.measure(lambda: next(_answers), bool, reps=2, warmup=1)


def test_checks():
    _c = bench.checks('Network & internet')
    assert _c['find (present)']([object()]) and _c['find (present)'](True)
    assert not _c['find (present)']([]) and not _c['find (present)'](False)
    assert _c['find (absent)']([]) and _c['find (absent)'](False)
    assert not _c['find (absent)']([object()]) and not _c['find (absent)'](True)
    assert not _c['find (absent)'](None)
    assert _c['read text']('Network & internet') and not _c['read text']('Network')
    assert _c['hierarchy'](HIERARCHY) and not _c['hierarchy']('<html/>') and not _c['hierarchy'](None)
    assert _c['screenshot'](bench.PNG + b'rest') and not _c['screenshot'](b'\xff\xd8\xff\xe0jpeg')

    class _Image:
        size = (320, 640)

    class _Empty:
        size = (0, 0)
    assert _c['screenshot'](_Image()) and not _c['screenshot'](_Empty()) and not _c['screenshot'](None)


def test_unique_text_skips_repeated_and_foreign_texts():
    assert bench.unique_text(HIERARCHY, 'com.android.settings') == 'Network & internet'
    with pytest.raises(bench.BenchError):
        bench.unique_text(HIERARCHY, 'com.example.none')
    _quoted = '<hierarchy><node package="p" text="say &quot;hi&quot;"/><node package="p" text="ok"/></hierarchy>'
    assert bench.unique_text(_quoted, 'p') == 'ok'


class FakeClient:

    def __init__(self, name, log, fail_on=None, text='Network & internet'):
        self.name, self.log, self.fail_on, self.text = name, log, fail_on, text

    def prepare(self):
        self.log.append((self.name, 'prepare'))

    def start(self):
        self.log.append((self.name, 'start'))

    def discover(self):
        self.log.append((self.name, 'discover'))
        return self.text

    def ops(self, name):
        _right = {'find (present)': [1], 'find (absent)': [], 'read text': name,
                  'hierarchy': '<hierarchy/>', 'screenshot': bench.PNG}
        if self.fail_on:
            _right[self.fail_on] = 'wrong'
        return {_op: (lambda _v=_v: _v) for _op, _v in _right.items()}

    def stop(self):
        self.log.append((self.name, 'stop'))


def test_run_rounds_alternates_and_keeps_the_cold_session_apart():
    _log = []
    _raw, _name = bench.run_rounds([FakeClient('a', _log), FakeClient('b', _log)], rounds=3, reps=2,
                                   warmup=1, clock=Clock([0.002]))
    assert _name == 'Network & internet'
    _starts = [_n for _n, _e in _log if _e == 'start']
    assert _starts == ['a', 'b', 'a', 'b', 'a', 'b']
    assert [_e for _n, _e in _log if _n == 'a'][:3] == ['prepare', 'start', 'discover']
    assert [_e for _n, _e in _log].count('discover') == 1          # one widget for both tools
    for _tool in ('a', 'b'):
        assert _raw[_tool]['session_cold'] == pytest.approx(2.0)
        assert len(_raw[_tool]['session']) == 2                     # rounds 2 and 3
        for _op in bench.OPERATIONS:
            assert len(_raw[_tool][_op]) == 6                       # 3 rounds x 2 reps


def test_run_rounds_stops_the_client_on_a_wrong_answer():
    _log = []
    with pytest.raises(bench.BenchError):
        bench.run_rounds([FakeClient('a', _log, fail_on='hierarchy')], rounds=1, reps=1)
    assert _log[-1] == ('a', 'stop')


def test_run_rounds_refuses_nothing_to_measure():
    with pytest.raises(ValueError):
        bench.run_rounds([FakeClient('a', [])], rounds=0, reps=1)
    with pytest.raises(ValueError):
        bench.run_rounds([FakeClient('a', [])], rounds=1, reps=0)


def test_summarize_and_markdown():
    _raw = {'uiautomator2': {'session_cold': 3000.04, 'session': [900.0, 1100.0],
                             **{_op: [10.0, 20.0, 30.0] for _op in bench.OPERATIONS}},
            'Appium': {'session_cold': 9000.0, 'session': [2000.0, 2200.0],
                       **{_op: [40.0, 50.0, 60.0] for _op in bench.OPERATIONS}}}
    _summary = bench.summarize(_raw)
    assert _summary['uiautomator2']['session_cold'] == 3000.0
    assert _summary['uiautomator2']['session']['median'] == 1000.0
    assert _summary['Appium']['hierarchy'] == {'n': 3, 'median': 50.0, 'p90': 60.0, 'mean': 50.0,
                                               'min': 40.0, 'max': 60.0}
    _md = bench.markdown(_summary, {'device': 'sdk_gphone64_x86_64 (Android 14, API 34)', 'reps': 3,
                                    'warmup': 1, 'rounds': 2})
    assert '| 操作 | uiautomator2 | Appium | Appium / uiautomator2 |' in _md
    assert '| 会话（热） | 1000.0 (1100.0) | 2100.0 (2200.0) | 2.1× |' in _md
    assert '| find (absent) | 20.0 (30.0) | 50.0 (60.0) | 2.5× |' in _md
    assert '| 会话（冷，第一轮） | 3000.0 | 9000.0 | — |' in _md
    assert 'API 34' in _md and '每项每轮 3 次' in _md


def test_markdown_with_one_tool_has_no_ratio_column():
    _summary = bench.summarize({'uiautomator2': {'session_cold': 1.0, 'session': [],
                                                 'hierarchy': [5.0]}})
    _md = bench.markdown(_summary, {'device': 'd', 'reps': 1, 'warmup': 0, 'rounds': 1})
    assert '| 操作 | uiautomator2 |\n' in _md
    assert '| hierarchy | 5.0 (5.0) |' in _md
    assert '| 会话（热） | — |' in _md
