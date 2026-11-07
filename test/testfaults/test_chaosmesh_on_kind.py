# -*- coding: utf-8 -*-
"""
@File  : test_chaosmesh_on_kind.py
@Time  : 2026-11-07

Chaos Mesh on a real cluster (D4b): CI's `chaos-mesh` job makes a kind
cluster with Chaos Mesh and a busybox web service (test/testfaults/kind/),
and these faults have to take effect on it -- and be gone after.

Skipped unless IPANDORA_REQUIRE_CHAOS_MESH (CI: fails without the cluster)
or IPANDORA_KIND_CONTEXT (a cluster you made with kind/setup.sh) is set.
"""
import json
import os
import statistics
import subprocess  # nosec B404 -- test code: kubectl, with arguments
import time

import pytest
import requests

from ipandora.core import chaosmesh, faults

REQUIRED = bool(os.environ.get('IPANDORA_REQUIRE_CHAOS_MESH'))
CONTEXT = os.environ.get('IPANDORA_KIND_CONTEXT') or ('kind-ipandora' if REQUIRED else '')
URL = 'http://127.0.0.1:30080/'
NO_PROXY = {'http': None, 'https': None}
WEB = chaosmesh.pods('web', namespace='shop', labels={'app': 'web'})

pytestmark = pytest.mark.skipif(not CONTEXT, reason='no cluster: set IPANDORA_KIND_CONTEXT (see kind/setup.sh)')


@pytest.fixture(autouse=True)
def cluster(monkeypatch, tmp_path):
    monkeypatch.setattr(faults, '_settings', lambda: {
        'allowed': True, 'backends': ['chaos-mesh'],
        'chaos_mesh': {'context': CONTEXT, 'namespace': 'shop', 'timeout': 120}})
    monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
    if not _until(_answers, 60):
        if REQUIRED:
            pytest.fail('IPANDORA_REQUIRE_CHAOS_MESH is set and the web service does not answer at ' + URL)
        pytest.skip('the web service does not answer at ' + URL)
    yield
    assert _ours() == [], 'a Chaos object was left on the cluster'


def _get(timeout=10, resets=0):
    """
    One answer; `resets` connection resets tried again (none by default).
    The resets seen on CI were the pod leaving its Service: under a 1 s delay
    its readiness probe (1 s timeout) failed -- kind/web.yaml now gives it 5 s.
    """
    for _attempt in range(resets + 1):
        try:
            _r = requests.get(URL, timeout=timeout, proxies=NO_PROXY)
            _r.raise_for_status()
            return _r
        except requests.ConnectionError as exc:
            if 'reset' not in str(exc).lower() or _attempt == resets:
                raise
            print('connection reset, trying again')
            time.sleep(0.5)


def _seconds(n=5):
    _t = []
    for _ in range(n):
        _start = time.monotonic()
        _get()
        _t.append(time.monotonic() - _start)
    return statistics.median(_t)


def _ours():
    _out = subprocess.run(['kubectl', '--context', CONTEXT, 'get', 'networkchaos,podchaos', '-A', '-l',
                           'app.kubernetes.io/managed-by=ipandora', '-o', 'json'],
                          capture_output=True, text=True, check=True).stdout
    return [_i['metadata']['name'] for _i in json.loads(_out)['items']]


def _until(predicate, seconds):
    _deadline = time.monotonic() + seconds
    while time.monotonic() < _deadline:
        if predicate():
            return True
        time.sleep(1)
    return False


def _answers():
    try:
        _get(timeout=2, resets=0)
        return True
    except requests.RequestException:
        return False


def _settled(seconds=15):
    """
    Seconds until the service answers again after an undo -- 0 unless the
    fault took the pod out of its Service. Printed, to keep track of it.
    """
    _start = time.monotonic()
    assert _until(_answers, seconds), 'the service does not answer {}s after the undo'.format(seconds)
    _took = time.monotonic() - _start
    print('answering again {:.2f}s after the undo'.format(_took))
    return _took


def test_a_delay_slows_every_answer_while_it_is_in_effect():
    assert _seconds() < 0.5
    with faults.injected(chaosmesh.delay(WEB, ms=1000)) as _records:
        assert _ours() == [_records[0]['name']]
        assert _seconds(3) >= 1.0
    _settled()
    assert _seconds() < 0.5
    assert _records[0]['backend'] == 'chaos-mesh' and _records[0]['via'] == 'kube-context:' + CONTEXT
    assert _records[0]['ended'] >= _records[0]['started']


def test_a_failed_pod_stops_answering_and_comes_back():
    with faults.injected(chaosmesh.pod_failure(WEB)):
        assert _until(lambda: not _answers(), 60), 'the service still answers with its pod failed'
    assert _until(_answers, 180), 'the service did not come back after the fault was undone'


def test_what_a_killed_run_left_is_cleaned():
    _left = chaosmesh.delay(WEB, ms=1000)
    _left.name = 'ipandora-999999-1'
    faults.backend('chaos-mesh').apply(_left)            # as if the process died inside injected()
    assert _ours() == ['ipandora-999999-1'] and _seconds(3) >= 1.0
    assert faults.clean() == ['shop/networkchaos/ipandora-999999-1']
    _settled()
    assert _seconds() < 0.5
