# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : android.py
@Time  : 2026-11-07

uiautomator2, as it is -- plus what a verdict layer needs from it
(docs/design/decisions/14 §5, M5).

"Integrate, don't wrap": a test gets uiautomator2's own Device, and uses its
own API. Nothing here is an API to learn.

    # conf/<env>.yaml
    android:
      serial: emulator-5554        # or $ANDROID_SERIAL; empty: the one device attached
      package: com.example.shop
      app_path: build/shop.apk     # installed once per session (optional)
      clear_data: false            # `pm clear` before each case

    def test_login(android):                     # uiautomator2.Device, the app started
        android(text='Login').click()
        assert android(resourceId='com.example.shop:id/welcome').exists

What the framework adds:

1. **The app's lifecycle.** Installed once per session, started before each
   case (its data cleared first with `clear_data`), stopped after.
2. **One case at a time per device.** The `android` fixture holds the
   resource lock `device:<serial>` across the workers of a parallel run, so
   two workers given the same device take turns.
3. **Evidence of a failure**, taken when it happens: a screenshot, the
   widget tree, and the device log since the case began -- the app's own
   lines and every crash or ANR.
4. **Attribution.** The app crashed or stopped responding (FATAL EXCEPTION or
   ANR of its package in the log) -- a product defect, by rule. A widget a
   selector did not find is looked for by name in the widget tree at that
   moment: a widget of that name is there -- the selector is wrong or stale,
   the test's problem; none is -- "待确认", it may be gone, or the screen may
   not have got there.

