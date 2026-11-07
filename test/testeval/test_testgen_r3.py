# -*- coding: utf-8 -*-
"""
@File  : test_testgen_r3.py
@Time  : 2026-11-07

R3b: what mutation testing of testgen.py found unpinned, in the parts that
run in-process -- the verdict and every check a Result reports, how one
test's failure is classified, when pytest's records are believed, which
hooks are found, what a fix touches and which mutants it yields, what
counts as an assertion, and task.yaml. No pytest subprocess here: those
paths are tested end to end in test_testgen.py.
"""
import datetime
import os
import re
import textwrap

import pytest
import yaml

from ipandora.core.eval import testgen
from ipandora.core.eval.testgen import Result, Run


def fields(check):
    return check.ok, check.name, check.expr, check.src, check.claim


GOOD = dict(tests=['t.py::test_a', 't.py::test_b'], before={'t.py::test_a': 'reproduced', 't.py::test_b': 'passed'},
            after=[{'t.py::test_a': 'passed', 't.py::test_b': 'passed'}] * 3,
            asserting={'t.py::test_a': True, 't.py::test_b': True})


class TestTheVerdict:

    def test_a_reproduction_every_check(self):
        assert [fields(_c) for _c in Result(**GOOD).checks()] == [
            (True, 'F→P：修复前失败、修复后通过', '2 个测试：修复前失败、修复后 3 次全过', 'testgen', 'fail to pass'),
            (True, '没有改测试以外的文件', '只改了测试', 'testgen', 'only test files changed'),
            (True, '不是弱复现', '—', 'testgen', 'not a weak reproduction'),
            (True, '修复后稳定通过', '3 次结果一致', 'testgen', 'not flaky'),
            (True, '每个测试都有断言', '都有', 'testgen', 'tests assert'),
            (True, '写了测试', '2 个新增或改动的测试', 'testgen', 'agent wrote tests'),
            (True, '判分完成', '—', 'testgen', 'grading completed'),
            (True, '测试结果可信', '没有钩子，记录与 pytest 的退出状态一致', 'testgen', 'test results trustworthy')]

    @pytest.mark.parametrize('change, why', [
        ({'tests': [], 'before': {}, 'after': []}, '没有新增或改动的测试'),
        ({'before': {'t.py::test_a': 'passed', 't.py::test_b': 'weak'}},
         '修复前没有一个测试在执行阶段失败（test_a passed、test_b weak）'),
        ({'after': [{'t.py::test_a': 'passed', 't.py::test_b': 'failed'}]}, '修复后不是每次都全部通过（test_b failed）'),
        ({'after': []}, '修复后不是每次都全部通过（无）'),
        ({'error': 'the fix does not apply: x'}, 'the fix does not apply: x'),
    ])
    def test_why_not(self, change, why):
        _c = Result(**dict(GOOD, **change)).checks()[0]
        assert (_c.ok, _c.expr) == (False, why)

    def test_reported_beside_it(self):
        _r = Result(**dict(GOOD, out_of_scope=['a.py', 'b.py', 'c.py', 'd.py', 'e.py', 'f.py'],
                           before={'t.py::test_a': 'weak', 't.py::test_b': 'weak'},
                           after=[{'t.py::test_a': 'passed', 't.py::test_b': 'passed'},
                                  {'t.py::test_a': 'failed', 't.py::test_b': 'passed'}],
                           asserting={'t.py::test_a': False, 't.py::test_b': True}))
        _c = {_x.claim: _x for _x in _r.checks()}
        assert fields(_c['only test files changed'])[:3] == (False, '没有改测试以外的文件', '越界改动（已丢弃）：a.py、b.py、c.py、d.py、e.py')
        assert fields(_c['not a weak reproduction'])[:3] == (False, '不是弱复现', '修复前只因测试本身出错而失败：test_a weak、test_b weak')
        assert fields(_c['not flaky'])[:3] == (False, '修复后稳定通过', '有测试在某次运行中没通过：test_a failed')
        assert fields(_c['tests assert'])[:3] == (False, '每个测试都有断言', '没有断言：t.py::test_a')
        assert _r.zero_assertion == ['t.py::test_a']

    def test_no_tests_assert_nothing_and_an_error_is_shown(self):
        _c = {_x.claim: _x for _x in Result(error='boom').checks()}
        assert (_c['tests assert'].ok, _c['agent wrote tests'].ok, _c['agent wrote tests'].expr) == (
            False, False, '0 个新增或改动的测试')
        assert (_c['grading completed'].ok, _c['grading completed'].expr) == (False, 'boom')
        assert _c['test results trustworthy'].ok         # an error is not tampering

    @pytest.mark.parametrize('error', [testgen.HOOKS_ERROR + 'conftest.py::pytest_runtest_makereport',
                                       testgen.INCONSISTENT])
    def test_tampering(self, error):
        _r = Result(**dict(GOOD, error=error))
        _c = {_x.claim: _x for _x in _r.checks()}
        assert _r.tampered and not _r.f2p
        assert fields(_c['test results trustworthy'])[:3] == (False, '测试结果可信', error)
        assert not Result(error=testgen.INCONSISTENT + ' ').tampered and not Result(error='x' + testgen.HOOKS_ERROR).tampered

    @pytest.mark.parametrize('mutation, ok', [({'score': 0.5, 'killed': 1, 'tested': 2, 'min_score': 0.5}, True),
                                              ({'score': 0.4, 'killed': 2, 'tested': 5, 'min_score': 0.5}, False),
                                              ({'score': 0.0, 'killed': 0, 'tested': 3}, True)])
    def test_the_mutation_check(self, mutation, ok):
        _c = Result(**dict(GOOD, mutation=mutation)).checks()[-1]
        assert fields(_c) == (ok, '杀死修复处的变异', '{killed}/{tested} 个变异被杀死'.format(**mutation), 'testgen',
                              'kills mutants of the fixed functions')

    def test_no_mutation_score_no_check(self):
        assert len(Result(**dict(GOOD, mutation={'score': None, 'killed': 0, 'tested': 0})).checks()) == 8
        assert len(Result(**GOOD).checks()) == 8

    def test_only_f2p_is_required(self):
        assert [(_g.check.claim, _g.required) for _g in Result(**GOOD).graded()][:2] == [
            ('fail to pass', True), ('only test files changed', False)]
        assert sum(_g.required for _g in Result(**GOOD).graded()) == 1

    def test_the_record(self):
        _rec = Result(**GOOD).record()
        assert {_k: _rec[_k] for _k in ('f2p', 'reproduced', 'weak', 'fixed_passes', 'flaky', 'zero_assertion')} == {
            'f2p': True, 'reproduced': True, 'weak': False, 'fixed_passes': True, 'flaky': False, 'zero_assertion': []}
        assert _rec['tests'] == GOOD['tests'] and _rec['error'] == '' and _rec['mutation'] is None

    def test_the_properties(self):
        assert not Result(before={'a': 'reproduced', 'b': 'weak'}).weak             # a reproduction is not weak
        assert Result(before={'a': 'weak', 'b': 'passed'}).weak
        assert not Result(after=[]).fixed_passes and not Result(after=[{'a': 'skipped'}]).fixed_passes
        assert not Result(tests=['a'], after=[{'a': 'passed'}]).flaky
        assert Result(tests=['a'], after=[{'a': 'passed'}, {'a': 'timeout'}]).flaky
        assert not Result(tests=['a'], after=[{'a': 'passed', 'b': 'x'}, {'a': 'passed'}]).flaky   # only its tests
        assert not Result(**dict(GOOD, tests=[])).f2p

    def test_texts_name_four_sorted(self):
        _before = {'t.py::test_{}'.format(_c): 'weak' for _c in 'edcba'}
        assert testgen._before_text(_before) == 'test_a weak、test_b weak、test_c weak、test_d weak'
        assert testgen._before_text({}) == '无' and testgen._after_text([{'a': 'passed'}]) == '无'
        assert testgen._after_text([{'t::x': 'failed'}, {'t::x': 'failed', 't::y': 'error'}]) == 'x failed、y error'


