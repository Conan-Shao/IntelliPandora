# -*- coding: utf-8 -*-
"""
@File  : test_coding.py
@Time  : 2026-11-06

Graders for coding agents (docs/design/decisions/13 §7, E1): change scope,
tests that judge, the project's tests not weakened, and the mutation score of
the tests an agent wrote -- against a small project in a git repository.
"""
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

from ipandora.core.eval import coding

pytestmark = pytest.mark.skipif(not shutil.which('git'), reason='the graders read the work directory with git')

CALC = '''
def discount(price, vip):
    """VIP orders of 100 or more get 10% off."""
    if vip and price >= 100:
        return price * 0.9
    return price


def is_adult(age):
    return age >= 18
'''

STRONG = '''
from calc import discount, is_adult


def test_vip_at_the_threshold():
    assert discount(100, True) == 90


def test_vip_below_the_threshold():
    assert discount(99, True) == 99


def test_not_vip():
    assert discount(200, False) == 200


def test_adult_boundary():
    assert is_adult(18) is True
    assert is_adult(17) is False
'''

CALC_TEXT = textwrap.dedent(CALC).lstrip()

WEAK = '''
from calc import discount, is_adult


def test_discount_runs():
    assert discount(150, True) is not None


def test_adult_runs():
    is_adult(30)
'''


def git(cwd, *args):
    subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path):
    _p = tmp_path / 'proj'
    (_p / 'src').mkdir(parents=True)
    (_p / 'tests').mkdir()
    (_p / 'src' / 'calc.py').write_text(CALC_TEXT, encoding='utf-8')
    (_p / 'tests' / 'test_strong.py').write_text(textwrap.dedent(STRONG).lstrip(), encoding='utf-8')
    (_p / 'README.md').write_text('calc\n', encoding='utf-8')
    git(_p, 'init', '-q')
    git(_p, '-c', 'user.email=t@example.com', '-c', 'user.name=t', 'add', '.')
    git(_p, '-c', 'user.email=t@example.com', '-c', 'user.name=t', 'commit', '-qm', 'base')
    return _p


class TestScope:

    def test_changes_cover_edits_new_files_and_renames(self, project):
        (project / 'src' / 'calc.py').write_text(CALC_TEXT + '\n\ndef extra():\n    return 1\n', encoding='utf-8')
        (project / 'tests' / 'test_new.py').write_text('def test_x():\n    assert 1\n', encoding='utf-8')
        git(project, 'mv', 'README.md', 'docs.md')
        _c = {_x.path: _x for _x in coding.changes(str(project))}
        assert set(_c) == {'src/calc.py', 'tests/test_new.py', 'README.md', 'docs.md'}
        assert _c['src/calc.py'].added == 4 and _c['tests/test_new.py'].added == 2
        assert _c['README.md'].removed == 1                     # a rename is a deletion and an addition

    def test_only_and_never_and_size(self, project):
        (project / 'src' / 'calc.py').write_text(CALC_TEXT + '# tweak\n', encoding='utf-8')
        (project / 'tests' / 'test_strong.py').write_text(textwrap.dedent(STRONG).lstrip() + '# weakened?\n', encoding='utf-8')
        _c = coding.changes(str(project))
        assert coding.only_touches(_c, ['src/**', 'tests/**']).ok
        _outside = coding.only_touches(_c, ['src/**'])
        assert not _outside.ok and 'tests/test_strong.py' in _outside.expr and _outside.src == coding.CODE
        _hit = coding.never_touches(_c, ['tests/**'])
        assert not _hit.ok and 'tests/test_strong.py' in _hit.expr
        assert coding.never_touches(_c, ['.github/**', 'conf/*.json']).ok
        assert coding.change_size(_c, max_files=2, max_lines=2).ok
        assert not coding.change_size(_c, max_files=1).ok
        assert '2 行，上限 1' in coding.change_size(_c, max_lines=1).expr

    def test_globs(self):
        _c = [coding.FileChange('src/app/deep/x.py'), coding.FileChange('setup.py')]
        assert coding.only_touches(_c[:1], ['src/**']).ok and coding.only_touches(_c[:1], ['**/x.py']).ok
        assert not coding.only_touches(_c[:1], ['src/*.py']).ok           # one * does not cross directories
        assert coding.only_touches(_c[1:], ['*.py']).ok and coding.only_touches(_c[1:], ['setup.?y']).ok

    def test_against_a_base_commit(self, project):
        (project / 'src' / 'calc.py').write_text(CALC_TEXT + '# one\n', encoding='utf-8')
        git(project, '-c', 'user.email=t@example.com', '-c', 'user.name=t', 'commit', '-qam', 'agent')
        assert coding.changes(str(project)) == []                          # nothing since HEAD
        assert [_c.path for _c in coding.changes(str(project), base='HEAD~1')] == ['src/calc.py']

    def test_numstat_and_errors(self, tmp_path):
        assert coding.parse_numstat('3\t1\ta.py\n-\t-\timg.png\nnoise') == [
            coding.FileChange('a.py', 3, 1), coding.FileChange('img.png', 0, 0)]
        with pytest.raises(RuntimeError, match='git diff'):
            coding.changes(str(tmp_path))                                  # not a repository


