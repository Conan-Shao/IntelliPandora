# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotsuite.py
@Time  : 2024-05-24
"""
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class RobotSettings:
    suite_setup: Optional[str] = None
    suite_teardown: Optional[str] = None
    test_setup: Optional[str] = None
    test_teardown: Optional[str] = None
    test_template: Optional[str] = None
    resource: List[str] = None
    library: List[str] = None
    force_tag: List[str] = None


@dataclass
class RobotCase:
    name: str
    steps: List[str] = None
    setup: Optional[str] = None
    teardown: Optional[str] = None
    documentation: Optional[str] = None
    tags: List[str] = None


@dataclass
class RobotSuite:
    name: str
    settings: RobotSettings
    cases: List[RobotCase] = None
