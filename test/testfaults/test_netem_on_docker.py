# -*- coding: utf-8 -*-
"""
@File  : test_netem_on_docker.py
@Time  : 2026-11-07

tc netem on real containers (D4c): CI's `netem` job runs these against the
runner's Docker -- a busybox web container, faults set by the admitted helper
image in its network namespace -- and they have to take effect and be gone.

Skipped unless IPANDORA_REQUIRE_NETEM (CI: fails without Docker) or
IPANDORA_NETEM_DOCKER=1 (your own Docker) is set.
"""
import os
import socket
import statistics
import subprocess  # nosec B404 -- test code: docker, with arguments
import time

import pytest
import requests

from ipandora.core import faults, netem

REQUIRED = bool(os.environ.get('IPANDORA_REQUIRE_NETEM'))
WEB_IMAGE = ('mirror.gcr.io/library/busybox@'
             'sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec')
NAME = 'ipandora-netem-web'
NO_PROXY = {'http': None, 'https': None}

pytestmark = pytest.mark.skipif(not (REQUIRED or os.environ.get('IPANDORA_NETEM_DOCKER')),
                                reason='no Docker to inject into: set IPANDORA_NETEM_DOCKER=1')


def _docker(*args):
    return subprocess.run(['docker'] + list(args), capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope='module')
def url():
    with socket.socket() as _s:
        _s.bind(('127.0.0.1', 0))
        _port = _s.getsockname()[1]
    subprocess.run(['docker', 'rm', '-f', NAME], capture_output=True)
    try:
        _docker('run', '-d', '--name', NAME, '-p', '127.0.0.1:{}:8080'.format(_port), WEB_IMAGE, 'sh', '-c',
                'mkdir -p /www && echo hello > /www/index.html && exec httpd -f -p 8080 -h /www')
    except (OSError, subprocess.CalledProcessError) as exc:
        if REQUIRED:
            pytest.fail('IPANDORA_REQUIRE_NETEM is set and Docker cannot start the target: {}'.format(exc))
        pytest.skip('Docker cannot start the target: {}'.format(exc))
    _url = 'http://127.0.0.1:{}/'.format(_port)
    assert _until(lambda: _answers(_url), 30), 'the target container does not answer'
    yield _url
    subprocess.run(['docker', 'rm', '-f', NAME], capture_output=True)


@pytest.fixture(autouse=True)
def allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True, 'backends': ['netem'], 'netem': {}})
    monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
    yield
    assert 'netem' not in _docker('run', '--rm', '--network', 'container:' + NAME, '--cap-add', 'NET_ADMIN',
                                  '--entrypoint', 'tc', netem.DEFAULT_IMAGE, 'qdisc', 'show', 'dev', 'eth0'), \
        'a netem qdisc was left on the container'


def _answers(url, timeout=2):
    try:
        return requests.get(url, timeout=timeout, proxies=NO_PROXY).ok
    except requests.RequestException:
        return False


def _until(predicate, seconds):
    _deadline = time.monotonic() + seconds
    while time.monotonic() < _deadline:
        if predicate():
            return True
        time.sleep(0.5)
    return False


def _seconds(url, n=5):
    _t = []
    for _ in range(n):
        _start = time.monotonic()
        requests.get(url, timeout=15, proxies=NO_PROXY).raise_for_status()
        _t.append(time.monotonic() - _start)
    return statistics.median(_t)


WEB = netem.container(NAME)


def test_a_delay_slows_every_answer_and_is_undone(url):
    assert _seconds(url) < 0.5
    with faults.injected(netem.delay(WEB, ms=1000)) as _records:
        assert _seconds(url, 3) >= 1.0
    assert _seconds(url) < 0.5
    assert _records[0]['backend'] == 'netem' and _records[0]['ended'] >= _records[0]['started']


def test_total_loss_stops_answers_and_is_undone(url):
    with faults.injected(netem.loss(WEB, percent=100)):
        assert not _answers(url, timeout=3)
    assert _until(lambda: _answers(url), 10)


def test_faults_on_one_container_add_up_and_come_off_one_by_one(url):
    with faults.injected(netem.delay(WEB, ms=1000)):
        with faults.injected(netem.rate(WEB, kbit=64)):
            assert _seconds(url, 3) >= 1.0
        assert _seconds(url, 3) >= 1.0              # the delay is still there
    assert _seconds(url) < 0.5


def test_what_a_killed_run_left_is_cleaned(url, tmp_path):
    import json
    _b = faults.backend('netem')
    _left = netem.delay(WEB, ms=1000)
    _left.name = 'ipandora-999999-1'
    _b.apply(_left)                                   # as if the process died inside injected()
    netem.Netem._active.clear()
    _marker = _b._marker(NAME)
    _m = json.load(open(_marker, encoding='utf-8'))
    _m['pid'] = 2 ** 22 + 9                            # a process that is gone
    json.dump(_m, open(_marker, 'w', encoding='utf-8'))
    assert _seconds(url, 3) >= 1.0
    assert faults.clean() == ['{}/eth0'.format(NAME)]
    assert _seconds(url) < 0.5
