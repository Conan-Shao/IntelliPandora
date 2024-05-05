# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : requestwrapper.py
@Time  : 2024-04-19
"""
from ipandora.core.base.data.markdata import MarkData
from ipandora.core.protocol.http.model.sessionmodel import HttpSessionModel
from ipandora.core.protocol.http.model.option.httpontion import HttpOption
from ipandora.core.wrapper.basewrapper import EndPointApiProxy
from ipandora.core.wrapper.interface.requestinterface import RequestInterface


class RequestApiProxy(EndPointApiProxy, RequestInterface):

    @property
    def url(self):
        if self.endpoint is {} or self.endpoint is None:
            return ""
        return self.endpoint.get('url')

    @property
    def path(self):
        if self.url == "":
            return str(self._url_path).lstrip('/')
        return str(self.url).rstrip('/') + '/' + str(self._url_path).lstrip('/')


class EncryptApiProxy(object):
    def __init__(self, request_proxy: RequestApiProxy = '',
                 mark_data: MarkData = None, params: dict = None):
        self._mark_data = mark_data
        self._request_proxy = request_proxy
        self._params = params

        [setattr(self, k, v) for k, v in params.items()]

    @property
    def request_proxy(self):
        return self._request_proxy

    @property
    def url(self):
        return self.request_proxy.path

    @property
    def mark_data(self):
        return self._mark_data

    @property
    def mark(self):
        return self.mark_data.module

    @property
    def endpoint(self):
        return self.request_proxy.get_end_point_config()


class RequestWrapper(object):

    def __init__(self, path: str = '', mark: MarkData = '', params: dict = None, method: str = ''):
        self.path = path
        self.mark = mark
        self.params = params
        self.request_proxy = RequestApiProxy(mark=self.mark, path=self.path)
        self.method = method

    # self.encrypt_proxy = EncryptApiProxy(request_proxy=self.request_proxy,
    #                                      mark_data=mark, params=params)

    def build(self):
        # default use session request
        _o = HttpOption().set_mark(mark=self.mark).set_origin_params(params=self.params)
        _model = HttpSessionModel(http_option=_o)

        # if self.mark.encrypt:
        #     _re = EncryptApi(self.encrypt_proxy,
        #                      params_data_key=self.mark.encrypt_data).encrypt
        #     # self.params.update({self.mark.encrypt_data: _re})
        #     self.params.update(_re)

        # deal with parameters `verify` which controls TLS certificate.
        if 'https' in self.request_proxy.path and 'verify' not in self.params:
            self.params.update({'verify': False})
        return getattr(_model, self.method)(self.request_proxy.path, **self.params)
