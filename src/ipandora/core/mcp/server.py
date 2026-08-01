# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : server.py
@Time  : 2026-08-01
"""
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import List, Optional

from mcp.server.mcpserver import MCPServer

from ipandora.core.engine.generator.model.data.case import Case, Step
from ipandora.core.engine.generator.repository.testcaserepository import TestCaseRepository
from ipandora.core.engine.generator.service.testcaseserivce import TestCaseService
from ipandora.core.schedule.runtime import Runtime
from ipandora.utils.error import MCPError
from ipandora.utils.log import logger
from ipandora.utils.robotlogparser import RobotLogParser

mcp = MCPServer(Runtime.Mcp.name)


def _serialize(obj):
    """Make a dataclass JSON-friendly (datetimes -> isoformat) for MCP responses."""
    if is_dataclass(obj):
        return {k: v.isoformat() if isinstance(v, datetime) else v
                for k, v in asdict(obj).items()}
    return obj


@mcp.tool()
def list_test_cases(source: Optional[str] = None, is_automated: Optional[bool] = None) -> list:
    """
    List test cases already stored in the case repository, optionally
    filtered by source ('doc'/'robot'/'handbook'/...) and automation status.
    """
    repo = TestCaseRepository()
    if source:
        cases = repo.get_test_cases_by_source(source)
    elif is_automated is not None:
        cases = repo.get_test_cases_by_is_automated(is_automated)
    else:
        cases = repo.get_full_cases()
    return [_serialize(c) for c in cases]


@mcp.tool()
def create_test_case(title: str, steps: List[dict], description: str = '',
                     precondition: str = '', tags: Optional[List[str]] = None,
                     submodule_id: Optional[int] = None) -> dict:
    """
    Create a new test case with its steps (and optional tags) via the
    existing TestCaseService. Each item in `steps` is a dict with
    "description" and "expected_result" keys.
    """
    service = TestCaseService()
    case = Case(TestCaseID=None, SubmoduleID=submodule_id, Title=title,
               Description=description, Precondition=precondition,
               Source='mcp', IsAutomated=False)
    step_objs = [
        Step(StepID=None, TestCaseID=None, StepNumber=_i + 1,
            StepDescription=_s.get('description', ''),
            ExpectedResult=_s.get('expected_result', ''))
        for _i, _s in enumerate(steps)
    ]
    case_id = service.create_test_case(case, step_objs, tags or [])
    return {"test_case_id": case_id}


@mcp.tool()
def run_test_suite(path: str, runner: str = 'pytest') -> dict:
    """
    Execute a test suite via pytest or robot as a subprocess and return the
    result summary. Used by an external AI client/agent to drive test runs.
    """
    if runner not in ('pytest', 'robot'):
        raise MCPError("Unsupported runner: {}".format(runner))
    logger.info("Running test suite <{}> with runner <{}>".format(path, runner))
    completed = subprocess.run([runner, path], capture_output=True, text=True, timeout=1800)
    return {
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


@mcp.tool()
def get_test_report(xml_file: str, details_url: Optional[str] = None) -> dict:
    """
    Parse a Robot Framework output.xml and return the statistics/details
    summary produced by the framework's existing RobotLogParser.
    """
    return RobotLogParser(xml_file, details_url=details_url).results


def serve():
    """Entry point used by the `ipandora mcp` CLI command."""
    logger.info("Starting IntelliPandora MCP server <{}> via <{}>".format(
        Runtime.Mcp.name, Runtime.Mcp.transport))
    mcp.run(transport=Runtime.Mcp.transport)
