# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : netem.py
@Time  : 2026-11-07

tc netem as a fault backend (docs/design/decisions/18, D4c): delay, loss,
corruption, duplication and a rate limit on a Docker container's network
interface -- a service of a docker compose stack, say -- through the same
`faults.injected()`, with its safety switch, lock, evidence, attribution and
undo.

    from ipandora.core import faults, netem

    db = netem.container('shop-db-1')
    with faults.injected(netem.delay(db, ms=800, jitter=200), netem.loss(db, percent=5)):
        resp = OrderApi().pay(order_id)

    # conf/<env>.yaml
    faults:
      allowed: true
      backends: [netem]
      netem:
        image: ...      # an image with `tc` (iproute2); default the admitted chaos-daemon image

How: a short-lived helper container joins the target's network namespace
(`docker run --network container:<target> --cap-add NET_ADMIN`) and runs tc
there. The target needs neither tc nor any privilege, and nothing is
installed in it. A container has one root qdisc: the faults in effect on it
are one netem qdisc together, rebuilt as each is added or undone, removed
with the last.

netem acts on what the container *sends*: a delay on a database delays its
answers, not the queries it receives.

A qdisc carries no name or label, so what a run has put on a container is
also written to a marker file, with its host and process: clean() removes
what a dead process of this host left (as for Chaos Mesh, CR20). A container
that restarts gets a new network namespace, without the qdisc.
"""
import json
import os
import shutil
import socket
# bandit B404: docker runs as a list of arguments, never through a shell (_docker)
import subprocess  # nosec B404
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ipandora.core import faults

BACKEND = 'netem'
DEFAULT_IMAGE = ('ghcr.io/chaos-mesh/chaos-daemon@'
                 'sha256:5e735d875fe7cdfbb7366d7826ab67d39a36c4ba26632cc928207abab7e5257d')
"""An image with tc (iproute2): Chaos Mesh's daemon, already admitted (docs/security/components.md)."""

KINDS = ('delay', 'loss', 'corrupt', 'duplicate', 'rate')


@dataclass(frozen=True)
class Container:
    """A Docker container, by name or id, and the interface in its network namespace."""
    name: str
    dev: str = 'eth0'

    def as_dict(self) -> Dict[str, str]:
        return {'name': self.name, 'dev': self.dev}


def container(name: str, dev: str = 'eth0') -> Container:
    """The container `name` (as `docker ps` shows it, or its id); `dev` its interface."""
    if not name or not dev or any(_c.isspace() for _c in name + dev):
        raise ValueError('container(name, dev): a container name or id and an interface')
    return Container(name, dev)


def _fault(kind: str, target: Container, **attributes) -> faults.Fault:
    return faults.Fault(target.name, kind, dict(attributes, container=target.as_dict()), backend=BACKEND)


def _percent(value) -> float:
    _v = float(value)
    if not 0 < _v <= 100:
        raise ValueError('percent: more than 0, at most 100')
    return _v


def delay(target: Container, ms: int, jitter: int = 0) -> faults.Fault:
    """Every packet the container sends is held `ms` (± `jitter`) milliseconds."""
    if int(ms) <= 0 or int(jitter) < 0:
        raise ValueError('delay(ms=...): more than 0; jitter at least 0')
    return _fault('delay', target, latency_ms=int(ms), jitter_ms=int(jitter))


def loss(target: Container, percent: float) -> faults.Fault:
    """`percent` of the packets the container sends are dropped."""
    return _fault('loss', target, percent=_percent(percent))


def corrupt(target: Container, percent: float) -> faults.Fault:
    """`percent` of the packets the container sends get a flipped bit."""
    return _fault('corrupt', target, percent=_percent(percent))


def duplicate(target: Container, percent: float) -> faults.Fault:
    """`percent` of the packets the container sends are sent twice."""
    return _fault('duplicate', target, percent=_percent(percent))


