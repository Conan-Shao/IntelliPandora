# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotsuitelegacy.py
@Time  : 2024-04-29
"""
from ipandora.utils.log import logger
from ipandora.core.engine.generator.model.data.robotcaselegacy import RobotCaseLegacy, TypeCheck
from ipandora.utils.error import VariableError
from typing import Union, List


class RobotSuiteLegacy(object):
    def __init__(self, name, setup=None, teardown=None):
        self._name = name
        self._setup = setup
        self._teardown = teardown
        self._cases = []
        self._case_obj = None
        self._setting = self.init_setting()

    def init_setting(self):
        _setting = {}
        if self._setup:
            _setting.update({"Suite Setup": self._setup})
        if self._teardown:
            _setting.update({"Suite Teardown": self._teardown})
        return _setting

    @property
    def content(self):
        return {
            "name": self._name,
            "setting": self._setting,
            "cases": self._cases,
        }

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        self._name = name

    @property
    def setting(self):
        return self._setting

    @setting.setter
    def setting(self, setting):
        if not isinstance(setting, dict):
            raise VariableError("Setting must be a dictionary.")
        for k, v in setting.items():
            if k.lower() in ["suite setup", "suite teardown", "test template",
                             "library", "resource", "test setup", "test teardown"]:
                if v:
                    self._setting.update({k: v})
            elif k.lower() == "setup":
                self.setup = v
            elif k.lower() == "teardown":
                self.teardown = v
            else:
                continue

    @property
    def setup(self):
        return self._setting.get("Suite Setup")

    @setup.setter
    def setup(self, setup: str):
        if not isinstance(setup, str):
            raise VariableError("Suite Setup must be a string.")
        if setup:
            self._setting.update({"Suite Setup": setup})
        else:
            logger.warn("Suite Setup is empty.")

    @property
    def teardown(self):
        return self._setting.get("Suite Teardown")

    @teardown.setter
    def teardown(self, teardown: str):
        if not isinstance(teardown, str):
            raise VariableError("Suite Teardown must be a string.")
        if teardown:
            self._setting.update({"Suite Teardown": teardown})
        else:
            logger.warn("Suite Teardown is empty.")

    @property
    def test_setup(self):
        return self._setting.get("Test Setup")

    @test_setup.setter
    def test_setup(self, testsetup: str):
        if not isinstance(testsetup, str):
            raise VariableError("Test Setup must be a string.")
        if testsetup:
            self._setting.update({"Test Setup": testsetup})
        else:
            logger.warn("Test Setup is empty.")

    @property
    def test_teardown(self):
        return self._setting.get("Test Teardown")

    @test_teardown.setter
    def test_teardown(self, test_teardown: str):
        if not isinstance(test_teardown, str):
            raise VariableError("Test Teardown must be a string.")
        if test_teardown:
            self._setting.update({"Test Teardown": test_teardown})
        else:
            logger.warn("Test Teardown is empty.")

    @property
    def tags(self):
        return self._setting.get("Test Tags") or []

    @tags.setter
    def tags(self, tags):
        _tag_list = self.tags
        if isinstance(tags, list):
            _tag_list.extend(tags)
        else:
            _tag_list.append(tags)
        self._setting.update({"Test Tags": _tag_list})

    @property
    def resource(self):
        return self._setting.get("Resource") or []

    @resource.setter
    def resource(self, resource):
        _resource_list = self.resource
        if isinstance(resource, list):
            _resource_list.extend(resource)
        else:
            _resource_list.append(resource)
        self._setting.update({"Resource": _resource_list})

    @property
    def library(self):
        return self.setting.get("Library") or []

    @library.setter
    def library(self, library):
        _library_list = self.library
        if isinstance(library, list):
            _library_list.extend(library)
        else:
            _library_list.append(library)
        self._setting.update({"Library": _library_list})

    @property
    def template(self):
        return self._setting.get("Test Template")

    @template.setter
    def template(self, template):
        self._setting.update({"Test Template": template})

    @property
    def cases(self):
        return self._cases

    @cases.setter
    def cases(self, case_objects: Union[RobotCaseLegacy, List[RobotCaseLegacy]]):
        if isinstance(case_objects, list):
            self._cases.extend(case_objects)
        else:
            self._cases.append(case_objects)

    @property
    def case_name(self):
        return self._case_obj.name

    @case_name.setter
    def case_name(self, case_name):
        # create new case object and attached to the suite
        self._case_obj = RobotCaseLegacy(case_name)
        self._cases.append(self._case_obj)

    @property
    def case_setup(self):
        return self._case_obj.setup

    @case_setup.setter
    def case_setup(self, case_setup: str):
        if not self._case_obj and isinstance(self._case_obj, RobotCaseLegacy):
            raise VariableError("Case object not found. Please add a case first.")
        if not isinstance(case_setup, str):
            raise VariableError("Case Setup must be a string.")
        self._case_obj.setup = case_setup

    @property
    def case_teardown(self):
        return self._case_obj.teardown

    @case_teardown.setter
    def case_teardown(self, case_teardown: str):
        if not isinstance(case_teardown, str):
            raise VariableError("Case Teardown must be a string.")
        if not self._case_obj and isinstance(self._case_obj, RobotCaseLegacy):
            raise VariableError("Case object not found. Please add a case first.")
        self._case_obj.teardown = case_teardown

    @property
    def steps(self):
        return self._case_obj.steps

    @steps.setter
    def steps(self, step):
        if not self._case_obj:
            raise VariableError("Case object not found. Please add a case first.")
        self._case_obj.steps = step

    def add_case(self, case_name, case_steps, case_setup=None, case_teardown=None):
        self._case_obj = RobotCaseLegacy(case_name, case_setup, case_teardown)
        if isinstance(case_steps, list):
            for step in case_steps:
                self._case_obj.steps = step
        else:
            self._case_obj.steps = case_steps
        self._cases.append(self._case_obj)

    def add_setting(self, resource=None, library=None, template=None):
        self.resource = resource
        self.library = library
        self._setting.update({
            "Resource": self.resource,
            "Library": self.library,
            "Test Template": template
        })

    def __str__(self):
        return f"RobotSuiteLegacy(name={self.name}, cases={self.cases}, setting={self.setting})"

    def __repr__(self):
        return f"RobotSuiteLegacy({self.name!r}, {self.cases!r}, setting={self.setting!r})"


if __name__ == '__main__':
    _suite_obj = RobotSuiteLegacy('test_suite_demo', 'Suite Setup', 'Suite Teardown')
    _suite_obj.setup = "Suite Setup update"
    _suite_obj.library = "SSHLibrary"
    _suite_obj.resource = "resource.robot"
    _suite_obj.add_setting('resource_of_template.robot', 'Collections', 'Keyword As Template New')

    # set cases and steps
    _suite_obj.case_name = "Test Case 1"
    _suite_obj.case_setup = "Case Setup"
    _suite_obj.case_teardown = "Case Teardown"
    _suite_obj.steps = "Step 1 for Case 1"
    _suite_obj.steps = "Step 2 for Case 1"

    _suite_obj.case_name = "Test Case 2"
    _suite_obj.steps = "Step 1 for Case 2"
    _suite_obj.steps = "Step 2 for Case 2"

    _case_obj_3 = RobotCaseLegacy("Test Case 3333", 'Case Setup 3333',
                            'Case Teardown 3333')
    _case_obj_3.steps = ["Step 300 for Case 3333", "Step 301 for Case 3333",
                         "Step 302 for Case 3333", "Step 303 for Case 3333"]
    _case_obj_4 = RobotCaseLegacy("Test Case 444", 'Case Setup 444',
                            'Case Teardown 444')
    _suite_obj.cases = [_case_obj_4, _case_obj_3]

    print(_suite_obj)

    from ipandora.core.engine.generator.model.handler.robotrendererlegacy import RobotRendererLegacy
    _content = RobotRendererLegacy(_suite_obj).content()
    print(_content)
    # from ipandora.common.filewriter import RobotFileWriter
    # RobotFileWriter("test.robot", _content)
