# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : server.py
@Time  : 2026-08-01
"""
from typing import Optional

from mcp.server.mcpserver import MCPServer

from ipandora.core.schedule.runtime import Runtime
from ipandora.utils.log import logger
from ipandora.utils.robotlogparser import RobotLogParser

mcp = MCPServer(Runtime.Mcp.name)


@mcp.tool()
def get_test_report(xml_file: str, details_url: Optional[str] = None) -> dict:
    """
    Parse a Robot Framework output.xml and return the statistics/details
    summary produced by the framework's existing RobotLogParser.
    """
    return RobotLogParser(xml_file, details_url=details_url).results


# Deliberately NOT exposed yet -- see docs/design/04-实施计划.md (P3):
#
#   run_tests(selector)      needs core/runner/api.py first. The previous
#                            implementation shelled out to pytest and parsed
#                            stdout, which docs/design/00 rules out.
#   explain_failure(run_id)  needs core/triage.
#   provision(spec)          needs core/fixture.
#
# `create_test_case` was removed on purpose: agents already write files, so
# generating cases through a tool hides them from diff review and git.


def serve():
    """Entry point used by the `ipandora mcp` CLI command."""
    logger.info("Starting IntelliPandora MCP server <{}> via <{}>".format(
        Runtime.Mcp.name, Runtime.Mcp.transport))
    mcp.run(transport=Runtime.Mcp.transport)
