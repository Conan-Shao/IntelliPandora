# -*- coding: utf-8 -*-
"""
@File  : test_backends.py
@Time  : 2026-11-07

The backend interface of core/faults.py (D4b, decision 18 addendum): another
fault platform is a Backend; the framework keeps the safety switch, the lock
per target, the evidence, the marker and the undo, whatever the backend.
"""
import os

import pytest

from ipandora.core import faults
from ipandora.core.evidence import recorder


class Recording(faults.Backend):
    """A platform that keeps its faults in a dict: what is in effect is what it holds."""

    name = 'recording'

    def __init__(self, fail_undo=(), fail_apply=()):
        self.held, self.log = {}, []
        self.fail_undo, self.fail_apply = set(fail_undo), set(fail_apply)

    def where(self):
        return 'recording://test'

    def apply(self, fault):
        if fault.kind in self.fail_apply:
            raise faults.BackendError('refused {}'.format(fault.kind))
        self.held[fault.name] = fault
        self.log.append(('apply', fault.kind, fault.proxy))

    def undo(self, fault):
        self.log.append(('undo', fault.kind, fault.proxy))
        if fault.kind in self.fail_undo:
            raise faults.BackendError('could not undo {}'.format(fault.kind))
        self.held.pop(fault.name, None)

    def clean(self):
        _ours = sorted(_n for _n in self.held if _n.startswith(faults.PREFIX))
        for _n in _ours:
            del self.held[_n]
        return _ours


@pytest.fixture
def platform(monkeypatch, tmp_path):
    _p = Recording()
    monkeypatch.setattr(faults, '_BACKENDS', dict(faults._BACKENDS))
    faults.register('recording', lambda: _p)
    monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True, 'backends': ['recording']})
    monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
    return _p


def fault(kind, target='orders', backend='recording', **attributes):
    return faults.Fault(target, kind, attributes, backend=backend)


def test_a_fault_goes_to_the_backend_it_names(platform):
    recorder.begin('t::case')
    try:
        with faults.injected(fault('pod-kill', 'orders'), fault('partition', 'payments', peer='db')) as _records:
            assert set(_f.kind for _f in platform.held.values()) == {'pod-kill', 'partition'}
            # what the framework keeps, the same as for Toxiproxy
            assert [(_r['backend'], _r['target'], _r['via'], _r['ended']) for _r in _records] == [
                ('recording', 'orders', 'recording://test', None), ('recording', 'payments', 'recording://test', None)]
            assert faults.during().startswith(' ({}: '.format(faults.INJECTED_MARKER))
            assert 'pod-kill(orders)' in faults.during() and 'partition(payments, peer=db)' in faults.during()
            assert all(_r['name'].startswith(faults.PREFIX) for _r in _records)
        assert platform.held == {} and faults.during() == ''
        assert all(_r['ended'] is not None for _r in _records)
        assert [_f['backend'] for _f in recorder.current().faults] == ['recording', 'recording']
    finally:
        recorder.end('t::case')
    # undone innermost first
    assert platform.log == [('apply', 'pod-kill', 'orders'), ('apply', 'partition', 'payments'),
                            ('undo', 'partition', 'payments'), ('undo', 'pod-kill', 'orders')]


def test_undone_when_the_case_raises(platform):
    with pytest.raises(ZeroDivisionError):
        with faults.injected(fault('pod-kill')):
            1 / 0
    assert platform.held == {}


def test_the_lock_is_per_target_whatever_the_backend(platform):
    from ipandora.core.runner.plugin import ResourceLock, lock_path
    with faults.injected(fault('pod-kill', 'orders')):
        _other = ResourceLock(lock_path('fault:orders'))
        assert not _other.acquire(0.05)          # another injector on `orders` waits
    assert _other.acquire(0.05)
    _other.release()


def test_still_off_unless_allowed(platform, monkeypatch):
    monkeypatch.setattr(faults, '_settings', lambda: {'backends': ['recording']})
    with pytest.raises(faults.FaultsNotAllowed):
        with faults.injected(fault('pod-kill')):
            pass
    monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True})
    monkeypatch.setenv('IPANDORA_ENV', 'prod')
    with pytest.raises(faults.FaultsNotAllowed):
        with faults.injected(fault('pod-kill')):
            pass
    assert platform.log == []


