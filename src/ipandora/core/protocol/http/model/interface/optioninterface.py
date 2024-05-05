# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : optioninterface.py
@Time  : 2024-04-19
"""
from abc import ABCMeta
from copy import copy
from typing import Union
from requests import Session
from ipandora.core.protocol.http.model.option.apioption import ApiOption

_OBJ = Union[Session]


class HttpOptionInterface(ApiOption, metaclass=ABCMeta):

    def __init__(self, host=None, headers: dict = None,
                 handler=None):
        # request header
        self._header = headers or {}

        # request host
        self._host = host

        # request params
        self._params = None

        # response handler
        self._handler = handler

        self._auth = None

        super(HttpOptionInterface, self).__init__()

    @property
    def header(self) -> dict:
        return self._header

    @property
    def host(self) -> str:
        return self._host

    @host.setter
    def host(self, host):
        self._host = host

    @property
    def response_handler(self):
        return self._handler

    @property
    def auth(self):
        return self._auth

    @property
    def params(self):
        return self._params

    def set_header(self, header: dict) -> 'HttpOptionInterface':
        self._header.update(header)
        return self

    def set_host(self, host: str) -> 'HttpOptionInterface':
        self._host = host
        return self

    def set_response_handler(self, handler=None) -> 'HttpOptionInterface':
        self._handler = handler
        return self

    def set_auth(self, auth=None):
        self._auth = auth
        return self

    def set_origin_params(self, params=None):
        _p = copy(params)
        try:
            if isinstance(params, dict):
                self._params = [{_item: _p.get(_item)} for _item in
                                ['params', 'data', 'json', 'files'] if
                                _item in _p]
            else:
                self._params = _p
        except Exception as e:
            self._params = str(e)
        return self


if __name__ == '__main__':
    p = HttpOptionInterface()