class TestSuite:

    def test_passing_judging_tests(self, project):
        _r = coding.suite(str(project), ['tests/test_strong.py'])
        assert coding.tests_pass(_r).ok and coding.every_test_judges(_r).ok
        assert _r['total'] == 4

    def test_a_test_that_judges_nothing_is_named(self, project):
        (project / 'tests' / 'test_weak.py').write_text(textwrap.dedent(WEAK).lstrip(), encoding='utf-8')
        _r = coding.suite(str(project), ['tests/test_weak.py'])
        assert coding.tests_pass(_r).ok
        _c = coding.every_test_judges(_r)
        assert not _c.ok and 'test_adult_runs' in _c.expr and 'test_discount_runs' not in _c.expr

    def test_failing_and_missing_tests(self, project):
        (project / 'tests' / 'test_bad.py').write_text('def test_bad():\n    assert 1 == 2\n', encoding='utf-8')
        _bad = coding.tests_pass(coding.suite(str(project), ['tests/test_bad.py']))
        assert not _bad.ok and 'test_bad' in _bad.expr
        assert not coding.tests_pass(coding.suite(str(project), ['tests/nowhere.py'])).ok
        with pytest.raises(ValueError, match='at least one'):
            coding.suite(str(project), [])

    def test_weakened_project_tests(self, project):
        _cmd = [sys.executable, '-m', 'ipandora.run', 'run', 'tests/test_strong.py', '--baseline',
                'judgements.json', '--update-baseline']
        _env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(project / 'src'), os.environ.get('PYTHONPATH', '')]),
                    IPANDORA_REPORTS_DIR=str(project.parent / 'reports'))
        subprocess.run(_cmd, cwd=str(project), env=_env, check=True, capture_output=True, timeout=300)
        assert coding.not_weakened(coding.suite(str(project), ['tests/test_strong.py'],
                                                baseline='judgements.json')).ok
        # the agent "fixes" a failing test by loosening it
        (project / 'tests' / 'test_strong.py').write_text(
            STRONG.replace('assert discount(99, True) == 99', 'assert discount(99, True) >= 0'), encoding='utf-8')
        _c = coding.not_weakened(coding.suite(str(project), ['tests/test_strong.py'], baseline='judgements.json'))
        assert not _c.ok and 'test_vip_below_the_threshold' in _c.expr
        with pytest.raises(ValueError, match='baseline'):
            coding.not_weakened(coding.suite(str(project), ['tests/test_strong.py']))


