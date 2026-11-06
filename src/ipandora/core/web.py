# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : web.py
@Time  : 2026-11-05

Playwright, as it is -- plus the two things a verdict layer needs from it.

"Integrate, don't wrap": tests use Playwright and pytest-playwright directly,
`page`, `expect`, `--browser`, `--headed` and all. Nothing here is an API to
learn. It is installed into every process that runs cases (runner/plugin.py)
and patches Playwright's classes for the duration of a run, so it works
however a test imported them.

1. **expect() is a judgement.** `expect(locator).to_have_text('100.50')` is not
   an `assert` statement, so the assertion-pass hook never sees it, and a test
   written only with expect -- which is how Playwright tests are written --
   read as unverified. Each expect that holds is recorded as a Check, and one
   that fails as a failed Check with Playwright's own message.

2. **A selector that finds nothing is not automatically the test's fault.**
   It may be stale (the page changed its markup, the button is still there)
   or the element may really be gone (a regression). Calling every such
   failure "test problem" is exactly how a self-healing tool hides a removed
   button. The difference is checked deterministically: each locator a passing
   case used is remembered by what it pointed at -- role and accessible name,
   from Playwright's aria snapshot. When it later finds nothing, the page is
   searched for an element with that role and name. Found: the selector is
   stale, the product is fine. Not found: "待确认" -- possibly a defect, with
   the screenshot. Never remembered: also "待确认". When unsure, this never
   leans towards "not the product's problem".

The screenshot and trace of a failure are pytest-playwright's own
(`--screenshot only-on-failure`, `--tracing retain-on-failure`, which run()
turns on); the collector picks them up from the report.

PYTEST_DONT_REWRITE
"""
import json
import os
import re
from contextlib import contextmanager
from typing import Any, Dict, Optional

import pytest

from ipandora.core.assertion.check import Check, Source
from ipandora.core.evidence import recorder

MEMORY_VAR = 'IPANDORA_LOCATOR_MEMORY'
"""Where remembered locators live; run() sets it for every process."""

STALE = 'stale_selector'
MISSING = 'missing'
UNKNOWN = 'unknown'

# Locator methods that resolve the locator to an element: these are where a
# selector either finds what it means or does not.
ACTIONS = ('click', 'dblclick', 'tap', 'hover', 'focus', 'fill', 'clear', 'press',
           'press_sequentially', 'type', 'check', 'uncheck', 'set_checked',
           'select_option', 'set_input_files', 'inner_text', 'text_content',
           'inner_html', 'input_value', 'get_attribute')

# kwargs that change how long to wait, not what is judged
_NOT_PART_OF_THE_CLAIM = ('timeout',)

# `- heading "价格" [level=2]`, `- checkbox "同意" [checked]`: attributes
# follow the name. Without them in the pattern, such lines matched nothing and
# those elements were never remembered.
_ARIA = re.compile(r'^- (?P<role>[\w-]+)(?: "(?P<name>(?:[^"\\]|\\.)*)")?(?: \[[^\]]*\])*'
                   r'(?::\s*(?P<text>.*))?$')

_ORIGINALS = {}
_MEMORY = {'path': None, 'data': None}


def available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


# -- install / uninstall ------------------------------------------------------

def install() -> bool:
    """Patch Playwright's assertion and locator classes. False if Playwright is absent."""
    if _ORIGINALS:
        return True
    if not available():
        return False
    from playwright.sync_api import (APIResponseAssertions, Expect, Locator,
                                     LocatorAssertions, PageAssertions)
    _patch(Expect, '__call__', _keeping_actual(Expect.__call__))
    for _cls in (LocatorAssertions, PageAssertions, APIResponseAssertions):
        for _name in dir(_cls):
            if _name.startswith(('to_', 'not_to_')) and callable(getattr(_cls, _name)):
                _patch(_cls, _name, _judged(getattr(_cls, _name), _name))
    for _name in ACTIONS:
        if hasattr(Locator, _name):
            _patch(Locator, _name, _remembered(getattr(Locator, _name), _name))
    return True


