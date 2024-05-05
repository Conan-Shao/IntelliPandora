# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotrenderer.py
@Time  : 2024-04-28
"""
from pandoragt.core.engine.generator.model import RobotSuite


class RobotRenderer(object):
    def __init__(self, suite: RobotSuite):
        self.suite = suite

    def content(self):
        content = ""
        content += self.render_setting()
        content += self.render_case()
        return content

    def render_setting(self):
        content = f"*** Settings ***\n"
        max_key_length = max(len(key) for key in self.suite.setting) + 4
        for _key, _value in self.suite.setting.items():
            if isinstance(_value, list) and (_key == "Library" or _key == "Resource"):
                for _v in _value:
                    content += f"{_key:<{max_key_length}}{_v}\n"
            elif isinstance(_value, list) and (_key == "Test Tags"):
                _value = "    ".join(_value)
                content += f"{_key:<{max_key_length}}{_value}\n"
            else:
                content += f"{_key:<{max_key_length}}{_value}\n"
        content += "\n"
        return content

    def render_case(self):
        content = f"*** Test Cases ***\n"
        for _case_obj in self.suite.cases:
            content += f"{_case_obj.name}\n"
            if _case_obj.setup:
                content += f"    [Setup]    {_case_obj.setup}\n"
            for _step in _case_obj.steps:
                content += f"    {_step}\n"
            if _case_obj.teardown:
                content += f"    [Teardown]    {_case_obj.teardown}\n"
            content += "\n"
        return content


if __name__ == '__main__':
    pass

