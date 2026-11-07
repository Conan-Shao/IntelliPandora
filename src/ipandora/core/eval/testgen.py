# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : testgen.py
@Time  : 2026-11-07

Test-generation tasks (E8): an agent is given an issue and writes a test that
reproduces it. The judgement is fail-to-pass (F→P), as SWT-bench defines it:
the agent's new or changed tests fail on the code before the fix -- and fail
in the test itself, not in collecting or importing it -- and pass, every time,
with the official fix applied.

    from ipandora.core.eval import testgen

    result = testgen.grade('/work', fix='/task/fix.patch', base='HEAD',
                           test_cmd='pytest -q {test_files}', runs=3)
    result.f2p, result.checks(), result.record()

`ipandora eval f2p /work --fix fix.patch` does the same from the command line,
inside the grading container (exit 0 when F→P holds).

The work directory is changed in place -- the project is installed there in
editable mode, so a copy elsewhere would test the installed code, not the
copy. Give it a disposable copy of the agent's workspace. In order:

1. What the agent changed: test files (under tests/, or test_*.py, *_test.py,
   conftest.py) are its tests; anything else is out of scope -- counted once
   and put back as it was at `base`, never judged.
2. Which tests are its own: collected after its change and not before, or
   whose function changed (pytest --collect-only on both, and the source of
   each function compared). Only those run.
3. Before the fix: at least one must fail while running the test (the `call`
   phase). A collection error, an ImportError, SyntaxError, NameError or a
   missing fixture is a *weak* reproduction: the test is broken, not the code.
4. After the fix (`git apply fix.patch`): all of them pass, `runs` times; a
   test that fails in any run is flaky.
5. F→P = 3 and 4. Reported apart, without changing it: whether each test
   asserts anything (read from its source), and -- when F→P holds -- how many
   mutants of the functions the fix touched the tests kill.
"""
import ast
import json
import os
import re
import shlex
import shutil
# bandit B404: pytest and git, run in the work directory with argument lists, never a shell
import subprocess  # nosec B404
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ipandora.core.assertion.check import Check
from ipandora.core.eval import coding

TESTGEN = 'testgen'
"""Check.src of the judgements this module makes."""

WEAK_EXCEPTIONS = ('ImportError', 'ModuleNotFoundError', 'SyntaxError', 'IndentationError', 'TabError',
                   'NameError', 'FixtureLookupError')
"""A failure with one of these is the test being broken, not the code under test failing."""

DEFAULT_CMD = 'python -m pytest -q {test_files}'

_TEST_FILE = re.compile(r'(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$|conftest\.py$)')


def is_test_file(path: str) -> bool:
    """Under a tests/ (or test/) directory, or named test_*.py, *_test.py, conftest.py."""
    return bool(_TEST_FILE.search(path.replace('\\', '/')))


# -- running pytest ------------------------------------------------------------------------------

_PLUGIN = r'''
import json, os, traceback
import pytest

_ROWS = []
# the path is taken out of the environment as soon as this loads -- before
# any conftest -- so the agent's test code cannot learn where results go
_OUT = os.environ.pop('IPANDORA_TESTGEN_OUT', '')
_COLLECT = os.environ.pop('IPANDORA_TESTGEN_COLLECT', '')


def _origin(excinfo):
    try:
        _tb = excinfo.traceback
        return str(_tb[-1].path) if len(_tb) else ''
    except Exception:
        return ''


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    _outcome = yield
    _rep = _outcome.get_result()
    _exc = call.excinfo
    if _rep.outcome != 'passed' or call.when == 'call':
        _ROWS.append({'nodeid': item.nodeid, 'when': call.when, 'outcome': _rep.outcome,
                      'exc': _exc.typename if _exc is not None else '',
                      'message': str(_exc.value)[:300] if _exc is not None else '',
                      'origin': _origin(_exc) if _exc is not None else ''})


def pytest_collectreport(report):
    if report.failed:
        _ROWS.append({'nodeid': report.nodeid, 'when': 'collect', 'outcome': 'failed', 'exc': 'CollectError',
                      'message': str(report.longrepr)[-300:], 'origin': ''})


def pytest_collection_finish(session):
    if _COLLECT:
        _ROWS.extend({'nodeid': _i.nodeid, 'when': 'collected', 'outcome': '', 'exc': '', 'message': '',
                      'origin': str(_i.path)} for _i in session.items)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    with open(_OUT, 'w', encoding='utf-8') as _f:
        json.dump({'rows': _ROWS, 'exitstatus': int(exitstatus)}, _f)
'''


@dataclass
class Run:
    """One pytest run: each test's outcome, and why it failed."""
    rows: List[Dict[str, Any]] = field(default_factory=list)
    returncode: Optional[int] = None
    output: str = ''
    timed_out: bool = False
    consistent: bool = True
    """Whether the recorded outcomes agree with the exit status pytest itself reported and returned."""

    def outcome(self, nodeid: str) -> Dict[str, Any]:
        """The decisive row of a test: its first failure, else its call."""
        _mine = [_r for _r in self.rows if _r['nodeid'] == nodeid and _r['when'] in ('setup', 'call', 'teardown')]
        return next((_r for _r in _mine if _r['outcome'] == 'failed'), None) or \
            next((_r for _r in _mine if _r['when'] == 'call'), None) or \
            {'nodeid': nodeid, 'when': '', 'outcome': 'missing', 'exc': '', 'message': 'not run', 'origin': ''}

    @property
    def collect_errors(self) -> List[Dict[str, Any]]:
        return [_r for _r in self.rows if _r['when'] == 'collect']


def _consistent(run: 'Run', status: Optional[int], collect_only: bool) -> bool:
    """
    Recorded rows, the status the plugin saw, and the process's exit code
    must tell one story: all passed is exit 0, a failure is exit 1. Test code
    that rewrote what was recorded rarely keeps all three in step.
    """
    if status is None or run.returncode != status:
        return False
    if collect_only:
        return True
    _failed = any(_r['outcome'] == 'failed' for _r in run.rows if _r['when'] in ('setup', 'call', 'teardown', 'collect'))
    _ran = any(_r['when'] == 'call' for _r in run.rows)
    return (status == 1) == _failed if _ran or _failed else status in (4, 5)