def row(outcome='failed', when='call', exc='AssertionError', origin=''):
    return {'nodeid': 't', 'outcome': outcome, 'when': when, 'exc': exc, 'message': '', 'origin': origin}


class TestClassify:

    @pytest.mark.parametrize('r, verdict', [
        (row('passed'), 'passed'), (row('skipped'), 'passed'),
        (row(), 'reproduced'), (row(exc='ZeroDivisionError'), 'reproduced'),
        (row(when='setup'), 'weak'), (row(when='teardown'), 'weak'),
        (row(exc='FixtureLookupError'), 'weak'), (row(exc='CollectError'), 'weak'),
        (row(exc='ImportError'), 'weak'), (row(exc='NameError'), 'weak'), (row(exc='SyntaxError'), 'weak'),
    ])
    def test_rows(self, r, verdict):
        assert testgen.classify(r) == verdict

    def test_where_a_name_error_came_from(self, tmp_path):
        _w = str(tmp_path)
        _src, _test = os.path.join(_w, 'calc', 'x.py'), os.path.join(_w, 'tests', 'test_x.py')
        assert testgen.classify(row(exc='NameError', origin=_src), _w) == 'reproduced'
        assert testgen.classify(row(exc='NameError', origin=_test), _w) == 'weak'
        assert testgen.classify(row(exc='NameError', origin=os.path.join(os.path.dirname(_w), 'x.py')), _w) == 'weak'
        assert testgen.classify(row(exc='NameError', origin='calc/x.py'), _w) == 'weak'   # not a path it can place
        assert testgen.classify(row(exc='NameError', origin=_src), '') == 'weak'


