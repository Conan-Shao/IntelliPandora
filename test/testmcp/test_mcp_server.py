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
        self.assertEqual({t.name for t in tools}, {'get_test_report'})


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
