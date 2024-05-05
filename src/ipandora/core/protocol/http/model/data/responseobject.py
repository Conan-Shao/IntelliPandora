# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : responseobject.py
@Time  : 2024-04-19
"""
import time
from abc import ABCMeta, abstractmethod
from copy import deepcopy
from socket import socket as sc
from typing import Union, Optional
from requests import Response

from ipandora.core.base.data.markdata import MarkData
from ipandora.core.base.loglib.log import Log
from ipandora.core.protocol.http.model.data.requestobject import RequestObject
from ipandora.core.protocol.http.model.handler.responsehandler import ResponseHandler
from ipandora.core.schedule.runtime import Runtime

R = Union[Response, bytes]


class PandoraRequest(metaclass=ABCMeta):
    def __init__(self, request_object: RequestObject = None):
        self._request_object = request_object
        self._response = None  # type:Optional[Response, bytes]
        self.total_time = 0
        self.handle_response()

    @property
    def request_object(self):
        return self._request_object

    @property
    def response(self):
        return self._response

    @response.setter
    def response(self, response):
        self._response = response

    @abstractmethod
    def build(self): pass

    def do_log(self):
        if (self.request_object.option.log and
                not self.request_object.mark.no_log and
                not Runtime.Option.no_log):
            self.log()

    @abstractmethod
    def log(self): pass

    @abstractmethod
    def set_step(self): pass

    def handle_response(self):
        _request_handle = getattr(self.request_object.option.obj,
                                  self.request_object.method)
        _start_time = time.perf_counter()
        self.response = _request_handle(*self.request_object.args,
                                        **self.request_object.kwargs)
        self.total_time = time.perf_counter() - _start_time
        self.set_step()

        # make sure need to print request log
        self.do_log()


class NiceRequest(PandoraRequest):

    def log(self):
        _m = 'red' if self.response.status_code < 200 or \
                      self.response.status_code > 400 else 'normal'
        _msg = "\n[{}]\t\t===>\t\t[{}]\n".format(self.response.status_code,
                                                 self.request_object.url)
        _msg += "[method]\t===>\t\t{}\n".format(self.request_object.method)

        _log_params = {**self.request_object.kwargs,
                       **{'headers': deepcopy(self.response.request.headers)}}
        for k, v in _log_params.items():
            if len(k) > 5:
                _msg += "[{}]\t===>\t\t{}\n".format(k, v)
            else:
                _msg += "[{}]\t\t===>\t\t{}\n".format(k, v)

        _msg += "[response]\t===>\t\t{}\n".format(self.response.text)
        # print(_msg)
        getattr(Log, _m)(msg=_msg)

    def set_step(self):
        if Runtime.Option.report_detail():
            _s = [self.response.request.url,
                  dict(self.response.request.headers),
                  self.request_object.option.params,
                  self.response.text]
            Runtime.Case.steps = _s

    def handle(self):

        # logging.info("Request url: {}\n".format(self.request_object.url))

        _response = ResponseObject(
            response=self.response,
            mark=self.request_object.mark,
            request=self.request_object,
            total_time=self.total_time)

        from ipandora.core.plugin.pluginmanager import PluginManager
        PluginManager.run('response', response=_response)

        return _response.content

    def build(self):
        return ResponseHandler().inject(response=self.response, content=self.handle())


class SocketRequest(PandoraRequest):

    def set_step(self):
        pass

    def build(self):
        return self.handle()
        # return self.response

    def handle(self):
        _response = SocketResponseObject(
            sock=self.request_object.option.obj,
            mark=self.request_object.mark
        )

        from ipandora.core.plugin.pluginmanager import PluginManager
        PluginManager.run('socketResponse', response=_response)
        return _response.content or self.response

    def log(self):
        pass

    def handle_response(self):
        _socket_obj = self.request_object.option.obj
        _request_handle = getattr(_socket_obj, self.request_object.method)

        # todo there aren't valid way to handler response message
        # _response_handle = getattr(_socket_obj, 'recv')

        self.response = _request_handle(
            *self.request_object.args, **self.request_object.kwargs)

        self.set_step()

        # make sure need to print request log
        self.do_log()


class ResponseObject(object):

    def __init__(self, response: R = None, mark: MarkData = None, content=None,
                 request: RequestObject = None, total_time=0):
        self._mark = mark
        self._response = response
        self._content = content or response.content
        self._request = request
        self._total_time = total_time

    @property
    def total_time(self):
        return self._total_time

    @property
    def mark(self):
        return self._mark

    @property
    def response(self) -> R:
        return self._response

    @property
    def content(self):
        return self._content or self.response.content

    @property
    def request(self):
        return self._request


class SocketResponseObject(object):

    def __init__(self, sock: sc = None, mark: MarkData = None):
        self._socket = sock
        self._mark = mark
        self._content = None

    @property
    def socket(self):
        return self._socket

    @property
    def mark(self):
        return self._mark

    @property
    def content(self):
        return self._content

    @content.setter
    def content(self, content):
        self._content = content
