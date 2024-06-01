# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotbaseprovider.py
@Time  : 2024-04-29
"""
from abc import ABC, abstractmethod


class RobotBaseProvider(ABC):
    def __init__(self, name, setup=None, teardown=None):
        self.name = name
        self.setup = setup
        self.teardown = teardown


class ICaseProvider(RobotBaseProvider):
    @abstractmethod
    def create_case(self, steps):
        pass


class ISuiteProvider(RobotBaseProvider):
    def __init__(self, name, setup=None, teardown=None):
        super(ISuiteProvider, self).__init__(name, setup, teardown)
        self.suite_object = None

    @abstractmethod
    def create_suite(self, cases):
        pass

    @abstractmethod
    def add_case_to_suite(self, cases):
        pass

    @abstractmethod
    def generate(self, directory: str):
        pass