def uninstall() -> None:
    for (_cls, _name), _original in _ORIGINALS.items():
        setattr(_cls, _name, _original)
    _ORIGINALS.clear()
    _MEMORY.update(path=None, data=None)


def _patch(cls, name, replacement):
    _ORIGINALS[(cls, name)] = getattr(cls, name)
    replacement.__wrapped__ = _ORIGINALS[(cls, name)]
    replacement.__doc__ = _ORIGINALS[(cls, name)].__doc__
    setattr(cls, name, replacement)


# -- 1. expect() as a judgement ------------------------------------------------

_ACTUAL = '_ipandora_actual'


def _keeping_actual(original):
    """expect(x) hands back an assertions object; keep the public x on it."""
    def _wrapper(self, actual, *args, **kwargs):
        _assertions = original(self, actual, *args, **kwargs)
        try:
            setattr(_assertions, _ACTUAL, actual)
        except AttributeError:
            pass
        return _assertions
    return _wrapper


def _target(assertions) -> str:
    _kind = type(assertions).__name__
    if _kind == 'LocatorAssertions':
        return 'locator({!r})'.format(selector_of(getattr(assertions, _ACTUAL, None)) or '?')
    if _kind == 'PageAssertions':
        return 'page'
    # Which response: two `expect(r).to_be_ok()` in one case produced the same
    # claim, and the inventory, which compares claims as a set, saw one.
    # The path, not the full URL: a query string often carries an id or a
    # timestamp that differs every run.
    _url = getattr(getattr(assertions, _ACTUAL, None), 'url', '') or ''
    if not isinstance(_url, str) or not _url:
        return 'response'
    from urllib.parse import urlsplit
    return 'response({})'.format(urlsplit(_url).path or '/')


def _shown(value) -> str:
    _pattern = getattr(value, 'pattern', None)
    if isinstance(_pattern, str):
        return '/{}/'.format(_pattern)
    return repr(value)


def claim_for(target: str, method: str, args, kwargs) -> str:
    """`expect locator('#amount') to_have_text '100.50'` -- stable across runs."""
    _parts = ['expect', target, method] + [_shown(_a) for _a in args]
    _parts += ['{}={}'.format(_k, _shown(_v)) for _k, _v in sorted(kwargs.items())
               if _k not in _NOT_PART_OF_THE_CLAIM]
    return ' '.join(_parts)


def _judged(original, method: str):
    def _wrapper(self, *args, **kwargs):
        _claim = claim_for(_target(self), method, args, kwargs)
        try:
            _result = original(self, *args, **kwargs)
        except AssertionError as exc:
            _lines = [_l.strip() for _l in str(exc).splitlines() if _l.strip()]
            recorder.add_checks([Check(name=_claim, ok=False, expr=' / '.join(_lines[:3]),
                                       src=Source.ASSERT, claim=_claim)])
            _locator = getattr(self, _ACTUAL, None)
            if type(self).__name__ == 'LocatorAssertions' and not method.startswith('not_'):
                _diagnose(_locator, method)
            raise
        recorder.add_checks([Check(name=_claim, ok=True, expr=_claim, src=Source.ASSERT,
                                   claim=_claim)])
        if type(self).__name__ == 'LocatorAssertions':
            _note(getattr(self, _ACTUAL, None))
        return _result
    return _wrapper


# -- 2. what a locator pointed at -----------------------------------------------

