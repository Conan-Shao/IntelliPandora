# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : log.py
# @Time  : 2024-04-17
import logging

logger = logging.getLogger("ipandora.logger")


class Log(object):
    name = 'default'
    END = '\033[0m'

    # color sequences
    BOLD = '\033[1m'
    RED = '\033[91m'
    GREEN = '\033[1;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[1;34m'
    VIOLET = '\033[35m'
    BEIGE = '\033[36m'

    @classmethod
    def green(cls, msg=None):
        cls.format(color=cls.GREEN, msg=msg)

    @classmethod
    def blue(cls, msg=None):
        cls.format(color=cls.BLUE, msg=msg)

    @classmethod
    def yellow(cls, msg=None):
        cls.format(color=cls.YELLOW, msg=msg)

    @classmethod
    def normal(cls, msg=None):
        cls.format(msg=msg)

    @classmethod
    def red(cls, msg=None):
        cls.format(color=cls.RED, msg=msg)

    @classmethod
    def format(cls, color=None, msg=None):
        _msg = color + msg + cls.END if color is not None else msg
        logger.info(_msg)
