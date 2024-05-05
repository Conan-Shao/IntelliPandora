# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : conftest.py
@Time  : 2024-04-20
"""
from ipandora.core.base.data.markdata import MarkData
from ipandora.core.plugin.pluginmanager import PluginManager
from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface


class EndPointPlugin(EndPointsInterface):
    def endpoints(self, mark: MarkData) -> dict:
        return {}


PluginManager.endpoints(reg=EndPointPlugin())