The fixture is `android`, not `device`: pytest-playwright already has a
session fixture named `device` (the browser's device emulation), and taking
the name broke every web case. `android_device` is the session's Device,
without the per-case lifecycle or lock.

Installed by `ipandora[android]`; needs adb (bundled by adbutils) and a device
or an emulator.

PYTEST_DONT_REWRITE
"""
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

_log = logging.getLogger(__name__)

STALE = 'stale_selector'
UNKNOWN = 'unknown'
PLATFORM = 'android'

CRASH, ANR = 'crash', 'anr'
LOG_LINES = 300
"""Lines of the device log kept with a failed case."""
EMPTY_KEPT = 20
"""Empty lookups remembered per case."""

NAME_KEYS = ('text', 'textContains', 'textStartsWith', 'description', 'descriptionContains',
             'descriptionStartsWith', 'resourceId')
"""Selector fields that name a widget, as a person would read it on screen or in the layout."""

_lock = threading.Lock()
_sessions: Dict[int, 'Session'] = {}
"""The case running on each thread, and its device: what the failure hooks look at."""


# -- configuration ---------------------------------------------------------------------------

def available() -> bool:
    try:
        import uiautomator2  # noqa: F401
        return True
    except ImportError:
        return False


def settings() -> Dict[str, Any]:
    """The `android` section of the environment's config."""
    from ipandora.core.schedule.runtime import Runtime
    from ipandora.common.dictutils import DictUtils
    _s = DictUtils.safe_get(Runtime.settings, 'android') or {}
    if not isinstance(_s, dict):
        raise ValueError('`android` in the config is a mapping: serial, package, app_path, clear_data')
    _unknown = sorted(set(_s) - {'serial', 'package', 'app_path', 'clear_data', 'keep_app'})
    if _unknown:
        raise ValueError('`android` in the config: unknown key(s) {}'.format(', '.join(_unknown)))
    return dict(_s)


# -- a case on a device ----------------------------------------------------------------------

@dataclass
class Session:
    """One case on one device: what its failure evidence is taken from."""
    device: Any
    serial: str
    package: str = ''
    nodeid: str = ''
    since: str = ''
    """Device time when the case began, as logcat -T reads it (seconds.millis since the epoch)."""
    pids: List[str] = field(default_factory=list)
    empty: List[Dict[str, Any]] = field(default_factory=list)
    """Lookups that came back empty during the case, latest last (at most EMPTY_KEPT): what an assert may be about."""


def current() -> Optional[Session]:
    with _lock:
        return _sessions.get(threading.get_ident())


def active() -> bool:
    return current() is not None


def _shell(device, args: List[str], timeout: float = 30) -> str:
    _out = device.shell(args, timeout=timeout)
    return str(getattr(_out, 'output', _out) or '')


def _device_time(device) -> str:
    """
    The device's clock as logcat -T reads it, to the millisecond.

    Whole seconds were not enough (CR19): `N.000` opens the window up to a
    second early, and a crash the previous case caused in that second became
    this case's -- a product defect, high confidence, on an innocent case.
    The fraction is cut, not rounded: a window opened a few microseconds
    early cannot reach the previous case, one opened late could miss a crash
    on launch. A device whose `date` has no %N (it prints it back) falls back
    to whole seconds.
    """
    try:
        _t = _shell(device, ['date', '+%s.%N']).strip()
        _m = re.fullmatch(r'(\d+)\.(\d{3})\d*', _t)
        if _m:
            return '{}.{}'.format(_m.group(1), _m.group(2))
        return '{}.000'.format(int(_t.split('.', 1)[0]))
    except Exception:  # noqa: BLE001 -- no device time: the log is read without a start
        return ''


def _pids(device, package: str) -> List[str]:
    if not package:
        return []
    try:
        return _shell(device, ['pidof', package]).split()
    except Exception:  # noqa: BLE001
        return []


def begin(device, serial: str, package: str, nodeid: str) -> Session:
    _s = Session(device=device, serial=serial, package=package, nodeid=nodeid, since=_device_time(device),
                 pids=_pids(device, package))
    with _lock:
        _sessions[threading.get_ident()] = _s
    return _s


def end() -> None:
    with _lock:
        _sessions.pop(threading.get_ident(), None)


# -- what the device log says ------------------------------------------------------------------

_FATAL = re.compile(r'FATAL EXCEPTION')
_PROCESS = re.compile(r'Process: (?P<package>[\w.:]+)')
_ANR = re.compile(r'ANR in (?P<package>[\w.:]+)')


def app_events(log: str, package: str) -> List[Dict[str, str]]:
    """
    Crashes and ANRs of `package` in a device log (logcat -v threadtime):
    {'kind': crash|anr, 'package', 'detail'} -- the exception, or the reason.
    Another app's crash is not this case's evidence.
    """
    _lines = (log or '').splitlines()
    _out = []
    for _i, _line in enumerate(_lines):
        if _FATAL.search(_line):
            _block = _lines[_i + 1:_i + 6]
            _process = next((_PROCESS.search(_l) for _l in _block if _PROCESS.search(_l)), None)
            if _process is None or _process.group('package').split(':')[0] != package:
                continue
            _after = _block[next(_j for _j, _l in enumerate(_block) if _PROCESS.search(_l)) + 1:]
            _detail = next((_message(_l) for _l in _after if _message(_l)), '')
            _out.append({'kind': CRASH, 'package': package, 'detail': _detail})
        _anr = _ANR.search(_line)
        if _anr and _anr.group('package').split(':')[0] == package:
            _reason = next((_message(_l) for _l in _lines[_i + 1:_i + 4] if 'Reason:' in _l), '')
            _out.append({'kind': ANR, 'package': package, 'detail': _reason.split('Reason:', 1)[-1].strip()})
    return _out


def _message(line: str) -> str:
    """The message part of a threadtime line: after 'TAG: '."""
    _m = re.match(r'^\S+\s+\S+\s+\d+\s+\d+\s+[VDIWEF]\s+[^:]*:\s?(?P<msg>.*)$', line)
    return (_m.group('msg') if _m else line).strip()


def relevant(log: str, package: str, pids: List[str]) -> str:
    """
    The app's own lines, and every crash and ANR line, of a threadtime log:
    at most LOG_LINES, in their order. Crash and ANR lines are kept first (the
    earliest, if there are more: the first crash is the cause); the room left
    goes to the latest of the others. Keeping just the last LOG_LINES lost
    the FATAL EXCEPTION on CI: after `am crash` the restarted app and the
    system's notes about it filled the window.
    """
    _keep = []
    for _line in (log or '').splitlines():
        _parts = _line.split()
        _pid = _parts[2] if len(_parts) > 2 else ''
        if (_pid and _pid in pids) or 'AndroidRuntime' in _line or (package and package in _line) \
                or 'ANR in' in _line:
            _keep.append(_line)
    _crash = [_i for _i, _l in enumerate(_keep) if 'AndroidRuntime' in _l or 'ANR in' in _l][:LOG_LINES]
    _room = LOG_LINES - len(_crash)
    _crash_set = set(_crash)
    _others = [_i for _i in range(len(_keep)) if _i not in _crash_set]
    _chosen = _crash_set | set(_others[len(_others) - _room:] if _room > 0 else [])
    return '\n'.join(_keep[_i] for _i in sorted(_chosen))


# -- the widget tree -----------------------------------------------------------------------------

def _names(selector: Dict[str, Any]) -> List[str]:
    """What a uiautomator2 selector calls the widget: its text, description or resource id (and the id's name)."""
    _out = []
    for _k in NAME_KEYS:
        _v = selector.get(_k) if isinstance(selector, dict) else None
        if isinstance(_v, str) and _v.strip():
            _out.append(_v.strip())
            if _k == 'resourceId' and ':id/' in _v:
                _out.append(_v.split(':id/', 1)[1])
    return _out


def _xpath_names(xpath: str) -> List[str]:
    """Quoted values in an XPath -- //*[@text="登录"] -- the names it looks for."""
    return [_v for _q in re.findall(r'"([^"]+)"|\'([^\']+)\'', xpath or '') for _v in _q if _v]


def same_name(hierarchy_xml: str, names: List[str]) -> List[Dict[str, str]]:
    """Widgets of the tree whose text, content-desc, resource-id (or the id's name) is one of `names`."""
    if not names or not hierarchy_xml:
        return []
    # bandit B405: the tree comes from the uiautomator server on the device under test, not from a user
    import xml.etree.ElementTree as ET  # nosec B405
    try:
        # bandit B314: expat resolves no external entities, and Python's expat limits entity expansion
        _root = ET.fromstring(hierarchy_xml)  # nosec B314
    except ET.ParseError:
        return []
    _wanted = {_n.lower() for _n in names}
    _found = []
    for _node in _root.iter('node'):
        _rid = _node.get('resource-id') or ''
        for _attr, _value in (('text', _node.get('text') or ''), ('content-desc', _node.get('content-desc') or ''),
                              ('resource-id', _rid), ('resource-id', _rid.split(':id/', 1)[-1] if _rid else '')):
            if _value and _value.lower() in _wanted:
                _found.append({'role': (_node.get('class') or '').rsplit('.', 1)[-1], 'name': _value,
                               'attribute': _attr})
                break
    return _found


def diagnose(selector_text: str, names: List[str], hierarchy_xml: str) -> Dict[str, Any]:
    """A selector found nothing: a widget of that name on screen (stale selector), or not (unknown)."""
    _found = same_name(hierarchy_xml, names)
    _entry: Dict[str, Any] = {'selector': selector_text, 'platform': PLATFORM, 'names': list(names)}
    if _found:
        _entry.update(verdict=STALE, identity={'role': _found[0]['role'], 'name': _found[0]['name']},
                      found=len(_found))
    else:
        _entry['verdict'] = UNKNOWN
    return _entry


def _record_not_found(selector_text: str, names: List[str]) -> None:
    from ipandora.core.evidence import recorder
    _evidence, _session = recorder.current(), current()
    if _evidence is None or _session is None:
        return
    try:
        _xml = _session.device.dump_hierarchy()
    except Exception:  # noqa: BLE001 -- the diagnosis must never replace the real failure
        _xml = ''
    _evidence.locator_failures.append(diagnose(selector_text, names, _xml))


def _record_empty(selector_text: str, names: List[str]) -> None:
    """
    A lookup that found nothing without raising -- `d(...).exists`, `d(...).wait()`
    false. Not a failure: a test may look for an optional dialog. Remembered
    in case an assert is about it (asserted_lookup()).
    """
    _session = current()
    if _session is None or not names:
        return
    _session.empty.append({'selector': selector_text, 'names': list(names)})
    del _session.empty[:-EMPTY_KEPT]


def asserted_lookup(session: Session, failure: str) -> Optional[Dict[str, Any]]:
    """
    The latest empty lookup a failed assert is about: one of its names,
    quoted, in the assertion's text -- pytest spells the call out
    (`where ... = <Device>(text='欢迎')`) and the statement is part of it.
    Quoted, so a name like OK does not match any message holding the word.
    """
    for _e in reversed(session.empty if session else []):
        if any("'{}'".format(_n) in (failure or '') or '"{}"'.format(_n) in (failure or '') for _n in _e['names']):
            return _e
    return None


# -- patching uiautomator2 for the run ---------------------------------------------------------------

_originals: List[tuple] = []


def install() -> bool:
    """Diagnose every selector that finds nothing, for this run. False without uiautomator2."""
    if not available() or _originals:
        return bool(_originals)
    from uiautomator2 import _selector, xpath
    from uiautomator2.exceptions import UiObjectNotFoundError, XPathElementNotFoundError

    _must_wait = _selector.UiObject.must_wait

    def must_wait(self, exists=True, timeout=None):
        try:
            return _must_wait(self, exists, timeout)
        except UiObjectNotFoundError:
            if exists:
                _record_not_found(str(self.selector), _names(self.selector))
            raise
    _patch(_selector.UiObject, 'must_wait', _must_wait, must_wait)

    # CR19: `assert d(text=...).exists` failing was a plain assert -- a product
    # defect, even when the selector was stale. Empty lookups are remembered,
    # and keep_evidence() diagnoses the one the failed assert names.
    _wait = _selector.UiObject.wait

    def wait(self, exists=True, timeout=None):
        _found = _wait(self, exists, timeout)
        if exists and not _found:
            _record_empty(str(self.selector), _names(self.selector))
        return _found
    _patch(_selector.UiObject, 'wait', _wait, wait)

    from uiautomator2 import utils
    _nonzero = utils.Exists.__nonzero__

    def __nonzero__(self):
        _found = _nonzero(self)
        if not _found:
            _record_empty(str(self.uiobject.selector), _names(self.uiobject.selector))
        return _found
    _patch(utils.Exists, '__nonzero__', _nonzero, __nonzero__)

    _cls = getattr(xpath, 'DeviceXPathSelector', None) or getattr(xpath, 'XPathSelector')
    _get = _cls.get

    def get(self, timeout=None):
        try:
            return _get(self, timeout)
        except XPathElementNotFoundError:
            _x = str(getattr(self, '_base_xpath', '') or self)
            _record_not_found(_x, _xpath_names(_x))
            raise
    _patch(_cls, 'get', _get, get)
    return True


def _patch(cls, name, original, replacement) -> None:
    setattr(cls, name, replacement)
    _originals.append((cls, name, original))


def uninstall() -> None:
    while _originals:
        _cls, _name, _original = _originals.pop()
        setattr(_cls, _name, _original)


# -- evidence of a failure -------------------------------------------------------------------------

def _artifacts_dir() -> str:
    from ipandora.core.assertion.visual import ARTIFACTS_VAR
    _dir = os.environ.get(ARTIFACTS_VAR) or os.path.join(tempfile.gettempdir(), 'ipandora-android')
    os.makedirs(_dir, exist_ok=True)
    return _dir


def _slug(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', text)[-100:]


def keep_evidence(nodeid: str, failure: str = '') -> List[Dict[str, Any]]:
    """
    The screenshot, widget tree and device log of the case failing on this
    thread, as its artifacts; the app's crashes and ANRs as its app events.
    Each piece is taken on its own: a device that cannot screenshot still
    gives its log. `failure` is the text of a failed assert: when it names a
    lookup that came back empty, that lookup is diagnosed against this
    widget tree, as a failed click is.
    """
    from ipandora.core.evidence import recorder
    from ipandora.core.report.redact import redact_text
    _s = current()
    if _s is None:
        return []
    _base = os.path.join(_artifacts_dir(), '{}-{}'.format(_slug(nodeid), int(time.time() * 1000)))
    _out = []
    try:
        _s.device.screenshot(_base + '.png')
        _out.append({'kind': 'screenshot', 'path': os.path.abspath(_base + '.png'), 'group': _s.serial})
    except Exception as exc:  # noqa: BLE001 -- evidence must never break the run
        _log.debug('no screenshot of %s: %s', nodeid, exc)
    _xml = ''
    try:
        _xml = _s.device.dump_hierarchy()
        with open(_base + '.xml', 'w', encoding='utf-8') as _f:
            _f.write(_xml)
        _out.append({'kind': 'hierarchy', 'path': os.path.abspath(_base + '.xml'), 'group': _s.serial})
    except Exception as exc:  # noqa: BLE001
        _log.debug('no widget tree of %s: %s', nodeid, exc)
    _lookup = asserted_lookup(_s, failure)
    _evidence = recorder.current()
    if _lookup is not None and _evidence is not None:
        _evidence.locator_failures.append(dict(diagnose(_lookup['selector'], _lookup['names'], _xml), asserted=True))
    _events = []
    try:
        _logcat = _shell(_s.device, ['logcat', '-d', '-v', 'threadtime', '-b', 'main,system,crash']
                         + (['-T', _s.since] if _s.since else []), timeout=60)
        _events = app_events(_logcat, _s.package)
        _text = redact_text(relevant(_logcat, _s.package, _s.pids + _pids(_s.device, _s.package)))
        if _text:
            with open(_base + '.log', 'w', encoding='utf-8') as _f:
                _f.write(_text + '\n')
            _out.append({'kind': 'device-log', 'path': os.path.abspath(_base + '.log'), 'group': _s.package or _s.serial,
                         'text': _text})
    except Exception as exc:  # noqa: BLE001
        _log.debug('no device log of %s: %s', nodeid, exc)
    for _entry in _out:
        recorder.add_artifact(_entry)
    for _event in _events:
        recorder.add_app_event(_event)
    return _out


# -- fixtures --------------------------------------------------------------------------------------

class Fixtures:
    """Registered as a pytest plugin when uiautomator2 is installed (core/runner/plugin.py)."""

    @pytest.fixture(scope='session')
    def android_device(self, request):
        """The uiautomator2 Device of `android.serial` (or $ANDROID_SERIAL), the app installed once."""
        import uiautomator2
        _s = settings()
        _serial = str(_s.get('serial') or os.environ.get('ANDROID_SERIAL') or '') or None
        _device = uiautomator2.connect(_serial)
        _app = _s.get('app_path')
        if _app:
            _path = _app if os.path.isabs(str(_app)) else os.path.join(str(request.config.rootpath), str(_app))
            if not os.path.isfile(_path):
                raise FileNotFoundError('android.app_path: no such file {}'.format(_path))
            _device.app_install(_path)
        return _device

    @pytest.fixture
    def android(self, android_device, request):
        """The device for this case, held for it alone, its app started (and its data cleared with clear_data)."""
        from ipandora.core.runner import plugin
        _s = settings()
        _package = str(_s.get('package') or '')
        _serial = str(getattr(android_device, 'serial', '') or _s.get('serial') or 'default')
        _held = plugin.ResourceLock(plugin.lock_path('device:{}'.format(_serial)))
        _timeout = float(os.environ.get(plugin.RESOURCE_TIMEOUT_VAR) or plugin.DEFAULT_RESOURCE_TIMEOUT)
        if not _held.acquire(_timeout):
            pytest.fail('{} {!r} after {:g}s: another case or another run on this machine still holds it'.format(
                plugin.RESOURCE_WAIT_MARKER, 'device:{}'.format(_serial), _timeout), pytrace=False)
        try:
            # the log window opens before the app starts: a crash on launch is this case's
            _session = begin(android_device, _serial, _package, request.node.nodeid)
            if _package:
                if _s.get('clear_data'):
                    android_device.app_clear(_package)
                android_device.app_start(_package, stop=True)
                _session.pids = _pids(android_device, _package)
            yield android_device
        finally:
            end()
            try:
                if _package and not _s.get('keep_app'):
                    android_device.app_stop(_package)
            finally:
                _held.release()


__all__ = ['Fixtures', 'Session', 'app_events', 'diagnose', 'same_name', 'relevant', 'keep_evidence', 'install',
           'uninstall', 'asserted_lookup', 'available', 'settings', 'active', 'current', 'begin', 'end', 'STALE', 'UNKNOWN', 'CRASH',
           'ANR', 'PLATFORM']
