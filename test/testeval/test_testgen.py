# -*- coding: utf-8 -*-
"""
@File  : test_testgen.py
@Time  : 2026-11-07

Test-generation tasks (E8): F→P judged on a real toy repository -- a package
with a bug, the official fix as a patch, and tests an agent might write: a
real reproduction, one that passes anyway, one that only fails to import, one
that is flaky, one that fixes the source instead. Each must be judged as the
grading rules say (fresh-repro's PLAN.md, "判分").
"""
import os
import re
import subprocess
import sys
import textwrap

import pytest

from ipandora.core.eval import testgen

SOURCE = '''\
def add(a, b):
    return a - b          # the bug


def parse(text):
    if not text.isdigit():
        raise ValueError('not a number: ' + text)
    return int(text)


def scale(x):
    if x > 10:
        return x * 2
    return x
'''

FIX = '''\
--- a/calc/__init__.py
+++ b/calc/__init__.py
@@ -1,5 +1,5 @@
 def add(a, b):
-    return a - b          # the bug
+    return a + b


 def parse(text):
'''

EXISTING = '''\
from calc import parse


def test_parse():
    assert parse('3') == 3


def test_scale_unchanged():
    from calc import scale
    assert scale(1) == 1
'''

CMD = '{} -m pytest -q {{test_files}}'.format(sys.executable)


