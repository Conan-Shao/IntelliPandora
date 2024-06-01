# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : dictutils.py
@Time  : 2024-05-15
"""
from functools import reduce
from operator import getitem


class HashableDict:
    def __init__(self, d):
        self.d = d

    def __hash__(self):
        return hash(frozenset(self.d.items()))

    def __eq__(self, other):
        return self.d == other.d

    def __repr__(self):
        return repr(self.d)


class DictUtils:
    @staticmethod
    def dict_to_hashable(d):
        return HashableDict(d)

    @staticmethod
    def hashable_to_dict(hd):
        return hd.d

    @staticmethod
    def safe_get(d, *keys):
        try:
            return reduce(getitem, keys, d)
        except KeyError:
            return ''


if __name__ == '__main__':
    print(DictUtils.safe_get({'a': {'b': {'c': 1}}}, *[ 'a', 'b', 'c']))
