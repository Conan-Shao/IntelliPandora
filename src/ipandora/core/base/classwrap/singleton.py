# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : singleton.py
# @Time  : 2024-04-17
import logging

logger = logging.getLogger(__name__)


# def synchronized(func):
#     func.__lock__ = threading.Lock()
#
#     def lock_func(*args, **kwargs):
#         with func.__lock__:
#             return func(*args, **kwargs)
#
#     return lock_func


class SingletonClass(object):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = \
                super(SingletonClass, cls).__new__(cls, *args, **kwargs)
        return cls._instance
