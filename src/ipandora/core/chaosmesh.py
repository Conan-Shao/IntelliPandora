# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : chaosmesh.py
@Time  : 2026-11-07

Chaos Mesh as a fault backend (docs/design/decisions/18, D4b): faults on the
pods of a Kubernetes cluster -- network delay, loss and partition, a pod that
fails or is killed -- through the same `faults.injected()`, with its safety
switch, lock, evidence, attribution and undo.

    from ipandora.core import chaosmesh, faults

    orders = chaosmesh.pods('orders', namespace='shop', labels={'app': 'orders'})
    with faults.injected(chaosmesh.delay(orders, ms=800, jitter=200)):
        resp = OrderApi().pay(order_id)

    # conf/<env>.yaml
    faults:
      allowed: true
      backends: [toxiproxy, chaos-mesh]
      chaos_mesh:
        context: kind-ipandora      # required: the cluster, named; the current context is never used
        namespace: default          # where the Chaos objects are created
        timeout: 60                 # seconds to wait for a fault to be in effect

A fault is a Chaos Mesh object (NetworkChaos, PodChaos) created with kubectl
and deleted to undo it; it is in effect when Chaos Mesh reports it injected
into every selected pod. Nothing to install in Python: kubectl and a cluster
with Chaos Mesh are the environment's.

Every kubectl call names the context from the config. A developer whose
kubectl points at a production cluster does not inject there by accident:
an environment that does not name its cluster cannot inject at all.
"""
import json
import os
import shutil
# bandit B404: kubectl runs as a list of arguments, never through a shell (_kubectl)
import subprocess  # nosec B404
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ipandora.core import faults

BACKEND = 'chaos-mesh'
MANAGED_BY = 'ipandora'
"""Label app.kubernetes.io/managed-by on every object created here: what clean() lists."""

API_VERSION = 'chaos-mesh.org/v1alpha1'
RESOURCES = {'NetworkChaos': 'networkchaos', 'PodChaos': 'podchaos'}

DEFAULT_TIMEOUT = 60.0


# -- what to inject into ------------------------------------------------------------------------------

@dataclass(frozen=True)
class Pods:
    """The pods a fault acts on: a name for the evidence and the lock, and how Chaos Mesh selects them."""
    name: str
    namespace: str
    labels: Dict[str, str] = field(default_factory=dict)
    mode: str = 'all'
    """all, one, fixed:N, fixed-percent:N, random-max-percent:N -- Chaos Mesh's modes."""

    def selector(self) -> Dict[str, Any]:
        _s: Dict[str, Any] = {'namespaces': [self.namespace]}
        if self.labels:
            _s['labelSelectors'] = dict(self.labels)
        return _s

    def as_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'namespace': self.namespace, 'labels': dict(self.labels), 'mode': self.mode}


def pods(name: str, namespace: str, labels: Optional[Dict[str, str]] = None, mode: str = 'all') -> Pods:
    """The pods of `namespace` carrying `labels` (all of the namespace without), called `name`."""
    if not name or not namespace:
        raise ValueError('pods(name, namespace, labels): a name for the evidence and the namespace')
    _mode = mode.split(':', 1)
    if _mode[0] not in ('all', 'one', 'fixed', 'fixed-percent', 'random-max-percent') or \
            (_mode[0] in ('all', 'one')) != (len(_mode) == 1):
        raise ValueError('pods(mode=...): all, one, fixed:N, fixed-percent:N or random-max-percent:N')
    return Pods(name, namespace, dict(labels or {}), mode)


def _fault(kind: str, target: Pods, **attributes) -> faults.Fault:
    return faults.Fault(target.name, kind, dict(attributes, pods=target.as_dict()), backend=BACKEND)


def delay(target: Pods, ms: int, jitter: int = 0) -> faults.Fault:
    """Every packet the pods send is held `ms` (± `jitter`) milliseconds."""
    return _fault('delay', target, latency_ms=int(ms), jitter_ms=int(jitter))


