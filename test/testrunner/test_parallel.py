# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_parallel.py
@Time  : 2026-11-05

Parallel runs give the same answer as serial ones.

Before M2a, `-n 4` lost every judgement: they were recorded in the xdist
workers into a collector that only existed in the main process, and every
case came back unverified. Faster and wrong is worse than slow. So the first
thing pinned here is sameness -- the inventory, case by case and byte for
byte -- and only then speed, environment, resources and timeouts.

Acceptance criteria from docs/design/decisions/14 §1, each one a test below.
"""
import json
import os
import subprocess
import sys
import textwrap
import time

import pytest

from ipandora.core.runner import api, inventory, plugin, run
from ipandora.core.triage import rules, triage

pytest.importorskip('xdist', reason='parallel runs need the `parallel` extra')


def suite(tmp_path, body, name='test_parallel_suite.py'):
    _file = tmp_path / name
    _file.write_text(textwrap.dedent(body), encoding='utf-8')
    return str(_file)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    # no developer conf/judgements.json; locks of this test only
    monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'no-conf'))
    monkeypatch.setenv(plugin.LOCK_DIR_VAR, str(tmp_path / 'locks'))


def run_both(target, **kwargs):
    kwargs.setdefault('persist', False)
    kwargs.setdefault('quiet', True)
    kwargs.setdefault('baseline', '')
    return run(target, **kwargs), run(target, workers=4, **kwargs)


def comparable(result):
    """Everything a report, the JSON and the inventory are built from, minus timing."""
    return {
        'cases': [{'nodeid': _c.nodeid, 'outcome': _c.outcome, 'message': _c.message,
                   'checks': _c.checks, 'exchanges': _c.exchanges, 'dims': _c.dims,
                   'flaky': _c.flaky, 'title': _c.title, 'judgeable': _c.judgeable,
                   'unverified': _c.unverified}
                  for _c in result.cases],
        'coverage': result.coverage,
        'deselected': result.deselected,
        'narrowed': result.narrowed,
        'collect_error': result.collect_error,
    }


MIXED = '''
    import warnings
    import pytest
    from ipandora.core.assertion.check import Check
    from ipandora.core.assertion.collector import assert_all
    from ipandora.core.assertion.field import that
    from ipandora.core.evidence import recorder
    from ipandora.core.evidence.recorder import Exchange

    COVERAGE = [{'role': ['admin', 'guest'], 'channel': ['web']}]

    def helper(v):
        assert v > 0

    @pytest.mark.dims(role='admin', channel='web')
    def test_plain_assert():
        """bare asserts, one inside a helper"""
        r = {'fee': 50}
        assert r['fee'] <= 100
        helper(r['fee'])

    def test_raises_and_warns():
        with pytest.raises(ZeroDivisionError):
            1 / 0
        with pytest.warns(UserWarning):
            warnings.warn('w', UserWarning)

    def test_checks_and_that():
        assert_all(Check(name='fee ok', ok=True, expr='fee=1', claim='fee <= 100'),
                   that(3, 'count') > 2)

    def test_judges_nothing():
        x = 1 + 1

    def test_literal_assert_is_not_a_judgement():
        assert True

    @pytest.mark.flaky(reason='upstream sandbox drops one call in fifty')
    def test_flaky():
        assert 2 * 2 == 4

    def test_fails():
        y = 1
        assert y == 2

    def test_skips():
        pytest.skip('no data in this env')

    def test_setup_error(no_such_fixture):
        pass

    class Opaque:
        def __repr__(self):
            return '<opaque>'

    def test_evidence_with_a_body_no_serialiser_knows():
        recorder.add_exchange(Exchange(method='GET', url='http://x/', status=200,
                                       response_body={'obj': Opaque(), 'n': 1}))
        assert 1 < 2

    @pytest.mark.parametrize('n', [1, 2, 3])
    def test_param(n):
        assert n > 0
'''


class TestSameAnswer:

    def test_inventory_is_byte_identical_to_serial(self, tmp_path):
        _serial, _parallel = run_both(suite(tmp_path, MIXED))
        _a = json.dumps(inventory.build(_serial), sort_keys=True, ensure_ascii=False)
        _b = json.dumps(inventory.build(_parallel), sort_keys=True, ensure_ascii=False)
        assert _a == _b
        # and the inventory is not trivially empty
        assert sum(len(_c.checks) for _c in _serial.cases) >= 12

    def test_every_case_carries_the_same_evidence_in_the_same_order(self, tmp_path):
        _serial, _parallel = run_both(suite(tmp_path, MIXED))
        assert comparable(_serial) == comparable(_parallel)
        assert [_c.nodeid for _c in _parallel.cases] == [_c.nodeid for _c in _serial.cases]

    def test_zero_judgement_cases_match_serial(self, tmp_path):
        # the exact regression: under `-n 4` every case used to be unverified
        _serial, _parallel = run_both(suite(tmp_path, MIXED))
        _names = sorted(_c.name for _c in _serial.unverified)
        assert _names == ['test_judges_nothing', 'test_literal_assert_is_not_a_judgement']
        assert sorted(_c.name for _c in _parallel.unverified) == _names

    def test_declarations_reach_the_main_process(self, tmp_path):
        _, _parallel = run_both(suite(tmp_path, MIXED))
        _by = {_c.name: _c for _c in _parallel.cases}
        assert _by['test_plain_assert'].dims == {'role': 'admin', 'channel': 'web'}
        assert _by['test_plain_assert'].title == 'bare asserts, one inside a helper'
        assert _by['test_flaky'].flaky == 'upstream sandbox drops one call in fifty'
        assert _parallel.coverage == [{'role': ['admin', 'guest'], 'channel': ['web']}]
        _body = _by['test_evidence_with_a_body_no_serialiser_knows'].exchanges[0]['response_body']
        assert '<opaque>' in json.dumps(_body)

    def test_selector_narrowing_is_seen_in_parallel(self, tmp_path):
        # deselection happens in the workers: without the worker output, a
        # `-k` run in parallel looked like a full run and missing cases like
        # deleted ones
        _serial, _parallel = run_both(suite(tmp_path, MIXED), extra_args=['-k', 'not flaky'])
        assert _serial.narrowed and _parallel.narrowed
        assert _parallel.deselected == _serial.deselected == []

    def test_deselected_cases_are_still_named(self, tmp_path):
        # xdist runs -m in the workers and does not forward pytest_deselected
        _serial, _parallel = run_both(suite(tmp_path, MIXED), exclude_flaky=True)
        assert _parallel.deselected == _serial.deselected
        assert [_n.split('::')[-1] for _n in _parallel.deselected] == ['test_flaky']

    def test_coverage_from_several_modules_is_counted_once_each(self, tmp_path):
        for _i in range(4):
            suite(tmp_path, '''
                COVERAGE = [{{'axis{0}': ['a', 'b']}}]
                def test_a():
                    assert {0} >= 0
                def test_b():
                    assert {0} >= 0
            '''.format(_i), name='test_cov_{}.py'.format(_i))
        _serial, _parallel = run_both(str(tmp_path))
        assert _parallel.coverage == _serial.coverage
        assert len(_parallel.coverage) == 4

    def test_a_collection_error_is_reported_once(self, tmp_path):
        # every worker collects the whole suite, and each may report the
        # same broken module
        suite(tmp_path, 'import no_such_module_anywhere\n', name='test_broken.py')
        suite(tmp_path, 'def test_ok():\n    assert 1 < 2\n', name='test_fine.py')
        _serial, _parallel = run_both(str(tmp_path))
        assert 'no_such_module_anywhere' in _serial.collect_error
        assert _parallel.collect_error == _serial.collect_error


class TestWorkersStartLikeTheMainProcess:

    def test_env_overlay_reaches_every_worker(self, tmp_path, monkeypatch):
        _conf = tmp_path / 'conf'
        _conf.mkdir()
        (_conf / 'staging.yaml').write_text('http:\n  read_timeout: 77\n', encoding='utf-8')
        monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(_conf))
        _out = tmp_path / 'seen'
        _out.mkdir()
        _target = suite(tmp_path, '''
            import os
            import pytest
            from ipandora.core.schedule.runtime import Runtime

            @pytest.mark.parametrize('i', range(8))
            def test_reads(i):
                with open(os.path.join({out!r}, str(i)), 'w') as f:
                    f.write('%s %s' % (Runtime.Http.read_timeout, os.getpid()))
                assert Runtime.Http.read_timeout > 0
        '''.format(out=str(_out)))
        _result = run(_target, env='staging', workers=4, persist=False, quiet=True, baseline='')
        assert _result.ok, _result.summary()
        _seen = [_f.read_text().split() for _f in _out.iterdir()]
        assert {float(_timeout) for _timeout, _ in _seen} == {77.0}
        assert len({_pid for _, _pid in _seen}) > 1      # it really ran in several workers

    def test_bytecode_from_plain_pytest_does_not_hide_asserts_in_workers(self, tmp_path):
        # plain pytest writes __pycache__ with no assertion-pass hook compiled
        # in. A worker that reused it would record nothing.
        _target = suite(tmp_path, '''
            import pytest
            @pytest.mark.parametrize('i', range(4))
            def test_x(i):
                assert i >= 0
        ''')
        subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', _target],
                       check=True, capture_output=True)
        assert any(_f.name.endswith('.pyc') for _f in (tmp_path / '__pycache__').iterdir())
        _result = run(_target, workers=2, persist=False, quiet=True, baseline='')
        assert not _result.unverified
        assert all(_c.checks for _c in _result.cases)


class TestSpeed:

    def test_four_workers_take_at_most_40_percent_of_serial(self, tmp_path):
        # IO-bound, as an API suite is: each case waits on a "response".
        # Worker start-up is a fixed cost: ~0.8s here, 1.3s measured on a
        # GitHub runner. With eight one-second cases that alone put a CI run
        # at 40.2% -- the threshold measured start-up, not parallelism.
        # Sixteen spread it out: ~5.3s against ~16s.
        _target = suite(tmp_path, '''
            import time
            import pytest
            @pytest.mark.parametrize('i', range(16))
            def test_waits(i):
                time.sleep(1.0)
                assert i >= 0
        ''')
        _serial, _parallel = run_both(_target)
        assert _serial.ok and _parallel.ok
        assert _parallel.duration <= 0.4 * _serial.duration, (
            'serial {:.2f}s, 4 workers {:.2f}s'.format(_serial.duration, _parallel.duration))


RESOURCE_SUITE = '''
    import json, os, time
    import pytest

    def _log(name):
        start = time.time()
        time.sleep(0.4)
        with open(os.path.join({out!r}, name), 'w') as f:
            json.dump([start, time.time()], f)

    @pytest.mark.resource('account:vip')
    @pytest.mark.parametrize('i', range(4))
    def test_shared(i):
        _log('shared-%d' % i)
        assert i >= 0

    @pytest.mark.parametrize('i', range(4))
    def test_free(i):
        _log('free-%d' % i)
        assert i >= 0
'''


def _intervals(directory, prefix):
    return sorted(json.loads((directory / _n).read_text())
                  for _n in os.listdir(str(directory)) if _n.startswith(prefix))


def _overlaps(intervals):
    return any(_b[0] < _a[1] for _a, _b in zip(intervals, intervals[1:]))


class TestResources:

    def test_cases_sharing_a_resource_never_overlap(self, tmp_path):
        _out = tmp_path / 'out'
        _out.mkdir()
        _result = run(suite(tmp_path, RESOURCE_SUITE.format(out=str(_out))), workers=4,
                      persist=False, quiet=True, baseline='')
        assert _result.ok, _result.summary()
        assert not _overlaps(_intervals(_out, 'shared-'))
        # the control: without a resource the same cases do run side by side,
        # so the check above is measuring the lock and not a serial run
        assert _overlaps(_intervals(_out, 'free-'))

    def test_two_resources_are_taken_in_one_order_so_nothing_deadlocks(self, tmp_path):
        _target = suite(tmp_path, '''
            import time
            import pytest
            @pytest.mark.resource('b', 'a')
            @pytest.mark.parametrize('i', range(3))
            def test_ba(i):
                time.sleep(0.1)
                assert i >= 0
            @pytest.mark.resource('a')
            @pytest.mark.resource('b')
            @pytest.mark.parametrize('i', range(3))
            def test_ab(i):
                time.sleep(0.1)
                assert i >= 0
        ''')
        _result = run(_target, workers=4, persist=False, quiet=True, baseline='',
                      timeout=60)
        assert _result.ok, _result.summary()

    def test_a_resource_held_elsewhere_is_an_environment_problem(self, tmp_path, monkeypatch):
        monkeypatch.setenv(plugin.RESOURCE_TIMEOUT_VAR, '0.5')
        _target = suite(tmp_path, '''
            import pytest
            @pytest.mark.resource('account:vip')
            def test_needs_it():
                assert 1 < 2
        ''')
        _held = plugin.ResourceLock(plugin.lock_path('account:vip'))
        assert _held.acquire(timeout=1)
        try:
            _result = run(_target, workers=2, persist=False, quiet=True, baseline='')
        finally:
            _held.release()
        _case = _result.cases[0]
        assert _case.outcome == 'error'
        assert plugin.RESOURCE_WAIT_MARKER in _case.message and 'account:vip' in _case.message
        assert triage(_result).findings[0].category == 'environment'


class TestTimeout:

    def test_a_hanging_case_is_cut_off_and_blamed_on_the_environment(self, tmp_path):
        pytest.importorskip('pytest_timeout')
        _target = suite(tmp_path, '''
            import time
            def test_hangs():
                time.sleep(30)
            def test_fine():
                assert 1 < 2
        ''')
        _start = time.perf_counter()
        _result = run(_target, workers=2, timeout=1, persist=False, quiet=True, baseline='')
        assert time.perf_counter() - _start < 20
        _by = {_c.name: _c for _c in _result.cases}
        assert _by['test_hangs'].outcome == 'failed'
        assert _by['test_fine'].outcome == 'passed'
        _finding = {_f.nodeid: _f for _f in triage(_result).findings}[_by['test_hangs'].nodeid]
        assert _finding.category == 'environment'


class TestEntryPoint:

    @pytest.mark.parametrize('value', ['two', -2, '0.5', 'auto4'])
    def test_a_bad_worker_count_is_refused(self, value):
        with pytest.raises(ValueError):
            api._workers_args(value)

    @pytest.mark.parametrize('value', [None, 0, 1, '1', ''])
    def test_one_or_no_worker_is_serial(self, value):
        assert api._workers_args(value) == []

    def test_workers_without_xdist_is_an_error_not_a_quiet_serial_run(self, monkeypatch, tmp_path):
        _real = api.importlib.util.find_spec
        monkeypatch.setattr(api.importlib.util, 'find_spec',
                            lambda name, *a: None if name == 'xdist' else _real(name, *a))
        _target = suite(tmp_path, 'def test_ok():\n    assert 1 < 2\n')
        with pytest.raises(api.MissingExtra, match='intellipandora\\[parallel\\]'):
            run(_target, workers=4, persist=False, quiet=True, baseline='')

    def test_a_users_own_junitxml_does_not_carry_our_evidence(self, tmp_path):
        _target = suite(tmp_path, '''
            def test_ok(record_property):
                record_property('ticket', 'QA-1')
                assert 1 < 2
        ''')
        for _workers in (None, 2):
            _xml = tmp_path / 'junit-{}.xml'.format(_workers)
            run(_target, workers=_workers, persist=False, quiet=True, baseline='',
                extra_args=['--junitxml', str(_xml)])
            _text = _xml.read_text(encoding='utf-8')
            assert plugin.KEY not in _text
            assert 'QA-1' in _text

    def test_a_lock_is_exclusive_and_freed_by_release(self, tmp_path):
        _path = str(tmp_path / 'r.lock')
        _a, _b = plugin.ResourceLock(_path), plugin.ResourceLock(_path)
        assert _a.acquire(timeout=1)
        assert not _b.acquire(timeout=0.2)
        _a.release()
        assert _b.acquire(timeout=1)
        _b.release()

    def test_a_dead_holder_does_not_keep_the_resource(self, tmp_path):
        # the lock belongs to the open file: a worker killed mid-case frees it
        _path = str(tmp_path / 'r.lock')
        _code = ('import sys; sys.path[:0] = {!r}; from ipandora.core.runner.plugin import '
                 'ResourceLock; ResourceLock({!r}).acquire(1); import os; os._exit(0)'
                 ).format(sys.path, _path)
        subprocess.run([sys.executable, '-c', _code], check=True)
        _lock = plugin.ResourceLock(_path)
        assert _lock.acquire(timeout=1)
        _lock.release()

    def test_loading_the_plugin_does_not_warn_in_every_run(self, tmp_path, capsys):
        # pytest warns about a -p module it cannot rewrite because it was
        # imported first; the runner always imports it first
        _target = suite(tmp_path, 'def test_ok():\n    assert 1 < 2\n')
        for _workers in (None, None, 2):
            run(_target, workers=_workers, persist=False, baseline='')
        assert 'PytestAssertRewriteWarning' not in capsys.readouterr().out

    def test_triage_and_the_plugin_agree_on_the_resource_marker(self):
        assert rules.RESOURCE_WAIT_MARKER == plugin.RESOURCE_WAIT_MARKER
