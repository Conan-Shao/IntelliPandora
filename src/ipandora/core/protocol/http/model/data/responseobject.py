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
from ipandora.core.protocol.http.transport import translate_error
from ipandora.core.schedule.runtime import Runtime

R = Union[Response, bytes]


def _as_text(body):
    """Request bodies reach us as str, bytes or None; the report wants text."""
    if body is None or isinstance(body, str):
        return body
    if isinstance(body, bytes):
        try:
            return body.decode('utf-8')
        except UnicodeDecodeError:
            return '<{} bytes>'.format(len(body))
    return str(body)


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

    def _record_failed_exchange(self, exc, elapsed):
        """
        Record a call that never produced a response.

        A report that only shows exchanges which succeeded is misleading in the
        exact case someone opens it for: the request that died leaves no trace,
        and the case looks like it never called anything.
        """
        try:
            from ipandora.core.evidence import add_exchange
            add_exchange(
                method=str(self.request_object.method).upper(),
                url=self.request_object.url,
                ms=round(elapsed * 1000.0, 1),
                error='{}: {}'.format(type(exc).__name__, exc))
        except Exception:  # noqa: BLE001
            pass

    def handle_response(self):
        _request_handle = getattr(self.request_object.option.obj,
                                  self.request_object.method)
        _start_time = time.perf_counter()
        try:
            self.response = _request_handle(*self.request_object.args,
                                            **self.request_object.kwargs)
        except Exception as exc:
            # A transport failure produced no response, so there is nothing to
            # assert on. Re-raise it as a framework error carrying the url,
            # method and elapsed time -- previously the bare requests exception
            # propagated with no context about which call died.
            _elapsed = time.perf_counter() - _start_time
            _translated = translate_error(
                exc, url=self.request_object.url,
                method=self.request_object.method, elapsed=_elapsed)
            self._record_failed_exchange(exc, _elapsed)
            if _translated is None:
                raise
            raise _translated from exc
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
        self.record_exchange()

    def record_exchange(self):
        """
        Hand the call to the evidence recorder so the report can show it.

        Separate from set_step, which feeds the legacy step list and is gated
        behind report_detail. This one is unconditional and cheap: it stores
        references the response already holds, and does nothing at all when no
        run is collecting.

        Never raises -- a request that succeeded must not fail because the
        report could not describe it.
        """
        try:
            from ipandora.core.evidence import add_exchange
            _req = getattr(self.response, 'request', None)
            add_exchange(
                method=str(self.request_object.method).upper(),
                url=getattr(_req, 'url', '') or self.request_object.url,
                status=self.response.status_code,
                reason=getattr(self.response, 'reason', '') or '',
                ms=round(self.total_time * 1000.0, 1),
                request_headers=dict(getattr(_req, 'headers', {}) or {}),
                request_body=_as_text(getattr(_req, 'body', None)),
                response_headers=dict(self.response.headers or {}),
                response_body=self.response.text)
        except Exception:  # noqa: BLE001 - see docstring
            pass

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
