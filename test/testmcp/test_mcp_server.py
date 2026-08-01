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
from unittest.mock import MagicMock, patch

from ipandora.core.mcp import server
from ipandora.utils.error import MCPError

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
    def test_tools_are_registered(self):
        tools = asyncio.run(server.mcp.list_tools())
        names = {t.name for t in tools}
        self.assertEqual(
            names,
            {'list_test_cases', 'create_test_case', 'run_test_suite', 'get_test_report'})


class TestListAndCreateTestCase(unittest.TestCase):
    @patch('ipandora.core.mcp.server.TestCaseRepository')
    def test_list_test_cases_serializes_dataclasses(self, mock_repo_cls):
        from ipandora.core.engine.generator.model.data.case import Case
        mock_repo = MagicMock()
        mock_repo.get_test_cases_by_source.return_value = [
            Case(TestCaseID=1, SubmoduleID=1, Title='t1', Description='d1',
                Precondition='p1', Source='doc', IsAutomated=True)
        ]
        mock_repo_cls.return_value = mock_repo

        result = server.list_test_cases(source='doc')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['Title'], 't1')
        mock_repo.get_test_cases_by_source.assert_called_once_with('doc')

    @patch('ipandora.core.mcp.server.TestCaseService')
    def test_create_test_case_wires_steps(self, mock_service_cls):
        mock_service = MagicMock()
        mock_service.create_test_case.return_value = 42
        mock_service_cls.return_value = mock_service

        result = server.create_test_case(
            title='new case',
            steps=[{'description': 'step 1', 'expected_result': 'ok'}],
            tags=['smoke'])

        self.assertEqual(result, {'test_case_id': 42})
        args, _kwargs = mock_service.create_test_case.call_args
        case_arg, steps_arg, tags_arg = args
        self.assertEqual(case_arg.Title, 'new case')
        self.assertEqual(len(steps_arg), 1)
        self.assertEqual(steps_arg[0].StepDescription, 'step 1')
        self.assertEqual(tags_arg, ['smoke'])


class TestRunTestSuite(unittest.TestCase):
    def test_unsupported_runner_raises(self):
        with self.assertRaises(MCPError):
            server.run_test_suite(path='.', runner='nosetests')


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
