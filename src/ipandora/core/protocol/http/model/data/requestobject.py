# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : requestobject.py
@Time  : 2024-04-19
"""
from requests.structures import CaseInsensitiveDict
from ipandora.core.protocol.http.model.data.baseobject import BaseObject
from ipandora.core.schedule.runtime import Runtime
from ipandora.core.schedule.session import SessionManager


class RequestObject(BaseObject):

    def _init(self):
        self.handleAuth()
        self.handleHeaders()
        self.handleUrl()
        self.handleTimeout()
        self.handleCatchResponse()

    @property
    def url(self):
        return self.args[0] if self.args else self.option.host

    @url.setter
    def url(self, url):
        _l = list(self.args)
        _l[0] = url
        self._args = tuple(_l)

    @property
    def headers(self):
        return self._headers or self.kwargs.get('headers', {})

    @headers.setter
    def headers(self, headers: dict = None):
        self._headers.update(headers)
        self._kwargs.update(
            {'headers': {**headers, **self._kwargs.get('headers', {})}})

    def handleAuth(self):

        # merge option auth
        if self._option.auth and 'auth' not in self.kwargs:
            self.kwargs.update({'auth': self._option.auth})

    def handleHeaders(self):
        _h_n = CaseInsensitiveDict()
        _r_h = self.kwargs.get('headers', {})

        _h_n.update(self.option.header)
        if isinstance(_r_h, dict):
            _h_n.update(_r_h)

        # file request don't need content-type
        if 'files' in self.kwargs and self.kwargs.get('files'):
            pass
        elif 'Content-Type' not in _h_n:
            _h_n.update({"Content-type": "application/json"})
            _h_n.update(SessionManager.getHeaders())

        self._headers = _h_n
        self.kwargs.update({"headers": _h_n})

    def handleUrl(self):
        if not self._option.host:
            return
        _r_u = str(self.args[0]).strip('/') if self.args else ''

        if '.' not in _r_u and '.' in self._option.host:
            self.url = '/'.join((self._option.host, _r_u))

    def handleTimeout(self):
        if self._option.timeout and 'timeout' not in self.kwargs:
            self.kwargs.update({'timeout': self._option.timeout})

    def handleCatchResponse(self):
        if Runtime.Frame.is_locust and self.mark.catch_response:
            self.kwargs.update({'catch_response': True})


class SocketRequestObject(BaseObject):

    def __init__(self, option, method, params, *args, **kwargs):
        super(SocketRequestObject, self) \
            .__init__(option, method, *args, **kwargs)
        self._params = params

    @property
    def params(self):
        return self._params

    def _init(self):
        self._handleTimeout()

    def _handleTimeout(self):
        # todo need to handler socket timeout
        pass

    def _handleData(self):

        if self.args:
            return

        method, params = self.method, self.params

        # key def
        data, flags, address = 'data', 'flags', 'address'
        ancdata, bufsize, ancbufsize = 'ancdata', 'bufsize', 'ancbufsize'
        nbytes, buffer, buffers = 'nbytes', 'buffer', 'buffers'

        if method in ['send', 'sendall']:
            _info = (data, flags), 1
        elif method in ['sendto']:
            _info = (data, address), 2
        elif method in ['sendmsg']:
            _info = (buffers, ancdata, flags, address), 1
        elif method in ['recv', 'recvfrom']:
            _info = (bufsize, flags), 1
        elif method in ['recvmsg']:
            _info = (bufsize, ancbufsize, flags), 1
        elif method in ['recv_into', 'recvfrom_into']:
            _info = (buffer, nbytes, flags), 1
        elif method in ['recvmsg_into']:
            _info = (buffers, ancbufsize, flags), 1
        else:
            raise ValueError('invalid socket method [{}]'.format(method))
        _l = []

        # parse parameters
        _pairs, _count = _info
        for _index, _key in enumerate(_pairs):
            if _index < _count and _key not in params:
                raise ValueError(
                    'key [{}] must be returned {}'.format(_key, params))
            if _key in params:
                _l.append(params.pop(_key))
            else:
                break

        self.args, self.kwargs = tuple(_l), {}
