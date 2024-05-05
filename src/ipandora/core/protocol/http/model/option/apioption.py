# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : apioption.py
@Time  : 2024-04-19
"""
from ipandora.core.base.data.markdata import MarkData


class ApiOption(object):

    def __init__(self):
        # log or not
        self._log = True

        # api mark obj
        self._mark = None

        # request obj, this is request object
        self._obj = None

        self._timeout = 0

    @property
    def timeout(self) -> int:
        return self._timeout

    @property
    def obj(self):
        return self._obj

    @property
    def mark(self) -> MarkData:
        return self._mark or MarkData()

    @property
    def log(self):
        return self._log

    def set_not_log(self):
        self._log = False
        return self

    def set_mark(self, mark):
        self._mark = mark
        return self

    def set_timeout(self, timeout=0):
        self._timeout = timeout
        return self

    def set_request_object(self, obj) -> object:
        self._obj = obj
        return self
