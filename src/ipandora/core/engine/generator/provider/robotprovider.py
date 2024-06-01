# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotprovider.py
@Time  : 2024-04-29
"""
from typing import List, Union
from ipandora.core.engine.generator.model.data.robotcaselegacy import RobotCaseLegacy
from ipandora.core.engine.generator.model.data.robotsuitelegacy import RobotSuiteLegacy
from ipandora.utils.filewriter import RobotFileWriter
from ipandora.core.engine.generator.model.handler.robotrendererlegacy import RobotRendererLegacy
from ipandora.core.engine.generator.provider.robotbaseprovider import ICaseProvider, ISuiteProvider


class RobotCaseProvider(ICaseProvider):
    def create_case(self, steps: Union[str, List[str]]) -> RobotCaseLegacy:
        _case_object = RobotCaseLegacy(self.name, self.setup, self.teardown)
        _case_object.steps = steps
        return _case_object


class RobotSuiteProvider(ISuiteProvider):
    def create_suite(self, case_objects: Union[RobotCaseLegacy, List[RobotCaseLegacy], None] = None):
        self.suite_object = RobotSuiteLegacy(self.name, self.setup, self.teardown)
        if case_objects:
            self.suite_object.cases = case_objects
        return self.suite_object

    def add_case_to_suite(self, case):
        if not self.suite_object:
            self.create_suite()
        self.suite_object.cases = case

    def add_setting_to_suite(self, setting: dict):
        if not self.suite_object:
            self.create_suite()
        self.suite_object.setting = setting

    def generate(self, directory: str = ''):
        RobotFileWriter(self.suite_object.name, RobotRendererLegacy(self.suite_object).content(),
                        directory)


if __name__ == '__main__':
    # generate a robot file, suite and cases
    # create case object
    _c1 = RobotCaseProvider('testcase_001').create_case(['step 01 of case 001', 'step 02 of case 001'])
    _c1.steps = 'step extra of case 001'
    _c1.documentation = 'this is a test case 001 documentation'
    _c1.tags = ['tag1111', 'tag22222']
    _c1.setup = 'setup of case 001'
    _c1.teardown = 'teardown of case 001'
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
    print(RobotRendererLegacy(_suite_obj).content())

    # generate file
    # _sp.generate('/Users/shaofeng/Repos/logtemp')
