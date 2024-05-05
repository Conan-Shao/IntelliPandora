# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __init__.py.py
@Time  : 2024-04-19
"""
from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface
from ipandora.core.plugin.interface.httpregisterinterface import HttpPluginInterface
from ipandora.core.plugin.interface.plugininterface import PluginInterface

__all__ = ['HttpPluginInterface', 'EndPointsInterface', 'PluginInterface']