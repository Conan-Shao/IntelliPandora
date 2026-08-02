# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __init__.py
@Time  : 2026-08-01

Library-callable test execution.

    from ipandora.core.runner import run

    result = run('test/testassertion', env='dev')
    result.ok            # bool
    result.summary()     # trimmed dict, safe to hand to an agent
    explain(result.run_id)   # full tracebacks, on demand

Both entry points -- the pytest CLI and the MCP `run_tests` tool -- go through
`run()`. The alternative, having MCP shell out to pytest and parse stdout,
throws away the structure pytest already provides and floods an agent's
context with output it cannot use.
"""
from ipandora.core.runner.api import explain, new_run_id, run
from ipandora.core.runner.result import CaseResult, RunResult

__all__ = ['run', 'explain', 'new_run_id', 'RunResult', 'CaseResult']
