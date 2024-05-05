# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : responseinterface.py
@Time  : 2024-04-19
"""
from abc import ABCMeta, abstractmethod
from collections import namedtuple
from requests import Response


class HttpResponseInterface(metaclass=ABCMeta):
    @property
    @abstractmethod
    def code(self): pass

    @property
    @abstractmethod
    def data(self): pass

    @abstractmethod
    def inject(self, response: Response, content: str = ''):
        pass

    @property
    @abstractmethod
    def origin(self): pass

    @property
    @abstractmethod
    def response(self) -> Response: pass

    @property
    @abstractmethod
    def target(self): pass

    @property
    @abstractmethod
    def origin_fetched(self): pass

    @property
    @abstractmethod
    def error_code(self): pass

    @abstractmethod
    def filter(self, **kwargs): pass

    @abstractmethod
    def fetch_all(self): pass

    @abstractmethod
    def fetch_one(self) -> namedtuple or list: pass

    @abstractmethod
    def fetch_last(self): pass

    @abstractmethod
    def fetch(self, index=0): pass