class TestTheRecords:

    def test_the_decisive_row(self):
        _run = Run(rows=[{'nodeid': 'a', 'when': 'setup', 'outcome': 'passed'},
                         {'nodeid': 'a', 'when': 'call', 'outcome': 'passed'},
                         {'nodeid': 'a', 'when': 'teardown', 'outcome': 'failed'},
                         {'nodeid': 'b', 'when': 'call', 'outcome': 'passed'},
                         {'nodeid': 'c', 'when': 'collect', 'outcome': 'failed'}])
        assert _run.outcome('a')['when'] == 'teardown' and _run.outcome('b')['outcome'] == 'passed'
        assert _run.outcome('c') == {'nodeid': 'c', 'when': '', 'outcome': 'missing', 'exc': '', 'message': 'not run',
                                     'origin': ''}
        assert _run.collect_errors == [{'nodeid': 'c', 'when': 'collect', 'outcome': 'failed'}]

    @pytest.mark.parametrize('rows, returncode, status, collect_only, ok', [
        ([{'when': 'call', 'outcome': 'passed'}], 0, 0, False, True),
        ([{'when': 'call', 'outcome': 'failed'}], 1, 1, False, True),
        ([{'when': 'call', 'outcome': 'failed'}], 0, 0, False, False),        # a failure recorded, exit 0
        ([{'when': 'call', 'outcome': 'passed'}], 1, 1, False, False),        # all passed, exit 1
        ([{'when': 'call', 'outcome': 'passed'}], 0, 1, False, False),        # the process and the plugin disagree
        ([{'when': 'call', 'outcome': 'passed'}], 0, None, False, False),     # the plugin wrote nothing
        ([{'when': 'collect', 'outcome': 'failed'}], 1, 1, False, True),
        ([{'when': 'setup', 'outcome': 'failed'}], 1, 1, False, True),
        ([], 5, 5, False, True), ([], 4, 4, False, True), ([], 0, 0, False, False), ([], 1, 1, False, False),
        ([], 2, 2, True, True), ([], 2, 0, True, False),
    ])
    def test_consistent(self, rows, returncode, status, collect_only, ok):
        assert testgen._consistent(Run(rows=rows, returncode=returncode), status, collect_only) is ok

    def test_the_command(self):
        assert testgen._command('python -m pytest -q {test_files} -x', ['a', 'b']) == [
            'python', '-m', 'pytest', '-q', 'a', 'b', '-x']
        assert testgen._command('pytest -q', ['a']) == ['pytest', '-q', 'a']
        assert testgen._command('', ['a']) == ['python', '-m', 'pytest', '-q', 'a']


