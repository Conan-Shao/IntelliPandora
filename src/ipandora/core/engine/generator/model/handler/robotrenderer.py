# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotrenderer.py
@Time  : 2024-05-25
"""
from ipandora.core.engine.generator.model.data.robotsuite import (RobotSuite, RobotSettings,
                                                                  RobotCase)


class RobotRenderer:
    def __init__(self, _robot_suite: RobotSuite):
        self.robot_suite = _robot_suite

    def content(self) -> str:
        content = ""
        content += self.render_setting()
        content += self.render_case()
        return content

    def render_setting(self) -> str:
        _settings = self.robot_suite.settings
        content = "*** Settings ***\n"

        setting_fields = {
            "suite_setup": "Suite Setup",
            "suite_teardown": "Suite Teardown",
            "test_setup": "Test Setup",
            "test_teardown": "Test Teardown",
            "test_template": "Test Template",
            "resource": "Resource",
            "library": "Library",
            "force_tag": "Force Tags"
        }
        for attr, keyword in setting_fields.items():
            value = getattr(_settings, attr)
            if isinstance(value, list):
                for item in value:
                    content += f"{keyword}    {item}\n"
            elif value:
                content += f"{keyword}    {value}\n"
        content += "\n"
        return content

    def render_case(self) -> str:
        content = "*** Test Cases ***\n"
        case_fields = {
            "documentation": "Documentation",
            "setup": "Setup",
            "teardown": "Teardown",
            "tags": "Tags",
            "steps": "Steps"
        }

        for case in self.robot_suite.cases:
            content += f"{case.name}\n"
            for attr, keyword in case_fields.items():
                value = getattr(case, attr)
                if isinstance(value, list) and keyword == "Steps":
                    for step in value:
                        content += f"    {step}\n"
                elif isinstance(value, list):
                    content += f"    [{keyword}]    {'    '.join(value)}\n"
                elif value:
                    content += f"    [{keyword}]    {value}\n"
            content += "\n"
        return content


if __name__ == '__main__':
    # 示例用法
    settings = RobotSettings(
        suite_setup="Setup Suite 012",
        suite_teardown="Teardown Suite 012",
        test_setup="Setup Test 012",
        test_teardown="Teardown Test 012",
        test_template="Test Template 012",
        resource=["Resource1", "Resource2"],
        library=["Library1", "Library2"],
        force_tag=["Tag1", "Tag2"]
    )

    cases = [
        RobotCase(
            name="Test Case 1",
            steps=["Step 1", "Step 2"],
            setup="Setup Case 1",
            teardown="Teardown Case 1",
            documentation="Documentation Case 1",
            tags=["Tag1", "Tag2"]
        ),
        RobotCase(
            name="Test Case 2",
            steps=["Step 1", "Step 2", "Step 3"],
            setup="Setup Case 2",
            teardown="Teardown Case 2",
            documentation="Documentation Case 2",
            tags=["Tag3", "Tag4"]
        )
    ]

    suite = RobotSuite(
        name="Test Suite",
        settings=settings,
        cases=cases
    )
    print(suite)
    renderer = RobotRenderer(suite)
    print(renderer.content())
