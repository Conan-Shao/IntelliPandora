# -*- coding: utf-8 -*-
"""
core/stack.py without Docker: a fake docker CLI (fake_docker.py) answers
and records every call, so these tests pin down what the module asks Docker
for and how it reads the answers -- fast enough to mutation-test. The real
thing is in test_stack.py.
"""
import json
import os
import re
import stat
import sys

import pytest

from ipandora.core import stack
from ipandora.core.triage import Category, classify

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fake_docker.py')


class Fake:
    def __init__(self, tmp_path):
        self.dir = tmp_path
        self.exe = str(tmp_path / 'docker')
        with open(self.exe, 'w', encoding='utf-8') as _f:
            _f.write('#!/bin/sh\nexec "{}" "{}" "$@"\n'.format(sys.executable, FAKE))
        os.chmod(self.exe, os.stat(self.exe).st_mode | stat.S_IXUSR)
        self.behaviour = {'log': str(tmp_path / 'calls.jsonl'), 'record_env': ['GREETING']}
        self._write()

    def _write(self):
        with open(str(self.dir / 'behaviour.json'), 'w', encoding='utf-8') as _f:
            json.dump(self.behaviour, _f)

    def set(self, **kwargs):
        self.behaviour.update(kwargs)
        self._write()

    def calls(self, verb=None):
        if not os.path.isfile(self.behaviour['log']):
            return []
        _all = [json.loads(_l) for _l in open(self.behaviour['log'], encoding='utf-8')]
        return [_c for _c in _all if verb is None or verb in _c['args']]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    _fake = Fake(tmp_path)
    monkeypatch.setenv('FAKE_DOCKER', str(tmp_path / 'behaviour.json'))
    monkeypatch.setattr(stack, '_settings', lambda: {'docker': _fake.exe})
    monkeypatch.setattr(stack, '_CHECKED', {})
    monkeypatch.setattr(stack, '_SWEPT', [])
    monkeypatch.setattr(stack, '_ACTIVE', [])
    (tmp_path / 'app').mkdir()
    (tmp_path / 'app' / 'compose.yaml').write_text('services: {}\n', encoding='utf-8')
    _fake.file = str(tmp_path / 'app' / 'compose.yaml')
    return _fake


def _project(name='compose'):
    return re.compile(r'^ipandora-{}-{}-{}-[0-9a-f]{{6}}$'.format(stack._host_tag(), os.getpid(), name))


class TestDocker:

    def test_found_checked_once_and_remembered(self, fake):
        assert stack.docker() == fake.exe
        assert stack.docker() == fake.exe
        assert len(fake.calls('version')) == 1 and len(fake.calls('info')) == 1

    @pytest.mark.parametrize('behaviour, why', [
        ({'version': '2.19.1'}, r'Compose v2\.20 或更新的版本.*现在是 2\.19'),
        ({'version': 'garbage'}, r'现在是 没有'),
        ({'daemon': ''}, '连不上守护进程'),
    ])
    def test_skipped_saying_what_is_missing(self, fake, behaviour, why):
        fake.set(**behaviour)
        with pytest.raises(pytest.skip.Exception, match=why):
            stack.docker()
        assert stack._CHECKED == {}                            # a failed check is tried again next time

    def test_no_docker_at_all(self, fake, monkeypatch):
        monkeypatch.setattr(stack, '_settings', lambda: {'docker': str(fake.dir / 'nowhere')})
        with pytest.raises(pytest.skip.Exception, match='没有找到 docker'):
            stack.docker()
        assert fake.calls() == []                              # nothing was run

    def test_compose_2_20_is_enough(self, fake):
        fake.set(version='v2.20.0')
        assert stack.docker() == fake.exe


class TestRun:

    def test_a_command_that_hangs_or_cannot_start(self, fake):
        with pytest.raises(stack.StackError, match=r'ipandora: environment did not start: `sleep 5` did not finish in 0\.3s'):
            stack._run([fake.exe, 'sleep', '5'], timeout=0.3)
        _done = stack._run([fake.exe, 'sleep', '5'], timeout=0.3, check=False)
        assert (_done.returncode, _done.stderr) == (-1, 'timed out')
        with pytest.raises(stack.StackError, match='could not run docker'):
            stack._run([str(fake.dir / 'nowhere')], timeout=5)
        assert stack._run([str(fake.dir / 'nowhere')], timeout=5, check=False).returncode == -1
        with pytest.raises(stack.StackError, match=r'`compose bogus` failed'):
            stack._run([fake.exe, 'compose', 'bogus'], timeout=5)