def loss(target: Pods, percent: float) -> faults.Fault:
    """`percent` of the packets the pods send are dropped."""
    if not 0 < float(percent) <= 100:
        raise ValueError('loss(percent=...): more than 0, at most 100')
    return _fault('loss', target, percent=float(percent))


def partition(target: Pods, peer: Pods) -> faults.Fault:
    """No traffic between the pods of `target` and those of `peer`, either way."""
    return _fault('partition', target, peer=peer.as_dict())


def pod_failure(target: Pods) -> faults.Fault:
    """The pods' containers are replaced by a pause image: they run, and do nothing, until undone."""
    return _fault('pod-failure', target)


def pod_kill(target: Pods) -> faults.Fault:
    """The pods are killed once (their controller starts new ones); undoing only removes the record."""
    return _fault('pod-kill', target)


# -- the Chaos Mesh objects ---------------------------------------------------------------------------

def _selector(spec: Dict[str, Any]) -> Dict[str, Any]:
    return Pods(spec['name'], spec['namespace'], spec.get('labels') or {}, spec.get('mode') or 'all').selector()


def _mode(spec: Dict[str, Any]) -> Dict[str, Any]:
    _m = (spec.get('mode') or 'all').split(':', 1)
    return {'mode': _m[0], **({'value': _m[1]} if len(_m) > 1 else {})}


def manifest(fault: faults.Fault, namespace: str) -> Dict[str, Any]:
    """The Chaos Mesh object for `fault`, created in `namespace`, named fault.name."""
    _a = fault.attributes
    _pods = _a.get('pods')
    if not isinstance(_pods, dict):
        raise ValueError('a chaos-mesh fault needs its pods: build it with chaosmesh.delay(), pod_failure(), ...')
    _spec: Dict[str, Any] = {'selector': _selector(_pods), **_mode(_pods)}
    if fault.kind == 'delay':
        _kind = 'NetworkChaos'
        _spec.update(action='delay', direction='to', delay={
            'latency': '{}ms'.format(int(_a['latency_ms'])), 'jitter': '{}ms'.format(int(_a.get('jitter_ms') or 0)),
            'correlation': '0'})
    elif fault.kind == 'loss':
        _kind = 'NetworkChaos'
        _spec.update(action='loss', direction='to', loss={'loss': '{:g}'.format(float(_a['percent'])),
                                                          'correlation': '0'})
    elif fault.kind == 'partition':
        _kind = 'NetworkChaos'
        _spec.update(action='partition', direction='both',
                     target={'selector': _selector(_a['peer']), **_mode(_a['peer'])})
    elif fault.kind in ('pod-failure', 'pod-kill'):
        _kind = 'PodChaos'
        _spec.update(action=fault.kind)
        if fault.kind == 'pod-kill':
            _spec['gracePeriod'] = 0
    else:
        raise ValueError('chaos-mesh cannot inject {!r}: delay, loss, partition, pod-failure, pod-kill'.format(
            fault.kind))
    return {'apiVersion': API_VERSION, 'kind': _kind,
            'metadata': {'name': fault.name, 'namespace': namespace,
                         'labels': {'app.kubernetes.io/managed-by': MANAGED_BY}},
            'spec': _spec}


def condition(obj: Dict[str, Any], kind: str) -> Optional[bool]:
    """A condition of a Chaos object's status (Selected, AllInjected, AllRecovered): True, False, or None if absent."""
    for _c in ((obj or {}).get('status') or {}).get('conditions') or []:
        if _c.get('type') == kind:
            return str(_c.get('status')) == 'True'
    return None


# -- the backend ---------------------------------------------------------------------------------------

