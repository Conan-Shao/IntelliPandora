# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_mcp_server.py
@Time  : 2026-08-01
"""
import asyncio
import unittest

from ipandora.core.mcp import server

class TestMcpToolRegistration(unittest.TestCase):
    def test_only_supported_tools_are_registered(self):
        tools = asyncio.run(server.mcp.list_tools())
        self.assertEqual(
            {t.name for t in tools},
            {'run_tests', 'explain_failure', 'list_runs', 'build_report'})

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


if __name__ == '__main__':
    unittest.main()