class TestHooks:

    def test_every_file_is_read_and_each_hook_named(self, tmp_path):
        (tmp_path / 'notes.md').write_text('def pytest_configure(): pass\n')
        (tmp_path / 'broken.py').write_text('def (:\n')
        (tmp_path / 'conftest.py').write_text(textwrap.dedent('''\
            import pytest

            def pytest_runtest_makereport(item, call):
                pass

            @pytest.hookimpl(tryfirst=True)
            def rewrite(report):
                pass

            async def pytest_sessionfinish(session):
                pass

            def helper():
                pass
        '''))
        # a file that is not Python, or does not parse, does not end the search
        assert testgen.hooks_in(str(tmp_path), ['notes.md', 'broken.py', 'missing.py', 'conftest.py']) == [
            'conftest.py::pytest_runtest_makereport', 'conftest.py::rewrite', 'conftest.py::pytest_sessionfinish']

    def test_a_test_file_without_hooks(self, tmp_path):
        (tmp_path / 'test_a.py').write_text('def test_pytest_like_name():\n    assert 1\n')
        assert testgen.hooks_in(str(tmp_path), ['test_a.py']) == []


NESTED = '''\
def outer(x=3):
    def inner(y):
        return y + 1
    return inner(x) * 2


def last(z):
    return z - 1
'''


class TestTheFix:

    def test_patched_lines(self):
        _patch = textwrap.dedent('''\
            --- a/a.py\t2026-01-01
            +++ b/a.py\t2026-01-02
            @@ -3,4 +3,4 @@
             one
            -two
            +TWO
             three

            @@ -20 +20,2 @@
            +x
            +y
            --- a/gone.py
            +++ /dev/null
            @@ -1,2 +0,0 @@
            -a
            -b
            --- /dev/null
            +++ b/new.py
            @@ -0,0 +1 @@
            +n
            \\ No newline at end of file
        ''')
        assert testgen.patched_files(_patch) == {'a.py': [4, 4, 20, 21], 'new.py': [1]}

    def test_the_innermost_function(self):
        assert testgen.touched_functions(NESTED, [3]) == [(2, 3, 'inner')]
        assert testgen.touched_functions(NESTED, [4, 8]) == [(1, 4, 'outer'), (7, 8, 'last')]
        assert testgen.touched_functions(NESTED, [1, 2, 3]) == [(1, 4, 'outer'), (2, 3, 'inner')]
        assert testgen.touched_functions('def (:', [1]) == []

    def test_mutants_on_the_first_and_last_line_are_inside(self):
        _first = testgen.mutants_in(NESTED, 'n.py', [(1, 4, 'outer')])
        assert '3 → 2' in {_m.what for _m in _first if _m.line == 1}
        assert all(1 <= _m.line <= 4 for _m in _first) and all(_m.file == 'n.py' for _m in _first)
        _last = testgen.mutants_in(NESTED, 'n.py', [(7, 8, 'last')])
        assert {_m.line for _m in _last} == {8} and '1 → 0' in {_m.what for _m in _last}
        assert _last == sorted(_last, key=lambda _m: (_m.line, _m.what))
        _minus = next(_m for _m in _last if _m.what == '1 → 0')
        assert 'return z - 0' in _minus.source and 'return z - 1' not in _minus.source
        assert testgen.mutants_in('def (:', 'x.py', [(1, 1, 'x')]) == []


