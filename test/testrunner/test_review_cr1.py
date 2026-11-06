# -*- coding: utf-8 -*-
"""
@File  : test_review_cr1.py
@Time  : 2026-11-06

Runner defects found in code review CR1 (docs/design/reviews/01-CR1.md, F1).
Each test fails on the code before the fix.
"""
import os
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest

from ipandora.core import web
from ipandora.core.assertion.check import Check
from ipandora.core.assertion.collector import assert_all, require
from ipandora.core.assertion.wait import eventually
from ipandora.core.concurrency import Outcome, Results, concurrently
from ipandora.core.evidence import recorder
from ipandora.core.evidence.recorder import Exchange
from ipandora.core.runner import inventory, plugin, run
from ipandora.core.runner.collector import ResultCollector
from ipandora.core.runner.result import ERROR, PASSED, CaseResult, RunResult
from ipandora.core.schedule.runtime import Runtime


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'no-conf'))
    monkeypatch.setenv(plugin.LOCK_DIR_VAR, str(tmp_path / 'locks'))
    monkeypatch.setenv(web.MEMORY_VAR, str(tmp_path / 'locators.json'))


def suite(tmp_path, body, name='test_cr1_suite.py'):
    _file = tmp_path / name
    _file.write_text(textwrap.dedent(body), encoding='utf-8')
    return str(_file)


def quiet_run(target, **kwargs):
    kwargs.setdefault('persist', False)
    kwargs.setdefault('quiet', True)
    kwargs.setdefault('baseline', '')
    return run(target, **kwargs)


THREE = '''
    import pytest

    def test_login():
        assert 1 + 1 == 2

    def test_order():
        assert 2 * 2 == 4

    @pytest.mark.smoke
    @pytest.mark.flaky(reason='network')
    def test_flaky_smoke():
        assert 3 == 3

    @pytest.mark.smoke
    def test_smoke():
        assert 4 == 4
'''


class TestSelectorIsNotExclusion:
    """P0 1, 2, 4: `-k` and the user's `-m` are scope, not --exclude-flaky."""

    def test_k_selector_reports_no_weakening_against_full_baseline(self, tmp_path):
        _target = suite(tmp_path, THREE)
        _base = inventory.build(quiet_run(_target))
        _narrow = quiet_run(_target, extra_args=['-k', 'login'])
        assert _narrow.deselected == []
        assert [_f for _f in inventory.compare(_base, _narrow) if _f.weakening] == []

    def test_narrow_update_keeps_other_cases_passed(self, tmp_path):
        _target = suite(tmp_path, THREE)
        _base = inventory.build(quiet_run(_target))
        _after = inventory.updated(_base, quiet_run(_target, extra_args=['-k', 'login']))
        _order = [_n for _n in _after['cases'] if _n.endswith('test_order')][0]
        assert _after['cases'][_order]['state'] == inventory.S_PASSED

    def test_exclude_flaky_keeps_the_users_marker_expression(self, tmp_path):
        _result = quiet_run(suite(tmp_path, THREE), extra_args=['-m', 'smoke'],
                            exclude_flaky=True)
        assert [_c.name for _c in _result.cases] == ['test_smoke']
        assert [_n.rsplit('::', 1)[-1] for _n in _result.deselected] == ['test_flaky_smoke']

    def test_excluded_flaky_case_is_still_a_weakening(self, tmp_path):
        _target = suite(tmp_path, THREE)
        _base = inventory.build(quiet_run(_target))
        _kinds = {(_f.case, _f.kind) for _f in
                  inventory.compare(_base, quiet_run(_target, exclude_flaky=True))}
        assert ('test_flaky_smoke', inventory.NOW_EXCLUDED) in _kinds