class ChaosMesh(faults.Backend):
    """Faults as Chaos Mesh objects, through kubectl, on the cluster the config names."""

    name = BACKEND

    def __init__(self, settings: Optional[Dict[str, Any]] = None, poll: float = 1.0):
        _s = dict(settings if settings is not None else (faults._settings().get('chaos_mesh') or {}))
        self.context = str(_s.get('context') or '')
        self.namespace = str(_s.get('namespace') or 'default')
        self.timeout = float(_s.get('timeout') or DEFAULT_TIMEOUT)
        self.kubectl = str(_s.get('kubectl') or 'kubectl')
        self.poll = poll

    def where(self) -> str:
        return 'kube-context:{}'.format(self.context)

    def _kubectl(self, args: List[str], stdin: Optional[str] = None, timeout: Optional[float] = None) -> str:
        if not self.context:
            raise faults.BackendError('faults.chaos_mesh.context is not set: name the cluster to inject into -- '
                                      'the current kubectl context is never used')
        _exe = shutil.which(self.kubectl) or (self.kubectl if os.path.isfile(self.kubectl) else None)
        if not _exe:
            raise faults.BackendError('kubectl not found ({}): chaos-mesh faults need it'.format(self.kubectl))
        try:
            # bandit B603: a list of arguments, no shell; the executable is kubectl, resolved on PATH or configured
            _p = subprocess.run([_exe, '--context', self.context] + args,  # nosec B603
                                input=stdin, capture_output=True, text=True,
                                timeout=timeout or self.timeout + 30)
        except subprocess.TimeoutExpired:
            raise faults.BackendError('kubectl {} did not answer in time'.format(' '.join(args[:3]))) from None
        if _p.returncode:
            raise faults.BackendError('kubectl {} failed: {}'.format(
                ' '.join(args[:3]), (_p.stderr or _p.stdout).strip()[-500:]))
        return _p.stdout

    def _get(self, resource: str, name: str) -> Dict[str, Any]:
        return json.loads(self._kubectl(['get', resource, name, '-n', self.namespace, '-o', 'json']) or '{}')

    def _delete(self, resource: str, name: str, namespace: Optional[str] = None) -> None:
        self._kubectl(['delete', resource, name, '-n', namespace or self.namespace, '--ignore-not-found',
                       '--wait=true', '--timeout={:g}s'.format(self.timeout)])

    def apply(self, fault: faults.Fault) -> None:
        _m = manifest(fault, self.namespace)
        _resource = RESOURCES[_m['kind']]
        self._kubectl(['apply', '-f', '-'], stdin=json.dumps(_m))
        _deadline = time.monotonic() + self.timeout
        _obj: Dict[str, Any] = {}
        try:
            while True:
                _obj = self._get(_resource, fault.name)
                if condition(_obj, 'AllInjected'):
                    return
                if condition(_obj, 'Selected') is False and time.monotonic() > _deadline - self.timeout / 2:
                    raise faults.BackendError('{} selected no pod: {}'.format(
                        fault.describe(), json.dumps(_m['spec']['selector'])))
                if time.monotonic() >= _deadline:
                    raise faults.BackendError('{} was not in effect after {:g}s: {}'.format(
                        fault.describe(), self.timeout, json.dumps((_obj.get('status') or {}).get('conditions'))))
                time.sleep(self.poll)
        except faults.BackendError:
            # nothing may stay behind from an apply that failed
            try:
                self._delete(_resource, fault.name)
            except faults.BackendError:
                pass
            raise

    def undo(self, fault: faults.Fault) -> None:
        # deleting the object is how Chaos Mesh recovers the pods; --wait returns once it has
        self._delete(RESOURCES[manifest(fault, self.namespace)['kind']], fault.name)

    def clean(self) -> List[str]:
        _out = json.loads(self._kubectl(['get', ','.join(sorted(RESOURCES.values())), '-A', '-l',
                                         'app.kubernetes.io/managed-by={}'.format(MANAGED_BY), '-o', 'json']) or '{}')
        _removed = []
        for _item in _out.get('items') or []:
            _meta = _item.get('metadata') or {}
            if not str(_meta.get('name', '')).startswith(faults.PREFIX):
                continue
            _resource = RESOURCES.get(_item.get('kind'), str(_item.get('kind', '')).lower())
            self._delete(_resource, _meta['name'], _meta.get('namespace'))
            _removed.append('{}/{}/{}'.format(_meta.get('namespace'), _resource, _meta['name']))
        return _removed


__all__ = ['Pods', 'pods', 'delay', 'loss', 'partition', 'pod_failure', 'pod_kill', 'manifest', 'condition',
           'ChaosMesh', 'BACKEND', 'MANAGED_BY']
