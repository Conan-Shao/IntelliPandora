# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : classproperty.py
# @Time  : 2024-04-17
class ClassPropertyMeta(type):
    def __new__(mcs, name, bases, dct):
        # Convert properties decorated with @classproperty into ClassProperty instances.
        for key, value in dct.items():
            if isinstance(value, ClassProperty):
                dct[key] = value
        return super(ClassPropertyMeta, mcs).__new__(mcs, name, bases, dct)

    def __setattr__(cls, key, value):
        obj = cls.__dict__.get(key)
        if obj and isinstance(obj, ClassProperty):
            return obj.__set__(cls, value)
        return super(ClassPropertyMeta, cls).__setattr__(key, value)

    def __getattr__(cls, item):
        return cls.get_meta_data(option=item)

    @classmethod
    def get_meta_data(mcs, option=None, default=None):
        return default


class ClassProperty:
    def __init__(self, f_get, f_set=None):
        self.f_get = f_get
        self.f_set = f_set

    def __get__(self, obj, cls=None):
        if cls is None:
            cls = type(obj)
        return self.f_get.__get__(obj, cls)()

    def __set__(self, obj, value):
        if not self.f_set:
            raise AttributeError("can't set attribute")
        self.f_set.__func__(obj, value)

    def setter(self, func):
        if not isinstance(func, (classmethod, staticmethod)):
            func = classmethod(func)
        self.f_set = func
        return self


def classproperty(f_get):
    if not isinstance(f_get, (classmethod, staticmethod)):
        f_get = classmethod(f_get)
    return ClassProperty(f_get)
