# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotcaselegacy.py
@Time  : 2024-04-29
"""


class RobotCaseLegacy:
    name: str
    documentation: str
    tags: list
    setup: None
    steps: list
    teardown: None

    def __init__(self, name, setup=None, teardown=None):
        self._documentation = ''
        self._name = str(name)
        self._setup = setup
        self._teardown = teardown
        self._steps = []
        self._tags = []

    @property
    def content(self):
        return {
            "tags": self._tags,
            "name": self._name,
            "setup": self._setup,
            "teardown": self._teardown,
            "steps": self._steps,
            "documentation": self._documentation
        }

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        self._name = name

    @property
    def setup(self):
        return self._setup

    @setup.setter
    def setup(self, setup):
        self._setup = setup

    @property
    def teardown(self):
        return self._teardown

    @teardown.setter
    def teardown(self, teardown):
        self._teardown = teardown

    @property
    def steps(self):
        return self._steps

    @steps.setter
    def steps(self, step):
        if isinstance(step, list):
            self._steps.extend(step)
        else:
            self._steps.append(str(step))

    @property
    def tags(self):
        """
        Get the tags of the case, ignore the duplicate tags.
        :return:
        """
        return list(set(self._tags))

    @tags.setter
    def tags(self, tags):
        if isinstance(tags, list):
            self._tags.extend(tags)
        else:
            self._tags.append(str(tags))

    @property
    def documentation(self):
        return self._documentation

    @documentation.setter
    def documentation(self, documentation):
        self._documentation = documentation

    def __str__(self):
        return (f"RobotCaseLegacy(name={self.name}, setup={self.setup}, teardown={self.teardown}, "
                f"steps={self.steps}, tags={self.tags}, documentation={self.documentation})")

    def __repr__(self):
        return (f"RobotCaseLegacy({self.name!r}, {self.steps!r}, {self.setup!r}, {self.teardown!r}, "
                f"tags={self.tags!r}, documentation={self.documentation!r})")


class TypeCheck(Exception):
    @staticmethod
    def check_type(variable, expected_type):
        if not isinstance(variable, expected_type):
            raise TypeError(f"Expected type {expected_type.__name__}, got {type(variable).__name__}")


if __name__ == '__main__':
    case = RobotCaseLegacy("Test Case 1")
    case.steps = "Step 1 for Case 1"
    case.steps = "Step 2 for Case 1"
    case.steps = "Step 3 for Case 1"
    case.steps = "Step 4 for Case 1"
    case.steps = "Step 5 for Case 1"
    case.tags = 'struct:xz'
    case.tags = 'struct:xyz'
    case.tags = ['struct: apple', 'struct:xyz']
    case.document = 'This is a test case for auto pilot.'
    print(case)
    print(case.content)
