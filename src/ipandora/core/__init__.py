# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : __init__.py.py
# @Time  : 2024-04-17
import os
import sys
from ipandora.core.schedule.runtime import Runtime
from ipandora.core.protocol import Api
api = Api()


def init(product=''):
    sys.path.append(
        os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
    Runtime.product = product


__all__ = ['api', 'init']