class TestBaselineRefusesBrokenRuns:
    """P0 3: a run that did not happen must not overwrite the baseline."""

    def test_collection_error_is_refused(self, tmp_path):
        _good = suite(tmp_path, THREE)
        _base = inventory.build(quiet_run(_good))
        (tmp_path / 'conftest.py').write_text('import does_not_exist_cr1\n', encoding='utf-8')
        _broken = quiet_run(_good)
        assert _broken.collect_error
        with pytest.raises(inventory.NotAcceptable):
            inventory.updated(_base, _broken)

    def test_cli_exits_non_zero_and_leaves_the_file(self, tmp_path, monkeypatch, capsys):
        from argparse import Namespace
        from ipandora.run.commands.run import Command
        _target = suite(tmp_path, THREE)
        _path = tmp_path / 'judgements.json'
        inventory.save(str(_path), inventory.build(quiet_run(_target)))
        _before = _path.read_text(encoding='utf-8')
        (tmp_path / 'conftest.py').write_text('import does_not_exist_cr1\n', encoding='utf-8')
        _options = Namespace(
            selector=_target, env='', title=None, report_dir=str(tmp_path / 'r'),
            no_archive=True, no_report=True, exclude_flaky=False, junit_xml=None,
            baseline=str(_path), compare_with=None, no_baseline=False,
            update_baseline=True, fail_on_weakened=False, workers=None, timeout=None,
            no_store=True, no_ai=True, pytest_arg=[], logger=None)
        _command = Command.__new__(Command)
        with pytest.raises(SystemExit) as _exit:
            _command.handle(_options)
        assert _exit.value.code == 1
        assert _path.read_text(encoding='utf-8') == _before
        assert '没有更新' in capsys.readouterr().out


class TestEventually:
    """P0 11."""

    def test_reads_that_did_not_hold_leave_no_failed_checks(self):
        _reads = {'n': 0}

        def _probe():
            _reads['n'] += 1
            return assert_all(Check(name='paid', ok=_reads['n'] >= 3, expr='status'))

        recorder.begin('case-eventually')
        try:
            _check = eventually(_probe, within=5, every=0.001)
        finally:
            _evidence = recorder.end('case-eventually')
        assert _check.ok
        assert [_c for _c in _evidence.checks if not _c['ok']] == []

    def test_require_inside_the_probe_is_a_read_not_a_skip(self):
        _reads = {'n': 0}

        def _probe():
            _reads['n'] += 1
            require(Check(name='data arrived', ok=_reads['n'] >= 2))
            return Check(name='value', ok=True)

        assert eventually(_probe, within=5, every=0.001).ok
        assert _reads['n'] == 2

    def test_require_never_met_fails_instead_of_skipping(self):
        _check = eventually(lambda: require(Check(name='never', ok=False)),
                            within=0, every=0.001)
        assert not _check.ok
        assert '前置条件不满足' in _check.expr


def _report(nodeid, when, outcome):
    return SimpleNamespace(nodeid=nodeid, when=when, outcome=outcome, duration=0.0,
                           user_properties=[], longreprtext='', longrepr=None)


class TestCollector:
    def test_case_with_no_call_report_is_not_a_pass(self):
        """P0 12: setup passed, then the process died."""
        _c = ResultCollector()
        _c.pytest_runtest_logreport(_report('t::a', 'setup', 'passed'))
        _c.pytest_runtest_logreport(_report('t::b', 'setup', 'passed'))
        _c.pytest_runtest_logreport(_report('t::b', 'call', 'passed'))
        _c.pytest_runtest_logreport(_report('t::b', 'teardown', 'passed'))
        _out = {_r.nodeid: _r.outcome for _r in _c.results()}
        assert _out == {'t::a': ERROR, 't::b': PASSED}

    def test_skip_marked_case_keeps_its_declarations(self, tmp_path):
        _result = quiet_run(suite(tmp_path, '''
            import pytest

            def test_first():
                assert 1 == 1

            @pytest.mark.skip(reason='later')
            @pytest.mark.dims(role='admin')
            def test_skipped():
                pass
        '''))
        _skipped = [_c for _c in _result.cases if _c.name == 'test_skipped'][0]
        assert _skipped.dims == {'role': 'admin'}


NESTED = '''
    import pytest
    from ipandora.core.runner import run

    def test_outer(tmp_path):
        _inner = tmp_path / 'test_inner_cr1.py'
        _inner.write_text('def test_i():\\n    assert 1 + 1 == 2\\n')
        _r = run(str(_inner), persist=False, quiet=True, baseline='')
        assert _r.ok
        with pytest.raises(ValueError):
            int('x')
        assert 'after' == 'after' + ''
'''


