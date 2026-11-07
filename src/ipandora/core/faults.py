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

Backends (decision 18 addendum, D4b): what injects a fault is a `Backend` --
apply, undo, clean up after a killed run, say where it acts. Toxiproxy is the
built-in one. The rest stays here, whatever the backend: the safety switch,
the lock per target, the evidence, the marker triage reads, undoing on the
way out. A company's or a cloud's fault platform is one more `Backend`,
registered with `faults.register()`; a fault names its backend.
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


class BackendError(RuntimeError):
    """A fault backend refused a request, or could not be reached."""


class ToxiproxyError(BackendError):
    """Toxiproxy refused a request, or could not be reached."""


@dataclass
class Fault:
    """
    One fault on one target. For Toxiproxy, the target is a proxy and the
    fault a toxic, or the whole proxy disabled (`down`). Another backend reads
    `proxy` as its own target (a service, a set of pods) and `kind` /
    `attributes` as its own vocabulary.
    """
    proxy: str
    kind: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    stream: str = 'downstream'
    toxicity: float = 1.0
    name: str = ''
    backend: str = 'toxiproxy'

    @property
    def target(self) -> str:
        return self.proxy

    def describe(self) -> str:
        # a nested target (Chaos Mesh's pods) by its name: the target itself is already the first argument
        _attrs = ', '.join('{}={}'.format(_k, _v['name'] if isinstance(_v, dict) and 'name' in _v else _v)
                           for _k, _v in sorted(self.attributes.items()) if _k != 'pods')
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


# -- backends --------------------------------------------------------------------------------

class Backend:
    """
    What injects faults. Subclass it to reach another fault platform, and
    register it (register()); a Fault names it in `backend`.

    A backend only applies and undoes. The framework keeps the rest, the same
    for every backend: injection is off unless the environment allows it; one
    injector at a time per target (resource lock `fault:<target>`); every
    fault is written into the case's evidence with its start and end; a
    transport error raised while it is in effect is marked, so triage says
    "injected", not "environment"; and it is undone on the way out, also when
    the case fails. What a backend must guarantee:

    - `apply(fault)` returns once the fault is in effect, or raises
      BackendError (nothing applied);
    - `undo(fault)` removes exactly that fault -- it may be called for a fault
      already gone, and must not fail then;
    - everything it creates is named with `fault.name`, which starts with
      PREFIX, so `clean()` can find what a killed run left behind and remove
      only that.
    """

    name = ''

    def where(self) -> str:
        """Where it acts, for the evidence (an API's address, a cluster's context)."""
        return self.name

    def apply(self, fault: Fault) -> None:
        raise NotImplementedError

    def undo(self, fault: Fault) -> None:
        raise NotImplementedError

    def clean(self) -> List[str]:
        """Remove every fault named PREFIX...; return what was removed."""
        return []


_BACKENDS: Dict[str, Any] = {}


def register(name: str, factory) -> None:
    """
    Make `factory()` the backend of faults whose `backend` is `name`. A
    factory, not an instance: it is created when a case injects, so it can
    read the environment's config then.
    """
    if not name or not callable(factory):
        raise ValueError('register(name, factory): a name and a callable that returns a Backend')
    _BACKENDS[name] = factory


def backend(name: str) -> Backend:
    """The backend registered as `name`."""
    if name not in _BACKENDS:
        raise ValueError('no fault backend named {!r}: registered are {}'.format(name, ', '.join(sorted(_BACKENDS))))
    return _BACKENDS[name]()


def configured() -> List[str]:
    """
    The backends this environment uses -- `faults.backends` in its config,
    default toxiproxy -- the ones cleaned up when a run starts and ends.
    """
    _names = _settings().get('backends') or ['toxiproxy']
    if isinstance(_names, str):
        _names = [_names]
    return [str(_n) for _n in _names]


# -- Toxiproxy -------------------------------------------------------------------------------

class Toxiproxy(Backend):
    """A small client for Toxiproxy's HTTP API (v2), and the built-in backend."""

    name = 'toxiproxy'

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

    # -- as a Backend

    def where(self) -> str:
        return self.url

    def apply(self, fault: Fault) -> None:
        if fault.kind == 'down':
            # the proxy is disabled; a marker toxic records that it was us, so the
            # next run's cleanup knows to enable it again if this process dies
            self.add_toxic(Fault(fault.proxy, 'latency', {'latency': 0, 'jitter': 0}, name=fault.name))
            self.enable(fault.proxy, False)
        else:
            self.add_toxic(fault)

    def undo(self, fault: Fault) -> None:
        if fault.kind == 'down':
            self.enable(fault.proxy, True)
        self.remove_toxic(fault.proxy, fault.name)

    def clean(self) -> List[str]:
        """
        Remove every toxic named `ipandora-...` on every proxy, and enable again
        each proxy one of them marks as disabled by us.
        """
        _removed = []
        for _name, _proxy in sorted(self.proxies().items()):
            _ours = [_t for _t in (_proxy.get('toxics') or []) if str(_t.get('name', '')).startswith(PREFIX)]
            if _ours and not _proxy.get('enabled', True):
                self.enable(_name, True)
            for _toxic in _ours:
                self.remove_toxic(_name, _toxic['name'])
                _removed.append('{}/{}'.format(_name, _toxic['name']))
        return _removed