class TestAssertions:

    def test_what_counts(self, tmp_path):
        (tmp_path / 't.py').write_text(textwrap.dedent('''\
            import pytest
            from pytest import raises, warns


            def test_raises_imported():
                with raises(ValueError):
                    int('x')


            def test_warns():
                with warns(UserWarning):
                    pass


            def test_deprecated():
                with pytest.deprecated_call():
                    pass


            def test_fail():
                pytest.fail('no')


            def test_assert_helper_name():
                assert_called(1)


            def test_calls_something():
                print(1)
        '''))
        _ids = ['t.py::test_raises_imported', 't.py::test_warns', 't.py::test_deprecated', 't.py::test_fail',
                't.py::test_assert_helper_name', 't.py::test_calls_something']
        assert testgen.asserting(str(tmp_path), _ids) == dict(zip(_ids, [True] * 5 + [False]))

    def test_through_helpers_and_never_forever(self, tmp_path):
        (tmp_path / 't.py').write_text(textwrap.dedent('''\
            def check(x):
                assert x


            def via(x):
                check(x)


            def ping(x):
                pong(x)


            def pong(x):
                ping(x)


            def test_two_steps():
                via(1)


            def test_a_cycle_that_asserts_nothing():
                ping(1)


            class TestC:
                def test_method_helper(self):
                    via(1)
        '''))
        assert testgen.asserting(str(tmp_path), ['t.py::test_two_steps', 't.py::test_a_cycle_that_asserts_nothing',
                                                 't.py::TestC::test_method_helper', 't.py::TestC::nope',
                                                 't.py::nope::deeper']) == {
            't.py::test_two_steps': True, 't.py::test_a_cycle_that_asserts_nothing': False,
            't.py::TestC::test_method_helper': True, 't.py::TestC::nope': False, 't.py::nope::deeper': False}

    def test_a_file_that_does_not_parse_or_is_missing(self, tmp_path):
        (tmp_path / 'bad.py').write_text('def test_x(:\n')
        assert testgen.asserting(str(tmp_path), ['bad.py::test_x', 'none.py::test_y']) == {
            'bad.py::test_x': False, 'none.py::test_y': False}

    def test_function_sources_and_names(self):
        _s = testgen._function_sources('class TestA:\n    def test_b(self): pass\n\ndef test_c(): pass\n')
        assert sorted(_s) == ['TestA::test_b', 'test_c'] and 'lineno' not in _s['test_c']
        assert testgen._function_sources('def (:') == {}
        assert testgen._function_of('tests/t.py::TestA::test_b[1-x]') == ('tests/t.py', 'TestA::test_b')


TASK = {'id': 'calc-12', 'repo': 'owner/calc', 'issue': 11, 'base_commit': '1a2b3c4', 'fix_commit': '5d6e7f8',
        'merged_at': '2026-09-14', 'image': 'img:v1', 'test_cmd': 'pytest -q {test_files}',
        'reference_tests': ['tests/test_add.py::test_add'], 'labels': {'difficulty': 'easy', 3: 'x'},
        'split': 'test', 'budget': {'max_usd': 0.5, 'max_minutes': 20}}


def task_dir(root, fields=None, name='calc-12', raw=None):
    _d = root / name
    _d.mkdir(parents=True)
    (_d / 'task.yaml').write_text(raw if raw is not None else yaml.safe_dump(dict(TASK, **(fields or {}))))
    for _f in testgen.TASK_FILES:
        (_d / _f).write_text('x')
    return _d