class TestNestedRun:
    def test_outer_case_still_records_after_an_inner_run(self, tmp_path):
        _result = quiet_run(suite(tmp_path, NESTED))
        _claims = [_c['claim'] for _c in _result.cases[0].checks]
        assert 'raises ValueError' in _claims
        assert any("'after'" in _c for _c in _claims)
        assert pytest.raises.__module__.startswith('_pytest')    # restored at the end

    def test_recorder_nesting_restores_the_outer_case(self):
        recorder.begin('outer')
        recorder.begin('inner')
        recorder.add_checks([Check(name='i', ok=True)])
        assert [_c['name'] for _c in recorder.end('inner').checks] == ['i']
        assert recorder.end('never-began') is None
        recorder.add_checks([Check(name='o', ok=True)])
        assert [_c['name'] for _c in recorder.end('outer').checks] == ['o']


class TestRunRestoresTheProcess:
    def test_coverage_survives_to_dict(self):
        _r = RunResult(run_id='r', coverage=[{'role': ['a', 'b']}])
        assert RunResult.from_dict(_r.to_dict()).coverage == [{'role': ['a', 'b']}]

    def test_env_name_is_set_in_a_serial_run_and_restored(self, tmp_path):
        _before = getattr(Runtime.Option, 'env', '')
        _result = quiet_run(suite(tmp_path, '''
            from ipandora.core.schedule.runtime import Runtime

            def test_env():
                assert Runtime.Option.env == 'staging'
        '''), env='staging')
        assert _result.ok, _result.cases[0].message
        assert getattr(Runtime.Option, 'env', '') == _before

    def test_error_before_pytest_starts_restores_settings(self, tmp_path, monkeypatch):
        _conf = tmp_path / 'conf-env'
        _conf.mkdir()
        (_conf / 'staging.yaml').write_text('cr1_marker: 1\n', encoding='utf-8')
        monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(_conf))
        _settings, _prefix = Runtime.settings, sys.pycache_prefix

        def _boom(*_a, **_k):
            raise RuntimeError('bad web settings')
        monkeypatch.setattr(web, 'pytest_args', _boom)
        with pytest.raises(RuntimeError):
            quiet_run(suite(tmp_path, THREE), env='staging')
        assert Runtime.settings is _settings
        assert sys.pycache_prefix == _prefix

    def test_locator_memory_failure_does_not_fail_the_run(self, tmp_path, monkeypatch):
        def _full_disk(_result):
            raise OSError(28, 'No space left on device')
        monkeypatch.setattr(web, 'remember', _full_disk)
        assert quiet_run(suite(tmp_path, THREE)).ok

    def test_lock_dir_does_not_follow_the_runs_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv(plugin.LOCK_DIR_VAR, raising=False)
        monkeypatch.setenv('IPANDORA_RUNS_DIR', str(tmp_path / 'a' / 'runs'))
        _first = plugin.lock_dir()
        monkeypatch.setenv('IPANDORA_RUNS_DIR', str(tmp_path / 'b' / 'runs'))
        assert plugin.lock_dir() == _first


class TestConcurrency:
    def test_warning_on_no_results_does_not_crash(self):
        assert Results().warning == ''
        assert Results([Outcome(index=0, duration=0.1)]).warning

    def test_timed_out_thread_adds_nothing_to_the_case(self):
        _release = threading.Event()

        def _fast():
            recorder.add_exchange(Exchange(method='GET', url='http://fast'))
            return 'fast'

        def _slow():
            _release.wait(5)
            recorder.add_exchange(Exchange(method='GET', url='http://late'))
            return 'slow'

        recorder.begin('case-burst')
        try:
            _results = concurrently([_fast, _slow], timeout=0.2)
            _release.set()
            time.sleep(0.2)
        finally:
            _evidence = recorder.end('case-burst')
        assert isinstance(_results[1].error, TimeoutError)
        assert [_e['url'] for _e in _evidence.exchanges] == ['http://fast']


class TestClaimPairing:
    def test_bound_pairs_with_the_same_direction(self):
        _findings = inventory._diff_claims('t::a', ['x == 1', 'x >= 0'], ['x >= -5'])
        _kinds = {(_f.kind, _f.before, _f.after) for _f in _findings}
        assert (inventory.LOOSENED, 'x >= 0', 'x >= -5') in _kinds
        assert (inventory.REMOVED, 'x == 1', '') in _kinds
