# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : auth.py
@Time  : 2026-11-06

Who a request is sent as. docs/design/decisions/17 §2.

A case names an identity; it never touches a credential:

    from ipandora.core import auth

    def test_buyer_cannot_see_other_orders():
        with auth.identity('buyer'):
            r = OrderApi().get(order_of('seller'))
        assert_all(status_is(r, 403))

How an identity gets its credential is the provider's business, written once
in conftest.py, because every system logs in differently:

    class Login(auth.Provider):
        def login(self, name, session):
            r = session.post(BASE + '/login', json={'user': name,
                             'password': auth.secret(name.upper() + '_PASSWORD')})
            return auth.Bearer(r.json()['token'], expires_in=r.json()['expires_in'])

    auth.provider(Login())

What the framework does with it:

- logs in on first use, once per process and identity;
- refreshes early, when less than min(60 s, a fifth of the lifetime) is left;
- when a response says "not logged in" (401 by default; the provider can say
  otherwise), gets a fresh credential and replays that one request once --
  never for a request whose body is a file or a stream, and never for a
  credential the case wrote itself, so "an expired token is rejected" cannot
  be quietly made to pass;
- `anonymous` sends no credential, `default` is the session every case had
  before identities existed and is left alone;
- forgets every credential when the run ends: the MCP server lives across runs.

Credentials stay in memory. They go into requests and nowhere else: the
evidence records the identity's name, and the report masks the headers.
"""
import base64
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

DEFAULT = 'default'
"""The session cases used before identities: no provider, unchanged behaviour."""

ANONYMOUS = 'anonymous'
"""No credential at all: for testing what a logged-out caller gets."""

EARLY_SECONDS = 60.0
EARLY_FRACTION = 0.2

LOGIN_FAILED = 'ipandora: login failed'
"""Start of the error a failed login raises. triage keys on it."""


@dataclass
class Credential:
    """What an identity sends: headers, cookies, query parameters."""
    headers: Dict[str, str] = field(default_factory=dict)
    cookies: Any = None
    """A dict, or a requests cookie jar (keeps domain and path)."""
    params: Dict[str, str] = field(default_factory=dict)
    expires_at: Optional[float] = None
    """Epoch seconds. None: does not expire, or the provider does not know."""
    issued_at: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    """Anything the provider wants back in refresh(): a refresh token, say."""

    def due(self, now: Optional[float] = None) -> bool:
        """Whether to get a new one before using it (§2.3)."""
        if self.expires_at is None:
            return False
        _now = time.time() if now is None else now
        _lifetime = max(self.expires_at - self.issued_at, 0.0)
        return self.expires_at - _now <= min(EARLY_SECONDS, EARLY_FRACTION * _lifetime)


def _jwt_expiry(token: str) -> Optional[float]:
    """`exp` from a JWT's payload, unverified -- only to know when to refresh."""
    _parts = token.split('.')
    if len(_parts) != 3:
        return None
    try:
        _payload = _parts[1] + '=' * (-len(_parts[1]) % 4)
        _exp = json.loads(base64.urlsafe_b64decode(_payload.encode('ascii'))).get('exp')
        return float(_exp) if isinstance(_exp, (int, float)) else None
    except (ValueError, TypeError, AttributeError):
        return None


def Bearer(token: str, expires_in: Optional[float] = None, **data) -> Credential:
    """`Authorization: Bearer <token>`. A JWT's own `exp` is used when expires_in is not given."""
    _now = time.time()
    _expires = _now + float(expires_in) if expires_in is not None else _jwt_expiry(token)
    return Credential(headers={'Authorization': 'Bearer {}'.format(token)},
                      expires_at=_expires, issued_at=_now, data=dict(data))


def ApiKey(value: str, header: str = 'X-Api-Key', param: Optional[str] = None) -> Credential:
    """A fixed key, in a header or, with `param`, in the query string."""
    if param:
        return Credential(params={param: value})
    return Credential(headers={header: value})


def Cookies(cookies=None, expires_in: Optional[float] = None, **values) -> Credential:
    """Cookies: a jar (from the session that logged in), a dict, or keyword values."""
    _now = time.time()
    _jar = cookies if cookies is not None else dict(values)
    return Credential(cookies=_jar, issued_at=_now,
                      expires_at=_now + float(expires_in) if expires_in is not None else None)