def _git(repo, *args):
    subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _r = tmp_path / 'work'
    (_r / 'calc').mkdir(parents=True)
    (_r / 'calc' / '__init__.py').write_text(SOURCE)
    (_r / 'tests').mkdir()
    (_r / 'tests' / 'test_existing.py').write_text(EXISTING)
    _git(_r, 'init', '-q')
    _git(_r, 'add', '-A')
    _git(_r, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-q', '-m', 'base')
    (tmp_path / 'fix.patch').write_text(FIX)
    return _r


def write(repo, path, text):
    _p = repo / path
    _p.parent.mkdir(parents=True, exist_ok=True)
    _p.write_text(textwrap.dedent(text))


def grade(repo, **kw):
    kw.setdefault('test_cmd', CMD)
    kw.setdefault('max_mutants', 0)
    return testgen.grade(str(repo), str(repo.parent / 'fix.patch'), **kw)


class TestF2P:

    def test_a_real_reproduction(self, repo):
        write(repo, 'tests/test_add.py', '''\
            from calc import add


            def test_add():
                assert add(1, 2) == 3
        ''')
        _r = grade(repo, max_mutants=20)
        assert _r.tests == ['tests/test_add.py::test_add']           # the existing tests are not the agent's
        assert _r.before == {'tests/test_add.py::test_add': 'reproduced'}
        assert _r.f2p and _r.fixed_passes and not _r.flaky and len(_r.after) == 3
        assert _r.before_detail['tests/test_add.py::test_add']['exc'] == 'AssertionError'
        assert [_c.ok for _c in _r.checks()][:5] == [True, True, True, True, True]
        # mutation: only the function the fix touched (add), all its mutants killed
        assert _r.mutation['total'] >= 1 and _r.mutation['tested'] == _r.mutation['killed']
        assert all(_s['line'] == 2 for _s in _r.mutation['survived'])

    def test_a_test_that_passes_before_the_fix_reproduces_nothing(self, repo):
        write(repo, 'tests/test_add.py', '''\
            from calc import add


            def test_add():
                assert add(2, 0) == 2
        ''')
        _r = grade(repo)
        assert _r.before == {'tests/test_add.py::test_add': 'passed'} and not _r.f2p and not _r.weak
        assert '修复前没有一个测试在执行阶段失败' in _r.checks()[0].expr

    @pytest.mark.parametrize('body, exc', [
        ('from calc import subtract\n\ndef test_add():\n    assert subtract(1, 2) == 3\n', 'CollectError'),
        ('def test_add():\n    from calc import subtract\n    assert subtract(1, 2) == 3\n', 'ImportError'),
        ('def test_add():\n    assert add(1, 2) == 3\n', 'NameError'),
        ('def test_add(nonexistent_fixture):\n    assert True\n', 'FixtureLookupError'),
        ('def test_add(:\n    pass\n', 'CollectError'),
    ], ids=['import-at-collection', 'import-in-test', 'name-error', 'missing-fixture', 'syntax-error'])
    def test_weak_reproductions(self, repo, body, exc):
        write(repo, 'tests/test_add.py', body)
        _r = grade(repo)
        assert _r.weak and not _r.f2p and not _r.reproduced
        assert list(_r.before.values()) == ['weak']
        assert [_d['exc'] for _d in _r.before_detail.values()] == [exc]
        assert not _r.checks()[2].ok                                    # 不是弱复现

    def test_an_exception_from_the_code_under_test_is_a_reproduction_and_counted_without_assertions(self, repo):
        write(repo, 'tests/test_parse.py', '''\
            from calc import add, parse


            def test_parse_sum():
                parse(str(add(1, 2)))
        ''')
        _r = grade(repo)
        assert _r.before == {'tests/test_parse.py::test_parse_sum': 'reproduced'}   # ValueError from parse
        assert _r.f2p and _r.zero_assertion == ['tests/test_parse.py::test_parse_sum']
        assert not _r.checks()[4].ok

    def test_a_changed_existing_test_is_the_agents_and_an_unchanged_one_is_not(self, repo):
        write(repo, 'tests/test_existing.py', EXISTING.replace(
            "    assert parse('3') == 3\n", "    from calc import add\n    assert parse('3') == add(1, 2)\n"))
        _r = grade(repo)
        assert _r.tests == ['tests/test_existing.py::test_parse'] and _r.f2p

    def test_changes_outside_the_tests_are_dropped_and_counted(self, repo):
        write(repo, 'calc/__init__.py', SOURCE.replace('return a - b          # the bug', 'return a + b'))
        write(repo, 'notes.txt', 'scratch')
        write(repo, 'tests/test_add.py', '''\
            from calc import add


            def test_add():
                assert add(1, 2) == 3
        ''')
        _r = grade(repo)
        # judged on the original source: the agent's own fix is not what is tested
        assert _r.out_of_scope == ['calc/__init__.py', 'notes.txt'] and _r.f2p
        assert not (repo / 'notes.txt').exists()
        assert not _r.checks()[1].ok and 'calc/__init__.py' in _r.checks()[1].expr

    def test_flaky_after_the_fix(self, repo, tmp_path):
        _counter = tmp_path / 'count'
        write(repo, 'tests/test_add.py', '''\
            import os
            from calc import add

            COUNT = {!r}


            def test_add():
                n = int(open(COUNT).read()) if os.path.exists(COUNT) else 0
                open(COUNT, 'w').write(str(n + 1))
                assert add(1, 2) == 3 and n != 2
        '''.format(str(_counter)))
        _r = grade(repo)
        assert _r.reproduced and _r.flaky and not _r.fixed_passes and not _r.f2p
        assert [list(_run.values())[0] for _run in _r.after] == ['passed', 'failed', 'passed']

    def test_no_tests_and_a_fix_that_does_not_apply(self, repo):
        _r = grade(repo)
        assert _r.tests == [] and not _r.f2p and _r.checks()[0].expr == '没有新增或改动的测试'
        write(repo, 'tests/test_add.py', 'from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n')
        (repo.parent / 'fix.patch').write_text(FIX.replace('return a - b', 'return a * b'))
        _r = grade(repo)
        assert not _r.f2p and _r.error.startswith('the fix does not apply')

    def test_the_record_is_one_json_line(self, repo):
        import json
        write(repo, 'tests/test_add.py', 'from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n')
        _rec = grade(repo, runs=2).record()
        assert json.loads(json.dumps(_rec))['f2p'] is True and len(_rec['after']) == 2
        assert set(_rec) >= {'tests', 'out_of_scope', 'before', 'after', 'asserting', 'mutation', 'f2p', 'weak',
                             'flaky', 'zero_assertion', 'seconds', 'error'}


class TestPieces:

    @pytest.mark.parametrize('path, test', [
        ('tests/test_a.py', True), ('test/helpers.py', True), ('pkg/test_x.py', True), ('pkg/x_test.py', True),
        ('conftest.py', True), ('pkg/conftest.py', True), ('pkg/contest.py', False), ('src/pkg/a.py', False),
        ('pkg/attest.py', False), ('setup.py', False),
    ])
    def test_what_counts_as_a_test_file(self, path, test):
        assert testgen.is_test_file(path) is test

    def test_patched_lines_and_touched_functions(self):
        assert testgen.patched_files(FIX) == {'calc/__init__.py': [2, 2]}
        assert testgen.touched_functions(SOURCE, [2]) == [(1, 2, 'add')]
        assert testgen.touched_functions(SOURCE, [100]) == []

    def test_mutants_stay_inside_the_function_and_include_minus_one(self):
        _m = testgen.mutants_in(SOURCE, 'calc/__init__.py', testgen.touched_functions(SOURCE, [12]))
        assert {_x.line for _x in _m} <= set(range(11, 15))
        assert {'10 → 9', '10 → 11', '> → >=', 'return … → return None'} <= {_x.what for _x in _m}

    def test_assertions_are_read_from_the_source(self, tmp_path):
        (tmp_path / 't.py').write_text(textwrap.dedent('''\
            import pytest


            def test_assert():
                assert 1


            def test_raises():
                with pytest.raises(ValueError):
                    int('x')


            def test_nothing():
                int('1')


            class TestCase:
                def test_method(self):
                    self.assertEqual(1, 1)
        '''))
        assert testgen.asserting(str(tmp_path), ['t.py::test_assert', 't.py::test_raises[1]', 't.py::test_nothing',
                                                 't.py::TestCase::test_method', 't.py::missing']) == {
            't.py::test_assert': True, 't.py::test_raises[1]': True, 't.py::test_nothing': False,
            't.py::TestCase::test_method': True, 't.py::missing': False}


TASK = {'id': 'calc-12', 'repo': 'owner/calc', 'issue': 11, 'base_commit': '1a2b3c4', 'fix_commit': '5d6e7f8',
        'merged_at': '2026-09-14', 'image': 'fresh-repro/calc-12:v1', 'test_cmd': CMD,
        'reference_tests': ['tests/test_add.py::test_add'], 'labels': {'difficulty': 'easy', 'bug_type': 'logic'},
        'split': 'test', 'budget': {'max_usd': 0.5, 'max_minutes': 20}}


def _task_dir(root, fields=None, files=('issue.md', 'fix.patch', 'reference_test.patch'), name='calc-12'):
    import yaml
    _d = root / 'tasks' / name
    _d.mkdir(parents=True)
    (_d / 'task.yaml').write_text(yaml.safe_dump(dict(TASK, **(fields or {}))))
    for _f in files:
        (_d / _f).write_text({'issue.md': 'add(1, 2) returns -1', 'fix.patch': FIX}.get(_f, '--- ref\n'))
    return _d


class TestTaskYaml:

    def test_a_task_as_the_frameworks_task(self, tmp_path):
        _t = testgen.load_task(str(_task_dir(tmp_path)))
        assert (_t.id, _t.input, _t.split, _t.tags) == ('calc-12', 'add(1, 2) returns -1', 'test',
                                                        {'difficulty': 'easy', 'bug_type': 'logic'})
        assert _t.expected == {'f2p': {'fix': 'calc-12/fix.patch', 'test_cmd': CMD,
                                       'reference_tests': ['tests/test_add.py::test_add']}}
        assert _t.initial_state == {'repo': 'owner/calc', 'base_commit': '1a2b3c4', 'image': 'fresh-repro/calc-12:v1'}
        assert _t.meta['budget'] == {'max_usd': 0.5, 'max_minutes': 20} and _t.meta['merged_at'] == '2026-09-14'
        assert _t.budget == {}             # the budget flags a run (over_budget), it does not fail it

    def test_the_dataset_hashes_the_fix_and_the_reference(self, tmp_path):
        _task_dir(tmp_path)
        _d = testgen.load(str(tmp_path / 'tasks'))
        assert [_t.id for _t in _d.tasks] == ['calc-12'] and _d.reference(_d.tasks[0]) == '--- ref\n'
        _before = _d.fingerprint
        (tmp_path / 'tasks' / 'calc-12' / 'fix.patch').write_text(FIX + '\n')
        assert testgen.load(str(tmp_path / 'tasks')).fingerprint != _before

    @pytest.mark.parametrize('fields, error', [
        ({'reference_test': []}, 'unknown: reference_test'),
        ({'issue': '11'}, 'issue must be int'),
        ({'base_commit': 'main'}, 'base_commit must be a commit hash'),
        ({'repo': 'calc'}, 'repo must be owner/name'),
        ({'id': 'other-1'}, 'not the directory name'),
        ({'reference_tests': []}, 'non-empty list of test ids'),
        ({'reference_tests': ['tests/test_add.py']}, 'non-empty list of test ids'),
        ({'split': 'train'}, 'split must be one of'),
        ({'test_cmd': 'pytest -q'}, 'needs {test_files}'),
        ({'budget': {'max_usd': 0.5}}, 'budget is'),
        ({'budget': {'max_usd': -1, 'max_minutes': 20}}, 'budget is'),
        ({'merged_at': 'last week'}, 'merged_at must be a date'),
    ])
    def test_mistakes(self, tmp_path, fields, error):
        with pytest.raises(ValueError, match=re.escape(error)):
            testgen.load_task(str(_task_dir(tmp_path, fields)))

    def test_missing_fields_and_files_are_all_named(self, tmp_path):
        _d = _task_dir(tmp_path, files=('issue.md',))
        _raw = dict(TASK)
        del _raw['image']
        import yaml
        (_d / 'task.yaml').write_text(yaml.safe_dump(_raw))
        with pytest.raises(ValueError) as _e:
            testgen.load_task(str(_d))
        assert 'missing: image' in str(_e.value) and 'fix.patch is missing' in str(_e.value) \
            and 'reference_test.patch is missing' in str(_e.value)

    def test_one_bad_task_names_itself_among_the_rest(self, tmp_path):
        _task_dir(tmp_path)
        _task_dir(tmp_path, {'id': 'calc-13', 'issue': 'x'}, name='calc-13')
        with pytest.raises(ValueError, match=r'1 task\(s\) cannot be read:\n  .*calc-13.*issue must be int'):
            testgen.load(str(tmp_path / 'tasks'))


class TestCommand:

    def test_exit_code_and_json(self, repo, tmp_path, capsys):
        import json
        from test.testeval.test_eval_cr1 import _cli
        write(repo, 'tests/test_add.py', 'from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n')
        _args = dict(workdir=str(repo), fix=str(repo.parent / 'fix.patch'), task=None, base='HEAD', test_cmd=CMD,
                     runs=2, max_mutants=0, timeout=120, json=True)
        assert _cli('f2p', **_args) == 0
        _line = json.loads(capsys.readouterr().out.strip())
        assert _line['f2p'] is True and _line['checks'][0]['name'].startswith('F→P')

    def test_the_task_gives_the_fix_and_the_command_and_a_failure_exits_one(self, repo, tmp_path, capsys):
        from test.testeval.test_eval_cr1 import _cli
        _d = _task_dir(tmp_path)
        write(repo, 'tests/test_add.py', 'from calc import add\n\ndef test_add():\n    assert add(2, 0) == 2\n')
        assert _cli('f2p', workdir=str(repo), fix=None, task=str(_d), base='HEAD', test_cmd=None, runs=1,
                    max_mutants=0, timeout=120, json=False) == 1
        assert 'FAIL  F→P' in capsys.readouterr().out


class TestCr14:
    """Found in code review CR14 (docs/design/reviews/14-CR14.md)."""

    def test_a_name_error_raised_by_the_code_under_test_is_a_reproduction(self, repo):
        write(repo, 'calc/__init__.py', SOURCE.replace('return a - b          # the bug', 'return a + offset'))
        _git(repo, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qam', 'the bug is a misspelt name')
        (repo.parent / 'fix.patch').write_text(FIX.replace('-    return a - b          # the bug',
                                                           '-    return a + offset'))
        write(repo, 'tests/test_add.py', 'from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n')
        _r = grade(repo)
        assert _r.before == {'tests/test_add.py::test_add': 'reproduced'} and _r.f2p
        # the same NameError in the test itself is still weak
        write(repo, 'tests/test_add.py', 'def test_add():\n    assert add(1, 2) == 3\n')
        _git(repo, 'checkout', '-q', '--', 'calc/__init__.py')
        assert grade(repo).weak

    def test_a_test_file_the_agent_deleted_stays_deleted(self, repo):
        (repo / 'tests' / 'test_existing.py').unlink()
        write(repo, 'tests/test_add.py', 'from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n')
        assert grade(repo).f2p and not (repo / 'tests' / 'test_existing.py').exists()

    def test_a_conftest_with_hooks_cannot_make_a_verdict(self, repo):
        write(repo, 'tests/test_add.py', 'def test_add():\n    assert True\n')
        write(repo, 'tests/conftest.py', '''\
            import pytest


            @pytest.hookimpl(trylast=True)
            def pytest_sessionfinish(session):
                pass
        ''')
        _r = grade(repo)
        assert not _r.f2p and _r.tampered and 'tests/conftest.py::pytest_sessionfinish' in _r.error
        assert testgen.failure_reason(_r.checks()) == 'tampering'

    def test_test_code_that_rewrites_the_records_is_caught_by_the_exit_status(self, repo):
        # no hook: the test reaches into the recording plugin itself
        write(repo, 'tests/test_add.py', '''\
            import sys


            def test_add():
                plugin = sys.modules['ipandora_testgen_plugin']
                plugin._ROWS.append({'nodeid': 'tests/test_add.py::test_add', 'when': 'call',
                                     'outcome': 'failed', 'exc': 'AssertionError', 'message': '',
                                     'origin': ''})
        ''')
        _r = grade(repo)
        assert not _r.f2p and _r.error == testgen.INCONSISTENT and _r.tampered

    def test_the_result_path_is_not_in_the_tests_environment(self, repo):
        write(repo, 'tests/test_add.py', '''\
            import os
            from calc import add


            def test_add():
                assert 'IPANDORA_TESTGEN_OUT' not in os.environ
                assert add(1, 2) == 3
        ''')
        assert grade(repo).f2p

    def test_assertions_in_a_helper_of_the_same_file_count(self, repo):
        write(repo, 'tests/test_add.py', '''\
            from calc import add


            def check(value):
                assert value == 3


            def deeper(value):
                check(value)


            def test_add():
                deeper(add(1, 2))
        ''')
        _r = grade(repo)
        assert _r.f2p and _r.zero_assertion == []
