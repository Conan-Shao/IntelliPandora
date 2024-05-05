# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotprovider.py
@Time  : 2024-04-29
"""
from typing import List, Union
from pandoragt.core.engine.generator.model.data.robotcase import RobotCase
from pandoragt.core.engine.generator.model.data.robotsuite import RobotSuite
from pandoragt.common.filewriter import RobotFileWriter
from pandoragt.core.engine.generator.model.handler.robotrenderer import RobotRenderer
from pandoragt.core.engine.generator.provider.caseprovider import ICaseProvider, ISuiteProvider


class RobotCaseProvider(ICaseProvider):
    def create_case(self, steps: List[str]) -> RobotCase:
        _case_object = RobotCase(self.name, self.setup, self.teardown)
        for step in steps:
            _case_object.steps = step
        return _case_object


class RobotSuiteProvider(ISuiteProvider):
    def create_suite(self, case_objects: Union[RobotCase, List[RobotCase]]) -> RobotSuite:
        self.suite_object = RobotSuite(self.name, self.setup, self.teardown)
        self.suite_object.cases = case_objects
        return self.suite_object

    def add_case_to_suite(self, suite:RobotSuite, case):
        suite.cases = case

    def generate(self, directory: str = ''):
        RobotFileWriter(self.suite_object.name, RobotRenderer(self.suite_object).content(),
                        directory)


if __name__ == '__main__':
    # generate a robot file, suite and cases
    # create case object
    _c1 = RobotCaseProvider('testcase_001').create_case(['step 01 of case 001', 'step 02 of case 001'])
    _c1.steps = 'step extra of case 001'
    _c2 = RobotCaseProvider('testcase_002', 'setup_case2', 'teardown_case2').create_case(
        ['step 01 of case 002', 'step 02 of case 002', 'step 03 of case 002'])
    # create suite object and attach case to suite.
    _sp = RobotSuiteProvider('testsuite_001', 'setup of suite 001', 'teardown of suite 001')
    _suite_obj = _sp.create_suite([_c1, _c2])
    _suite_obj.test_setup = 'test setup of suite 001'
    _suite_obj.test_teardown = 'test teardown of suite 001'
    _suite_obj.tags = ['tag1', 'tag2']
    _suite_obj.tags = 'smoke'
    _suite_obj.library = ['SSHLibrary', 'Collections']
    _suite_obj.resource = ['GT_resource.robot']
    print(_suite_obj)

    # generate file
    _sp.generate('/Users/shaofeng/Repos/logtemp')