class Provider:
    """
    How identities get credentials. Subclass it and register an instance with
    `auth.provider(...)`, usually in conftest.py.
    """

    refresh_on_401 = True
    """Replay a request once after a fresh login when it was rejected as not logged in."""

    def login(self, name: str, session) -> Optional[Credential]:
        """
        Log `name` in and return its credential. `session` is that identity's
        own requests.Session: a login that sets cookies leaves them there, and
        returning None means "the session now carries the login".

        Requests made through the framework's API classes inside login() use
        the same session, and are recorded in the case's evidence as a login.
        """
        raise NotImplementedError('a provider must implement login(name, session)')

    def refresh(self, name: str, credential: Credential, session) -> Optional[Credential]:
        """A new credential from an old one -- with a refresh token, say. Default: log in again."""
        return self.login(name, session)

    def unauthenticated(self, response) -> bool:
        """Whether a response means "not logged in". Default: HTTP 401."""
        return getattr(response, 'status_code', None) == 401

    def sign(self, name: str, credential: Credential, request) -> None:
        """
        Per-request signing (HMAC of timestamp, path and body): change
        `request.kwargs` -- headers, params -- before it is sent. Default: none.
        """

    def manages(self, name: str) -> bool:
        """Which identities this provider logs in. Default: all but default and anonymous."""
        return name not in (DEFAULT, ANONYMOUS)

    # -- the browser (page_as, core/web.py; §2.5) ----------------------------------

    login_url = None
    """A regular expression the *path* of the login page matches in full,
    e.g. r'/login' or r'/auth/.*'. The path only, and in full: /login-history
    or ?next=/login are not the login page. page_as(name, url) checks it
    after opening the page: sent there, it logs in afresh and opens the page
    once more. Without it -- or web_logged_in() -- page_as cannot tell
    "logged in, but the page is not" from a page that works."""

    web_headers = False
    """Send the credential's headers (a Bearer token) with every request the
    browser makes, for an application that reads them. Off by default: the
    browser then sends them to every host a page loads from."""

    web_indexed_db = False
    """Keep IndexedDB in the saved browser state (Firebase keeps its token there)."""

    def web_login(self, name: str, page) -> None:
        """
        Log in through the login page, for systems where only the browser can
        (SSO, a token in localStorage). Implement it and page_as uses it: once
        per identity and process, the browser state saved and reused. Leave it
        out and page_as uses the API login instead -- faster, no login page --
        by moving the identity's cookies into the browser.
        """
        raise NotImplementedError

    def web_prepare(self, name: str, credential: Optional['Credential'], context) -> Optional[bool]:
        """
        Anything else the browser needs before the first page opens: a token
        into sessionStorage, which a saved browser state does not keep --
        `context.add_init_script(...)`. Return True when this put the
        credential into the browser; page_as refuses a header-only credential
        that nothing delivered. Default: nothing.
        """
        return None

    def web_logged_in(self, page) -> Optional[bool]:
        """Whether an opened page is logged in. Default: by login_url; None when unknown."""
        if not self.login_url:
            return None
        import re
        from urllib.parse import urlsplit
        return re.fullmatch(self.login_url, urlsplit(page.url or '').path or '/') is None

    def logs_in_with_page(self) -> bool:
        return type(self).web_login is not Provider.web_login


class _FunctionProvider(Provider):
    def __init__(self, login: Callable):
        self._login = login

    def login(self, name, session):
        return self._login(name, session)


class LoginFailed(RuntimeError):
    """The provider could not log an identity in. Not a defect of the system under test."""


# -- state -------------------------------------------------------------------------------

_STATE = {'provider': None}
BROWSER_STATES = {}
"""identity -> Playwright storage state from a page login; this process only, never on disk."""
_CACHE = {}         # name -> (version, Credential)
_LOCKS = {}         # name -> Lock: one login at a time per identity
_GUARD = threading.Lock()
_LOCAL = threading.local()


def provider(value=None):
    """
    Register the provider: a Provider instance or subclass, or a plain
    function `login(name, session) -> Credential`. Without an argument,
    return the registered one.
    """
    if value is None:
        return _STATE['provider']
    if isinstance(value, type) and issubclass(value, Provider):
        value = value()
    elif not isinstance(value, Provider):
        if not callable(value):
            raise TypeError('auth.provider() takes a Provider or a login(name, session) function')
        value = _FunctionProvider(value)
    _STATE['provider'] = value
    return value