def rate(target: Container, kbit: int) -> faults.Fault:
    """The container sends at most `kbit` kilobits per second."""
    if int(kbit) <= 0:
        raise ValueError('rate(kbit=...): more than 0')
    return _fault('rate', target, kbit=int(kbit))


def netem_args(active: List[faults.Fault]) -> List[str]:
    """
    The netem parameters of all the faults in effect on one container, in the
    order they were added; a later fault of the same kind replaces an earlier.
    """
    _by_kind: Dict[str, faults.Fault] = {}
    for _f in active:
        if _f.kind not in KINDS:
            raise ValueError('netem cannot inject {!r}: {}'.format(_f.kind, ', '.join(KINDS)))
        _by_kind.pop(_f.kind, None)
        _by_kind[_f.kind] = _f
    _args: List[str] = []
    for _kind, _f in _by_kind.items():
        _a = _f.attributes
        if _kind == 'delay':
            _args += ['delay', '{}ms'.format(int(_a['latency_ms']))]
            if int(_a.get('jitter_ms') or 0):
                _args.append('{}ms'.format(int(_a['jitter_ms'])))
        elif _kind == 'rate':
            _args += ['rate', '{}kbit'.format(int(_a['kbit']))]
        else:
            _args += [_kind, '{:g}%'.format(float(_a['percent']))]
    return _args


