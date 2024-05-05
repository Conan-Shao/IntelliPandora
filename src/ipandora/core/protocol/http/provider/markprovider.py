# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : markprovider.py
@Time  : 2024-04-19
"""
from ipandora.core.base.data.markdata import MarkData


class Mark(object):
    mark_key = '__pandora_mark__'

    mark_not_null_keys = ['module']

    def __init__(self, module: str = '', encrypt: str = '',
                 no_log: bool = False, catch_response: bool = False,
                 proto_handle=None, **kwargs):
        """
        mark api
        :param module: point out which host this api need to use in variable file endpoints
        :param encrypt: the encrypt type of current api, such as aks etc.
        :param no_log: log this api info or not
        :param catch_response: catch virtual user http response, just valid in locust test
        :param kwargs:
        """
        self._func = ''
        self._encrypt = encrypt
        self._module = module
        self._keyword = {
            **kwargs,
            **{
                'encrypt': encrypt,
                'module': module,
                'no_log': no_log,
                'proto_handle': proto_handle,
                'catch_response': catch_response
            }
        }

    @property
    def keyword(self):
        for _key in self.mark_not_null_keys:
            if _key not in self._keyword or not self._keyword.get(_key):
                raise ValueError('must give a [{0}] value in @api.mark('
                                 '{0}=\'{{here need a value}}\') '.format(_key))

        return self._keyword

    def __call__(self, f):
        self._func = f
        setattr(f, self.mark_key, MarkData(keywords=self.keyword))
        return f
