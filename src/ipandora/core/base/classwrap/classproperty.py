# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : classproperty.py
# @Time  : 2024-04-17
import json


class ClassPropertyMeta(type):
    def __setattr__(self, key, value):
        obj = self.__dict__.get(key) if key in self.__dict__ else None
        if obj and type(obj) is ClassProperty:
            return obj.__set__(self, value)

        return super(ClassPropertyMeta, self).__setattr__(key, value)

    @classmethod
    def getMetaData(mcs, option=None, default=None):
        return None

    def __getattr__(self, item):
        return self.getMetaData(option=item)


class ClassProperty(object):
    def __init__(self, fget, fset=None):
        self.fget = fget
        self.fset = fset

    def __get__(self, obj, klass=None):
        if klass is None:
            klass = type(obj)
        return self.fget.__get__(obj, klass)()

    def __set__(self, obj, value):
        if not self.fset:
            raise AttributeError("can't set attribute")
        # type_ = type(obj)
        # return self.fset.__get__(obj, obj)(value)
        return self.fset.__func__(obj, value)

    def set(self, func):
        if not isinstance(func, (classmethod, staticmethod)):
            func = classmethod(func)
        self.fset = func
        return self


def classproperty(f):
    if not isinstance(f, (classmethod, staticmethod)):
        f = classmethod(f)

    return ClassProperty(f)


class StrEncoder(json.JSONEncoder):
    def default(self, obj):
        return str(obj)
