# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotrendererlegacy.py
@Time  : 2024-04-28
"""
from ipandora.core.engine.generator.model import RobotSuiteLegacy


class RobotRendererLegacy(object):
    def __init__(self, suite: RobotSuiteLegacy):
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
            for _attr in _case_obj.__annotations__:
                key = _attr.capitalize()
                value = getattr(_case_obj, _attr)
                if not value:
                    continue
                if key.lower() == 'name':
                    content += f"{value}\n"
                elif key.lower() == 'steps':
                    for _step in value:
                        content += f"    {_step}\n"
                else:
                    if isinstance(value, list):
                        value = "    ".join(value)
                    content += f"    [{key}]    {value}\n"
            content += "\n"
        return content


if __name__ == '__main__':
    pass

