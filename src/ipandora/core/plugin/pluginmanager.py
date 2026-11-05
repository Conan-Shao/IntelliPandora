# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : pluginmanager.py
@Time  : 2024-04-19
"""
from ipandora.core.plugin.specificationsbuilder import SpecificationsManager
from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface
from ipandora.core.plugin.interface.httpregisterinterface import HttpPluginInterface
from ipandora.core.plugin.interface.plugininterface import PluginInterface


class PluginManager(object):

    @classmethod
    def init(cls):
        """
        Create the registry so plugins can be added to it.

        This used to also register an InnerPlugin whose only job was to feed
        every response into a batcher that POSTed it to a reporting host. The
        framework runs standalone now -- nothing is sent anywhere -- so the
        plugin, the batcher and the host config are gone. Only the registry
        the user's own plugins go into is set up here.
        """
        cls.get_builder()

    @classmethod
    def http(cls, reg: HttpPluginInterface = None):
        cls.register(reg)

    @classmethod
    def endpoints(cls, reg: EndPointsInterface = None):
        cls.register(reg)

    @classmethod
    def register(cls, plugin: PluginInterface = None):
        cls.get_builder().add_register(plugin)

    @classmethod
    def run(cls, method=None, *args, **kwargs):
        return cls.get_builder().run(method=method, *args, **kwargs)

    @classmethod
    def get_builder(cls):
        return SpecificationsManager.get_builder(tag='default_plugin', interface=PluginInterface)
