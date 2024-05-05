# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotcase.py
@Time  : 2024-04-29
"""


class RobotCase:
    def __init__(self, name, setup=None, teardown=None):
        self._name = str(name)
        self._setup = setup
        self._teardown = teardown
        self._steps = []

    @property
    def content(self):
        return {
            "name": self._name,
            "setup": self._setup,
            "teardown": self._teardown,
            "steps": self._steps
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

    def __str__(self):
        return (f"RobotCase(name={self.name}, setup={self.setup}, teardown={self.teardown}, "
                f"steps={self.steps})")

    def __repr__(self):
        return f"RobotCase({self.name!r}, {self.steps!r}, {self.setup!r}, {self.teardown!r})"


class TypeCheck(Exception):
    @staticmethod
    def check_type(variable, expected_type):
        if not isinstance(variable, expected_type):
            raise TypeError(f"Expected type {expected_type.__name__}, got {type(variable).__name__}")


if __name__ == '__main__':
    case = RobotCase("Test Case 1")
    case.steps = "Step 1 for Case 1"
    case.steps = "Step 2 for Case 1"
    case.steps = "Step 3 for Case 1"
    case.steps = "Step 4 for Case 1"
    case.steps = "Step 5 for Case 1"
    print(case)
    print(case.content)