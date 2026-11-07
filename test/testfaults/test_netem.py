# -*- coding: utf-8 -*-
"""
@File  : test_netem.py
@Time  : 2026-11-07

tc netem as a fault backend (core/netem.py, D4c), against a stand-in docker
that keeps each container's qdisc in a file: one netem qdisc per container,
rebuilt as faults come and go, removed with the last; markers for cleanup.
The real thing is CI's `netem` job (test_netem_on_docker.py).
"""
import json
import os
import stat
import sys

import pytest

from ipandora.core import faults, netem
from ipandora.core.evidence import recorder

FAKE = os.path.join(os.path.dirname(__file__), 'fake_docker.py')
DB = netem.container('shop-db-1')
WEB = netem.container('shop-web-1', dev='eth1')


@pytest.fixture
def docker(tmp_path, monkeypatch):
    _state = tmp_path / 'docker.json'
    _state.write_text(json.dumps({'containers': ['shop-db-1', 'shop-web-1']}), encoding='utf-8')
    _exe = tmp_path / 'docker'
    _exe.write_text('#!/bin/sh\nexec "{}" "{}" "$@"\n'.format(sys.executable, FAKE), encoding='utf-8')
    _exe.chmod(_exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('FAKE_DOCKER_STATE', str(_state))
    monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
    _settings = {'allowed': True, 'backends': ['netem'], 'netem': {'docker': str(_exe), 'image': 'tc-image'}}
    monkeypatch.setattr(faults, '_settings', lambda: _settings)
    monkeypatch.setattr(netem.Netem, '_active', {})

    class _Docker:
        @staticmethod
        def state():
            return json.loads(_state.read_text(encoding='utf-8'))

        @staticmethod
        def set(**values):
            _s = _Docker.state()
            _s.update(values)
            _state.write_text(json.dumps(_s), encoding='utf-8')
    return _Docker


def markers(tmp_path):
    _dir = tmp_path / 'locks' / 'netem'
    return sorted(json.loads(_p.read_text(encoding='utf-8'))['faults'] for _p in _dir.glob('*.json')) \
        if _dir.exists() else []


class TestTheQdisc:

    def test_parameters(self):
        assert netem.netem_args([netem.delay(DB, 800, jitter=200)]) == ['delay', '800ms', '200ms']
        assert netem.netem_args([netem.delay(DB, 800), netem.loss(DB, 5), netem.rate(DB, 512)]) == [
            'delay', '800ms', 'loss', '5%', 'rate', '512kbit']
        assert netem.netem_args([netem.corrupt(DB, 0.5), netem.duplicate(DB, 1)]) == [
            'corrupt', '0.5%', 'duplicate', '1%']
        # a later fault of a kind replaces the earlier one, at the end
        assert netem.netem_args([netem.loss(DB, 5), netem.delay(DB, 10), netem.loss(DB, 50)]) == [
            'delay', '10ms', 'loss', '50%']
        assert netem.netem_args([]) == []

    def test_what_cannot_be_built(self):
        for _bad in (lambda: netem.container(''), lambda: netem.container('a b'), lambda: netem.container('x', dev=''),
                     lambda: netem.delay(DB, 0), lambda: netem.delay(DB, 10, jitter=-1), lambda: netem.loss(DB, 0),
                     lambda: netem.loss(DB, 101), lambda: netem.rate(DB, 0)):
            with pytest.raises(ValueError):
                _bad()
        with pytest.raises(ValueError, match='cannot inject'):
            netem.netem_args([faults.Fault('db', 'reorder', {}, backend='netem')])

    def test_described_by_container(self):
        assert netem.delay(DB, 800).describe() == 'delay(shop-db-1, container=shop-db-1, jitter_ms=0, latency_ms=800)'
        assert netem.loss(DB, 5).backend == 'netem' and netem.loss(DB, 5).target == 'shop-db-1'


class TestInjecting:

    def test_faults_on_one_container_are_one_qdisc(self, docker, tmp_path):
        recorder.begin('t::case')
        try:
            with faults.injected(netem.delay(DB, 800)) as _outer:
                assert docker.state()['qdiscs'] == {'shop-db-1/eth0': ['delay', '800ms']}
                with faults.injected(netem.loss(DB, 30), netem.rate(WEB, 256)):
                    assert docker.state()['qdiscs'] == {'shop-db-1/eth0': ['delay', '800ms', 'loss', '30%'],
                                                        'shop-web-1/eth1': ['rate', '256kbit']}
                    assert len(markers(tmp_path)) == 2
                assert docker.state()['qdiscs'] == {'shop-db-1/eth0': ['delay', '800ms']}
                assert [_r['backend'] for _r in _outer] == ['netem'] and _outer[0]['via'].startswith('docker:')
            assert docker.state()['qdiscs'] == {} and markers(tmp_path) == []
            assert [_f['kind'] for _f in recorder.current().faults] == ['delay', 'loss', 'rate']
        finally:
            recorder.end('t::case')
        # every helper joins the target's namespace with NET_ADMIN, from the configured image
        _runs = [_c for _c in docker.state()['calls']]
        assert all(_c[:8] == ['run', '--rm', '--network', 'container:' + _c[3].split(':', 1)[1], '--cap-add',
                              'NET_ADMIN', '--entrypoint', 'tc'] and _c[8] == 'tc-image' for _c in _runs)

    def test_a_refused_fault_leaves_what_was_there(self, docker):
        with faults.injected(netem.delay(DB, 100)):
            docker.set(behaviour='not-shown')
            with pytest.raises(faults.BackendError, match='not in effect'):
                with faults.injected(netem.loss(DB, 10)):
                    pass
            docker.set(behaviour='')
            assert docker.state()['qdiscs'] == {'shop-db-1/eth0': ['delay', '100ms']}
        assert docker.state()['qdiscs'] == {}

    def test_a_refused_replace(self, docker):
        docker.set(behaviour='fail-replace')
        with pytest.raises(faults.BackendError, match='Exclusivity flag'):
            with faults.injected(netem.delay(DB, 100)):
                pass
        assert docker.state()['qdiscs'] == {}

    def test_no_such_container(self, docker):
        with pytest.raises(faults.BackendError, match='No such container'):
            with faults.injected(netem.delay(netem.container('gone'), 100)):
                pass

    def test_undo_when_the_container_is_gone_is_not_an_error(self, docker):
        with faults.injected(netem.delay(DB, 100)):
            docker.set(containers=['shop-web-1'], qdiscs={})       # the container went away
        assert docker.state()['qdiscs'] == {}

    def test_no_docker(self, docker):
        _b = netem.Netem({'docker': 'ipandora-no-such-docker'}, state_dir='/nonexistent')
        with pytest.raises(faults.BackendError, match='docker not found'):
            _b.apply(netem.delay(DB, 1))

    def test_still_off_unless_allowed(self, docker, monkeypatch):
        monkeypatch.setattr(faults, '_settings', lambda: {'allowed': False})
        with pytest.raises(faults.FaultsNotAllowed):
            with faults.injected(netem.delay(DB, 1)):
                pass
        assert 'calls' not in docker.state()

    def test_found_without_importing_it_first(self, docker):
        assert isinstance(faults.backend('netem'), netem.Netem)
        assert faults.backend('netem').image == 'tc-image'
        assert netem.Netem({}, state_dir='x').image == netem.DEFAULT_IMAGE


class TestCleaning:

    def _leave(self, docker, tmp_path, host, pid, target='shop-db-1'):
        _b = netem.Netem(faults._settings()['netem'], state_dir=str(tmp_path / 'locks' / 'netem'))
        _f = netem.delay(netem.container(target), 100)
        _f.name = 'ipandora-{}-1'.format(pid)
        _b.apply(_f)
        netem.Netem._active.clear()                          # as if this process were a new one
        _marker = _b._marker(target)
        _m = json.load(open(_marker, encoding='utf-8'))
        _m.update(host=host, pid=pid)
        json.dump(_m, open(_marker, 'w', encoding='utf-8'))

    def test_only_what_dead_processes_of_this_host_left(self, docker, tmp_path):
        import socket
        self._leave(docker, tmp_path, socket.gethostname(), 2 ** 22 + 7, 'shop-db-1')     # dead
        self._leave(docker, tmp_path, socket.gethostname(), os.getppid(), 'shop-web-1')   # alive
        assert faults.clean() == ['shop-db-1/eth0']
        assert list(docker.state()['qdiscs']) == ['shop-web-1/eth0']
        self._leave(docker, tmp_path, 'another-host', 2 ** 22 + 8, 'shop-web-1')          # cannot tell
        assert faults.clean() == []

    def test_a_marker_whose_container_is_gone(self, docker, tmp_path):
        import socket
        self._leave(docker, tmp_path, socket.gethostname(), 2 ** 22 + 7)
        docker.set(containers=['shop-web-1'])
        assert faults.clean() == ['shop-db-1/eth0']
        assert markers(tmp_path) == []

    def test_nothing_to_clean(self, docker, tmp_path):
        assert faults.clean() == []
        (tmp_path / 'locks' / 'netem').mkdir(parents=True)
        (tmp_path / 'locks' / 'netem' / 'broken.json').write_text('{', encoding='utf-8')
        assert faults.clean() == []


def test_the_default_image_is_admitted():
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _registry = open(os.path.join(_root, 'docs', 'security', 'components.md'), encoding='utf-8').read()
    assert netem.DEFAULT_IMAGE.split('@', 1)[1] in _registry
