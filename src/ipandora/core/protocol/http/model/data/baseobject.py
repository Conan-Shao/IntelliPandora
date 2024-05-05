# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : baseobject.py
@Time  : 2024-04-19
"""
from abc import ABCMeta, abstractmethod
from ipandora.core.protocol.http.model.interface.optioninterface import HttpOptionInterface


class BaseObject(metaclass=ABCMeta):
    def __init__(self, option, method, *args, **kwargs):
        self._args = args
        self._kwargs = kwargs
        self._method = method
        self._headers = {}
        self._option = option  # type:HttpOptionInterface
        self._init()

    @abstractmethod
    def _init(self): pass

    @property
    def mark(self):
        return self.option.mark

    @property
    def option(self):
        return self._option

    @property
    def args(self):
        return self._args

    @args.setter
    def args(self, args):
        self._args = args

    @property
    def kwargs(self):
        """
        e.g. requests info include data and headers
        {data:{"user_name":"","password":""},
        headers:{"content-type":"application/json"}}
        :return:
        """
        return self._kwargs

    @kwargs.setter
    def kwargs(self, kwargs):
        self._kwargs = kwargs

    @property
    def method(self):
        return self._method
