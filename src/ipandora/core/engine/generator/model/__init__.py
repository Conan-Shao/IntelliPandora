# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __init__.py.py
@Time  : 2024-04-28
"""
from ipandora.core.engine.generator.model.data.robotsuite import RobotSuite
from ipandora.core.engine.generator.model.data.robotcase import RobotCase
from ipandora.core.engine.generator.model.data.robotsuitelegacy import RobotSuiteLegacy
from ipandora.core.engine.generator.model.data.robotcaselegacy import RobotCaseLegacy

__all__ = ["RobotSuiteLegacy", "RobotCaseLegacy", "RobotSuite", "RobotCase"]
