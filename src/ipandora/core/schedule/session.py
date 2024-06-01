# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : session.py
@Time  : 2024-04-19
"""
import logging
from threading import current_thread, RLock
from typing import Dict
import requests
from requests.structures import CaseInsensitiveDict
from requests.utils import default_headers

logger = logging.getLogger(__name__)


class Session(object):

    def __init__(self, session: requests.Session = None):
        self._session = session or requests.Session()

        self._default_headers = self._session.headers

        self._global_headers = CaseInsensitiveDict(
            {'Content-type': 'application/json'})

    @property
    def global_headers(self):
        return self._global_headers

    @global_headers.setter
    def global_headers(self, headers: dict = None):
        self._global_headers.update(headers)

    @property
    def default_headers(self):
        return self._default_headers

    @property
    def session(self):
        return self._session

    @property
    def headers(self):
        return self.session.headers

    @headers.setter
    def headers(self, headers: dict = None):
        if not isinstance(headers, dict):
            raise ValueError(
                'headers must be a dict , not a [{}] object/{}'.format(
                    type(headers), headers))

        self.session.headers.update(headers)

    def clearHeaders(self):
        self.session.cookies.clear()
        self.session.headers = default_headers()


class SessionManager(object):
    _session_map = {}  # type:Dict[str,Session]

    _lock = RLock()

    @classmethod
    def getSession(cls) -> requests.Session:
        return cls._get_session_obj().session

    @classmethod
    def setSession(cls, session: requests.Session):
        if isinstance(session, requests.Session):
            cls._session_map[cls.name()] = Session(session)

    @classmethod
    def _get_session_obj(cls) -> Session:
        if cls.name() not in cls._session_map:
            cls.newSession()
        return cls._session_map.get(cls.name())

    @classmethod
    def newSession(cls):
        cls._lock.acquire()
        _new_session = Session()
        cls._session_map[cls.name()] = _new_session
        cls._lock.release()
        return _new_session.session

    @classmethod
    def name(cls):
        _c = current_thread()
        return "{}_{}".format(_c.getName(), _c.ident)

    @classmethod
    def setHeaders(cls, headers: dict = None):
        cls._get_session_obj().headers = headers

    @classmethod
    def getHeaders(cls):
        return cls._get_session_obj().headers

    @classmethod
    def clearHeaders(cls):
        cls._get_session_obj().clearHeaders()


if __name__ == "__main__":
    pass
