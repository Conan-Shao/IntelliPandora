# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : match.py
# @Time  : 2024-04-17
import logging
from abc import ABCMeta, abstractmethod

logger = logging.getLogger(__name__)
basetype = int, float, bytes, bytearray, str, bool


class Compare(object):

    def __init__(self, a=None, b=None):
        self._b = b
        self._a = a

    def cmp_in(self):
        return self._a in self._b

    def cmp_notIn(self):
        return self._a not in self._b

    def cmp_gt(self):
        if type(self._b) == int:
            return int(float(self._a)) > self._b
        else:
            return type(self._b)(self._a) > self._b

    def cmp_startWith(self):
        return str(self._a).startswith(str(self._b))

    def cmp_contains(self):
        return str(self._b).lower() in str(self._a).lower()

    def cmp_eq(self):
        if type(self._b) == int:
            return int(float(self._a)) == self._b
        else:
            return type(self._b)(self._a) == self._b


class Matcher(metaclass=ABCMeta):
    def __init__(self, superset: dict = None):
        self._super_dict = superset
        self._condition = None

    def condition(self, condition=None):
        self._condition = condition
        return self

    @abstractmethod
    def match(self) -> bool:
        pass


class DictMatcher(Matcher):

    def match(self) -> bool:
        if self._condition is None:
            return True

        if not isinstance(self._condition, dict):
            raise ValueError(
                'condition must be dict {}'.format(self._condition))

        for _k, _v in self._condition.items():
            if _k not in self._super_dict:
                return False

            if isinstance(_v, basetype):
                if str(_v) != str(self._super_dict.get(_k, '')):
                    return False

            elif isinstance(_v, dict):
                for _e_k, _e_v in _v.items():
                    _method = str(_e_k).replace('$', 'cmp_')
                    if not hasattr(Compare(), _method):
                        return False
                    if not getattr(Compare(a=self._super_dict.get(_k), b=_e_v),
                                   _method)():
                        return False

            else:
                raise ValueError(
                    u'compare value must be basetype or dict, {}/{}'.format(
                        type(_v), _v))

        return True