class TestTaskYaml:

    def test_meta_tags_and_root(self, tmp_path):
        _t = testgen.load_task(str(task_dir(tmp_path)) + os.sep)
        assert _t.meta == {'issue': 11, 'fix_commit': '5d6e7f8', 'merged_at': '2026-09-14',
                           'budget': {'max_usd': 0.5, 'max_minutes': 20}, 'repo': 'owner/calc'}
        assert _t.tags == {'difficulty': 'easy', '3': 'x'} and _t.reference == 'calc-12/reference_test.patch'
        assert _t.root == str(tmp_path)

    @pytest.mark.parametrize('merged_at', [datetime.date(2026, 9, 14), datetime.datetime(2026, 9, 14, 8, 30),
                                           '2026-09-14T08:30:00Z'])
    def test_merged_at_as_a_date_or_a_time(self, tmp_path, merged_at):
        assert testgen.load_task(str(task_dir(tmp_path, {'merged_at': merged_at}))).meta['merged_at'] == '2026-09-14'

    @pytest.mark.parametrize('fields, error', [
        ({'merged_at': 20260914}, 'merged_at must be a date'),
        ({'issue': True}, 'issue must be int, got True'),
        ({'labels': ['a']}, "labels must be dict, got ['a']"),
        ({'fix_commit': 'HEAD'}, 'fix_commit must be a commit hash'),
        ({'budget': {'max_usd': 0, 'max_minutes': 20}}, 'both positive'),
        ({'budget': {'max_usd': True, 'max_minutes': 20}}, 'both positive'),
        ({'budget': {'max_usd': 1, 'max_minutes': 20, 'x': 1}}, 'both positive'),
        ({'budget': 5}, 'budget must be dict, got 5'),
    ])
    def test_mistakes(self, tmp_path, fields, error):
        with pytest.raises(ValueError, match=re.escape(error)):
            testgen.load_task(str(task_dir(tmp_path, fields)))

    def test_every_problem_is_named_and_the_directory_with_a_trailing_slash(self, tmp_path):
        _d = task_dir(tmp_path, {'id': 'other', 'issue': 'x', 'image': 1, 'split': 'nope'})
        with pytest.raises(ValueError) as _e:
            testgen.load_task(str(_d) + os.sep)
        _msg = str(_e.value)
        assert _msg.startswith(os.path.join(str(_d) + os.sep, 'task.yaml') + ': ')
        for _p in ("issue must be int, got 'x'", 'image must be str, got 1', 'split must be one of',
                   "id 'other' is not the directory name 'calc-12'"):
            assert _p in _msg, _p

    @pytest.mark.parametrize('raw, error', [('- a\n- b\n', 'a mapping of fields'), ('a: [\n', 'not valid YAML')])
    def test_a_file_that_is_not_a_task(self, tmp_path, raw, error):
        with pytest.raises(ValueError, match=error):
            testgen.load_task(str(task_dir(tmp_path, raw=raw)))

    def test_no_file(self, tmp_path):
        with pytest.raises(ValueError, match='^cannot read .*task.yaml: '):
            testgen.load_task(str(tmp_path))

    def test_the_dataset(self, tmp_path):
        task_dir(tmp_path / 'tasks')
        (tmp_path / 'tasks' / 'notes').mkdir()
        _d = testgen.load(str(tmp_path / 'tasks'), name='fresh', version='v2')
        assert (_d.name, _d.version, [_t.id for _t in _d.tasks]) == ('fresh', 'v2', ['calc-12'])
        assert _d.path == os.path.join(str(tmp_path / 'tasks'), '.dataset')
        _default = testgen.load(str(tmp_path / 'tasks'))
        assert (_default.name, _default.version) == ('tasks', '')
        with pytest.raises(ValueError, match='^no such directory: '):
            testgen.load(str(tmp_path / 'nowhere'))
        with pytest.raises(ValueError, match='no task directories'):
            testgen.load(str(tmp_path / 'tasks' / 'notes'))


class TestReadingBack:

    def test_from_json_takes_the_last_json_line(self):
        _text = 'noise\n{"checks": [{"name": "old", "ok": false}]}\n{"checks": [{"name": "F→P", "ok": 1, ' \
                '"expr": "e", "claim": "fail to pass"}, {"name": "n", "ok": 0}]}\n'
        assert [fields(_c) for _c in testgen.from_json(_text)] == [
            (True, 'F→P', 'e', 'testgen', 'fail to pass'), (False, 'n', '', 'testgen', '')]
        assert testgen.from_json('{"x": 1}') == []
        with pytest.raises(ValueError, match='not the output of `ipandora eval f2p --json`: no json'):
            testgen.from_json('no json')
        with pytest.raises(ValueError, match='not the output'):
            testgen.from_json(None)

    def test_by_claim_reads_checks_and_dicts(self):
        _check = Result(**GOOD).checks()[0]
        assert testgen._by_claim([_check, {'claim': 'x', 'ok': 0}, {'claim': 'y'}]) == {
            'fail to pass': True, 'x': False, 'y': False}
