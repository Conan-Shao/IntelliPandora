# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_without_xdist.py
@Time  : 2026-11-05

The parallel extra is optional, so a run must work without pytest-xdist.

It did not, with pytest 9.2: the collector registered its xdist hook only when
`hasattr(config.hook, 'pytest_testnodedown')`, and pytest 9.2 answers yes for
any hook name. Without xdist every run then stopped with "unknown hook
'pytest_testnodedown'". CI did not see it because its lock files install
xdist and pin an older pytest.
"""
import textwrap

from ipandora.core.runner import run
from ipandora.core.runner.collector import _WorkerOutput


def test_the_xdist_hook_is_optional():
    assert _WorkerOutput.pytest_testnodedown.pytest_impl.get('optionalhook') is True


def test_a_run_works_with_xdist_blocked(tmp_path):
    _suite = tmp_path / 'test_plain.py'
    _suite.write_text(textwrap.dedent('''
        def test_passes():
            assert 1 == 1

        def test_fails():
            assert 1 == 2
    '''), encoding='utf-8')
    _result = run(str(_suite), extra_args=['-p', 'no:xdist'], persist=False, quiet=True,
                  baseline='')
    assert not _result.collect_error, _result.collect_error
    assert sorted(_c.outcome for _c in _result.cases) == ['failed', 'passed']
