# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : sessionmodel.py
@Time  : 2024-04-19
"""
from ipandora.core.protocol.http.model.httpmodel import HttpModel
from ipandora.core.schedule.session import SessionManager


class HttpSessionModel(HttpModel):

    @property
    def option(self):
        return self._option.set_request_object(obj=SessionManager.getSession())
