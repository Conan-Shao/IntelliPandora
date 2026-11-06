# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : faults.py
@Time  : 2026-11-06

Fault injection through Toxiproxy (docs/design/decisions/18, D4a): make a
downstream slow, cut it, reset its connections -- inside one case, undone
afterwards whatever happens, and written into the evidence.

    from ipandora.core import faults

    with faults.injected(faults.reset_peer('orders-db')):
        resp = OrderApi().pay(order_id)
    assert_all(status_is(resp, 503), ...)        # degraded cleanly, did not charge twice

The service under test reaches the dependency through a Toxiproxy proxy (its
config points at the proxy's port); faults are toxics on that proxy. This
module talks to Toxiproxy's HTTP API with requests -- nothing to install in
Python; Toxiproxy itself is a separate server the environment runs.

Safety:

- **off unless allowed**: `faults.allowed: true` in the environment's config,
  never in an environment named prod or production. Decision 18: local and CI
  only.
- **always undone**: a context manager; the toxics it added are removed on the
  way out, even when the case fails or raises. What a killed process left
  behind is removed when the next run starts (everything named `ipandora-`),
  and again when a run ends.
- **one injector at a time per proxy**: injecting holds the resource lock
  `fault:<proxy>`, across the workers of a parallel run. Cases that only *use*
  the dependency and must not see the fault declare the same resource:
  `@pytest.mark.resource('fault:orders-db')`.

Triage tells the two apart by the moment: a transport error raised while a
fault is in effect says so in its message, and is "an injected fault the
system did not withstand", not "the environment is down". A real outage
after the block is still the environment.
"""
import contextlib
import itertools
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

PREFIX = 'ipandora-'
"""Every toxic this module creates is named with it; cleanup removes only those."""

DEFAULT_URL = 'http://127.0.0.1:8474'
FORBIDDEN_ENVS = ('prod', 'production')

_COUNTER = itertools.count(1)
_TOKEN = '{}{}'.format(PREFIX, os.getpid())


class FaultsNotAllowed(RuntimeError):
    """This environment does not allow fault injection."""


class ToxiproxyError(RuntimeError):
    """Toxiproxy refused a request, or could not be reached."""


@dataclass
class Fault:
    """One fault on one proxy: a Toxiproxy toxic, or the whole proxy disabled (`down`)."""
    proxy: str
    kind: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    stream: str = 'downstream'
    toxicity: float = 1.0
    name: str = ''

    def describe(self) -> str:
        _attrs = ', '.join('{}={}'.format(_k, _v) for _k, _v in sorted(self.attributes.items()))
        return '{}({}{}{}{})'.format(self.kind, self.proxy, ', ' + _attrs if _attrs else '',
                                     '' if self.stream == 'downstream' else ', ' + self.stream,
                                     '' if self.toxicity >= 1 else ', toxicity={:g}'.format(self.toxicity))


def latency(proxy: str, ms: int, jitter: int = 0, stream: str = 'downstream', toxicity: float = 1.0) -> Fault:
    """Every chunk of data is held `ms` (± `jitter`) milliseconds."""
    return Fault(proxy, 'latency', {'latency': int(ms), 'jitter': int(jitter)}, stream, toxicity)


def bandwidth(proxy: str, kbps: int, stream: str = 'downstream') -> Fault:
    """At most `kbps` KB/s gets through."""
    return Fault(proxy, 'bandwidth', {'rate': int(kbps)}, stream)


def timeout(proxy: str, ms: int = 0, stream: str = 'downstream') -> Fault:
    """Nothing gets through; after `ms` the connection is closed (0: held open, silent, until undone)."""
    return Fault(proxy, 'timeout', {'timeout': int(ms)}, stream)


def reset_peer(proxy: str, after_ms: int = 0, stream: str = 'downstream', toxicity: float = 1.0) -> Fault:
    """Connections are reset (TCP RST) after `after_ms`: an abrupt failure, not a clean close."""
    return Fault(proxy, 'reset_peer', {'timeout': int(after_ms)}, stream, toxicity)


def slow_close(proxy: str, ms: int, stream: str = 'downstream') -> Fault:
    """Closing the connection is delayed by `ms`."""
    return Fault(proxy, 'slow_close', {'delay': int(ms)}, stream)


def down(proxy: str) -> Fault:
    """The proxy is disabled: new connections are refused, open ones dropped."""
    return Fault(proxy, 'down')


# -- configuration ---------------------------------------------------------------------------

def _settings() -> Dict[str, Any]:
    from ipandora.core.schedule.runtime import Runtime
    from ipandora.common.dictutils import DictUtils
    return DictUtils.safe_get(Runtime.settings, 'faults') or {}


def _env_name() -> str:
    from ipandora.core.schedule.runtime import Runtime
    return str(getattr(Runtime.Option, 'env', '') or os.environ.get('IPANDORA_ENV', '') or '')


def allowed() -> bool:
    """Whether this environment allows injection: `faults.allowed: true`, and not production."""
    if _env_name().lower() in FORBIDDEN_ENVS:
        return False
    return _settings().get('allowed') is True


def _require_allowed() -> None:
    _env = _env_name()
    if _env.lower() in FORBIDDEN_ENVS:
        raise FaultsNotAllowed('fault injection is never allowed in the {!r} environment'.format(_env))
    if _settings().get('allowed') is not True:
        raise FaultsNotAllowed('fault injection is off in this environment ({}): set `faults: {{allowed: true}}` '
                               'in its conf/<env>.yaml -- local and CI environments only'.format(_env or 'default'))


# -- Toxiproxy -------------------------------------------------------------------------------

class Toxiproxy:
    """A small client for Toxiproxy's HTTP API (v2)."""

    def __init__(self, url: Optional[str] = None, timeout: float = 5.0):
        self.url = (url or _settings().get('toxiproxy') or os.environ.get('TOXIPROXY_URL') or DEFAULT_URL).rstrip('/')
        self.timeout = timeout

    def _call(self, method: str, path: str, body=None, ok=(200, 201, 204)):
        import requests
        try:
            _r = requests.request(method, self.url + path, json=body, timeout=self.timeout,
                                  proxies={'http': None, 'https': None})
        except requests.RequestException as exc:
            raise ToxiproxyError('Toxiproxy at {} is not reachable: {}'.format(self.url, exc)) from None
        if _r.status_code not in ok:
            raise ToxiproxyError('Toxiproxy {} {} answered {}: {}'.format(method, path, _r.status_code,
                                                                       _r.text.strip()[:300]))
        try:
            return _r.json() if _r.content else None
        except ValueError:
            return None

    def version(self) -> str:
        import requests
        try:
            return requests.get(self.url + '/version', timeout=self.timeout,
                                proxies={'http': None, 'https': None}).text.strip()
        except requests.RequestException as exc:
            raise ToxiproxyError('Toxiproxy at {} is not reachable: {}'.format(self.url, exc)) from None

    def proxies(self) -> Dict[str, Dict[str, Any]]:
        return self._call('GET', '/proxies') or {}

    def proxy(self, name: str, listen: str, upstream: str) -> Dict[str, Any]:
        """The proxy `name`, created if missing, updated if it points elsewhere."""
        _existing = self.proxies().get(name)
        if _existing is None:
            return self._call('POST', '/proxies', {'name': name, 'listen': listen, 'upstream': upstream,
                                                   'enabled': True})
        if _existing.get('upstream') != upstream or _existing.get('listen') != listen:
            return self._call('POST', '/proxies/{}'.format(name), {'listen': listen, 'upstream': upstream})
        return _existing

    def delete_proxy(self, name: str) -> None:
        self._call('DELETE', '/proxies/{}'.format(name), ok=(200, 204, 404))

    def enable(self, name: str, enabled: bool) -> None:
        self._call('POST', '/proxies/{}'.format(name), {'enabled': enabled})

    def add_toxic(self, fault: Fault) -> None:
        self._call('POST', '/proxies/{}/toxics'.format(fault.proxy),
                   {'name': fault.name, 'type': fault.kind, 'stream': fault.stream,
                    'toxicity': fault.toxicity, 'attributes': fault.attributes})

    def remove_toxic(self, proxy: str, name: str) -> None:
        self._call('DELETE', '/proxies/{}/toxics/{}'.format(proxy, name), ok=(200, 204, 404))


# -- injecting ---------------------------------------------------------------------------------

def _evidence(fault: Fault, started: float, ended: Optional[float], url: str) -> Dict[str, Any]:
    return {'kind': fault.kind, 'proxy': fault.proxy, 'stream': fault.stream, 'toxicity': fault.toxicity,
            'attributes': dict(fault.attributes), 'name': fault.name, 'description': fault.describe(),
            'started': started, 'ended': ended, 'via': url}


def _apply(client: Toxiproxy, fault: Fault) -> None:
    if fault.kind == 'down':
        # the proxy is disabled; a marker toxic records that it was us, so the
        # next run's cleanup knows to enable it again if this process dies
        client.add_toxic(Fault(fault.proxy, 'latency', {'latency': 0, 'jitter': 0}, name=fault.name))
        client.enable(fault.proxy, False)
    else:
        client.add_toxic(fault)


def _undo(client: Toxiproxy, fault: Fault) -> None:
    if fault.kind == 'down':
        client.enable(fault.proxy, True)
    client.remove_toxic(fault.proxy, fault.name)


_HELD = {}             # proxy -> [ResourceLock, depth]: the locks this process holds
_GUARD = threading.Lock()


class _Held:
    """
    The lock on one proxy, re-entrant within this process. Nested injected()
    blocks on the same proxy -- latency, then a reset on top -- are one case
    and one injector; with a plain file lock the inner block waited for the
    outer one until the resource timeout, then failed.
    """

    def __init__(self, proxy: str):
        self.proxy = proxy

    def acquire(self) -> None:
        with _GUARD:
            if self.proxy in _HELD:
                _HELD[self.proxy][1] += 1
                return
        from ipandora.core.runner.plugin import (DEFAULT_RESOURCE_TIMEOUT, RESOURCE_TIMEOUT_VAR, ResourceLock,
                                                 lock_path)
        try:
            _wait = float(os.environ.get(RESOURCE_TIMEOUT_VAR) or DEFAULT_RESOURCE_TIMEOUT)
        except ValueError:
            _wait = DEFAULT_RESOURCE_TIMEOUT
        _lock = ResourceLock(lock_path('fault:{}'.format(self.proxy)))
        if not _lock.acquire(_wait):
            raise TimeoutError('ipandora: gave up waiting for resource fault:{} after {:g}s: another case is '
                               'injecting faults into it'.format(self.proxy, _wait))
        with _GUARD:
            _HELD[self.proxy] = [_lock, 1]

    def release(self) -> None:
        with _GUARD:
            _entry = _HELD.get(self.proxy)
            if _entry is None:
                return
            _entry[1] -= 1
            if _entry[1] > 0:
                return
            del _HELD[self.proxy]
        _entry[0].release()


def _lock(proxy: str) -> _Held:
    _held = _Held(proxy)
    _held.acquire()
    return _held


_ACTIVE: List[Dict[str, Any]] = []
"""
Faults in effect in this process, innermost last. Process-wide, not
per-thread: a fault on a proxy affects every connection through it,
including those concurrently() makes from its own threads.
"""

INJECTED_MARKER = 'ipandora: during injected fault'
"""Appended to a transport error raised while a fault is in effect (core/protocol/http/transport.py)."""


def active() -> List[Dict[str, Any]]:
    """The faults in effect in this process right now, innermost last."""
    with _GUARD:
        return list(_ACTIVE)


def during() -> str:
    """The marker for a transport error raised now, or '' when no fault is in effect."""
    _now = active()
    if not _now:
        return ''
    return ' ({}: {})'.format(INJECTED_MARKER, ', '.join(_f['description'] for _f in _now))


@contextlib.contextmanager
def injected(*faults: Fault, client: Optional[Toxiproxy] = None) -> Iterator[List[Dict[str, Any]]]:
    """
    Inject `faults` for the duration of the block, then undo them -- also when
    the block raises. Yields the evidence records (one per fault). An undo
    that fails is raised after every other fault has been undone.
    """
    if not faults:
        raise ValueError('injected() needs at least one fault')
    _require_allowed()
    from ipandora.core.evidence import recorder
    _client = client or Toxiproxy()
    _locks, _applied, _records = [], [], []
    try:
        for _proxy in sorted({_f.proxy for _f in faults}):
            _locks.append(_lock(_proxy))
        for _fault in faults:
            _fault.name = _fault.name or '{}-{}'.format(_TOKEN, next(_COUNTER))
            _apply(_client, _fault)
            _applied.append(_fault)
            _entry = _evidence(_fault, time.time(), None, _client.url)
            _records.append(_entry)
            recorder.add_fault(_entry)
        with _GUARD:
            _ACTIVE.extend(_records)
        yield _records
    finally:
        _errors = []
        for _fault, _record in reversed(list(zip(_applied, _records))):
            try:
                _undo(_client, _fault)
            except ToxiproxyError as exc:
                _errors.append(str(exc))
            _record['ended'] = time.time()
        with _GUARD:
            _ACTIVE[:] = [_r for _r in _ACTIVE if not any(_r is _x for _x in _records)]
        for _lock_held in reversed(_locks):
            _lock_held.release()
        if _errors:
            raise ToxiproxyError('could not undo every injected fault -- the next run removes what is left: '
                                 + '; '.join(_errors))


def clean(client: Optional[Toxiproxy] = None) -> List[str]:
    """
    Remove every toxic named `ipandora-...` on every proxy, and enable again
    each proxy one of them marks as disabled by us. Returns what it removed.
    For leftovers of a process that was killed while injecting. A Toxiproxy
    shared by several concurrent runs loses their faults too: give each run
    its own.
    """
    _client = client or Toxiproxy()
    _removed = []
    for _name, _proxy in sorted(_client.proxies().items()):
        _ours = [_t for _t in (_proxy.get('toxics') or []) if str(_t.get('name', '')).startswith(PREFIX)]
        if _ours and not _proxy.get('enabled', True):
            _client.enable(_name, True)
        for _toxic in _ours:
            _client.remove_toxic(_name, _toxic['name'])
            _removed.append('{}/{}'.format(_name, _toxic['name']))
    return _removed


def proxy(name: str, listen: str, upstream: str, client: Optional[Toxiproxy] = None) -> Dict[str, Any]:
    """Make sure the proxy `name` exists: listening on `listen`, forwarding to `upstream`."""
    _require_allowed()
    return (client or Toxiproxy()).proxy(name, listen, upstream)


__all__ = ['Fault', 'latency', 'bandwidth', 'timeout', 'reset_peer', 'slow_close', 'down', 'injected',
           'active', 'during', 'clean', 'proxy', 'allowed', 'Toxiproxy', 'ToxiproxyError', 'FaultsNotAllowed',
           'PREFIX', 'INJECTED_MARKER']