def _command(test_cmd: str, targets: Sequence[str]) -> List[str]:
    _cmd = shlex.split(test_cmd or DEFAULT_CMD)
    if '{test_files}' in _cmd:
        _i = _cmd.index('{test_files}')
        _cmd = _cmd[:_i] + list(targets) + _cmd[_i + 1:]
    else:
        _cmd = _cmd + list(targets)
    return _cmd


def pytest_run(workdir: str, targets: Sequence[str], test_cmd: str = DEFAULT_CMD, collect_only: bool = False,
               timeout: float = 600) -> Run:
    """Run pytest on `targets` (node ids or files) in `workdir`, with the recording plugin."""
    _tmp = tempfile.mkdtemp(prefix='ipandora-testgen-')
    try:
        with open(os.path.join(_tmp, 'ipandora_testgen_plugin.py'), 'w', encoding='utf-8') as _f:
            _f.write(_PLUGIN)
        _out = os.path.join(_tmp, 'rows.json')
        _env = dict(os.environ, IPANDORA_TESTGEN_OUT=_out,
                    PYTHONPATH=os.pathsep.join([_tmp] + [_p for _p in os.environ.get('PYTHONPATH', '').split(
                        os.pathsep) if _p]),
                    PYTHONDONTWRITEBYTECODE='1')
        if collect_only:
            _env['IPANDORA_TESTGEN_COLLECT'] = '1'
        _cmd = _command(test_cmd, targets) + ['-p', 'ipandora_testgen_plugin', '-p', 'no:cacheprovider']
        if collect_only:
            _cmd.append('--collect-only')
        try:
            # bandit B603: the task's own test command, split without a shell, in its work directory
            _done = subprocess.run(_cmd, cwd=workdir, env=_env, capture_output=True, text=True,  # nosec B603
                                   timeout=timeout)
        except subprocess.TimeoutExpired:
            return Run(timed_out=True, output='timed out after {:g}s'.format(timeout))
        except OSError as exc:
            raise RuntimeError('cannot run the test command {!r}: {}'.format(' '.join(_cmd[:3]), exc))
        _rows, _status = [], None
        if os.path.isfile(_out):
            with open(_out, encoding='utf-8') as _f:
                _data = json.load(_f)
            _rows, _status = _data.get('rows', []), _data.get('exitstatus')
        _run = Run(rows=_rows, returncode=_done.returncode, output=(_done.stdout + _done.stderr)[-2000:])
        _run.consistent = _consistent(_run, _status, collect_only)
        return _run
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)


# -- what the agent wrote --------------------------------------------------------------------------

def split_changes(workdir: str, base: str = 'HEAD') -> Tuple[List[str], List[str]]:
    """(test files, other files) the agent changed since `base`, untracked files included."""
    _tests, _other = [], []
    for _c in coding.changes(workdir, base):
        (_tests if is_test_file(_c.path) else _other).append(_c.path)
    return _tests, _other


def _tracked_at(workdir: str, base: str, path: str) -> bool:
    try:
        coding._git(workdir, 'cat-file', '-e', '{}:{}'.format(base, path))
        return True
    except RuntimeError:
        return False


def restore(workdir: str, base: str, paths: Iterable[str]) -> None:
    """Put `paths` back as they were at `base`: a file new since then is removed."""
    for _p in paths:
        if _tracked_at(workdir, base, _p):
            coding._git(workdir, 'checkout', base, '--', _p)
        else:
            _full = os.path.join(workdir, _p)
            if os.path.isfile(_full) or os.path.islink(_full):
                os.remove(_full)


def hooks_in(workdir: str, test_files: Sequence[str]) -> List[str]:
    """
    pytest hooks the agent's test files define (`pytest_*` functions, or
    anything decorated with hookimpl). A reproduction test has no business
    changing how pytest runs or reports, and a hook can rewrite any verdict.
    """
    _out = []
    for _f in test_files:
        if not _f.endswith('.py'):
            continue
        try:
            _tree = ast.parse(_read(os.path.join(workdir, _f)))
        except SyntaxError:
            continue
        for _n in ast.walk(_tree):
            if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _hookimpl = any('hookimpl' in ast.dump(_d) for _d in _n.decorator_list)
                if _n.name.startswith('pytest_') or _hookimpl:
                    _out.append('{}::{}'.format(_f, _n.name))
    return _out


def _function_sources(source: str) -> Dict[str, str]:
    """`Class::name` or `name` -> the source of each test function in a file."""
    try:
        _tree = ast.parse(source)
    except SyntaxError:
        return {}
    _out = {}

    def _walk(nodes, prefix):
        for _n in nodes:
            if isinstance(_n, ast.ClassDef):
                _walk(_n.body, prefix + [_n.name])
            elif isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _out['::'.join(prefix + [_n.name])] = ast.dump(_n, include_attributes=False)
    _walk(_tree.body, [])
    return _out


def _function_of(nodeid: str) -> Tuple[str, str]:
    """('tests/test_x.py', 'TestA::test_b') from 'tests/test_x.py::TestA::test_b[1]'."""
    _path, _, _rest = nodeid.partition('::')
    return _path, re.sub(r'\[.*\]$', '', _rest)


def _read(path: str) -> str:
    try:
        with open(path, encoding='utf-8') as _f:
            return _f.read()
    except (OSError, UnicodeDecodeError):
        return ''


# -- the fix -------------------------------------------------------------------------------------

