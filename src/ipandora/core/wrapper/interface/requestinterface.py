# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : requestinterface.py
@Time  : 2024-04-19
"""
from abc import ABCMeta, abstractmethod


class RequestInterface(metaclass=ABCMeta):

    @property
    @abstractmethod
    def path(self): pass


class SocketProxyInterface(metaclass=ABCMeta):

    @property
    @abstractmethod
    def addr(self): pass


class UIProxyInterface(metaclass=ABCMeta):

    @property
    @abstractmethod
    def selector(self): pass

    @property
    @abstractmethod
    def selector_manager(self): pass
