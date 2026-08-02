# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : server.py
@Time  : 2026-08-01
"""
from typing import Optional

from mcp.server.mcpserver import MCPServer

from ipandora.core import report
from ipandora.core.runner import api as runner
from ipandora.core.runner import store
from ipandora.core.schedule.runtime import Runtime
from ipandora.core.triage import triage
from ipandora.utils.log import log_to_stderr, logger
from ipandora.utils.robotlogparser import RobotLogParser

mcp = MCPServer(Runtime.Mcp.name)


@mcp.tool()
def run_tests(selector: str = '', env: str = '') -> dict:
    """
    Run tests and return a summary of what happened.

    selector: a path, a pytest nodeid, or a -k expression. Empty runs everything.
    env: environment name, e.g. "dev" or "prod". Optional.

    Returns totals plus, for each failure, the case name, the assertion
    message, and a rule-based classification saying whether it looks like a
    product defect, a contract change, an environment problem, missing test
    data, or a broken test. Full tracebacks are NOT included -- call
    explain_failure(run_id) when you actually need them.
    """
    # quiet=True is not optional here: on stdio transport, anything pytest
    # prints would land in the middle of this server's JSON-RPC stream.
    _result = runner.run(selector=selector, env=env, quiet=True)
    _summary = _result.summary()

    _report = triage(_result)
    if _report.findings:
        _by_node = {_f.nodeid: _f for _f in _report.findings}
        for _failure in _summary.get('failures', []):
            _finding = _by_node.get(_failure['nodeid'])
            if _finding:
                _failure['category'] = _finding.category
                _failure['reason'] = _finding.reason
                _failure['next_step'] = _finding.next_step
        _summary['triage'] = {
            'headline': _report.headline(),
            'by_category': _report.by_category,
            'blames_system_under_test': len(_report.product_failures),
        }
    return _summary


@mcp.tool()
def explain_failure(run_id: str) -> dict:
    """
    Full context for a previous run: every failure with its complete traceback.

    Use this after run_tests reports failures and the summary is not enough to
    tell you what to change. Output is large by design.
    """
    _detail = runner.explain(run_id)
    if _detail is None:
        return {'error': 'unknown run_id {!r}'.format(run_id),
                'known_runs': store.list_runs(limit=10)}
    return _detail


@mcp.tool()
def list_runs(limit: int = 10) -> dict:
    """Recent run ids, newest first, for use with explain_failure."""
    return {'runs': store.list_runs(limit=limit)}


@mcp.tool()
def build_report(run_id: str, directory: str, title: str = '') -> dict:
    """
    Write an HTML and JSON report for a previous run.

    Both come from the same data and have already had secrets stripped.
    Returns the paths written plus the totals, so the caller does not have to
    open the files to know what happened.
    """
    _result = store.load(run_id)
    if _result is None:
        return {'error': 'unknown run_id {!r}'.format(run_id),
                'known_runs': store.list_runs(limit=10)}
    _report = report.build(_result, title=title or None)
    return {'written': report.write(_report, directory),
            'totals': _report.totals,
            'pass_rate': _report.pass_rate,
            'ok': _report.ok}


@mcp.tool()
def get_test_report(xml_file: str, details_url: Optional[str] = None) -> dict:
    """
    Parse a Robot Framework output.xml and return its statistics and details.
    """
    return RobotLogParser(xml_file, details_url=details_url).results


# Deliberately NOT exposed -- see docs/design/04-实施计划.md:
#
#   provision(spec)   needs core/fixture (P2)
#   impact(diff)      needs a call-graph source (P5)
#
# `create_test_case` was removed on purpose: agents already write files, so
# generating cases through a tool hides them from diff review and git.


def serve():
    """Entry point used by the `ipandora mcp` CLI command."""
    if Runtime.Mcp.transport == 'stdio':
        # stdout belongs to the JSON-RPC stream from here on. The framework's
        # console handler writes to stdout by default, and a single log line
        # in the middle of a protocol message drops the connection.
        log_to_stderr()
    logger.info("Starting IntelliPandora MCP server <{}> via <{}>".format(
        Runtime.Mcp.name, Runtime.Mcp.transport))
    mcp.run(transport=Runtime.Mcp.transport)
