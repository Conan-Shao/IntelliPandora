# -*- coding: utf-8 -*-
"""
@File  : test_chaosmesh.py
@Time  : 2026-11-07

Chaos Mesh as a fault backend (core/chaosmesh.py, D4b), against a stand-in
kubectl that keeps the Chaos objects in a file: the objects made, the wait
for "in effect", the undo, the cleanup, and the named cluster. The real
cluster is CI's `chaos-mesh` job (test_chaosmesh_on_kind.py).
"""
import json
import os
import stat
import sys

import pytest

from ipandora.core import chaosmesh, faults
from ipandora.core.evidence import recorder

FAKE = os.path.join(os.path.dirname(__file__), 'fake_kubectl.py')
ORDERS = chaosmesh.pods('orders', namespace='shop', labels={'app': 'orders'})
DB = chaosmesh.pods('db', namespace='shop', labels={'app': 'db'}, mode='one')


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    """A stand-in kubectl, and an environment allowed to inject into the cluster `kind-test`."""
    _state = tmp_path / 'state.json'
    _exe = tmp_path / 'kubectl'
    _exe.write_text('#!/bin/sh\nexec "{}" "{}" "$@"\n'.format(sys.executable, FAKE), encoding='utf-8')
    _exe.chmod(_exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('FAKE_KUBECTL_STATE', str(_state))
    monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
    _settings = {'allowed': True, 'backends': ['chaos-mesh'],
                 'chaos_mesh': {'context': 'kind-test', 'namespace': 'chaos', 'timeout': 2, 'kubectl': str(_exe)}}
    monkeypatch.setattr(faults, '_settings', lambda: _settings)

    class _Cluster:
        settings = _settings

        @staticmethod
        def state():
            return json.loads(_state.read_text(encoding='utf-8')) if _state.exists() else {'objects': {}, 'calls': []}

        @staticmethod
        def behave(how):
            _s = _Cluster.state()
            _s['behaviour'] = how
            _state.write_text(json.dumps(_s), encoding='utf-8')
    return _Cluster


def backend(cluster):
    return chaosmesh.ChaosMesh(cluster.settings['chaos_mesh'], poll=0.01)


class TestTheObjects:

    def test_delay(self):
        _f = chaosmesh.delay(ORDERS, ms=800, jitter=200)
        _f.name = 'ipandora-1-1'
        assert chaosmesh.manifest(_f, 'chaos') == {
            'apiVersion': 'chaos-mesh.org/v1alpha1', 'kind': 'NetworkChaos',
            'metadata': {'name': 'ipandora-1-1', 'namespace': 'chaos',
                         'labels': {'app.kubernetes.io/managed-by': 'ipandora'}},
            'spec': {'selector': {'namespaces': ['shop'], 'labelSelectors': {'app': 'orders'}}, 'mode': 'all',
                     'action': 'delay', 'direction': 'to',
                     'delay': {'latency': '800ms', 'jitter': '200ms', 'correlation': '0'}}}

    def test_loss_partition_and_pods(self):
        assert chaosmesh.manifest(chaosmesh.loss(ORDERS, 30), 'c')['spec']['loss'] == {'loss': '30',
                                                                                       'correlation': '0'}
        _p = chaosmesh.manifest(chaosmesh.partition(ORDERS, DB), 'c')['spec']
        assert (_p['action'], _p['direction']) == ('partition', 'both')
        assert _p['target'] == {'selector': {'namespaces': ['shop'], 'labelSelectors': {'app': 'db'}}, 'mode': 'one'}
        _failure = chaosmesh.manifest(chaosmesh.pod_failure(ORDERS), 'c')
        assert (_failure['kind'], _failure['spec']['action']) == ('PodChaos', 'pod-failure')
        assert 'gracePeriod' not in _failure['spec']
        _kill = chaosmesh.manifest(chaosmesh.pod_kill(chaosmesh.pods('w', 'shop', mode='fixed-percent:50')), 'c')
        assert (_kill['spec']['action'], _kill['spec']['gracePeriod']) == ('pod-kill', 0)
        assert (_kill['spec']['mode'], _kill['spec']['value']) == ('fixed-percent', '50')
        assert _kill['spec']['selector'] == {'namespaces': ['shop']}            # no labels: the whole namespace

    def test_what_cannot_be_built(self):
        with pytest.raises(ValueError):
            chaosmesh.pods('', 'shop')
        with pytest.raises(ValueError):
            chaosmesh.pods('x', 'shop', mode='fixed')                           # fixed needs its N
        with pytest.raises(ValueError):
            chaosmesh.pods('x', 'shop', mode='one:3')
        with pytest.raises(ValueError):
            chaosmesh.loss(ORDERS, 0)
        with pytest.raises(ValueError, match='cannot inject'):
            chaosmesh.manifest(faults.Fault('orders', 'clock-skew', {'pods': ORDERS.as_dict()}, backend='chaos-mesh'),
                               'c')
        with pytest.raises(ValueError, match='needs its pods'):
            chaosmesh.manifest(faults.Fault('orders', 'delay', {'latency_ms': 1}, backend='chaos-mesh'), 'c')

    def test_described_by_name_not_by_selector(self):
        assert chaosmesh.delay(ORDERS, 800).describe() == 'delay(orders, jitter_ms=0, latency_ms=800)'
        assert chaosmesh.partition(ORDERS, DB).describe() == 'partition(orders, peer=db)'
        assert chaosmesh.pod_failure(ORDERS).backend == 'chaos-mesh'

    def test_conditions(self):
        _obj = {'status': {'conditions': [{'type': 'Selected', 'status': 'True'},
                                          {'type': 'AllInjected', 'status': 'False'}]}}
        assert (chaosmesh.condition(_obj, 'Selected'), chaosmesh.condition(_obj, 'AllInjected'),
                chaosmesh.condition(_obj, 'AllRecovered'), chaosmesh.condition({}, 'Selected')) == (
            True, False, None, None)


class TestInjecting:

    def test_in_effect_for_the_block_then_removed(self, cluster):
        recorder.begin('t::case')
        try:
            with faults.injected(chaosmesh.delay(ORDERS, 800), chaosmesh.pod_failure(DB)) as _records:
                _objects = cluster.state()['objects']
                assert sorted(_k.rsplit('/', 1)[0] for _k in _objects) == ['networkchaos/chaos', 'podchaos/chaos']
                assert [(_r['backend'], _r['target'], _r['via']) for _r in _records] == [
                    ('chaos-mesh', 'orders', 'kube-context:kind-test'), ('chaos-mesh', 'db', 'kube-context:kind-test')]
                assert 'delay(orders, jitter_ms=0, latency_ms=800)' in faults.during()
            assert cluster.state()['objects'] == {}
            assert [_f['backend'] for _f in recorder.current().faults] == ['chaos-mesh', 'chaos-mesh']
        finally:
            recorder.end('t::case')
        # every call names the cluster; deletes wait for Chaos Mesh to recover the pods
        _calls = cluster.state()['calls']
        assert all(_c[:2] == ['--context', 'kind-test'] for _c in _calls)
        assert any(_c[2] == 'delete' and '--wait=true' in _c and '--timeout=2s' in _c for _c in _calls)

    def test_not_in_effect_in_time_is_an_error_and_leaves_nothing(self, cluster):
        cluster.behave('never')
        with pytest.raises(faults.BackendError, match='was not in effect after 2s'):
            with faults.injected(chaosmesh.delay(ORDERS, 100)):
                pytest.fail('the block must not run')
        assert cluster.state()['objects'] == {}

    def test_a_selector_matching_no_pod_says_so(self, cluster):
        cluster.behave('noselect')
        with pytest.raises(faults.BackendError, match='selected no pod.*"app": "orders"'):
            with faults.injected(chaosmesh.pod_failure(ORDERS)):
                pass
        assert cluster.state()['objects'] == {}

    def test_a_refused_object(self, cluster):
        cluster.behave('fail-apply')
        with pytest.raises(faults.BackendError, match='admission webhook denied'):
            with faults.injected(chaosmesh.pod_kill(ORDERS)):
                pass

    def test_an_undo_that_fails_is_raised(self, cluster):
        with pytest.raises(faults.BackendError, match='could not undo every injected fault.*unable to handle'):
            with faults.injected(chaosmesh.delay(ORDERS, 100)):
                cluster.behave('fail-delete')
        assert len(cluster.state()['objects']) == 1                 # left for clean()

    def test_the_cluster_must_be_named(self, cluster):
        _b = chaosmesh.ChaosMesh({'namespace': 'chaos', 'kubectl': cluster.settings['chaos_mesh']['kubectl']})
        with pytest.raises(faults.BackendError, match='context is not set.*never used'):
            _b.apply(chaosmesh.delay(ORDERS, 1))
        assert cluster.state()['calls'] == []                      # kubectl not even run

    def test_no_kubectl(self, cluster):
        _b = chaosmesh.ChaosMesh({'context': 'kind-test', 'kubectl': 'ipandora-no-such-kubectl'})
        with pytest.raises(faults.BackendError, match='kubectl not found'):
            _b.clean()

    def test_still_off_unless_allowed(self, cluster, monkeypatch):
        monkeypatch.setattr(faults, '_settings', lambda: dict(cluster.settings, allowed=False))
        with pytest.raises(faults.FaultsNotAllowed):
            with faults.injected(chaosmesh.delay(ORDERS, 1)):
                pass
        assert cluster.state()['calls'] == []

    def test_the_backend_is_found_without_importing_it_first(self, cluster):
        assert isinstance(faults.backend('chaos-mesh'), chaosmesh.ChaosMesh)
        assert faults.backend('chaos-mesh').context == 'kind-test'      # reads the config when created


class TestCleaning:

    def test_only_ours(self, cluster):
        _b = backend(cluster)
        _f = chaosmesh.delay(ORDERS, 100)
        _f.name = 'ipandora-123-1'
        _b.apply(_f)
        _theirs = chaosmesh.pod_failure(DB)
        _theirs.name = 'someone-else'
        _b.apply(_theirs)
        assert faults.clean() == ['chaos/networkchaos/ipandora-123-1']
        assert list(cluster.state()['objects']) == ['podchaos/chaos/someone-else']


def test_the_cluster_pins_are_registered():
    """What CI's chaos-mesh job installs is what docs/security/components.md admitted."""
    import re
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _registry = open(os.path.join(_root, 'docs', 'security', 'components.md'), encoding='utf-8').read()
    _kind = os.path.join(os.path.dirname(__file__), 'kind')
    _setup = open(os.path.join(_kind, 'setup.sh'), encoding='utf-8').read()
    _pins = dict(re.findall(r"^([A-Z0-9_]+)='?([^'\n]+)'?$", _setup, re.MULTILINE))
    for _name in ('KIND_VERSION', 'KIND_MODULE_HASH', 'CHART_VERSION', 'CHART_SHA256', 'CONTROLLER_DIGEST',
                  'DAEMON_DIGEST'):
        assert _pins.get(_name) and _pins[_name] in _registry, '{}={} is not registered'.format(_name, _pins.get(_name))
    _images = re.findall(r'^\s*image:\s*(\S+)', open(os.path.join(_kind, 'web.yaml'), encoding='utf-8').read(),
                         re.MULTILINE)
    assert _images
    for _image in _images:
        assert '@sha256:' in _image and _image.split('@', 1)[1] in _registry, _image