register('toxiproxy', Toxiproxy)


def _chaos_mesh():
    from ipandora.core.chaosmesh import ChaosMesh
    return ChaosMesh()


register('chaos-mesh', _chaos_mesh)


# -- injecting ---------------------------------------------------------------------------------

def _evidence(fault: Fault, started: float, ended: Optional[float], via: str, backend_name: str) -> Dict[str, Any]:
    return {'kind': fault.kind, 'proxy': fault.proxy, 'target': fault.proxy, 'backend': backend_name,
            'stream': fault.stream, 'toxicity': fault.toxicity,
            'attributes': dict(fault.attributes), 'name': fault.name, 'description': fault.describe(),
            'started': started, 'ended': ended, 'via': via}


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
def injected(*faults: Fault, client: Optional[Backend] = None) -> Iterator[List[Dict[str, Any]]]:
    """
    Inject `faults` for the duration of the block, then undo them -- also when
    the block raises. Yields the evidence records (one per fault). An undo
    that fails is raised after every other fault has been undone.

    Each fault goes to the backend it names (default toxiproxy); `client`
    is the backend for all of them instead. A fault naming a backend nobody
    registered is refused before anything is applied.
    """
    if not faults:
        raise ValueError('injected() needs at least one fault')
    _require_allowed()
    from ipandora.core.evidence import recorder
    _backends: Dict[str, Backend] = {}
    for _fault in faults:
        if client is None and _fault.backend not in _backends:
            _backends[_fault.backend] = backend(_fault.backend)

    def _of(fault: Fault) -> Backend:
        return client if client is not None else _backends[fault.backend]
    _locks, _applied, _records = [], [], []
    try:
        for _target in sorted({_f.proxy for _f in faults}):
            _locks.append(_lock(_target))
        for _fault in faults:
            _fault.name = _fault.name or '{}-{}'.format(_TOKEN, next(_COUNTER))
            _of(_fault).apply(_fault)
            _applied.append(_fault)
            _entry = _evidence(_fault, time.time(), None, _of(_fault).where(),
                               _of(_fault).name or _fault.backend)
            _records.append(_entry)
            recorder.add_fault(_entry)
        with _GUARD:
            _ACTIVE.extend(_records)
        yield _records
    finally:
        _errors = []
        for _fault, _record in reversed(list(zip(_applied, _records))):
            try:
                _of(_fault).undo(_fault)
            except BackendError as exc:
                _errors.append(str(exc))
            _record['ended'] = time.time()
        with _GUARD:
            _ACTIVE[:] = [_r for _r in _ACTIVE if not any(_r is _x for _x in _records)]
        for _lock_held in reversed(_locks):
            _lock_held.release()
        if _errors:
            _cls = ToxiproxyError if all(isinstance(_of(_f), Toxiproxy) for _f in _applied) else BackendError
            raise _cls('could not undo every injected fault -- the next run removes what is left: '
                       + '; '.join(_errors))


def clean(client: Optional[Backend] = None) -> List[str]:
    """
    Remove every fault named `ipandora-...` that a backend still holds: on
    `client`, or on every backend this environment uses (configured()).
    Returns what it removed. For leftovers of a process that was killed while
    injecting. A backend shared by several concurrent runs loses their faults
    too: give each run its own.
    """
    if client is not None:
        return client.clean()
    _removed = []
    for _name in configured():
        _removed += backend(_name).clean()
    return _removed


def proxy(name: str, listen: str, upstream: str, client: Optional[Toxiproxy] = None) -> Dict[str, Any]:
    """Make sure the proxy `name` exists: listening on `listen`, forwarding to `upstream`."""
    _require_allowed()
    return (client or Toxiproxy()).proxy(name, listen, upstream)


__all__ = ['Fault', 'latency', 'bandwidth', 'timeout', 'reset_peer', 'slow_close', 'down', 'injected',
           'active', 'during', 'clean', 'proxy', 'allowed', 'Backend', 'BackendError', 'register', 'backend',
           'configured', 'Toxiproxy', 'ToxiproxyError', 'FaultsNotAllowed', 'PREFIX', 'INJECTED_MARKER']
