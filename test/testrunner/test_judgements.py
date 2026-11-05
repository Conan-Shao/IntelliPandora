# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_judgements.py
@Time  : 2026-11-05

What a pass actually verified: recording judgements pytest does not hand
over, calling out passes that judged nothing, and noticing when the suite
judges less than its baseline.
"""
import json
import textwrap

import pytest

from ipandora.core.runner import inventory, run
from ipandora.core.runner.inventory import (ADDED, CHANGED, DELETED, LOOSENED, NEW_CASE,
                                            NOW_EXCLUDED, NOW_SKIPPED, REMOVED, TIGHTENED,
                                            UNVERIFIED, Finding, classify, parse)
from ipandora.core.runner.result import CaseResult, RunResult


def suite(tmp_path, body, name='test_suite_under_test.py'):
    _file = tmp_path / name
    _file.write_text(textwrap.dedent(body), encoding='utf-8')
    return str(_file)


def claims(case):
    return [(_c['claim'], _c['ok']) for _c in case.checks]


def by_name(result):
    return {_c.name: _c for _c in result.cases}


@pytest.fixture(autouse=True)
def no_project_baseline(monkeypatch, tmp_path):
    # keep any conf/judgements.json in the developer's cwd out of these runs
    monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'no-conf'))


class TestPlainPytestIsRecorded:
    """A suite written with bare asserts still gets a judgement inventory."""

    BODY = '''
        import warnings
        import pytest

        def helper(v):
            assert v > 0

        def test_plain():
            r = {'fee': 50}
            assert r['fee'] <= 100
            helper(r['fee'])

        def test_raises_block():
            with pytest.raises(ZeroDivisionError):
                1 / 0

        def test_raises_call():
            pytest.raises(KeyError, {}.__getitem__, 'x')

        def test_warns():
            with pytest.warns(UserWarning, match='careful'):
                warnings.warn('careful', UserWarning)

        def test_bare_failure():
            assert 150 <= 100

        def test_did_not_raise():
            with pytest.raises(ValueError):
                pass
    '''

    def test_passing_asserts_with_their_source(self, tmp_path):
        cases = by_name(run(suite(tmp_path, self.BODY), persist=False, quiet=True))
        assert claims(cases['test_plain']) == [("assert r['fee'] <= 100", True),
                                               ('assert v > 0', True)]
        assert cases['test_plain'].checks[0]['expr'] == '50 <= 100'
        assert cases['test_plain'].checks[0]['src'] == 'assert'

    def test_raises_and_warns(self, tmp_path):
        cases = by_name(run(suite(tmp_path, self.BODY), persist=False, quiet=True))
        assert claims(cases['test_raises_block']) == [('raises ZeroDivisionError', True)]
        assert claims(cases['test_raises_call']) == [('raises KeyError', True)]
        assert claims(cases['test_warns']) == [("warns UserWarning match 'careful'", True)]

    def test_a_failed_bare_assert_is_a_failed_judgement(self, tmp_path):
        cases = by_name(run(suite(tmp_path, self.BODY), persist=False, quiet=True))
        failed = cases['test_bare_failure'].checks
        assert len(failed) == 1 and failed[0]['ok'] is False
        assert '150 <= 100' in failed[0]['expr']

    def test_raises_that_did_not_raise_records_nothing_passed(self, tmp_path):
        cases = by_name(run(suite(tmp_path, self.BODY), persist=False, quiet=True))
        assert cases['test_did_not_raise'].outcome == 'failed'
        assert not any(_c['ok'] for _c in cases['test_did_not_raise'].checks)

    def test_pytest_raises_is_restored_after_the_run(self, tmp_path):
        _before = pytest.raises
        run(suite(tmp_path, self.BODY), persist=False, quiet=True)
        assert pytest.raises is _before

    def test_a_stale_bytecode_cache_does_not_hide_asserts(self, tmp_path):
        # plain pytest writes hook-less bytecode into __pycache__ first; the
        # hook is compiled in, so reusing that cache would record nothing
        import subprocess
        import sys
        _path = suite(tmp_path, self.BODY)
        subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', _path],
                       capture_output=True, cwd=str(tmp_path), timeout=120)
        assert list((tmp_path / '__pycache__').glob('*.pyc'))
        cases = by_name(run(_path, persist=False, quiet=True))
        assert claims(cases['test_plain'])

    def test_assert_all_failure_is_not_double_counted(self, tmp_path):
        body = '''
            from ipandora.core.assertion import assert_all, that
            def test_x():
                assert_all(that(3, 'n') > 5)
        '''
        case = run(suite(tmp_path, body), persist=False, quiet=True).cases[0]
        assert [_c['claim'] for _c in case.checks] == ['n > 5']


class TestUnverified:
    BODY = '''
        import unittest
        from ipandora.core.assertion import assert_all, gap

        def test_nothing():
            {}.get('x')

        def test_assert_true():
            assert True

        def test_only_a_gap():
            assert_all(gap('数据库落库', '没查'))

        def test_real():
            assert 1 + 1 == 2

        class TestOld(unittest.TestCase):
            def test_eq(self):
                self.assertEqual(1, 1)
    '''

    def test_passes_that_judge_nothing(self, tmp_path):
        result = run(suite(tmp_path, self.BODY), persist=False, quiet=True)
        assert sorted(_c.name for _c in result.unverified) == ['test_assert_true', 'test_nothing']

    def test_constant_asserts_are_not_judgements(self, tmp_path):
        case = by_name(run(suite(tmp_path, self.BODY), persist=False, quiet=True))['test_assert_true']
        assert case.checks == [] and case.unverified

    def test_a_declared_gap_is_a_statement_not_silence(self, tmp_path):
        assert not by_name(run(suite(tmp_path, self.BODY), persist=False,
                               quiet=True))['test_only_a_gap'].unverified

    def test_unittest_items_are_not_called_unverified(self, tmp_path):
        # assertEqual is not an assert statement; we cannot see it, so say nothing
        case = by_name(run(suite(tmp_path, self.BODY), persist=False, quiet=True))['test_eq']
        assert case.outcome == 'passed' and not case.judgeable and not case.unverified

    def test_still_counted_as_passed_by_pytest_but_named(self, tmp_path):
        result = run(suite(tmp_path, self.BODY), persist=False, quiet=True)
        assert result.ok
        assert '2 unverified' in result.headline()
        summary = result.summary()
        assert summary['totals']['unverified'] == 2
        assert len(summary['unverified']) == 2 and 'gap()' in summary['unverified_hint']

    def test_report_status_and_pass_rate(self, tmp_path):
        from ipandora.core.report import build
        report = build(run(suite(tmp_path, self.BODY), persist=False, quiet=True))
        statuses = {_c.name: _c.status for _c in report.cases}
        assert statuses['test_nothing'] == 'UNVERIFIED'
        assert statuses['test_real'] == 'PASS'
        assert report.totals['unverified'] == 2
        # 3 conclusive (real, gap-only, unittest), all passed
        assert report.pass_rate == '100.0%'
        assert all(_c.conclusive is False for _c in report.cases if _c.status == 'UNVERIFIED')

    def test_junit_writes_it_as_skipped_with_the_real_type(self, tmp_path):
        from ipandora.core.report import build
        from ipandora.core.report.junit import to_junit
        xml = to_junit(build(run(suite(tmp_path, self.BODY), persist=False, quiet=True)))
        assert xml.count('type="unverified"') == 2


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------

def case(nodeid, outcome='passed', claims_=(), message=''):
    return CaseResult(nodeid=nodeid, outcome=outcome, message=message,
                      checks=[{'name': _c, 'claim': _c, 'ok': True, 'kind': 'assert'}
                              for _c in claims_])


def result_of(*cases, selector='tests', deselected=()):
    return RunResult(run_id='r', selector=selector, cases=list(cases),
                     deselected=list(deselected))


def base_of(*cases, selector='tests', deselected=()):
    return inventory.build(result_of(*cases, selector=selector, deselected=deselected))


def kinds(findings):
    return sorted((_f.kind, _f.case) for _f in findings)


class TestParse:
    @pytest.mark.parametrize('claim,expected', [
        ('data.fee <= 100', ('data.fee', '<=', '100')),
        ("assert r['fee'] <= 100", ("r['fee']", '<=', '100')),
        ('data.items[*].price > 0', ('data.items[*].price', '>', '0')),
        ("data.status in ['ok']", ('data.status', 'in', "['ok']")),
        ("data.status not in ['x']", ('data.status', 'not in', "['x']")),
        ('status is 2xx', ('status', 'is', '2xx')),
        ('body conforms to schema ab12', ('body', 'conforms to schema', 'ab12')),
        ('raises KeyError', ('raises KeyError', '', '')),
    ])
    def test_parse(self, claim, expected):
        assert parse(claim) == expected


class TestClassify:
    @pytest.mark.parametrize('old,new,expected', [
        ('x <= 100', 'x <= 1000', LOOSENED),
        ('x <= 1000', 'x <= 100', TIGHTENED),
        ('x < 100', 'x <= 100', LOOSENED),
        ('x <= 100', 'x < 100', TIGHTENED),
        ('x > 0', 'x > -1', LOOSENED),
        ('x >= 0', 'x > 0', TIGHTENED),
        ('x > 0', 'x >= 0', LOOSENED),
        ("x <= Decimal('100')", "x <= Decimal('150.5')", LOOSENED),
        ('x == 100', 'x == 200', CHANGED),
        ('x <= 100', 'x >= 100', CHANGED),
        ("x == 'paid'", "x == 'pending'", CHANGED),
    ])
    def test_classify(self, old, new, expected):
        assert classify(old, new) == expected


class TestCompare:
    def test_nothing_changed(self):
        base = base_of(case('t::a', claims_=['x <= 100']))
        assert inventory.compare(base, result_of(case('t::a', claims_=['x <= 100']))) == []

    def test_no_baseline(self):
        assert inventory.compare(None, result_of(case('t::a'))) == []

    def test_removed_loosened_changed_added(self):
        base = base_of(case('t::a', claims_=['x <= 100', 'y > 0', "s == 'paid'", 'raises E']))
        now = result_of(case('t::a', claims_=['x <= 1000', "s == 'pending'", 'raises E', 'z exists']))
        found = {(_f.kind, _f.before, _f.after) for _f in inventory.compare(base, now)}
        assert found == {(LOOSENED, 'x <= 100', 'x <= 1000'),
                         (REMOVED, 'y > 0', ''),
                         (CHANGED, "s == 'paid'", "s == 'pending'"),
                         (ADDED, '', 'z exists')}

    def test_case_level_changes(self):
        base = base_of(case('t::skipped', claims_=['a > 0']),
                       case('t::excluded', claims_=['b > 0']),
                       case('t::empty', claims_=['c > 0']),
                       case('t::gone', claims_=['d > 0']))
        now = result_of(case('t::skipped', 'skipped', message='环境不稳定'),
                        case('t::empty'),
                        case('t::brand_new', claims_=['e > 0']),
                        case('t::new_and_empty'),
                        deselected=['t::excluded'])
        assert kinds(inventory.compare(base, now)) == sorted([
            (NOW_SKIPPED, 'skipped'), (NOW_EXCLUDED, 'excluded'), (UNVERIFIED, 'empty'),
            (DELETED, 'gone'), (NEW_CASE, 'brand_new'), (UNVERIFIED, 'new_and_empty')])

    def test_skip_reason_is_carried(self):
        base = base_of(case('t::a', claims_=['a > 0']))
        found = inventory.compare(base, result_of(case('t::a', 'skipped', message='环境不稳定')))
        assert found[0].note == '环境不稳定'

    def test_a_failing_case_is_not_compared(self):
        # it stopped part-way; what it did not reach is not "removed"
        base = base_of(case('t::a', claims_=['a > 0', 'b > 0']))
        assert inventory.compare(base, result_of(case('t::a', 'failed', claims_=['a > 0']))) == []

    def test_a_narrower_run_does_not_report_the_rest_as_deleted(self):
        base = base_of(case('t::a', claims_=['a > 0']), case('t::b', claims_=['b > 0']))
        now = result_of(case('t::a', claims_=['a > 0']), selector='t::a')
        assert inventory.compare(base, now) == []

    def test_an_accepted_unverified_case_is_not_reported_again(self):
        base = base_of(case('t::a'))
        assert inventory.compare(base, result_of(case('t::a'))) == []

    def test_previously_skipped_case_cannot_weaken(self):
        base = base_of(case('t::a', 'skipped'))
        assert inventory.compare(base, result_of(case('t::a', claims_=['a > 0']))) == []

    def test_weakening_is_listed_first(self):
        base = base_of(case('t::a', claims_=['x <= 100']))
        now = result_of(case('t::a', claims_=['x <= 50', 'y > 0']), case('t::b', claims_=['q']))
        findings = inventory.compare(base, now)
        assert [_f.weakening for _f in findings] == sorted(
            [_f.weakening for _f in findings], reverse=True)

    def test_gating_kinds(self):
        gating = {_k for _k in (REMOVED, LOOSENED, CHANGED, NOW_SKIPPED, NOW_EXCLUDED,
                                UNVERIFIED, DELETED)}
        assert gating == set(inventory.WEAKENING)
        assert not Finding(TIGHTENED, 'x').weakening and not Finding(ADDED, 'x').weakening

    def test_line_is_readable(self):
        line = Finding(LOOSENED, 'tests/t.py::test_fee', 'x <= 100', 'x <= 1000').line()
        assert line == '~ 放宽  test_fee  x <= 100 → x <= 1000'


class TestBaselineFile:
    def test_round_trip_is_stable_and_reviewable(self, tmp_path):
        inv = base_of(case('t::b', claims_=['z > 0', 'a > 0']), case('t::a', claims_=['m']))
        path = inventory.save(str(tmp_path / 'conf' / 'judgements.json'), inv)
        text = open(path, encoding='utf-8').read()
        assert inventory.load(path) == inv
        assert text.index('t::a') < text.index('t::b')          # sorted for diffs
        assert json.loads(text)['cases']['t::b']['claims'] == ['a > 0', 'z > 0']

    def test_missing_file_is_none(self, tmp_path):
        assert inventory.load(str(tmp_path / 'nope.json')) is None

    def test_not_an_inventory(self, tmp_path):
        _f = tmp_path / 'j.json'
        _f.write_text('[1, 2]', encoding='utf-8')
        with pytest.raises(ValueError):
            inventory.load(str(_f))

    def test_update_keeps_what_this_run_could_not_speak_for(self):
        old = base_of(case('t::a', claims_=['a > 0']), case('t::b', claims_=['b > 0']),
                      case('t::c', claims_=['c > 0']))
        now = result_of(case('t::a', claims_=['a > 1']), case('t::b', 'failed'))
        new = inventory.updated(old, now)
        assert new['cases']['t::a']['claims'] == ['a > 1']       # accepted
        assert new['cases']['t::b']['claims'] == ['b > 0']       # failed: kept
        assert 't::c' not in new['cases']                        # same scope, gone

    def test_update_from_a_narrower_run_keeps_the_rest(self):
        old = base_of(case('t::a', claims_=['a > 0']), case('t::b', claims_=['b > 0']))
        new = inventory.updated(old, result_of(case('t::a', claims_=['a > 1']), selector='t::a'))
        assert set(new['cases']) == {'t::a', 't::b'} and new['selector'] == 'tests'


class TestRunComparesWithTheBaseline:
    BEFORE = '''
        def test_fee():
            fee = 50
            assert fee <= 100
            assert fee >= 0
    '''
    AFTER = '''
        def test_fee():
            fee = 50
            assert fee <= 1000
    '''

    def project(self, tmp_path, monkeypatch, body):
        (tmp_path / 'conf').mkdir(exist_ok=True)
        monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'conf'))
        return suite(tmp_path, body, 'test_fee_suite.py')

    def test_default_baseline_is_used_when_present(self, tmp_path, monkeypatch):
        path = self.project(tmp_path, monkeypatch, self.BEFORE)
        inventory.save(inventory.default_path(), inventory.build(run(path, persist=False, quiet=True)))
        suite(tmp_path, self.AFTER, 'test_fee_suite.py')
        result = run(path, persist=False, quiet=True)
        assert result.ok                                        # weaker is not failing
        assert result.baseline == inventory.default_path()
        assert {_c['kind'] for _c in result.weakened} == {LOOSENED, REMOVED}
        summary = result.summary()
        assert summary['judgements_weakened'] is True and '--update-baseline' in summary['judgement_hint']

    def test_empty_string_turns_it_off(self, tmp_path, monkeypatch):
        path = self.project(tmp_path, monkeypatch, self.BEFORE)
        inventory.save(inventory.default_path(), inventory.build(run(path, persist=False, quiet=True)))
        suite(tmp_path, self.AFTER, 'test_fee_suite.py')
        result = run(path, persist=False, quiet=True, baseline='')
        assert result.baseline == '' and result.judgement_changes == []

    def test_unreadable_baseline_is_not_silence(self, tmp_path, monkeypatch):
        path = self.project(tmp_path, monkeypatch, self.BEFORE)
        (tmp_path / 'conf' / 'judgements.json').write_text('{broken', encoding='utf-8')
        result = run(path, persist=False, quiet=True)
        assert result.weakened and '无法读取' in result.weakened[0]['note']

    def test_changes_survive_the_run_store(self, tmp_path, monkeypatch):
        from ipandora.core.runner import store
        path = self.project(tmp_path, monkeypatch, self.BEFORE)
        inventory.save(inventory.default_path(), inventory.build(run(path, persist=False, quiet=True)))
        suite(tmp_path, self.AFTER, 'test_fee_suite.py')
        result = run(path, quiet=True)
        again = store.load(result.run_id)
        assert again.judgement_changes == result.judgement_changes
        assert again.baseline == result.baseline

    def test_report_shows_them(self, tmp_path, monkeypatch):
        from ipandora.core.report import build
        from ipandora.core.report.junit import to_junit
        from ipandora.core.report.render import to_html
        path = self.project(tmp_path, monkeypatch, self.BEFORE)
        inventory.save(inventory.default_path(), inventory.build(run(path, persist=False, quiet=True)))
        suite(tmp_path, self.AFTER, 'test_fee_suite.py')
        report = build(run(path, persist=False, quiet=True))
        html = to_html(report)
        assert '判定变化' in html and 'fee &lt;= 1000' in html and 'PASS · 判定变弱' in html
        assert report.to_dict()['weakened'] == 2
        assert 'name="ipandora.judgements.weakened" value="2"' in to_junit(report)


class TestEditsBetweenRunsAreSeen:
    """
    The MCP server calls run() many times in one process. Test modules used
    to stay imported, so a file edited between runs kept running its first
    version -- an agent fixing a test got its old result back.
    """

    def test_an_edited_test_file_is_reimported(self, tmp_path):
        path = suite(tmp_path, 'def test_x():\n    assert 1 == 1\n', 'test_edited.py')
        assert run(path, persist=False, quiet=True).ok
        suite(tmp_path, 'def test_x():\n    assert 1 == 2\n', 'test_edited.py')
        assert not run(path, persist=False, quiet=True).ok

    def test_an_edited_helper_module_is_reimported(self, tmp_path):
        (tmp_path / 'helpers_for_edit.py').write_text('LIMIT = 100\n', encoding='utf-8')
        path = suite(tmp_path, '''
            import sys, os
            sys.path.insert(0, os.path.dirname(__file__))
            from helpers_for_edit import LIMIT
            def test_x():
                assert 50 <= LIMIT
        ''', 'test_helper_user.py')
        assert run(path, persist=False, quiet=True).ok
        (tmp_path / 'helpers_for_edit.py').write_text('LIMIT = 10\n', encoding='utf-8')
        assert not run(path, persist=False, quiet=True).ok

    def test_the_framework_itself_is_not_reimported(self, tmp_path):
        import sys
        from ipandora.core.assertion import check
        run(suite(tmp_path, 'def test_x():\n    assert 1 == 1\n', 'test_keep.py'),
            persist=False, quiet=True)
        assert sys.modules['ipandora.core.assertion.check'] is check


class TestRecordingEdges:
    def test_raises_with_the_wrong_exception_records_no_pass(self, tmp_path):
        body = '''
            import pytest
            def test_wrong():
                with pytest.raises(ValueError):
                    raise KeyError('k')
        '''
        case = run(suite(tmp_path, body), persist=False, quiet=True).cases[0]
        assert case.outcome == 'failed'
        assert not any(_c['ok'] for _c in case.checks), case.checks

    def test_forgetting_spares_the_framework_even_under_the_rootdir(self, tmp_path):
        # A project that vendors or develops the framework has ipandora under
        # its rootdir. Dropping it would split class identities between runs.
        import os
        import sys
        import types
        import ipandora
        from ipandora.core.runner.api import _forget_project_modules
        before = set(sys.modules)
        framework = types.ModuleType('zz_fake_framework_mod')
        framework.__file__ = os.path.join(os.path.dirname(ipandora.__file__), 'zz_fake.py')
        project = types.ModuleType('zz_fake_project_mod')
        project.__file__ = os.path.join(os.path.dirname(os.path.dirname(ipandora.__file__)),
                                        'zz_project_helper.py')
        sys.modules.update({'zz_fake_framework_mod': framework, 'zz_fake_project_mod': project})
        try:
            _forget_project_modules(before, os.path.dirname(os.path.dirname(ipandora.__file__)))
            assert 'zz_fake_framework_mod' in sys.modules
            assert 'zz_fake_project_mod' not in sys.modules
        finally:
            sys.modules.pop('zz_fake_framework_mod', None)
            sys.modules.pop('zz_fake_project_mod', None)