def reset() -> None:
    """
    Forget the provider, every credential and every identity's session.

    Called when a run ends. The MCP server serves many runs from one process,
    and a token from the last run -- or a provider from a conftest.py that has
    since changed -- must not carry over.
    """
    with _GUARD:
        _STATE['provider'] = None
        _CACHE.clear()
        _LOCKS.clear()
        BROWSER_STATES.clear()
    from ipandora.core.schedule.session import SessionManager
    SessionManager.forget_identities()


def _stack():
    _s = getattr(_LOCAL, 'stack', None)
    if _s is None:
        _s = _LOCAL.stack = []
    return _s


def current() -> str:
    """The identity this thread's requests are sent as."""
    _s = _stack()
    return _s[-1] if _s else DEFAULT


@contextmanager
def identity(name: str):
    """
    Send this thread's requests as `name` inside the block. Nests; also works
    as a decorator. Threads started by concurrently() inherit it.
    """
    if not name or not isinstance(name, str):
        raise ValueError('an identity is a non-empty name, got {!r}'.format(name))
    _stack().append(name)
    try:
        yield name
    finally:
        _stack().pop()


def adopt(name: str) -> None:
    """Make a fresh thread send as `name` (core/concurrency.py)."""
    _LOCAL.stack = [] if name == DEFAULT else [name]


def logging_in() -> bool:
    return bool(getattr(_LOCAL, 'logging_in', False))


@contextmanager
def logging_in_as():
    """Requests made inside are a login's: not authenticated, recorded as 'login'. Nests."""
    _before = logging_in()
    _LOCAL.logging_in = True
    try:
        yield
    finally:
        _LOCAL.logging_in = _before


def login_failed(name: str, exc: BaseException, how: str = '') -> 'LoginFailed':
    """The error a failed login raises; triage keys on its first words."""
    return LoginFailed('{} for identity {!r}{}: {}: {}'.format(
        LOGIN_FAILED, name, ' ({})'.format(how) if how else '', type(exc).__name__, exc))


def managed(name: Optional[str] = None) -> bool:
    _name = current() if name is None else name
    _p = _STATE['provider']
    return _p is not None and _p.manages(_name)


def secret(name: str, default: Optional[str] = None) -> str:
    """
    A secret from the environment. Passwords and keys do not belong in
    conf/config.yaml or in the repository (§2.4).
    """
    _value = os.environ.get(name, default)
    if _value is None:
        raise LookupError('secret {} is not set: export it, or set it in the CI job\'s '
                          'secret variables'.format(name))
    return _value


# -- credentials -------------------------------------------------------------------------

def _lock_for(name: str) -> threading.Lock:
    with _GUARD:
        return _LOCKS.setdefault(name, threading.Lock())


def _obtain(name: str, old: Optional[Credential], session) -> Credential:
    _p = _STATE['provider']
    _start = time.time()
    try:
        with logging_in_as():
            _got = _p.login(name, session) if old is None else _p.refresh(name, old, session)
    except Exception as exc:  # noqa: BLE001 -- re-raised as a login failure, with its cause
        raise login_failed(name, exc) from exc
    if _got is None:
        # the login left its cookies in the session
        _got = Credential(cookies=session.cookies.copy(), issued_at=_start)
    if not isinstance(_got, Credential):
        raise LoginFailed('{} for identity {!r}: the provider returned {}, not a Credential'.format(
            LOGIN_FAILED, name, type(_got).__name__))
    if _got.cookies is None and len(session.cookies):
        _got.cookies = session.cookies.copy()
    return _got


def credential(name: Optional[str] = None, session=None):
    """
    (version, Credential) for a managed identity: cached, refreshed when due,
    logged in on first use. None for an identity no provider manages.
    """
    _name = current() if name is None else name
    if not managed(_name):
        return None
    if session is None:
        from ipandora.core.schedule.session import SessionManager
        session = SessionManager.getSession()
    with _lock_for(_name):
        _entry = _CACHE.get(_name)
        if _entry is not None and not _entry[1].due():
            return _entry
        _new = _obtain(_name, _entry[1] if _entry and _entry[1].due() else None, session)
        _entry = ((_entry[0] + 1) if _entry else 1, _new)
        _CACHE[_name] = _entry
        return _entry


