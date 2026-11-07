# -*- coding: utf-8 -*-
"""
@File  : test_testgen_plain.py
@Time  : 2026-11-07

SWT-bench's plain F→P, to compare with its harness (fresh-repro PLAN.md 2.5):
the out-of-scope discard and the weak-reproduction rule switched off. Both
are on by default; off, a test that fails only by not importing what the fix
adds is F→P, and the agent's own source changes stay -- as SWT-bench's
harness applies the whole patch.
"""
import json
import subprocess
import sys

import pytest

from ipandora.core.eval import testgen

from test.testeval.test_testgen import CMD, grade, repo, write  # noqa: F401 -- repo is a fixture

ADDS_MUL = '''\
--- a/calc/__init__.py
+++ b/calc/__init__.py
@@ -12,3 +12,7 @@ def scale(x):
     if x > 10:
         return x * 2
     return x
+
+
+def mul(a, b):
+    return a * b
'''

IMPORTS_MUL = '''\
from calc import mul


def test_mul():
    assert mul(2, 3) == 6
'''


def adds_mul(repo):
    (repo.parent / 'mul.patch').write_text(ADDS_MUL)
    return str(repo.parent / 'mul.patch')


class TestWithoutTheWeakRule:

    def test_importing_what_the_fix_adds_is_weak_by_default(self, repo):
        write(repo, 'tests/test_mul.py', IMPORTS_MUL)
        _r = testgen.grade(str(repo), adds_mul(repo), test_cmd=CMD, max_mutants=0)
        assert not _r.f2p and _r.weak and _r.rules == {'discard_out_of_scope': True, 'weak_rule': True}

    def test_and_plain_f2p_without_it(self, repo):
        write(repo, 'tests/test_mul.py', IMPORTS_MUL)
        _r = testgen.grade(str(repo), adds_mul(repo), test_cmd=CMD, max_mutants=0, weak_rule=False)
        assert _r.f2p and not _r.weak and _r.tests == ['tests/test_mul.py::test_mul']
        assert _r.before == {'tests/test_mul.py::test_mul': 'reproduced'}
        assert _r.before_detail['tests/test_mul.py::test_mul']['exc'] == 'CollectError'
        assert _r.asserting == {'tests/test_mul.py::test_mul': True} and len(_r.after) == 3
        _c = _r.checks()[0]
        assert _c.name == 'F→P：修复前失败、修复后通过（关掉了：弱复现规则）' and _c.claim == 'fail to pass'
        assert _r.record()['rules'] == {'discard_out_of_scope': True, 'weak_rule': False} and _r.plain

    def test_a_file_the_fix_does_not_make_collect_is_not_f2p(self, repo):
        write(repo, 'tests/test_div.py', 'from calc import div\n\n\ndef test_div():\n    assert div(6, 3) == 2\n')
        _r = testgen.grade(str(repo), adds_mul(repo), test_cmd=CMD, max_mutants=0, weak_rule=False)
        assert not _r.f2p and _r.reproduced and not _r.fixed_passes
        assert _r.before == {'tests/test_div.py': 'reproduced'} and _r.after == [{'tests/test_div.py': 'error'}]

    def test_a_failure_in_the_test_itself_reproduces(self, repo):
        # a NameError of the test: weak by default, a reproduction without the rule
        write(repo, 'tests/test_add.py', 'def test_add():\n    assert add(1, 2) == 3\n')
        assert grade(repo).weak
        _r = grade(_fresh(repo), weak_rule=False)
        assert _r.reproduced and not _r.weak and not _r.f2p          # it still fails with the fix

    @pytest.mark.parametrize('row', [{'outcome': 'failed', 'when': 'setup', 'exc': 'FixtureLookupError'},
                                     {'outcome': 'failed', 'when': 'call', 'exc': 'ImportError'},
                                     {'outcome': 'failed', 'when': 'call', 'exc': 'AssertionError'}])
    def test_classify(self, row):
        assert testgen.classify(row, weak_rule=False) == 'reproduced'
        assert testgen.classify({'outcome': 'skipped', 'when': 'setup', 'exc': ''}, weak_rule=False) == 'passed'