def _remembered(original, method: str):
    def _wrapper(self, *args, **kwargs):
        _note(self)            # before: a click that navigates leaves nothing to look at after
        try:
            _result = original(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 -- re-raised; only Playwright errors are diagnosed
            if _is_playwright_error(exc):
                _diagnose(self, method)
            raise
        _note(self)
        return _result
    return _wrapper


def _is_playwright_error(exc) -> bool:
    try:
        from playwright.sync_api import Error
    except ImportError:
        return False
    return isinstance(exc, Error)


def selector_of(locator) -> str:
    return getattr(getattr(locator, '_impl_obj', None), '_selector', '') or ''


def identity_of(locator) -> Optional[Dict[str, str]]:
    """
    What one element is, in the terms a person would use: its role and
    accessible name (`button "付款"`), from Playwright's aria snapshot.

    None when the locator does not match exactly one element right now --
    `count()` does not wait, so this never holds a test up.
    """
    try:
        if locator.count() != 1:
            return None
        _line = locator.aria_snapshot(timeout=1000).splitlines()[0].strip()
    except Exception:  # noqa: BLE001 -- best effort; a missing identity means "待确认" later
        return None
    _m = _ARIA.match(_line)
    if not _m:
        return None
    _role, _name, _text = _m.group('role'), _m.group('name'), (_m.group('text') or '').strip()
    if _role == 'text':
        # `- text: "100.50"` quotes text that would otherwise read as YAML
        _name, _text = _text, ''
        if len(_name) >= 2 and _name[0] == _name[-1] == '"':
            _name = _name[1:-1]
    if not _name:
        return None          # nothing a person would recognise it by
    return {'role': _role, 'name': _name.replace('\\"', '"')}


def _note(locator) -> None:
    _evidence = recorder.current()
    if _evidence is None or locator is None:
        return
    _selector = selector_of(locator)
    if not _selector or _selector in _evidence.locators:
        return
    _identity = identity_of(locator)
    if _identity:
        _evidence.locators[_selector] = _identity


def describe(identity: Dict[str, str]) -> str:
    return '{} "{}"'.format(identity.get('role'), identity.get('name'))


def find(page, identity: Dict[str, str]) -> int:
    """How many elements on the page have this role and accessible name."""
    if identity.get('role') == 'text':
        return page.get_by_text(identity['name'], exact=True).count()
    return page.get_by_role(identity['role'], name=identity['name'], exact=True).count()


def _diagnose(locator, method: str) -> None:
    """
    The selector found nothing: stale, or is the element really gone?

    Runs where the failure happens, while the page is still there to look at.
    """
    _evidence = recorder.current()
    if _evidence is None or locator is None:
        return
    try:
        if locator.count() > 0:
            return           # it is there, just not in the state asked for: not a locator problem
        _selector = selector_of(locator)
        _identity = _evidence.locators.get(_selector) or remembered(_evidence.nodeid, _selector)
        _entry = {'selector': _selector, 'action': method}
        if not _identity:
            _entry['verdict'] = UNKNOWN
        else:
            _found = find(locator.page, _identity)
            _entry.update(verdict=STALE if _found else MISSING, identity=_identity, found=_found)
    except Exception:  # noqa: BLE001 -- the diagnosis must never replace the real failure
        return
    _evidence.locator_failures.append(_entry)


# -- memory across runs -------------------------------------------------------------

def artifacts_dir(run_id: str) -> str:
    from ipandora.core.runner import store
    return os.path.join(os.path.dirname(store.runs_dir()), 'artifacts', run_id)


def memory_path() -> str:
    _path = os.environ.get(MEMORY_VAR)
    if _path:
        return _path
    from ipandora.core.runner import store
    return os.path.join(os.path.dirname(store.runs_dir()), 'locators.json')


def _load() -> dict:
    _path = memory_path()
    if _MEMORY['path'] != _path:
        try:
            with open(_path, encoding='utf-8') as _f:
                _data = json.load(_f)
        except (OSError, ValueError):
            _data = {}
        _MEMORY.update(path=_path, data=_data if isinstance(_data, dict) else {})
    return _MEMORY['data']


def remembered(nodeid: str, selector: str) -> Optional[Dict[str, str]]:
    return (_load().get(nodeid) or {}).get(selector)


def remember(result) -> None:
    """
    Keep what each passing case's locators pointed at, for the next run.

    Main process, after a run -- workers only read. A failing case is not
    remembered: what it touched is exactly what is in question.
    """
    _updates = {_c.nodeid: _c.locators for _c in getattr(result, 'cases', ())
                if _c.outcome == 'passed' and getattr(_c, 'locators', None)}
    if not _updates:
        return
    _path = memory_path()
    os.makedirs(os.path.dirname(_path) or '.', exist_ok=True)
    # Two runs finishing together -- two CI jobs, the MCP server and a
    # terminal -- read, merged and wrote the same file, and shared one '.tmp'
    # name: one run's locators were lost, or a half-written temp file was
    # moved into place. Read-modify-write under a lock, temp file per process.
    from ipandora.core.runner.plugin import ResourceLock
    _lock = ResourceLock(_path + '.lock')
    _locked = _lock.acquire(10.0)
    try:
        try:
            with open(_path, encoding='utf-8') as _f:
                _data = json.load(_f)
        except (OSError, ValueError):
            _data = {}
        if not isinstance(_data, dict):
            _data = {}
        for _nodeid, _locators in _updates.items():
            _data.setdefault(_nodeid, {}).update(_locators)
        _tmp = '{}.{}.tmp'.format(_path, os.getpid())
        with open(_tmp, 'w', encoding='utf-8') as _f:
            json.dump(_data, _f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(_tmp, _path)
    finally:
        if _locked:
            _lock.release()
    _MEMORY.update(path=None, data=None)


@contextmanager
def nested_session():
    """
    Let run() start a pytest session while another one's test is running.

    pytest-playwright wraps every test in Playwright's soft-assertion scope,
    which is one process-wide global that refuses to nest. run() is meant to
    be called anywhere in a process -- including from inside a test, which is
    how this framework tests itself -- and the inner session's first test
    failed with "nested soft assertion scopes are not supported". The outer
    scope is set aside for the inner session and put back after.
    """
    try:
        from playwright._impl import _assertions
    except ImportError:
        yield
        return
    _outer = getattr(_assertions, '_soft_errors', None)
    _assertions._soft_errors = None
    try:
        yield
    finally:
        _assertions._soft_errors = _outer


# -- config: conf/<env>.yaml `web:` onto pytest-playwright -----------------------------

def pytest_args(existing, output_dir: str = '') -> list:
    """
    --screenshot / --tracing on failure, plus web.base_url and web.browser from
    the config, for whatever the caller did not already pass.

    `--output` gets a folder of its own per run: pytest-playwright empties its
    output folder when a session starts, so with the shared default
    (test-results) the next run would delete the screenshot an archived report
    still points to.
    """
    import importlib.util
    if importlib.util.find_spec('pytest_playwright') is None:
        return []
    from ipandora.core.schedule.runtime import Runtime
    _given = ' '.join(existing)
    _args = []
    if '--screenshot' not in _given:
        _args += ['--screenshot', 'only-on-failure']
    if '--tracing' not in _given:
        _args += ['--tracing', Runtime.Web.trace]
    if '--output' not in _given and output_dir:
        _args += ['--output', output_dir]
    if '--base-url' not in _given and Runtime.Web.base_url:
        _args += ['--base-url', str(Runtime.Web.base_url)]
    if '--browser' not in _given.replace('--browser-channel', '') and Runtime.Web.browser:
        _args += ['--browser', str(Runtime.Web.browser)]
    return _args


# -- login state: page_as (docs/design/decisions/17 §2.5) ----------------------------------

def _cookie_domain(cookie_domain: str, host: str) -> str:
    """
    The domain as Playwright wants it. A leading dot is kept: it is what makes
    a cookie set with Domain=shop.example reach www.shop.example, and without
    it Playwright treats the cookie as host-only. http.cookiejar names a
    dotless host such as `localhost` 'localhost.local'; that name is turned
    back into the host's own, never into some other host's.
    """
    _domain = cookie_domain or host
    _bare = _domain.lstrip('.')
    if _bare.endswith('.local') and '.' not in _bare[:-len('.local')]:
        return _bare[:-len('.local')]
    return _domain


def _http_only(cookie) -> bool:
    _rest = getattr(cookie, '_rest', None) or {}
    return any(str(_k).lower() == 'httponly' for _k in _rest)


def browser_cookies(cookies, base_url: str = '') -> list:
    """
    Cookies from an HTTP session, as Playwright's add_cookies() takes them.

    Not via a storage-state file: requests' cookies carry no SameSite. A
    cookie with no domain (from a dict) gets web.base_url's host and path
    '/'; a cookie the server scoped keeps its own domain -- leading dot
    included -- and path. Values are text, which is all Playwright accepts.
    """
    from urllib.parse import urlsplit
    _host = (urlsplit(base_url).hostname or '') if base_url else ''
    _out = []
    if cookies is None:
        return _out
    if isinstance(cookies, dict):
        _items = [(_k, _v, None) for _k, _v in cookies.items()]
    else:
        _items = [(_c.name, _c.value, _c) for _c in cookies]
    for _name, _value, _c in _items:
        _domain = _cookie_domain(getattr(_c, 'domain', '') if _c is not None else '', _host)
        if not _domain:
            raise ValueError('cookie {!r} has no domain: set web.base_url so page_as knows '
                             'which site it belongs to'.format(_name))
        _entry = {'name': str(_name), 'value': '' if _value is None else str(_value),
                  'domain': _domain,
                  'path': (getattr(_c, 'path', '') or '/') if _c is not None else '/'}
        if _c is not None:
            _entry['secure'] = bool(_c.secure)
            _entry['httpOnly'] = _http_only(_c)
            if _c.expires:
                _entry['expires'] = float(_c.expires)
        _out.append(_entry)
    return _out


def credential_from_browser(context, local_storage_key: str = None):
    """
    A Credential from a logged-in browser context: its cookies, and with
    `local_storage_key`, a Bearer token read from localStorage.
    """
    import requests
    from ipandora.core import auth
    _jar = requests.cookies.RequestsCookieJar()
    for _c in context.cookies():
        _jar.set(_c['name'], _c['value'], domain=_c.get('domain', ''), path=_c.get('path', '/'))
    if local_storage_key:
        for _origin in context.storage_state().get('origins', []):
            for _item in _origin.get('localStorage', []):
                if _item.get('name') == local_storage_key:
                    _cred = auth.Bearer(_item.get('value', ''))
                    _cred.cookies = _jar
                    return _cred
        raise LookupError('no {!r} in the browser\'s localStorage'.format(local_storage_key))
    return auth.Cookies(_jar)


def share_with_api(name: str, context_or_page, local_storage_key: str = None):
    """
    The other direction (§2.5): a login only the browser can complete (SSO,
    an OAuth code flow), handed to the same identity's HTTP requests. Call it
    with the context or page of page_as(name) -- typically a provider that
    logs in with web_login -- and API calls as `name` use that login from
    then on. Not from inside Provider.login(): pytest-playwright already
    drives the browser in this thread, and a second Playwright cannot start.
    """
    from ipandora.core import auth
    _context = getattr(context_or_page, 'context', context_or_page)
    _cred = credential_from_browser(_context, local_storage_key)
    auth.store(name, _cred)
    return _cred


def _base_url(request) -> str:
    try:
        return request.getfixturevalue('base_url') or ''
    except Exception:  # noqa: BLE001 -- no base_url fixture: fall back to the config
        from ipandora.core.schedule.runtime import Runtime
        return str(Runtime.Web.base_url or '')


SETTLE_MS = 3000
"""How long page_as lets a page settle before checking it is logged in."""


def _settle(page) -> bool:
    """Wait for the network to go quiet, up to SETTLE_MS. False if it never did."""
    try:
        page.wait_for_load_state('networkidle', timeout=SETTLE_MS)
    except Exception:  # noqa: BLE001 -- a page that never goes idle is checked as it is
        return False
    return True


def open_as(new_context, name: str, url: str = None, base_url: str = '',
            login_context=None, context_args: dict = None):
    """page_as without pytest: a page whose context carries `name`'s login."""
    from ipandora.core import auth
    _provider = auth.provider()
    _checked = _provider is not None and auth.managed(name)
    for _attempt in (1, 2):
        _context = _context_for(new_context, _provider, name, base_url,
                                login_context or new_context, context_args or {})
        _page = _context.new_page()
        if not url:
            return _page
        _page.goto(url)
        _ok = _provider.web_logged_in(_page) if _checked else None
        if _ok is True and _provider.login_url:
            # a single-page app checks its session after `load` and sends
            # itself to the login page from script: let it settle first
            _settle(_page)
            _ok = _provider.web_logged_in(_page)
        if _ok is not False:
            return _page
        # sent to the login page: the saved state or cookie is stale. Once more
        # from a fresh login, then it is not the page's problem but the login's
        _landed = _page.url
        _context.close()
        auth.forget(name)
    raise auth.login_failed(name, RuntimeError('{} still lands on the login page ({}) after a '
                                               'fresh login'.format(url, _landed)), 'page')


def _context_for(new_context, provider, name, base_url, login_context, context_args):
    from ipandora.core import auth
    if provider is None or not auth.managed(name):
        if name not in (auth.DEFAULT, auth.ANONYMOUS):
            raise ValueError('page_as({!r}): no login provider manages this identity; register '
                             'one with auth.provider(...) in conftest.py'.format(name))
        return new_context()
    if provider.logs_in_with_page():
        if 'storage_state' in context_args:
            raise ValueError('page_as({!r}) with a page login cannot also take the storage_state '
                             'set in browser_context_args; remove one of the two'.format(name))
        _state = auth.BROWSER_STATES.get(name)
        if _state is None:
            # not traced: the login types a password, and a retained trace
            # of it would end up in a CI artifact
            _login = login_context()
            try:
                with auth.logging_in_as():
                    try:
                        provider.web_login(name, _login.new_page())
                    except Exception as exc:  # noqa: BLE001 -- reported as a login failure
                        raise auth.login_failed(name, exc, 'page login') from exc
                _state = _login.storage_state(indexed_db=bool(provider.web_indexed_db))
            finally:
                _login.close()
            auth.BROWSER_STATES[name] = _state
        _context = new_context(storage_state=_state)
        provider.web_prepare(name, None, _context)
        return _context
    # the API login: the identity's HTTP session logs in, its cookies go to the browser
    from ipandora.core.schedule.session import SessionManager
    with auth.identity(name):
        _session = SessionManager.getSession()
        _version, _credential = auth.credential(name, session=_session)
        _cookies = _credential.cookies if _credential.cookies is not None else _session.cookies
    _list = browser_cookies(_cookies, base_url)      # before the context: may raise
    _context = new_context()
    try:
        if _list:
            _context.add_cookies(_list)
        _headers = provider.web_headers and _credential.headers
        if _headers:
            # added to what the suite's browser_context_args set, not instead
            _context.set_extra_http_headers(dict(context_args.get('extra_http_headers') or {},
                                                 **_credential.headers))
        _delivered = provider.web_prepare(name, _credential, _context)
        if not _list and not _headers and not _delivered:
            raise ValueError(
                'page_as({!r}): the credential has no cookies for the browser. A token in a header '
                'reaches the browser by setting web_headers = True on the provider, by putting it '
                'into storage in web_prepare() and returning True, or by logging in with the page '
                '(web_login)'.format(name))
    except Exception:
        _context.close()
        raise
    return _context


class ContextDefaults:
    """
    web.viewport onto pytest-playwright's browser_context_args.

    Registered as a plugin only when pytest-playwright is loaded, after it, so
    this definition is the one pytest uses and the one it overrides is handed
    in. What the suite's own conftest sets still wins over both.
    """

    @pytest.fixture(scope='session')
    def browser_context_args(self, browser_context_args):
        from ipandora.core.schedule.runtime import Runtime
        _args = dict(browser_context_args)
        _viewport = Runtime.Web.viewport
        if _viewport and 'viewport' not in _args:
            _args['viewport'] = {'width': int(_viewport['width']),
                                 'height': int(_viewport['height'])}
        return _args

    @pytest.fixture
    def page_as(self, new_context, browser, browser_context_args, request):
        """
        page_as('buyer') -> a new page, in its own browser context, logged in
        as buyer. Each call is a separate context, so one case can hold a
        buyer and a seller side by side. page_as('buyer', '/orders/7') opens
        the page and checks it did not land on the login page (see
        Provider.login_url).

        Built with pytest-playwright's new_context, not by overriding
        browser_context_args per test, which keeps only the first test logged
        in (playwright-python #2151).
        """
        _base = _base_url(request)
        _args = dict(browser_context_args)

        def _login_context():
            return browser.new_context(**_args)

        def _open(name: str, url: str = None):
            return open_as(new_context, name, url, base_url=_base,
                           login_context=_login_context, context_args=_args)
        return _open
