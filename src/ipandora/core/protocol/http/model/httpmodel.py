# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : httpmodel.py
@Time  : 2024-04-19
"""
import logging
from functools import update_wrapper
import requests
from ipandora.core.protocol.http.model.option.httpontion import HttpOption
from ipandora.core.protocol.http.model.data.requestobject import RequestObject
from ipandora.core.protocol.http.model.data.responseobject import NiceRequest
from ipandora.core.protocol.http.model.data.responseobject import ResponseHandler
from ipandora.core.protocol.http.model.interface.requestinterface import HttpRequestInterface

logger = logging.getLogger(__name__)


def request_hook(f):
    def do_request(*args, **kwargs):
        _instance = args[0]

        if not isinstance(_instance, HttpRequestInterface):
            _option = HttpOption()
        else:
            _option = getattr(_instance, 'option')
            args = args[1:]

        _request_object = RequestObject(_option, f.__name__, *args, **kwargs)
        if 'other_params' in _request_object.kwargs:
            _other_params = _request_object.kwargs.pop('other_params')
            if _other_params:
                _request_object.url = _request_object.url.format(**_other_params)

        from ipandora.core.plugin import PluginManager
        PluginManager.run('request', request=_request_object)
        return NiceRequest(request_object=_request_object).build()

    return update_wrapper(do_request, f)


class HttpModel(HttpRequestInterface):
    @property
    def option(self):
        return self._option.set_request_object(obj=requests)

    @request_hook
    def get(self, url, params=None, **kwargs) -> ResponseHandler:
        pass

    @request_hook
    def post(self, url, data=None, json=None, **kwargs) -> ResponseHandler:
        pass

    @request_hook
    def options(self, url, **kwargs) -> ResponseHandler:
        pass

    @request_hook
    def put(self, url, data=None, **kwargs) -> ResponseHandler:
        pass

    @request_hook
    def patch(self, url, data=None, **kwargs) -> ResponseHandler:
        pass

    @request_hook
    def head(self, url, **kwargs) -> ResponseHandler:
        pass

    @request_hook
    def delete(self, url, **kwargs) -> ResponseHandler:
        pass
