# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : markdata.py
@Time  : 2024-04-19
"""


class MarkData(object):

    def __init__(self, keywords: dict = None):
        self._keywords = keywords or {}
        self._doc = ''

    @property
    def doc(self):
        return self._doc

    @doc.setter
    def doc(self, doc):
        self._doc = doc

    @property
    def keyword(self):
        return self._keywords

    @property
    def no_log(self):
        return self.keyword.get('no_log', False)

    @property
    def catch_response(self):
        return self.keyword.get('catch_response', False)

    @property
    def encrypt(self):
        return self.keyword.get('encrypt')

    @property
    def encrypt_data(self):
        return self.keyword.get('encrypt_data')

    @property
    def module(self):
        return self.keyword.get('module')

    @property
    def proto_handle(self):
        return self.keyword.get('proto_handle')

    @property
    def elements(self):
        return self.keyword.get('elements') if self.keyword.get('elements') else False

    def __getattr__(self, item):
        return self.keyword.get(item, None)