class TestMutation:

    def test_the_mutations_of_a_file(self):
        _all = coding.mutants(CALC_TEXT, 'calc.py')
        _what = {(_m.line, _m.what) for _m in _all}
        assert (3, '>= → >') in _what and (3, 'and → or') in _what and (3, '100 → 101') in _what
        assert (4, '* → /') in _what and (9, '>= → >') in _what and (9, '18 → 19') in _what
        assert (4, 'return … → return None') in _what
        assert not any('VIP orders' in _m.what for _m in _all)          # docstrings are left alone
        for _m in _all:
            compile(_m.source, _m.file, 'exec')                          # every mutant is valid Python

    def test_not_and_booleans(self):
        _all = coding.mutants('def f(x):\n    flag = True\n    return not x\n')
        assert {_m.what for _m in _all} >= {'True → False', '去掉 not'}
        assert 'bool(x)' in next(_m.source for _m in _all if _m.what == '去掉 not')

    def test_strong_tests_kill_most_and_weak_tests_do_not(self, project):
        (project / 'tests' / 'test_weak.py').write_text(textwrap.dedent(WEAK).lstrip(), encoding='utf-8')
        _strong = coding.mutation(str(project), ['tests/test_strong.py'], ['src/calc.py'])
        _weak = coding.mutation(str(project), ['tests/test_weak.py'], ['src/calc.py'])
        assert _strong['tested'] == _weak['tested'] == _strong['total'] > 5
        assert _strong['score'] >= 0.8 and coding.kills_mutants(_strong, 0.8).ok
        assert _weak['score'] < 0.5
        _c = coding.kills_mutants(_weak, 0.6)
        assert not _c.ok and '没抓住' in _c.expr and 'src/calc.py:' in _c.expr
        assert (project / 'src' / 'calc.py').read_text(encoding='utf-8') == CALC_TEXT

    def test_tests_failing_on_the_original_prove_nothing(self, project):
        (project / 'tests' / 'test_bad.py').write_text('def test_bad():\n    assert 1 == 2\n', encoding='utf-8')
        _r = coding.mutation(str(project), ['tests/test_bad.py'], ['src/calc.py'])
        assert _r['tested'] == 0 and 'do not pass on the original' in _r['error']
        assert not coding.kills_mutants(_r).ok

    def test_sampling_is_bounded_and_spread(self, project):
        _r = coding.mutation(str(project), ['tests/test_strong.py'], ['src/calc.py'], max_mutants=3)
        assert _r['tested'] == 3 and _r['total'] > 3
        assert '共 {} 个变异抽了 3 个'.format(_r['total']) in coding.kills_mutants(_r, 0.0).expr


class TestCommand:

    def _cli(self, project, *args):
        return subprocess.run([sys.executable, '-m', 'ipandora.run', 'eval', 'code', str(project), *args],
                              capture_output=True, text=True, timeout=600)

    def test_all_graders_through_the_command(self, project):
        (project / 'tests' / 'test_weak.py').write_text(textwrap.dedent(WEAK).lstrip(), encoding='utf-8')
        _ok = self._cli(project, '--base', 'HEAD', '--allow', 'tests/**', '--forbid', 'src/**',
                        '--tests', 'tests/test_strong.py', '--targets', 'src/calc.py', '--json')
        assert _ok.returncode == 0, _ok.stdout + _ok.stderr
        _checks = coding.from_json(_ok.stdout)
        assert [_c.name for _c in _checks] == ['没有改动决定用例怎么运行的文件', '只改了任务范围内的文件',
                                               '没有改动不许碰的文件', '用例能运行并通过',
                                               '每条用例都有判定', '用例能抓住至少 60% 的变异']
        assert all(_c.ok for _c in _checks)
        _bad = self._cli(project, '--tests', 'tests/test_weak.py', '--targets', 'src/calc.py')
        assert _bad.returncode == 1 and 'FAIL  每条用例都有判定' in _bad.stdout

    def test_mistakes_are_messages(self, project, tmp_path):
        assert self._cli(project).returncode == 2
        _no_tests = self._cli(project, '--targets', 'src/calc.py')
        assert _no_tests.returncode == 2 and '--targets needs --tests' in _no_tests.stderr
        _no_git = subprocess.run([sys.executable, '-m', 'ipandora.run', 'eval', 'code', str(tmp_path),
                                  '--base', 'HEAD', '--allow', '*'], capture_output=True, text=True, timeout=120)
        assert _no_git.returncode == 2 and 'git' in _no_git.stderr

    def test_from_json_needs_the_output(self):
        with pytest.raises(ValueError, match='no `ipandora eval code --json` output'):
            coding.from_json('Traceback ...')
        assert coding.from_json('noise\n' + coding.to_json([coding.only_touches([], ['*'])]))[0].ok