def forget(name: str) -> None:
    """
    Make the next use of `name` log in afresh, and drop its browser state.

    The entry is marked expired rather than removed: its version counter must
    keep counting, or a request rejected with version 1 just before would
    find a new version 1 and log in a second time -- on a single-session
    server, revoking the login it was handed.
    """
    with _GUARD:
        BROWSER_STATES.pop(name, None)
        _entry = _CACHE.get(name)
        if _entry is not None:
            from dataclasses import replace as _replace
            _CACHE[name] = (_entry[0], _replace(_entry[1], expires_at=0.0, issued_at=0.0))


def store(name: str, credential: Credential) -> None:
    """
    Use `credential` for `name` from now on: a login done some other way --
    in the browser, by page_as -- handed to the HTTP side (web.share_with_api).
    """
    if not isinstance(credential, Credential):
        raise TypeError('auth.store() takes a Credential')
    with _lock_for(name):
        _entry = _CACHE.get(name)
        _CACHE[name] = ((_entry[0] + 1) if _entry else 1, credential)


def renew(name: str, seen_version: int, session):
    """
    A fresh credential after a rejection. If another thread already renewed
    it since `seen_version` was used, that one is returned instead of logging
    in a second time.
    """
    with _lock_for(name):
        _entry = _CACHE.get(name)
        if _entry is not None and _entry[0] != seen_version:
            return _entry
        _new = _obtain(name, _entry[1] if _entry else None, session)
        _entry = ((_entry[0] + 1) if _entry else 1, _new)
        _CACHE[name] = _entry
        return _entry


# -- requests ----------------------------------------------------------------------------

def _explicit(request) -> Dict[str, str]:
    return {str(_k).lower(): _v for _k, _v in (getattr(request, 'explicit_headers', None) or {}).items()}


def written_by_case(request) -> bool:
    """
    Whether the case put a credential on this request itself: an
    Authorization, Cookie or API-key header of its own. Decided before any
    login, so a case that sends an expired token on purpose does not even
    cause one.
    """
    from ipandora.core.report.redact import SECRET_HEADERS
    return any(_k in SECRET_HEADERS for _k in _explicit(request))


def apply(request, session, entry) -> bool:
    """
    Put a credential into one request. False when the case wrote that
    credential itself -- an Authorization header of its own, say -- in which
    case nothing is changed and the request is never replayed.
    """
    _version, _cred = entry
    _mine = _explicit(request)
    if any(str(_k).lower() in _mine for _k in _cred.headers):
        return False
    _headers = request.kwargs.setdefault('headers', {})
    for _k, _v in _cred.headers.items():
        _headers[_k] = _v
    if _cred.params:
        # whatever form the case gave its own parameters in: a credential
        # quietly left out sent the request unauthenticated, and its replay too
        _params = request.kwargs.get('params')
        if _params is None or isinstance(_params, dict):
            request.kwargs['params'] = dict(_cred.params, **(_params or {}))
        elif isinstance(_params, (list, tuple)):
            _given = {_p[0] for _p in _params if isinstance(_p, (list, tuple)) and _p}
            request.kwargs['params'] = list(_params) + [
                (_k, _v) for _k, _v in _cred.params.items() if _k not in _given]
        elif isinstance(_params, (str, bytes)):
            from urllib.parse import urlencode
            _text = _params.decode('utf-8') if isinstance(_params, bytes) else _params
            request.kwargs['params'] = '&'.join(filter(None, [_text, urlencode(_cred.params)]))
    if _cred.cookies is not None and session is not None:
        if getattr(session, '_ipandora_cookie_version', None) != (id(_cred), _version):
            try:
                session.cookies.update(_cred.cookies)
            except (TypeError, AttributeError):
                for _k, _v in dict(_cred.cookies).items():
                    session.cookies.set(_k, _v)
            session._ipandora_cookie_version = (id(_cred), _version)
    _STATE['provider'].sign(current(), _cred, request)
    return True


def replayable(request) -> bool:
    """A body that can be sent twice: not a file, not a stream (§2.3)."""
    _kw = request.kwargs
    if _kw.get('files'):
        return False
    _data = _kw.get('data')
    return _data is None or isinstance(_data, (str, bytes, dict, list, tuple))


def label() -> str:
    """The identity to record in evidence: '' for the default session."""
    _name = current()
    return '' if _name == DEFAULT else _name
