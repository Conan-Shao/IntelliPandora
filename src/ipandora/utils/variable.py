# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : variable.py
@Time  : 2024-04-19
"""
try:
    from robot.libraries.BuiltIn import BuiltIn
except ImportError:
    pass
try:
    from robot.running.context import EXECUTION_CONTEXTS
except ImportError:
    EXECUTION_CONTEXTS = None
import logging
import random
import string
logger = logging.getLogger()


class Variable(object):
    def __init__(self, **kwargs):
        # print("Set Global Variables to Namespace -- variable_execution:")
        if self.is_robot_env():
            # get value from robot variable
            for key, value in kwargs.items():
                key_robot = '${%s}' % key
                BuiltIn().set_global_variable(key_robot, value)
        else:
            globals().update(kwargs)

    @classmethod
    def get_variable_value_in_pyenv(cls, key, default_value=None):
        """
        The keyword used to get variable value in python.
        global value in python or robot framework
        :param key:
        :param default_value:
        :return: the value of the key
        """
        if cls.is_robot_env():
            # get value from robot variable
            key_robot = '${%s}' % key
            return BuiltIn().get_variable_value(key_robot, default_value)
        else:
            if key in globals():
                return globals().get(key)
            else:
                return default_value

    @classmethod
    def is_robot_env(cls):
        if EXECUTION_CONTEXTS is None:
            return False
        else:
            current = getattr(EXECUTION_CONTEXTS, 'current')
            if current is None:
                return False
            else:
                return True

    @staticmethod
    def get_random_from_list(items):
        return random.choice(items)

    @staticmethod
    def get_random_str(length=8):
        return ''.join(random.sample(string.ascii_letters + string.digits, length))

    @classmethod
    def get_endpoints(cls, key='ENDPOINTS'):
        return cls.get_variable_value_in_pyenv(key)

    @classmethod
    def get_appkey(cls):
        return cls.get_variable_value_in_pyenv('APP_KEY')


if __name__ == '__main__':
    pass