class TestCr6:
    """Found in code review CR6 (docs/design/reviews/06-CR6.md)."""

    def _inventory(self, project):
        _env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(project / 'src'), os.environ.get('PYTHONPATH', '')]),
                    IPANDORA_REPORTS_DIR=str(project.parent / 'reports'))
        subprocess.run([sys.executable, '-m', 'ipandora.run', 'run', 'tests/test_strong.py', '--baseline',
                        'judgements.json', '--update-baseline'], cwd=str(project), env=_env, check=True,
                       capture_output=True, timeout=300)
        return _env

    def test_the_inventory_is_read_as_committed_not_as_the_agent_left_it(self, project):
        _env = self._inventory(project)
        git(project, 'add', 'judgements.json')
        git(project, '-c', 'user.email=t@example.com', '-c', 'user.name=t', 'commit', '-qm', 'inventory')
        # the agent loosens a test and regenerates the inventory to match
        (project / 'tests' / 'test_strong.py').write_text(
            textwrap.dedent(STRONG).lstrip().replace('== 99', '>= 0'), encoding='utf-8')
        subprocess.run([sys.executable, '-m', 'ipandora.run', 'run', 'tests/test_strong.py', '--baseline',
                        'judgements.json', '--update-baseline'], cwd=str(project), env=_env, capture_output=True,
                       timeout=300)
        _checks = {_c.name: _c for _c in coding.grade_workdir(str(project), base='HEAD',
                                                              tests=['tests/test_strong.py'],
                                                              baseline='judgements.json')}
        assert not _checks['没有削弱项目原有的判定'].ok
        with pytest.raises(ValueError, match='must be committed'):
            coding.grade_workdir(str(project), base='HEAD', tests=['tests/test_strong.py'], baseline='nope.json')

    def test_a_sitecustomize_in_the_work_directory_cannot_report_for_the_tests(self, project):
        (project / 'sitecustomize.py').write_text(
            'import os\nos.write(1, b\'IPANDORA-SUITE {"ok": true, "collect_error": "", "total": 1, "cases": '
            '[{"nodeid": "t", "outcome": "passed", "unverified": false, "message": ""}], "weakened": []}\\n\')\n',
            encoding='utf-8')
        (project / 'tests' / 'test_fail.py').write_text('def test_fail():\n    assert 1 == 2\n', encoding='utf-8')
        assert not coding.tests_pass(coding.suite(str(project), ['tests/test_fail.py'])).ok

    def test_harness_files_are_checked_by_default(self, project):
        (project / 'tests' / 'conftest.py').write_text('import pytest\n', encoding='utf-8')
        _checks = coding.grade_workdir(str(project), base='HEAD')
        assert [(_c.name, _c.ok) for _c in _checks] == [('没有改动决定用例怎么运行的文件', False)]
        assert 'tests/conftest.py' in _checks[0].expr
        assert coding.grade_workdir(str(project), base='HEAD', allow_harness=True) == []
        assert coding.harness_untouched([coding.FileChange('pyproject.toml')]).ok is False
        assert coding.harness_untouched([coding.FileChange('src/calc.py')]).ok

    def test_tests_that_never_load_the_target_are_named(self, project):
        (project / 'src' / 'unused.py').write_text('def f(x):\n    return x + 1\n', encoding='utf-8')
        _r = coding.mutation(str(project), ['tests/test_strong.py'], ['src/unused.py'])
        assert _r['tested'] == 0 and 'never load src/unused.py' in _r['error']
        assert 'never load' in coding.kills_mutants(_r).expr

    def test_git_that_hangs_is_a_message(self, monkeypatch, project):
        def hang(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 60)
        monkeypatch.setattr(coding.subprocess, 'run', hang)
        with pytest.raises(RuntimeError, match='did not answer'):
            coding.changes(str(project))