def _owner() -> Dict[str, Any]:
    return {'host': socket.gethostname(), 'pid': os.getpid()}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Netem(faults.Backend):
    """Faults as one netem qdisc per container, set by a helper container in its network namespace."""

    name = BACKEND

    def __init__(self, settings: Optional[Dict[str, Any]] = None, state_dir: Optional[str] = None):
        _s = dict(settings if settings is not None else (faults._settings().get('netem') or {}))
        self.image = str(_s.get('image') or DEFAULT_IMAGE)
        self.docker = str(_s.get('docker') or 'docker')
        self.timeout = float(_s.get('timeout') or 120)
        if state_dir is None:
            from ipandora.core.runner.plugin import lock_dir
            state_dir = os.path.join(lock_dir(), 'netem')
        self.state_dir = state_dir

    def where(self) -> str:
        return 'docker:{}'.format(os.environ.get('DOCKER_HOST') or 'local')

    # -- running tc in the target's network namespace

    def _docker(self, args: List[str]) -> str:
        _exe = shutil.which(self.docker) or (self.docker if os.path.isfile(self.docker) else None)
        if not _exe:
            raise faults.BackendError('docker not found ({}): netem faults need it'.format(self.docker))
        try:
            # bandit B603: a list of arguments, no shell; the executable is docker, resolved on PATH or configured
            _p = subprocess.run([_exe] + args, capture_output=True, text=True, timeout=self.timeout)  # nosec B603
        except subprocess.TimeoutExpired:
            raise faults.BackendError('docker {} did not answer in {:g}s'.format(' '.join(args[:2]),
                                                                                 self.timeout)) from None
        if _p.returncode:
            raise faults.BackendError('docker {} failed: {}'.format(
                ' '.join(args[:2]), (_p.stderr or _p.stdout).strip()[-500:]))
        return _p.stdout

    def tc(self, target: str, args: List[str]) -> str:
        """`tc args` inside the network namespace of the container `target`."""
        return self._docker(['run', '--rm', '--network', 'container:{}'.format(target), '--cap-add', 'NET_ADMIN',
                             '--entrypoint', 'tc', self.image] + args)

    # -- what is in effect, per container, in this process and on disk

    _active: Dict[str, List[faults.Fault]] = {}
    _guard = threading.Lock()

    def _marker(self, target: str) -> str:
        import hashlib
        return os.path.join(self.state_dir, '{}.json'.format(hashlib.sha256(target.encode('utf-8')).hexdigest()[:16]))

    def _write_marker(self, target: str, dev: str, active: List[faults.Fault]) -> None:
        _path = self._marker(target)
        if not active:
            try:
                os.remove(_path)
            except FileNotFoundError:
                pass
            return
        os.makedirs(self.state_dir, exist_ok=True)
        _tmp = _path + '.tmp'
        with open(_tmp, 'w', encoding='utf-8') as _f:
            json.dump(dict(_owner(), container=target, dev=dev, faults=[_x.name for _x in active]), _f)
        os.replace(_tmp, _path)

    def _set(self, target: str, dev: str, active: List[faults.Fault]) -> None:
        if active:
            self.tc(target, ['qdisc', 'replace', 'dev', dev, 'root', 'netem'] + netem_args(active))
            _shown = self.tc(target, ['qdisc', 'show', 'dev', dev])
            if 'netem' not in _shown:
                raise faults.BackendError('netem on {} is not in effect: tc shows {!r}'.format(target, _shown.strip()))
        else:
            self._delete_root(target, dev)

    def _delete_root(self, target: str, dev: str) -> None:
        try:
            self.tc(target, ['qdisc', 'del', 'dev', dev, 'root'])
        except faults.BackendError as exc:
            # already gone (no netem there), or the container is: nothing left to undo
            if not any(_s in str(exc) for _s in ('No such file or directory', 'Cannot delete qdisc with handle of zero',
                                                 'No such container', 'is not running')):
                raise

    def apply(self, fault: faults.Fault) -> None:
        _c = fault.attributes.get('container')
        if not isinstance(_c, dict):
            raise ValueError('a netem fault needs its container: build it with netem.delay(), loss(), ...')
        netem_args([fault])                                 # refuse an unknown kind before touching anything
        with self._guard:
            _before = list(self._active.get(fault.proxy, []))
            _now = _before + [fault]
            # the marker first (CR21): the helper container takes a second or so, and a run
            # killed meanwhile -- a timeout, a cancelled CI job -- left a qdisc nothing knew of
            self._write_marker(fault.proxy, _c['dev'], _now)
            try:
                self._set(fault.proxy, _c['dev'], _now)
            except faults.BackendError:
                # nothing may stay behind from an apply that failed: back to what was in effect
                try:
                    self._set(fault.proxy, _c['dev'], _before)
                except faults.BackendError:
                    pass
                self._write_marker(fault.proxy, _c['dev'], _before)
                raise
            self._active[fault.proxy] = _now

    def undo(self, fault: faults.Fault) -> None:
        _dev = (fault.attributes.get('container') or {}).get('dev', 'eth0')
        with self._guard:
            _now = [_f for _f in self._active.get(fault.proxy, []) if _f.name != fault.name]
            self._set(fault.proxy, _dev, _now)
            if _now:
                self._active[fault.proxy] = _now
            else:
                self._active.pop(fault.proxy, None)
            self._write_marker(fault.proxy, _dev, _now)

    def clean(self) -> List[str]:
        """
        Remove the netem qdisc a dead process of this host (or this process)
        left on a container, as its marker says. Another live run's, and
        markers written on another host, are left alone.
        """
        if not os.path.isdir(self.state_dir):
            return []
        _removed = []
        for _name in sorted(os.listdir(self.state_dir)):
            if not _name.endswith('.json'):
                continue
            _path = os.path.join(self.state_dir, _name)
            try:
                with open(_path, encoding='utf-8') as _f:
                    _m = json.load(_f)
                _pid = int(_m['pid'])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if _m.get('host') != socket.gethostname() or (_pid != os.getpid() and _alive(_pid)):
                continue
            self._delete_root(str(_m['container']), str(_m.get('dev') or 'eth0'))
            with self._guard:
                self._active.pop(str(_m['container']), None)
            os.remove(_path)
            _removed.append('{}/{}'.format(_m['container'], _m.get('dev') or 'eth0'))
        return _removed


__all__ = ['Container', 'container', 'delay', 'loss', 'corrupt', 'duplicate', 'rate', 'netem_args', 'Netem',
           'BACKEND', 'DEFAULT_IMAGE', 'KINDS']
