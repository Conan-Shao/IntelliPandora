# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_mcp_server.py
@Time  : 2026-08-01
"""
import asyncio
import os
import tempfile
import unittest

from ipandora.core.mcp import server

SAMPLE_ROBOT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<robot generated="20260101 00:00:00.000">
  <suite name="Sample Suite" source="/tmp/sample.robot">
    <test name="Test One">
      <status status="FAIL">Assertion failed</status>
    </test>
    <status status="FAIL" elapsed="1"/>
  </suite>
  <statistics>
    <total>
      <stat pass="0" fail="1">All Tests</stat>
    </total>
  </statistics>
</robot>
"""


class TestMcpToolRegistration(unittest.TestCase):
    def test_only_supported_tools_are_registered(self):
        tools = asyncio.run(server.mcp.list_tools())
        self.assertEqual(
            {t.name for t in tools},
            {'run_tests', 'explain_failure', 'list_runs', 'get_test_report'})

    def test_every_tool_documents_itself(self):
        # the docstring is the prompt: a model decides whether and how to call
        # a tool from it, so an undocumented tool is an unusable one
        for tool in asyncio.run(server.mcp.list_tools()):
            self.assertTrue((tool.description or '').strip(),
                            '{} has no description'.format(tool.name))

    def test_run_tests_does_not_shell_out(self):
        # docs/design/00 rules out shelling out to pytest and parsing stdout;
        # run_tests must go through the library runner instead
        import inspect
        source = inspect.getsource(server.run_tests)
        self.assertNotIn('subprocess', source)
        self.assertIn('runner.run', source)

    def test_run_tests_silences_pytest_for_stdio(self):
        # stdout carries the JSON-RPC stream under stdio transport
        import inspect
        self.assertIn('quiet=True', inspect.getsource(server.run_tests))


class TestGetTestReport(unittest.TestCase):
    def test_parses_robot_output(self):
        with tempfile.TemporaryDirectory() as _tmp_dir:
            xml_path = os.path.join(_tmp_dir, 'output.xml')
            with open(xml_path, 'w') as f:
                f.write(SAMPLE_ROBOT_XML)
            result = server.get_test_report(xml_file=xml_path)
            self.assertEqual(result['statistics']['fail'], 1)
            self.assertIn('Sample_Suite', result['Details'])


if __name__ == '__main__':
    unittest.main()