def test_an_unknown_backend_is_refused_before_anything_is_applied(platform):
    with pytest.raises(ValueError, match="no fault backend named 'chaos'.*recording"):
        with faults.injected(fault('pod-kill'), fault('delay', backend='chaos')):
            pass
    assert platform.log == []


def test_a_refused_apply_undoes_what_was_applied(platform):
    platform.fail_apply = {'partition'}
    with pytest.raises(faults.BackendError, match='refused partition'):
        with faults.injected(fault('pod-kill'), fault('partition')):
            pass
    assert platform.held == {} and platform.log[-1] == ('undo', 'pod-kill', 'orders')


def test_an_undo_that_fails_is_raised_after_the_others_are_undone(platform):
    platform.fail_undo = {'pod-kill'}
    with pytest.raises(faults.BackendError, match='could not undo every injected fault.*could not undo pod-kill') as _e:
        with faults.injected(fault('pod-kill'), fault('partition')):
            pass
    assert not isinstance(_e.value, faults.ToxiproxyError)       # not Toxiproxy's: it was another platform
    assert [_f.kind for _f in platform.held.values()] == ['pod-kill']   # left for the next run's clean()
    _left = list(platform.held)
    assert faults.clean() == _left and platform.held == {}


def test_clean_reaches_every_backend_the_environment_uses(platform, monkeypatch):
    platform.held = {'ipandora-1-1': None, 'theirs': None}
    _second = Recording()
    _second.held = {'ipandora-2-1': None}
    faults.register('second', lambda: _second)
    monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True, 'backends': ['recording', 'second']})
    assert faults.clean() == ['ipandora-1-1', 'ipandora-2-1']
    assert platform.held == {'theirs': None} and _second.held == {}  # only ours
    assert faults.clean(_second) == []                              # or the one given


def test_configured_backends():
    for _settings, _names in (({}, ['toxiproxy']), ({'backends': 'recording'}, ['recording']),
                              ({'backends': ['toxiproxy', 'recording']}, ['toxiproxy', 'recording'])):
        _old = faults._settings
        faults._settings = lambda _s=_settings: _s
        try:
            assert faults.configured() == _names
        finally:
            faults._settings = _old


def test_register_refuses_what_is_not_a_backend_factory():
    with pytest.raises(ValueError):
        faults.register('', Recording)
    with pytest.raises(ValueError):
        faults.register('x', Recording())        # an instance, not a factory


def test_the_base_class_must_be_implemented():
    _b = faults.Backend()
    with pytest.raises(NotImplementedError):
        _b.apply(fault('x'))
    with pytest.raises(NotImplementedError):
        _b.undo(fault('x'))
    assert _b.clean() == [] and _b.where() == ''


def test_toxiproxy_is_the_built_in_backend():
    assert isinstance(faults.backend('toxiproxy'), faults.Toxiproxy)
    assert issubclass(faults.ToxiproxyError, faults.BackendError)
    assert faults.latency('db', 100).backend == 'toxiproxy' and faults.latency('db', 100).target == 'db'


def test_run_cleanup_goes_backend_by_backend(platform, monkeypatch, caplog):
    import logging
    from ipandora.core.runner import plugin
    platform.held = {'ipandora-9-1': None}

    class _Down(faults.Backend):
        name = 'down'

        def clean(self):
            raise faults.BackendError('not reachable')
    faults.register('down', _Down)
    monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True, 'backends': ['down', 'recording']})
    monkeypatch.setattr(plugin, 'is_worker', lambda config: False)
    monkeypatch.setitem(plugin._SESSIONS, 'depth', 1)
    with caplog.at_level(logging.INFO):
        plugin._clean_faults(None, 'start')
    assert platform.held == {}                                      # the unreachable one did not stop it
    assert 'fault cleanup on down at start skipped: not reachable' in caplog.text
    assert 'removed 1 injected fault(s) left on recording at start: ipandora-9-1' in caplog.text
