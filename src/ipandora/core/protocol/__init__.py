# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __init__.py.py
@Time  : 2024-05-04
"""
from ipandora.core.protocol.http.provider import Http, Mark
from ipandora.core.plugin import PluginManager
from ipandora.core.base.classwrap.multihandle import init as exit_init
from ipandora.core.protocol.http.model.interface.responseinterface import HttpResponseInterface

# init plugin manager
PluginManager.init()

# init exit
exit_init()


class Api(object):
    http = Http()
    mark = Mark
    # socket = Socket()
    # data object
    response = None  # type:HttpResponseInterface
