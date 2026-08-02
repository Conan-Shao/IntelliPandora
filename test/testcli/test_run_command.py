# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_run_command.py
@Time  : 2026-08-02

`ipandora run` is the only way most people will ever produce a report, so it is
worth testing as a command rather than as the library underneath it.

Driven as a subprocess: the command calls sys.exit, and its exit code is the
part CI depends on.
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

PASSING = '''
    def test_ok():
        assert True
'''

FAILING = '''
    from ipandora.core.assertion import assert_all, failed, gap, passed

    def test_ok():
        """一条通过的用例"""
        assert_all(passed('状态正确', 'status = 200', src='api'),
                   gap('余额实际增加', 'balanceOf 未校验', src='onchain'))

    def test_broken():
        """一条失败的用例"""
        assert_all(failed('金额一致', 'got 3, want 5', src='api'))
'''


def write_suite(tmp_path, name, body):
    _file = tmp_path / name
    _file.write_text(textwrap.dedent(body), encoding='utf-8')
    return str(_file)


def ipandora(*args, reports=None, cwd=None):
    _env = dict(os.environ)
    if reports:
        _env['IPANDORA_REPORTS_DIR'] = str(reports)
    return subprocess.run(
        [sys.executable, '-m', 'ipandora.run'] + list(args),
        capture_output=True, text=True, env=_env, cwd=cwd, timeout=180)


@pytest.fixture
def reports(tmp_path):
    return tmp_path / 'reports'


class TestOneCommandProducesAReport:
    def test_a_passing_run_exits_zero_and_writes_html(self, tmp_path, reports):
        suite = write_suite(tmp_path, 'test_p.py', PASSING)
        done = ipandora('run', suite, reports=reports)
        assert done.returncode == 0, done.stderr
        assert (reports / 'index.html').is_file()
        runs = [p for p in reports.iterdir() if p.is_dir()]
        assert len(runs) == 1
        assert (runs[0] / 'report.html').is_file()
        assert (runs[0] / 'report.json').is_file()

    def test_a_failing_run_exits_nonzero(self, tmp_path, reports):
        """CI goes green on red otherwise -- the verdict is the run's, not the
        report's."""
        suite = write_suite(tmp_path, 'test_f.py', FAILING)
        assert ipandora('run', suite, reports=reports).returncode == 1

    def test_the_report_path_is_printed(self, tmp_path, reports):
        suite = write_suite(tmp_path, 'test_p.py', PASSING)
        out = ipandora('run', suite, reports=reports).stdout
        assert 'report.html' in out and 'index.html' in out

    def test_the_summary_names_checks_and_gaps(self, tmp_path, reports):
        suite = write_suite(tmp_path, 'test_f.py', FAILING)
        out = ipandora('run', suite, reports=reports).stdout
        assert '未覆盖' in out and '通过率' in out

    def test_the_html_carries_the_structured_evidence(self, tmp_path, reports):
        suite = write_suite(tmp_path, 'test_f.py', FAILING)
        ipandora('run', suite, reports=reports)
        run_dir = next(p for p in reports.iterdir() if p.is_dir())
        html = (run_dir / 'report.html').read_text(encoding='utf-8')
        # the check names, not just a pytest traceback
        assert '金额一致' in html and 'got 3, want 5' in html
        assert '余额实际增加' in html

    def test_the_json_is_machine_readable(self, tmp_path, reports):
        suite = write_suite(tmp_path, 'test_f.py', FAILING)
        ipandora('run', suite, reports=reports)
        run_dir = next(p for p in reports.iterdir() if p.is_dir())
        data = json.loads((run_dir / 'report.json').read_text(encoding='utf-8'))
        assert data['totals']['failed'] == 1
        assert data['check_totals']['gap'] == 1


class TestHistoryAccumulates:
    def test_two_runs_leave_two_reports(self, tmp_path, reports):
        suite = write_suite(tmp_path, 'test_p.py', PASSING)
        ipandora('run', suite, reports=reports)
        ipandora('run', suite, reports=reports)
        assert len([p for p in reports.iterdir() if p.is_dir()]) == 2
        assert len(json.loads((reports / 'index.json').read_text(encoding='utf-8'))) == 2

    def test_the_index_shows_what_regressed(self, tmp_path, reports):
        suite = write_suite(tmp_path, 'test_same.py', PASSING)
        assert ipandora('run', suite, reports=reports).returncode == 0

        # same file, one case now broken -- this is the question a CI report
        # gets opened to answer
        write_suite(tmp_path, 'test_same.py', '''
            def test_ok():
                assert True

            def test_ok2():
                assert 0
        ''')
        assert ipandora('run', suite, reports=reports).returncode == 1

        newest = json.loads((reports / 'index.json').read_text(encoding='utf-8'))[0]
        assert newest['new_failures'] == ['test_same.py::test_ok2']


class TestFlags:
    def test_no_report_writes_nothing(self, tmp_path, reports):
        suite = write_suite(tmp_path, 'test_p.py', PASSING)
        done = ipandora('run', suite, '--no-report', reports=reports)
        assert done.returncode == 0
        assert not (reports / 'index.html').exists()

    def test_a_selector_that_matches_nothing_is_a_failure(self, tmp_path, reports):
        # the classic silent pass: a typo'd selector used to look like success
        assert ipandora('run', 'no_such_test_xyz', reports=reports).returncode == 1

    def test_report_dir_without_archiving_writes_in_place(self, tmp_path, reports):
        suite = write_suite(tmp_path, 'test_p.py', PASSING)
        flat = tmp_path / 'flat'
        done = ipandora('run', suite, '-d', str(flat), '--no-archive', reports=reports)
        assert done.returncode == 0
        assert (flat / 'report.html').is_file()
        assert not (flat / 'index.json').exists()