class TestCompose:

    def test_up_waits_and_down_always_follows(self, fake):
        fake.set(ports={'web:8080': '0.0.0.0:49153'})
        with stack.compose(fake.file, services=['web'], env={'GREETING': 'hi'}, wait=30) as _s:
            assert _project().match(_s.project) and _s in stack.active()
            assert _s.port('web', 8080) == 49153 and _s.url('web', 8080, path='/x') == 'http://127.0.0.1:49153/x'
        _up = fake.calls('up')[0]
        assert _up['args'] == ['compose', '-p', _s.project, '-f', fake.file, 'up', '--detach', '--wait',
                               '--wait-timeout', '30', 'web']
        assert _up['cwd'] == os.path.dirname(fake.file) and _up['env'] == {'GREETING': 'hi'}
        assert fake.calls('down')[-1]['args'] == ['compose', '-p', _s.project, '-f', fake.file, 'down',
                                                  '--volumes', '--remove-orphans', '--timeout', '10']
        assert _s not in stack.active()

    def test_down_also_when_the_block_raises(self, fake):
        with pytest.raises(KeyError):
            with stack.compose(fake.file):
                raise KeyError('the case failed')
        assert len(fake.calls('down')) == 1 and stack.active() == []

    def test_a_stack_that_does_not_come_up(self, fake):
        fake.set(up_rc=1, up_stderr='container app-broken-1 is unhealthy',
                 ps=[{'Service': 'broken', 'State': 'running', 'Health': 'unhealthy'},
                     {'Service': 'db', 'State': 'running', 'Health': 'healthy'},
                     {'Service': 'init', 'State': 'exited', 'Health': ''}],
                 logs={'broken': 'connecting\npassword=hunter2 rejected\n', 'init': 'migrated\n'})  # pragma: allowlist secret
        with pytest.raises(stack.StackError) as _e:
            with stack.compose(fake.file):
                pass
        _message = str(_e.value)
        assert _message.startswith(stack.STACK_MARKER + ': `compose -p ')
        assert 'is unhealthy' in _message and 'broken：running（unhealthy）' in _message
        assert 'init：exited' in _message and 'db：' not in _message           # only what did not come up
        assert 'rejected' in _message and 'hunter2' not in _message           # its last lines, redacted
        assert len(fake.calls('down')) == 1 and stack.active() == []
        assert classify('t::x', 'error', _message).category == Category.ENVIRONMENT

    def test_files_and_names(self, fake, tmp_path):
        with pytest.raises(FileNotFoundError, match='compose file not found'):
            stack.compose(str(tmp_path / 'missing.yaml'))
        with pytest.raises(ValueError, match='needs a compose file'):
            stack.compose([])
        (tmp_path / 'app' / 'override.yaml').write_text('services: {}\n', encoding='utf-8')
        with stack.compose([fake.file, str(tmp_path / 'app' / 'override.yaml')], name='Shop API') as _s:
            assert _project('shop-api').match(_s.project)
        assert fake.calls('up')[0]['args'][3:7] == ['-f', fake.file, '-f', str(tmp_path / 'app' / 'override.yaml')]

    def test_ports_as_docker_prints_them(self, fake, monkeypatch):
        fake.set(ports={'web:8080': '0.0.0.0:49153', 'web:9090': '[::]:49154'})
        monkeypatch.setattr(stack, '_settings', lambda: {'docker': fake.exe, 'host': 'docker.test'})
        with stack.compose(fake.file) as _s:
            assert _s.port('web', 9090) == 49154
            assert _s.address('web', 8080) == 'docker.test:49153'
            with pytest.raises(stack.StackError, match=r'web does not publish port 7000/udp'):
                _s.port('web', 7000, protocol='udp')
        assert ['port', '--protocol', 'udp', 'web', '7000'] == fake.calls('port')[-1]['args'][-5:]

    def test_logs_since_and_tail(self, fake):
        fake.set(logs={'web': 'a\nb\n'})
        with stack.compose(fake.file) as _s:
            assert _s.logs('web', since=0, tail=5) == 'a\nb\n'
            _s.logs()
        _with, _all = fake.calls('logs')
        assert _with['args'][-8:] == ['logs', '--no-color', '--timestamps', '--since', '1970-01-01T00:00:00.000000Z',
                                      '--tail', '5', 'web']
        assert _all['args'][-3:] == ['logs', '--no-color', '--timestamps']

    def test_keep_logs_writes_and_quotes_each_service(self, fake, monkeypatch, tmp_path):
        monkeypatch.setenv('IPANDORA_ARTIFACTS_DIR', str(tmp_path / 'artifacts'))
        fake.set(services=['web', 'db'], logs={'web': ''.join('line {}\n'.format(_i) for _i in range(100))})
        with stack.compose(fake.file) as _s:
            _entries = _s.keep_logs('test_x.py::test_y', since=1000.0)
        assert [(_e['kind'], _e['group']) for _e in _entries] == [('service-log', 'web')]     # db logged nothing
        _lines = _entries[0]['text'].splitlines()
        assert len(_lines) == stack.LOG_LINES and _lines[-1] == 'line 99'
        assert os.path.dirname(_entries[0]['path']) == str(tmp_path / 'artifacts')
        assert open(_entries[0]['path'], encoding='utf-8').read() == _entries[0]['text'] + '\n'
        assert '--tail' in fake.calls('logs')[0]['args']


class TestClean:

    def test_only_dead_processes_of_this_host(self, fake):
        _tag = stack._host_tag()
        _dead = 4194301
        while stack._alive(_dead):
            _dead -= 1
        _names = {'dead': 'ipandora-{}-{}-shop-abc123'.format(_tag, _dead),
                  'mine': 'ipandora-{}-{}-shop-abc123'.format(_tag, os.getpid()),
                  'alive': 'ipandora-{}-{}-shop-abc123'.format(_tag, 1),
                  'other host': 'ipandora-ffffff-{}-shop-abc123'.format(_dead),
                  'not ours': 'shop'}
        fake.set(projects=[{'Name': _n} for _n in _names.values()])
        assert stack.clean(fake.exe) == [_names['dead']]
        assert [_c['args'] for _c in fake.calls('down')] == [
            ['compose', '-p', _names['dead'], 'down', '-v', '--remove-orphans', '--timeout', '5']]

    def test_unreadable_listing(self, fake):
        fake.set(projects_text='not json')
        assert stack.clean(fake.exe) == []

    def test_swept_once_per_process(self, fake):
        with stack.compose(fake.file):
            pass
        with stack.compose(fake.file):
            pass
        assert len(fake.calls('ls')) == 1