def _fresh(repo):
    """The same work directory, the agent's tests kept, at its state before grading changed it."""
    subprocess.run(['git', '-C', str(repo), 'checkout', '--', '.'], check=True, capture_output=True)
    return repo


class TestKeepingTheOutOfScope:

    def test_put_back_by_default(self, repo):
        write(repo, 'calc/__init__.py', (repo / 'calc' / '__init__.py').read_text().replace('a - b', 'a + b'))
        write(repo, 'tests/test_add.py', 'from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n')
        _r = grade(repo)
        assert _r.f2p and _r.out_of_scope == ['calc/__init__.py']

    def test_kept_the_agents_fix_meets_the_official_one(self, repo):
        write(repo, 'calc/__init__.py', (repo / 'calc' / '__init__.py').read_text().replace('a - b', 'a + b'))
        write(repo, 'tests/test_add.py', 'from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n')
        _r = grade(repo, discard_out_of_scope=False)
        # the agent changed the line the fix changes: it no longer applies, as in SWT-bench's harness
        assert not _r.f2p and _r.error.startswith('the fix does not apply')
        assert _r.out_of_scope == ['calc/__init__.py'] and 'a + b' in (repo / 'calc' / '__init__.py').read_text()
        assert not _r.reproduced          # with its own fix in place, the test passed before the official one
        _names = {_c.claim: _c for _c in _r.checks()}
        assert _names['fail to pass'].name.endswith('（关掉了：越界丢弃）') and not _names['only test files changed'].ok

    def test_kept_elsewhere_it_still_counts(self, repo):
        write(repo, 'calc/extra.py', 'X = 1\n')
        write(repo, 'tests/test_add.py', 'from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n')
        _r = grade(repo, discard_out_of_scope=False)
        assert _r.f2p and _r.out_of_scope == ['calc/extra.py'] and (repo / 'calc' / 'extra.py').exists()


class TestTheCommand:

    def test_the_flags(self, repo):
        write(repo, 'tests/test_mul.py', IMPORTS_MUL)
        _done = subprocess.run([sys.executable, '-m', 'ipandora.run', 'eval', 'f2p', str(repo), '--fix', adds_mul(repo),
                                '--test-cmd', CMD, '--max-mutants', '0', '--keep-out-of-scope', '--no-weak-rule',
                                '--json'], capture_output=True, text=True, timeout=300)
        assert _done.returncode == 0, _done.stderr
        _line = json.loads(_done.stdout.strip().splitlines()[-1])
        assert _line['f2p'] and _line['rules'] == {'discard_out_of_scope': False, 'weak_rule': False}
        assert _line['checks'][0]['name'] == 'F→P：修复前失败、修复后通过（关掉了：越界丢弃、弱复现规则）'


class TestCr18:
    """Found in code review CR18 (docs/design/reviews/18-CR18.md)."""

    def test_only_files_that_do_not_collect_count_as_failing_before(self, repo):
        from test.testeval.test_testgen import EXISTING
        write(repo, 'tests/test_mul.py', IMPORTS_MUL)
        write(repo, 'tests/test_existing.py', EXISTING + '\n\ndef test_new_passes_anyway():\n    assert parse("4") == 4\n')
        _r = testgen.grade(str(repo), adds_mul(repo), test_cmd=CMD, max_mutants=0, weak_rule=False)
        # the agent's test in the file that collects ran before the fix and passed; the unchanged ones are not its own
        assert _r.before == {'tests/test_existing.py::test_new_passes_anyway': 'passed',
                             'tests/test_mul.py::test_mul': 'reproduced'}
        assert _r.tests == ['tests/test_existing.py::test_new_passes_anyway', 'tests/test_mul.py::test_mul']
        assert _r.f2p and len(_r.after) == 3