def patched_files(patch: str) -> Dict[str, List[int]]:
    """file -> the lines of the new version a unified diff adds or changes next to (1-based)."""
    _out: Dict[str, List[int]] = {}
    _file, _line = None, 0
    for _l in patch.splitlines():
        if _l.startswith('+++ '):
            _name = _l[4:].strip().split('\t')[0]
            _file = None if _name == '/dev/null' else re.sub(r'^b/', '', _name)
            if _file is not None:
                _out.setdefault(_file, [])
            continue
        _m = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', _l)
        if _m:
            _line = int(_m.group(1))
            continue
        if _file is None or _l.startswith('--- '):
            continue
        if _l.startswith('+'):
            _out[_file].append(_line)
            _line += 1
        elif _l.startswith('-'):
            _out[_file].append(_line)             # a deletion is a change at this place
        elif _l.startswith(' ') or _l == '':
            _line += 1
    return _out


def touched_functions(source: str, lines: Sequence[int]) -> List[Tuple[int, int, str]]:
    """(first line, last line, name) of the innermost functions containing any of `lines`."""
    try:
        _tree = ast.parse(source)
    except SyntaxError:
        return []
    _funcs = [_n for _n in ast.walk(_tree) if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    _out = {}
    for _line in lines:
        _inside = [_f for _f in _funcs if _f.lineno <= _line <= (_f.end_lineno or _f.lineno)]
        if _inside:
            _f = min(_inside, key=lambda _x: (_x.end_lineno or _x.lineno) - _x.lineno)
            _out[(_f.lineno, _f.end_lineno or _f.lineno)] = _f.name
    return sorted((_a, _b, _n) for (_a, _b), _n in _out.items())


def _minus_one(tree, index: int, value: int) -> Optional[str]:
    """The source with the integer constant at `index` one smaller, or None if it cannot be written back."""
    _copy = coding._apply(tree, index, 'int')
    next(_n for _j, _n in enumerate(ast.walk(_copy)) if _j == index).value = value - 1
    try:
        return ast.unparse(_copy)
    except Exception:  # noqa: BLE001 -- a mutant that cannot be written is not made
        return None


def mutants_in(source: str, path: str, spans: Sequence[Tuple[int, int, str]]) -> List[coding.Mutant]:
    """The single-point mutants of `source` inside `spans`, including integer constants minus one."""
    try:
        _tree = ast.parse(source)
    except SyntaxError:
        # a file this Python cannot parse has no mutants -- it must not end the grading of an F→P (R3b)
        return []
    if not spans:
        return []
    _all = coding.mutants(source, path)
    for _index, _node in enumerate(ast.walk(_tree)):
        if isinstance(_node, ast.Constant) and isinstance(_node.value, int) and not isinstance(_node.value, bool):
            _code = _minus_one(_tree, _index, _node.value)
            if _code is not None:
                _all.append(coding.Mutant(path, _node.lineno, '{} → {}'.format(_node.value, _node.value - 1), _code))
    _inside = [_m for _m in _all if any(_a <= _m.line <= _b for _a, _b, _ in spans)]
    _inside.sort(key=lambda _m: (_m.line, _m.what))
    return _inside


# -- the judgement ---------------------------------------------------------------------------------

def _asserts(function_node) -> bool:
    for _n in ast.walk(function_node):
        if isinstance(_n, ast.Assert):
            return True
        if isinstance(_n, ast.Call):
            _f = _n.func
            _name = _f.attr if isinstance(_f, ast.Attribute) else (_f.id if isinstance(_f, ast.Name) else '')
            if _name in ('raises', 'warns', 'deprecated_call', 'fail') or _name.startswith('assert'):
                return True
    return False


def _asserts_through(function_node, helpers: Dict[str, Any], seen=None) -> bool:
    """Asserts itself, or calls a function of the same file that does (transitively)."""
    if _asserts(function_node):
        return True
    _seen = set() if seen is None else seen
    for _n in ast.walk(function_node):
        if isinstance(_n, ast.Call) and isinstance(_n.func, ast.Name) and _n.func.id in helpers \
                and _n.func.id not in _seen:
            _seen.add(_n.func.id)
            if _asserts_through(helpers[_n.func.id], helpers, _seen):
                return True
    return False


def asserting(workdir: str, nodeids: Sequence[str]) -> Dict[str, bool]:
    """
    nodeid -> whether its function asserts anything (assert, pytest.raises /
    warns, self.assert*), itself or through a function of the same file.
    """
    _out = {}
    _cache: Dict[str, Any] = {}
    for _id in nodeids:
        _path, _name = _function_of(_id)
        if _path not in _cache:
            try:
                _cache[_path] = ast.parse(_read(os.path.join(workdir, _path)))
            except SyntaxError:
                _cache[_path] = None
        _tree, _found = _cache[_path], None
        _parts = _name.split('::')
        _nodes = _tree.body if _tree is not None else []
        for _i, _part in enumerate(_parts):
            _hit = next((_n for _n in _nodes if isinstance(_n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                         and _n.name == _part), None)
            if _hit is None:
                break
            if _i == len(_parts) - 1:
                _found = _hit
            _nodes = getattr(_hit, 'body', [])
        _helpers = {_n.name: _n for _n in (_tree.body if _tree is not None else [])
                    if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        _out[_id] = bool(_found is not None and _asserts_through(_found, _helpers))
    return _out


def classify(row: Dict[str, Any], workdir: str = '') -> str:
    """
    'reproduced', 'weak' or 'passed' for one test's decisive row before the
    fix. A failure while running the test reproduces -- unless it is an
    import, syntax or name error *of the test*: the same error raised from
    the code under test (the bug is a misspelt name) is a reproduction.
    """
    if row['outcome'] in ('passed', 'skipped'):
        return 'passed'
    if row['when'] != 'call' or row['exc'] in ('FixtureLookupError', 'CollectError'):
        return 'weak'
    if row['exc'] not in WEAK_EXCEPTIONS:
        return 'reproduced'
    _origin = row.get('origin') or ''
    if workdir and _origin and os.path.isabs(_origin):
        _rel = os.path.relpath(_origin, os.path.abspath(workdir)).replace('\\', '/')
        if not _rel.startswith('../') and not is_test_file(_rel):
            return 'reproduced'
    return 'weak'


@dataclass
class Result:
    tests: List[str] = field(default_factory=list)
    """The agent's new or changed tests: what was run."""
    out_of_scope: List[str] = field(default_factory=list)
    before: Dict[str, str] = field(default_factory=dict)
    """nodeid -> reproduced | weak | passed, on the code before the fix."""
    before_detail: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    after: List[Dict[str, str]] = field(default_factory=list)
    """One mapping nodeid -> outcome per run with the fix."""
    asserting: Dict[str, bool] = field(default_factory=dict)
    mutation: Optional[Dict[str, Any]] = None
    error: str = ''
    """Why grading could not finish: the fix does not apply, the tests cannot be collected..."""
    seconds: float = 0.0

    @property
    def reproduced(self) -> bool:
        return any(_v == 'reproduced' for _v in self.before.values())

    @property
    def weak(self) -> bool:
        """Failed before the fix, but only by being broken -- never in a way the code caused."""
        return not self.reproduced and any(_v == 'weak' for _v in self.before.values())

    @property
    def fixed_passes(self) -> bool:
        return bool(self.after) and all(_o == 'passed' for _run in self.after for _o in _run.values())

    @property
    def flaky(self) -> bool:
        """Some test passed in one run with the fix and not in another."""
        return any(len({_run.get(_t) for _run in self.after}) > 1 for _t in self.tests)

    @property
    def f2p(self) -> bool:
        return not self.error and bool(self.tests) and self.reproduced and self.fixed_passes

    @property
    def tampered(self) -> bool:
        """The agent's tests define pytest hooks, or what was recorded disagrees with pytest's own exit status."""
        return self.error.startswith(HOOKS_ERROR) or self.error == INCONSISTENT

    @property
    def zero_assertion(self) -> List[str]:
        return [_t for _t, _ok in sorted(self.asserting.items()) if not _ok]

    def checks(self) -> List[Check]:
        """F→P as the one required judgement; the rest are reported beside it (see Graded)."""
        _why = self.error or (
            '没有新增或改动的测试' if not self.tests else
            '修复前没有一个测试在执行阶段失败（{}）'.format(_before_text(self.before)) if not self.reproduced else
            '修复后不是每次都全部通过（{}）'.format(_after_text(self.after)) if not self.fixed_passes else
            '{} 个测试：修复前失败、修复后 {} 次全过'.format(len(self.tests), len(self.after)))
        _out = [Check(name='F→P：修复前失败、修复后通过', ok=self.f2p, expr=_why, src=TESTGEN, claim='fail to pass')]
        _out.append(Check(name='没有改测试以外的文件', ok=not self.out_of_scope,
                          expr='越界改动（已丢弃）：{}'.format('、'.join(self.out_of_scope[:5]))
                          if self.out_of_scope else '只改了测试', src=TESTGEN, claim='only test files changed'))
        _out.append(Check(name='不是弱复现', ok=not self.weak,
                          expr='修复前只因测试本身出错而失败：{}'.format(_before_text(self.before))
                          if self.weak else '—', src=TESTGEN, claim='not a weak reproduction'))
        _out.append(Check(name='修复后稳定通过', ok=not self.flaky,
                          expr='有测试在某次运行中没通过：{}'.format(_after_text(self.after)) if self.flaky
                          else '{} 次结果一致'.format(len(self.after)), src=TESTGEN, claim='not flaky'))
        _out.append(Check(name='每个测试都有断言', ok=bool(self.tests) and not self.zero_assertion,
                          expr='没有断言：{}'.format('、'.join(self.zero_assertion[:5])) if self.zero_assertion
                          else '都有', src=TESTGEN, claim='tests assert'))
        _out.append(Check(name='写了测试', ok=bool(self.tests),
                          expr='{} 个新增或改动的测试'.format(len(self.tests)), src=TESTGEN, claim='agent wrote tests'))
        _out.append(Check(name='判分完成', ok=not self.error, expr=self.error or '—', src=TESTGEN,
                          claim='grading completed'))
        _out.append(Check(name='测试结果可信', ok=not self.tampered, src=TESTGEN, claim='test results trustworthy',
                          expr=self.error if self.tampered else '没有钩子，记录与 pytest 的退出状态一致'))
        if self.mutation is not None and self.mutation.get('score') is not None:
            _out.append(Check(name='杀死修复处的变异', ok=self.mutation['score'] >= self.mutation.get('min_score', 0),
                              expr='{killed}/{tested} 个变异被杀死'.format(**self.mutation), src=TESTGEN,
                              claim='kills mutants of the fixed functions'))
        return _out

    def graded(self) -> List[Any]:
        """The checks for a grader: F→P required, every other one reported beside it."""
        from ipandora.core.eval.trial import Graded
        return [Graded(_c, required=_c.claim == 'fail to pass') for _c in self.checks()]

    def record(self) -> Dict[str, Any]:
        """The grading half of one JSON line per run."""
        _out = asdict(self)
        _out.update(f2p=self.f2p, reproduced=self.reproduced, weak=self.weak, fixed_passes=self.fixed_passes,
                    flaky=self.flaky, zero_assertion=self.zero_assertion)
        return _out


def _before_text(before: Dict[str, str]) -> str:
    return '、'.join('{} {}'.format(_t.split('::')[-1], _v) for _t, _v in sorted(before.items())[:4]) or '无'


def _after_text(after: List[Dict[str, str]]) -> str:
    _bad = sorted({'{} {}'.format(_t.split('::')[-1], _o) for _run in after for _t, _o in _run.items()
                   if _o != 'passed'})
    return '、'.join(_bad[:4]) or '无'


COLLECT_ERROR = 'the tests do not collect: '
INCONSISTENT = ('what was recorded does not agree with pytest\'s exit status: the results were tampered with, '
                'or pytest did not run the tests')
HOOKS_ERROR = 'the agent\'s test files define pytest hooks -- its results cannot be trusted: '


def _selected(workdir: str, base: str, test_files: List[str], test_cmd: str, timeout: float) -> Tuple[List[str], str]:
    """The agent's new or changed test ids, and a collection error if its files do not collect."""
    _py = [_f for _f in test_files if _f.endswith('.py') and os.path.isfile(os.path.join(workdir, _f))
           and os.path.basename(_f) != 'conftest.py']
    if not _py:
        return [], ''
    _after = pytest_run(workdir, _py, test_cmd, collect_only=True, timeout=timeout)
    if _after.timed_out:
        return [], 'collecting the tests timed out'
    if _after.collect_errors:
        return _py, COLLECT_ERROR + _after.collect_errors[0]['message'][-200:]
    _now = [_r['nodeid'] for _r in _after.rows if _r['when'] == 'collected']
    # the same files as they were before the agent: what was there already
    _saved = {_f: _read(os.path.join(workdir, _f)) for _f in test_files if os.path.isfile(os.path.join(workdir, _f))}
    _old_sources = {}
    try:
        restore(workdir, base, test_files)
        _existing = [_f for _f in _py if os.path.isfile(os.path.join(workdir, _f))]
        _old_sources = {_f: _function_sources(_read(os.path.join(workdir, _f))) for _f in _existing}
        _was = set()
        if _existing:
            _before = pytest_run(workdir, _existing, test_cmd, collect_only=True, timeout=timeout)
            _was = {_r['nodeid'] for _r in _before.rows if _r['when'] == 'collected'}
    finally:
        for _f in test_files:
            # a file the agent deleted came back with the base version: delete it again
            if _f not in _saved and os.path.isfile(os.path.join(workdir, _f)):
                os.remove(os.path.join(workdir, _f))
        for _f, _text in _saved.items():
            _full = os.path.join(workdir, _f)
            os.makedirs(os.path.dirname(_full) or '.', exist_ok=True)
            with open(_full, 'w', encoding='utf-8') as _out:
                _out.write(_text)
    _new_sources = {_f: _function_sources(_read(os.path.join(workdir, _f))) for _f in _py}
    _picked = []
    for _id in _now:
        _path, _name = _function_of(_id)
        if _id not in _was:
            _picked.append(_id)
        elif _old_sources.get(_path, {}).get(_name) != _new_sources.get(_path, {}).get(_name):
            _picked.append(_id)
    return _picked, ''


def grade(workdir: str, fix: str, base: str = 'HEAD', test_cmd: str = DEFAULT_CMD, runs: int = 3,
          max_mutants: int = 20, min_score: float = 0.0, timeout: float = 600) -> Result:
    """
    Judge the agent's tests in `workdir` (changed in place: give it a copy) by
    F→P against `fix`, a unified diff of the official fix. See the module.
    """
    if runs < 1:
        raise ValueError('runs must be at least 1')
    _start = time.monotonic()
    _r = Result()
    try:
        with open(fix, encoding='utf-8') as _f:
            _patch = _f.read()
    except OSError as exc:
        raise ValueError('cannot read the fix {}: {}'.format(fix, exc))
    _tests, _r.out_of_scope = split_changes(workdir, base)
    # out of scope: counted, then put back -- the code under test is the original
    restore(workdir, base, _r.out_of_scope)
    _hooks = hooks_in(workdir, _tests)
    if _hooks:
        _r.tests = []
        _r.error = HOOKS_ERROR + '、'.join(_hooks[:5])
        _r.seconds = round(time.monotonic() - _start, 3)
        return _r
    _r.tests, _r.error = _selected(workdir, base, _tests, test_cmd, timeout)
    if _r.error.startswith(COLLECT_ERROR):
        # a test that cannot even be collected is a weak reproduction, not a grading failure
        _r.before = {_f: 'weak' for _f in _r.tests}
        _r.before_detail = {_f: {'when': 'collect', 'outcome': 'failed', 'exc': 'CollectError',
                                 'message': _r.error[len(COLLECT_ERROR):]} for _f in _r.tests}
        _r.asserting = {_f: False for _f in _r.tests}
        _r.error = ''
        _r.seconds = round(time.monotonic() - _start, 3)
        return _r
    if _r.error or not _r.tests:
        _r.seconds = round(time.monotonic() - _start, 3)
        return _r
    _r.asserting = asserting(workdir, _r.tests)
    _pre = pytest_run(workdir, _r.tests, test_cmd, timeout=timeout)
    if not _pre.timed_out and not _pre.consistent:
        _r.error = INCONSISTENT
        _r.seconds = round(time.monotonic() - _start, 3)
        return _r
    if _pre.timed_out:
        _r.error = 'the tests timed out before the fix'
        _r.seconds = round(time.monotonic() - _start, 3)
        return _r
    for _t in _r.tests:
        _row = _pre.outcome(_t)
        _r.before[_t] = classify(_row, workdir)
        _r.before_detail[_t] = {_k: _row.get(_k, '') for _k in ('when', 'outcome', 'exc', 'message')}
    _fix_file = os.path.abspath(fix)
    try:
        coding._git(workdir, 'apply', '--whitespace=nowarn', _fix_file)
    except RuntimeError as exc:
        _r.error = 'the fix does not apply: {}'.format(str(exc)[-200:])
        _r.seconds = round(time.monotonic() - _start, 3)
        return _r
    for _ in range(runs):
        _post = pytest_run(workdir, _r.tests, test_cmd, timeout=timeout)
        if not _post.timed_out and not _post.consistent:
            _r.error = INCONSISTENT
            break
        _r.after.append({_t: ('timeout' if _post.timed_out else _post.outcome(_t)['outcome']) for _t in _r.tests})
    if _r.f2p and max_mutants > 0:
        _r.mutation = dict(_mutate(workdir, _patch, _r.tests, test_cmd, max_mutants, timeout), min_score=min_score)
    _r.seconds = round(time.monotonic() - _start, 3)
    return _r


def _mutate(workdir: str, patch: str, tests: List[str], test_cmd: str, max_mutants: int,
            timeout: float) -> Dict[str, Any]:
    """Mutants of the functions the fix touched, at most `max_mutants`; killed when any test does not pass."""
    _all = []
    for _file, _lines in sorted(patched_files(patch).items()):
        if not _file.endswith('.py') or is_test_file(_file):
            continue
        _source = _read(os.path.join(workdir, _file))
        _all += mutants_in(_source, _file, touched_functions(_source, _lines))
    _picked = coding._sample(_all, max_mutants)
    _out = {'total': len(_all), 'tested': 0, 'killed': 0, 'survived': [], 'score': None, 'error': ''}
    if not _picked:
        return _out
    # are the tests loading these files from the work directory at all?
    _first = _picked[0].file
    _path = os.path.join(workdir, _first)
    _original = _read(_path)
    try:
        with open(_path, 'w', encoding='utf-8') as _f:
            _f.write('raise ImportError("ipandora testgen probe: {} was loaded")\n'.format(_first))
        _probe = pytest_run(workdir, tests, test_cmd, timeout=timeout)
    finally:
        with open(_path, 'w', encoding='utf-8') as _f:
            _f.write(_original)
    if all(_probe.outcome(_t)['outcome'] == 'passed' for _t in tests):
        _out['error'] = 'the tests never load {} from the work directory'.format(_first)
        return _out
    for _m in _picked:
        _path = os.path.join(workdir, _m.file)
        _original = _read(_path)
        try:
            with open(_path, 'w', encoding='utf-8') as _f:
                _f.write(_m.source)
            _run = pytest_run(workdir, tests, test_cmd, timeout=timeout)
        finally:
            with open(_path, 'w', encoding='utf-8') as _f:
                _f.write(_original)
        _out['tested'] += 1
        if _run.timed_out or any(_run.outcome(_t)['outcome'] != 'passed' for _t in tests):
            _out['killed'] += 1
        else:
            _out['survived'].append({'file': _m.file, 'line': _m.line, 'what': _m.what})
    _out['score'] = _out['killed'] / _out['tested'] if _out['tested'] else None
    return _out


# -- task.yaml -------------------------------------------------------------------------------------

TASK_FIELDS = {
    'id': str, 'repo': str, 'issue': int, 'base_commit': str, 'fix_commit': str, 'merged_at': None,
    'image': str, 'test_cmd': str, 'reference_tests': list, 'labels': dict, 'split': str, 'budget': dict,
}
"""task.yaml's fields (fresh-repro's PLAN.md, "task.yaml"); all required."""
TASK_FILES = ('issue.md', 'fix.patch', 'reference_test.patch')
"""Files next to task.yaml; a Dockerfile is the image's business."""
_SHA = re.compile(r'^[0-9a-f]{7,40}$')


def load_task(directory: str):
    """
    One test-generation task directory as a framework Task. Raises
    ValueError naming every problem: a missing or misspelt field, a wrong
    type, a missing file.

        id, repo, issue, base_commit, fix_commit, merged_at, image, test_cmd,
        reference_tests, labels, split, budget {max_usd, max_minutes}
    """
    import datetime
    import yaml
    from ipandora.core.eval.dataset import SPLITS, Task
    _yaml = os.path.join(directory, 'task.yaml')
    try:
        with open(_yaml, encoding='utf-8') as _f:
            _raw = yaml.safe_load(_f)
    except OSError as exc:
        raise ValueError('cannot read {}: {}'.format(_yaml, exc.strerror or exc))
    except yaml.YAMLError as exc:
        raise ValueError('{}: not valid YAML: {}'.format(_yaml, exc))
    if not isinstance(_raw, dict):
        raise ValueError('{}: a mapping of fields'.format(_yaml))
    _problems = []
    _missing = [_k for _k in TASK_FIELDS if _k not in _raw]
    _unknown = sorted(set(_raw) - set(TASK_FIELDS))
    if _missing:
        _problems.append('missing: {}'.format(', '.join(_missing)))
    if _unknown:
        _problems.append('unknown: {}'.format(', '.join(_unknown)))
    for _k, _type in TASK_FIELDS.items():
        _v = _raw.get(_k)
        if _k not in _raw or _type is None:
            continue
        if not isinstance(_v, _type) or (_type is int and isinstance(_v, bool)):
            _problems.append('{} must be {}, got {!r}'.format(_k, _type.__name__, _v))
    if isinstance(_raw.get('merged_at'), str):
        try:
            _raw['merged_at'] = datetime.date.fromisoformat(_raw['merged_at'][:10])
        except ValueError:
            _problems.append('merged_at must be a date (2026-09-14)')
    elif 'merged_at' in _raw and not isinstance(_raw['merged_at'], (datetime.date, datetime.datetime)):
        _problems.append('merged_at must be a date (2026-09-14)')
    for _k in ('base_commit', 'fix_commit'):
        if isinstance(_raw.get(_k), str) and not _SHA.match(_raw[_k]):
            _problems.append('{} must be a commit hash'.format(_k))
    if isinstance(_raw.get('repo'), str) and not re.match(r'^[\w.-]+/[\w.-]+$', _raw['repo']):
        _problems.append('repo must be owner/name')
    _dirname = os.path.basename(os.path.normpath(directory))
    if isinstance(_raw.get('id'), str) and _raw['id'] != _dirname:
        # the name compared, also for 'tasks/calc-12/' -- whose basename is '' (R3b)
        _problems.append('id {!r} is not the directory name {!r}'.format(_raw['id'], _dirname))
    if isinstance(_raw.get('reference_tests'), list) and (
            not _raw['reference_tests'] or not all(isinstance(_t, str) and '::' in _t for _t in _raw['reference_tests'])):
        _problems.append('reference_tests is a non-empty list of test ids (tests/test_x.py::test_y)')
    if isinstance(_raw.get('split'), str) and _raw['split'] not in SPLITS:
        _problems.append('split must be one of {}'.format(', '.join(SPLITS)))
    if isinstance(_raw.get('test_cmd'), str) and '{test_files}' not in _raw['test_cmd']:
        _problems.append('test_cmd needs {test_files}, where the tests to run go')
    _budget = _raw.get('budget') if isinstance(_raw.get('budget'), dict) else {}
    if 'budget' in _raw and isinstance(_raw.get('budget'), dict):
        if sorted(_budget) != ['max_minutes', 'max_usd'] or not all(
                isinstance(_v, (int, float)) and not isinstance(_v, bool) and _v > 0 for _v in _budget.values()):
            _problems.append('budget is {max_usd: number, max_minutes: number}, both positive')
    for _name in TASK_FILES:
        if not os.path.isfile(os.path.join(directory, _name)):
            _problems.append('{} is missing'.format(_name))
    if _problems:
        raise ValueError('{}: {}'.format(_yaml, '; '.join(_problems)))
    with open(os.path.join(directory, 'issue.md'), encoding='utf-8') as _f:
        _issue = _f.read()
    _rel = os.path.basename(os.path.normpath(directory))
    _task = Task(
        id=_raw['id'], input=_issue,
        initial_state={'repo': _raw['repo'], 'base_commit': _raw['base_commit'], 'image': _raw['image']},
        expected={'f2p': {'fix': '{}/fix.patch'.format(_rel), 'test_cmd': _raw['test_cmd'],
                          'reference_tests': list(_raw['reference_tests'])}},
        tags={str(_k): _v for _k, _v in _raw['labels'].items()}, split=_raw['split'],
        reference='{}/reference_test.patch'.format(_rel),
        meta={'issue': _raw['issue'], 'fix_commit': _raw['fix_commit'], 'merged_at': str(_raw['merged_at'])[:10],
              'budget': dict(_budget), 'repo': _raw['repo']})
    _task.root = os.path.dirname(os.path.abspath(os.path.normpath(directory)))
    return _task


def load(tasks_dir: str, name: str = 'tasks', version: str = ''):
    """Every task directory under `tasks_dir` (each with a task.yaml) as one Dataset."""
    from ipandora.core.eval.dataset import Dataset
    if not os.path.isdir(tasks_dir):
        raise ValueError('no such directory: {}'.format(tasks_dir))
    _dirs = sorted(_d for _d in os.listdir(tasks_dir) if os.path.isfile(os.path.join(tasks_dir, _d, 'task.yaml')))
    if not _dirs:
        raise ValueError('{}: no task directories (each needs a task.yaml)'.format(tasks_dir))
    _errors, _tasks = [], []
    for _d in _dirs:
        try:
            _tasks.append(load_task(os.path.join(tasks_dir, _d)))
        except ValueError as exc:
            _errors.append(str(exc))
    if _errors:
        raise ValueError('{} task(s) cannot be read:\n  {}'.format(len(_errors), '\n  '.join(_errors)))
    # reference and fix paths are relative to tasks_dir: the dataset "file" sits in it
    return Dataset(name=name, version=version, tasks=_tasks, path=os.path.join(os.path.abspath(tasks_dir), '.dataset'))


# -- reading a verdict back, attributing a failure ---------------------------------------------------

def from_json(text: str) -> List[Check]:
    """The checks of an `ipandora eval f2p --json` line -- for a scorer that ran it in the sandbox."""
    _line = next((_l for _l in reversed((text or '').strip().splitlines()) if _l.startswith('{')), '')
    try:
        _data = json.loads(_line)
    except ValueError:
        raise ValueError('not the output of `ipandora eval f2p --json`: {}'.format((text or '')[-200:]))
    return [Check(name=_c['name'], ok=bool(_c['ok']), expr=_c.get('expr', ''), src=TESTGEN,
                  claim=_c.get('claim', '')) for _c in _data.get('checks', [])]


ENVIRONMENT, TIMEOUT_OR_BUDGET, MODIFIED_SOURCE, WEAK_REPRODUCTION, NOT_REPRODUCED, FLAKY, NO_TESTS = (
    'environment', 'timeout_or_budget', 'modified_source', 'weak_reproduction', 'not_reproduced', 'flaky',
    'no_tests')
ZERO_ASSERTION, WEAK_ASSERTIONS, OUT_OF_SCOPE = 'zero_assertion', 'weak_assertions', 'out_of_scope'
TAMPERING = 'tampering'
REASONS = {TAMPERING: '测试改动了判分（钩子或记录与退出状态不符）', ENVIRONMENT: '环境问题', TIMEOUT_OR_BUDGET: '超时或超预算', MODIFIED_SOURCE: '改了源码',
           WEAK_REPRODUCTION: '弱复现', NOT_REPRODUCED: '没复现（修复前就通过）', FLAKY: '修复后不稳定',
           NO_TESTS: '没有写测试', ZERO_ASSERTION: '零断言', WEAK_ASSERTIONS: '断言太弱（变异分数低）',
           OUT_OF_SCOPE: '越界改动'}


def _by_claim(checks: Sequence[Any]) -> Dict[str, bool]:
    _out = {}
    for _c in checks:
        _claim = _c.get('claim') if isinstance(_c, dict) else getattr(_c, 'claim', '')
        _ok = _c.get('ok') if isinstance(_c, dict) else getattr(_c, 'ok', None)
        _out[_claim] = bool(_ok)
    return _out


def failure_reason(checks: Sequence[Any], status: str = 'graded', ended: str = 'completed',
                   over_budget: bool = False) -> str:
    """
    Why a test-generation run did not reach F→P, by rule -- the first that
    applies: environment (the harness failed), tampering, timeout_or_budget,
    environment (grading did not finish), no_tests, modified_source,
    weak_reproduction, flaky, not_reproduced. '' when it succeeded.
    """
    _c = _by_claim(checks)
    if status == 'infra' or ended == 'error':
        return ENVIRONMENT
    if _c.get('fail to pass'):
        return ''
    if _c.get('test results trustworthy') is False:
        return TAMPERING
    if ended.startswith('limit:') or over_budget:
        return TIMEOUT_OR_BUDGET
    if 'fail to pass' not in _c or _c.get('grading completed') is False:
        return ENVIRONMENT                         # the fix did not apply, the tests timed out, nothing graded
    _changed_source = _c.get('only test files changed') is False
    if _c.get('agent wrote tests') is False:
        return MODIFIED_SOURCE if _changed_source else NO_TESTS
    if _c.get('not a weak reproduction') is False:
        return WEAK_REPRODUCTION
    if _c.get('not flaky') is False:
        return FLAKY
    if _changed_source:
        return MODIFIED_SOURCE                     # its tests did not reproduce, and it changed the code
    return NOT_REPRODUCED


def flags(checks: Sequence[Any], over_budget: bool = False) -> List[str]:
    """Problems that do not decide F→P but are reported: zero assertions, weak assertions, out of scope, budget."""
    _c = _by_claim(checks)
    _out = []
    if _c.get('only test files changed') is False:
        _out.append(OUT_OF_SCOPE)
    if _c.get('tests assert') is False:
        _out.append(ZERO_ASSERTION)
    if _c.get('kills mutants of the fixed functions') is False:
        _out.append(WEAK_ASSERTIONS)
    if over_budget:
        _out.append(TIMEOUT_OR_BUDGET)
    return _out


# -- selfcheck: the grader on answers whose verdict is known --------------------------------------------

def _reset(workdir: str, base: str) -> None:
    """Back to `base`: tracked files as committed, untracked ones removed -- ignored files (an editable
    install's metadata, build output) are kept, the environment depends on them."""
    coding._git(workdir, 'reset', '-q', '--hard', base)
    coding._git(workdir, 'clean', '-q', '-fd')


_BAD_ANSWERS = {
    'source_only': None,                            # the fix itself, no test: out of scope, nothing to judge
    'zero_assertion': 'def test_ipandora_selfcheck_does_nothing():\n    pass\n',
    'import_only': 'import ipandora_selfcheck_no_such_module\n\n\ndef test_ipandora_selfcheck():\n'
                   '    assert ipandora_selfcheck_no_such_module\n',
}


def selfcheck(workdir: str, task_dir: str, runs: int = 3, oracle_runs: int = 3, base: str = 'HEAD',
              timeout: float = 600) -> List[Dict[str, Any]]:
    """
    The grader on answers whose verdict is known, in `workdir` at `base`
    (reset before each and at the end):

    - oracle: the reference tests (reference_test.patch), `oracle_runs`
      times -- F→P every time, and not weakly;
    - noop: no change -- not F→P;
    - source_only: the fix applied as the agent's change, no test -- not F→P,
      out of scope;
    - zero_assertion: a test that does nothing -- not F→P;
    - import_only: a test that fails only on an import -- a weak reproduction.

    Returns one row per check: {'case', 'expected', 'got', 'ok', 'detail'}.
    """
    _task = load_task(task_dir)
    _f2p = _task.expected['f2p']
    _fix = os.path.join(_task.root, _f2p['fix'])
    _ref = os.path.join(_task.root, _task.reference)
    _cmd = _f2p['test_cmd']
    _test_dir = os.path.dirname(_f2p['reference_tests'][0].split('::')[0]) or 'tests'
    _rows = []

    def _grade():
        return grade(workdir, _fix, base=base, test_cmd=_cmd, runs=runs, max_mutants=0, timeout=timeout)

    def _row(case, expected, result, ok):
        _rows.append({'case': case, 'expected': expected, 'ok': ok,
                      'got': 'F→P' if result.f2p else ('weak' if result.weak else 'not F→P'),
                      'detail': result.checks()[0].expr})
    try:
        _verdicts = []
        for _i in range(oracle_runs):
            _reset(workdir, base)
            coding._git(workdir, 'apply', '--whitespace=nowarn', os.path.abspath(_ref))
            _r = _grade()
            _verdicts.append(_r.f2p)
            _row('oracle#{}'.format(_i + 1), 'F→P', _r, _r.f2p and not _r.weak)
        if len(set(_verdicts)) > 1:
            _rows.append({'case': 'oracle', 'expected': 'the same verdict every run', 'got': str(_verdicts),
                          'ok': False, 'detail': 'the reference tests are flaky on this task'})
        _reset(workdir, base)
        _r = _grade()
        _row('noop', 'not F→P', _r, not _r.f2p)
        _reset(workdir, base)
        coding._git(workdir, 'apply', '--whitespace=nowarn', os.path.abspath(_fix))
        _r = _grade()
        _row('source_only', 'not F→P', _r, not _r.f2p and bool(_r.out_of_scope))
        for _case in ('zero_assertion', 'import_only'):
            _reset(workdir, base)
            _path = os.path.join(workdir, _test_dir, 'test_ipandora_selfcheck_{}.py'.format(_case))
            os.makedirs(os.path.dirname(_path), exist_ok=True)
            with open(_path, 'w', encoding='utf-8') as _f:
                _f.write(_BAD_ANSWERS[_case])
            _r = _grade()
            if _case == 'import_only':
                _row(_case, 'weak', _r, _r.weak and not _r.f2p)
            else:
                _row(_case, 'not F→P', _r, not _r.f2p and bool(_r.zero_assertion))
    finally:
        _reset(workdir, base)
    return _rows


__all__ = ['grade', 'load', 'load_task', 'selfcheck', 'from_json', 'failure_reason', 'flags', 'REASONS', 'TASK_FIELDS', 'TASK_FILES', 'Result', 'Run', 'pytest_run', 'split_changes', 'restore', 'is_test_file', 'classify',
           'asserting', 'patched_files', 'touched_functions', 'mutants_in', 'WEAK_EXCEPTIONS', 'TESTGEN']
