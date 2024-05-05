# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : requestinterface.py
@Time  : 2024-04-19
"""
from abc import ABCMeta, abstractmethod
from ipandora.core.protocol.http.model.option.httpontion import HttpOption


class HttpRequestInterface(metaclass=ABCMeta):

    def __init__(self, http_option: HttpOption = HttpOption()):
        self._option = http_option

    @property
    def option(self):
        return self._option

    @option.setter
    def option(self, option=None):
        self._option = option

    @abstractmethod
    def get(self, url, params=None, **kwargs): pass

    @abstractmethod
    def post(self, url, data=None, json=None, **kwargs): pass

    @abstractmethod
    def options(self, url, **kwargs): pass

    @abstractmethod
    def put(self, url, data=None, **kwargs): pass

    @abstractmethod
    def patch(self, url, data=None, **kwargs): pass

    @abstractmethod
    def head(self, url, **kwargs): pass

    @abstractmethod
    def delete(self, url, **kwargs): pass
