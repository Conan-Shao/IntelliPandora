# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __init__.py.py
@Time  : 2024-04-28
"""
from ipandora.core.engine.generator.provider.robotprovider import (RobotSuiteProvider,
                                                                    RobotCaseProvider)
__all__ = ['RobotSuiteProvider', 'RobotCaseProvider', 'GeneratorApi']


class GeneratorApi(object):
    def __init__(self, config):
        self.config = config

    def generate_robot_cases_with_config(self):
        self.handle_robot_gen_config()

    def handle_robot_gen_config(self):
        pass

    def generate_universal_cases_with_config(self):
        self.handle_universal_gen_config()

    def handle_universal_gen_config(self):
        pass
        
