# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : variable.py
@Time  : 2024-04-19

A module-global bag, used by the wrapper to find ENDPOINTS.

This used to carry a second implementation of every accessor, reading from and
writing to Robot Framework's variable table when a Robot execution context was
live. The Robot adapter is gone, so that branch could never be taken and has
been removed along with it; the plain-Python path is what always ran under
pytest and is what remains.
"""
import logging
import random
import string

logger = logging.getLogger()


class Variable(object):
    def __init__(self, **kwargs):
        globals().update(kwargs)

    @classmethod
    def get_variable_value_in_pyenv(cls, key, default_value=None):
        """
        Read a global set earlier through this class.

        :param key:
        :param default_value:
        :return: the value of the key
        """
        return globals().get(key, default_value)

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
