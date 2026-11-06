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
            cls._session_map[cls.key()] = Session(session)

    @classmethod
    def _get_session_obj(cls) -> Session:
        # Check-then-act under the lock: two threads racing here would each
        # build a session and one would be discarded along with its cookies.
        _name = cls.key()
        with cls._lock:
            if _name not in cls._session_map:
                cls._session_map[_name] = cls._build_session()
            return cls._session_map.get(_name)

    @classmethod
    def _build_session(cls) -> Session:
        """A session carrying the transport policy (retries, pool sizing)."""
        from ipandora.core.protocol.http.transport import mount
        _session = Session()
        mount(_session.session)
        return _session

    @classmethod
    def newSession(cls):
        # `with` rather than acquire/release: the old form had no try/finally,
        # so any exception in between left the RLock held forever.
        with cls._lock:
            _new_session = cls._build_session()
            cls._session_map[cls.key()] = _new_session
        return _new_session.session

    @classmethod
    def clone(cls, session: requests.Session) -> requests.Session:
        """
        A new session that sends what `session` sends: headers, cookies, auth,
        TLS, proxy and redirect settings.

        For core/concurrency.py. A thread cannot share the caller's session --
        requests does not promise a Session is thread-safe -- and without this
        it got an empty one, so concurrent requests went out logged-out. The
        transport policy (retries, pool size) is mounted fresh, as for any new
        session; adapters a test mounted by hand are not carried over.
        """
        _new = cls._build_session().session
        _new.headers = CaseInsensitiveDict(session.headers)
        _new.cookies = session.cookies.copy()
        _new.auth = session.auth
        _new.proxies = dict(session.proxies or {})
        _new.params = dict(session.params or {})
        _new.verify = session.verify
        _new.cert = session.cert
        _new.trust_env = session.trust_env
        _new.max_redirects = session.max_redirects
        _new.stream = session.stream
        _new.hooks = {_k: list(_v) for _k, _v in (session.hooks or {}).items()}
        return _new

    @classmethod
    def forget(cls):
        """
        Drop this thread's session.

        Sessions are keyed by thread name and ident, and the OS reuses idents.
        A short-lived thread that does not forget its session leaves it for
        the next thread that happens to get the same name and ident -- cookies
        and all. core/concurrency.py calls this as each of its threads ends.
        """
        _prefix = cls.name() + cls.SEP
        with cls._lock:
            for _key in [_k for _k in cls._session_map if _k == cls.name() or _k.startswith(_prefix)]:
                cls._session_map.pop(_key, None)

    @classmethod
    def forget_identities(cls):
        """
        Drop every thread's sessions for named identities; the default ones stay.
        Called when a run ends (core/auth.reset): their cookies are last run's login.
        """
        with cls._lock:
            for _key in [_k for _k in cls._session_map if cls.SEP in _k]:
                cls._session_map.pop(_key, None)

    SEP = '|identity='

    @classmethod
    def key(cls):
        """
        This thread's session for its current identity (core/auth.py). The
        default identity keeps the old key, so existing cases see the same
        session they always did; every other identity has its own -- its own
        cookies and headers -- so a buyer's login never leaks into a seller's
        requests.
        """
        from ipandora.core import auth
        _identity = auth.current()
        return cls.name() if _identity == auth.DEFAULT else cls.name() + cls.SEP + _identity

    @classmethod
    def name(cls):
        _c = current_thread()
        # .name, not .getName() -- deprecated since 3.10
        return "{}_{}".format(_c.name, _c.ident)

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
