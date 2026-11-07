# -*- coding: utf-8 -*-
"""
@File  : test_stack.py
@Time  : 2026-11-06

Services from a compose file (docs/design/decisions/19, D5). Acceptance:
a stack comes up with random ports and is gone afterwards; a stack whose
health check fails is an environment problem, with its logs; a failed case
keeps the services' logs; a dead process's stack is removed by the next one.
"""
import json
import os
import subprocess
import sys
import textwrap
import time

import pytest
import requests

from ipandora.core import faults, stack
from ipandora.core.evidence import recorder
from ipandora.core.triage import Category, classify

from .conftest import HERE


def _projects(exe):
    _out = subprocess.run([exe, 'compose', 'ls', '--all', '--format', 'json'], capture_output=True, text=True).stdout
    return {_p['Name'] for _p in json.loads(_out or '[]')}


def _get(url):
    _s = requests.Session()
    _s.trust_env = False
    return _s.get(url, timeout=10)


class TestCompose:

    def test_a_stack_comes_up_on_random_ports_and_is_gone_after(self, needs_docker):
        with stack.compose(os.path.join(HERE, 'web.yaml'), env={'GREETING': 'from-env'}) as _s:
            assert _s.project.startswith('ipandora-') and str(os.getpid()) in _s.project
            assert _s in stack.active()
            _r = _get(_s.url('web', 8080))
            assert _r.status_code == 200 and _r.text.strip() == 'from-env'
            assert _s.address('web', 8080) == '127.0.0.1:{}'.format(_s.port('web', 8080))   # Docker picked it
            assert 'web started' in _s.logs('web')
            with pytest.raises(stack.StackError, match='does not publish port 9999'):
                _s.port('web', 9999)
        assert _s not in stack.active()
        assert _s.project not in _projects(needs_docker)

    def test_a_stack_that_does_not_come_up_is_the_environment(self, needs_docker):
        with pytest.raises(stack.StackError) as _e:
            with stack.compose(os.path.join(HERE, 'unhealthy.yaml'), wait=20):
                pass
        _message = str(_e.value)
        assert stack.STACK_MARKER in _message
        assert 'broken' in _message and 'cannot reach the database' in _message      # its last log lines
        assert 'hunter2' not in _message
        _finding = classify('t::x', 'error', _message)
        assert _finding.category == Category.ENVIRONMENT and '依赖环境没有起来' in _finding.reason
        assert not any(_p.endswith('-unhealthy') and str(os.getpid()) in _p for _p in _projects(needs_docker))

    def test_a_dead_processs_stack_is_removed_by_the_next(self, needs_docker, tmp_path):
        _script = tmp_path / 'leave.py'
        _script.write_text(textwrap.dedent('''
            import os, sys
            from ipandora.core import stack
            s = stack.compose(sys.argv[1]).__enter__()
            print(s.project, flush=True)
            os._exit(0)                       # killed: never taken down
        '''), encoding='utf-8')
        _left = subprocess.run([sys.executable, str(_script), os.path.join(HERE, 'web.yaml')], capture_output=True,
                               text=True, timeout=300).stdout.strip().splitlines()[-1]
        assert _left in _projects(needs_docker)
        assert _left in stack.clean()
        assert _left not in _projects(needs_docker)

    def test_faults_through_a_real_toxiproxy_in_the_stack(self, needs_docker, monkeypatch, tmp_path):
        with stack.compose(os.path.join(HERE, 'faulty.yaml')) as _s:
            _api = _s.url('toxiproxy', 8474)
            monkeypatch.setattr(faults, '_settings', lambda: {'allowed': True, 'toxiproxy': _api})
            monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
            for _ in range(50):                                   # the API answers shortly after start
                try:
                    faults.Toxiproxy().version()
                    break
                except faults.ToxiproxyError:
                    time.sleep(0.2)
            faults.proxy('web', '0.0.0.0:8666', 'web:8080')
            _through = _s.url('toxiproxy', 8666)
            assert _get(_through).text.strip() == 'hello'
            with faults.injected(faults.latency('web', 600)):
                _t = time.monotonic()
                _get(_through)
                assert time.monotonic() - _t >= 0.5
            _t = time.monotonic()
            _get(_through)
            assert time.monotonic() - _t < 0.5


class TestServiceLogs:

    def test_a_failed_case_keeps_what_the_services_logged_meanwhile(self, needs_docker, tmp_path, monkeypatch):
        from ipandora.core.report.builder import build_from_run
        from ipandora.core.report.render import to_html
        from ipandora.core.runner import run
        monkeypatch.setenv('WEB_COMPOSE', os.path.join(HERE, 'web.yaml'))
        _suite = tmp_path / 'suite'
        _suite.mkdir()
        (_suite / 'test_shop.py').write_text(textwrap.dedent('''
            import os
            import time
            import pytest
            import requests
            from ipandora.core import stack

            @pytest.fixture(scope='module')
            def web():
                with stack.compose(os.environ['WEB_COMPOSE']) as s:
                    yield s

            def test_passes(web):
                s = requests.Session(); s.trust_env = False
                assert s.get(web.url('web', 8080, path='/index.html'), timeout=10).status_code == 200
                time.sleep(1)    # Docker stamps a line when its daemon reads it: a moment late

            def test_fails(web):
                s = requests.Session(); s.trust_env = False
                assert s.get(web.url('web', 8080, path='/missing-page'), timeout=10).status_code == 200
        '''), encoding='utf-8')
        _result = run(str(_suite), persist=False, quiet=True, baseline='')
        _by = {_c.nodeid.split('::')[-1]: _c for _c in _result.cases}
        assert _by['test_passes'].outcome == 'passed' and not _by['test_passes'].artifacts
        _logs = [_a for _a in _by['test_fails'].artifacts if _a['kind'] == 'service-log']
        assert [_a['group'] for _a in _logs] == ['web']
        assert '/missing-page' in _logs[0]['text']               # the request, as the service saw it
        assert 'index.html' not in _logs[0]['text']              # only what happened during this case
        assert os.path.isfile(_logs[0]['path'])
        _html = to_html(build_from_run(_result))
        assert '服务 web' in _html and '/missing-page' in _html


def test_every_image_the_tests_pull_is_pinned_and_registered():
    import re
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _registry = open(os.path.join(_root, 'docs', 'security', 'components.md'), encoding='utf-8').read()
    _images = []
    for _name in sorted(os.listdir(HERE)):
        _images += re.findall(r'^\s*image:\s*(\S+)', open(os.path.join(HERE, _name), encoding='utf-8').read(),
                              re.MULTILINE)
    assert _images
    for _image in _images:
        assert '@sha256:' in _image, '{} is not pinned by digest'.format(_image)
        assert '`{}`'.format(_image.split('@', 1)[1]) in _registry, '{} is not registered'.format(_image)


class TestCr11:
    """Found in code review CR11 (docs/design/reviews/11-CR11.md)."""

    def test_two_compose_files_of_the_same_name_are_two_projects(self, needs_docker, tmp_path):
        _web = open(os.path.join(HERE, 'web.yaml'), encoding='utf-8').read()
        for _dir, _greeting in (('shop', 'from-shop'), ('payment', 'from-payment')):
            (tmp_path / _dir).mkdir()
            (tmp_path / _dir / 'compose.yaml').write_text(_web.replace('GREETING:-hello', 'GREETING:-' + _greeting),
                                                          encoding='utf-8')
        with stack.compose(str(tmp_path / 'shop' / 'compose.yaml')) as _shop:
            with stack.compose(str(tmp_path / 'payment' / 'compose.yaml')) as _payment:
                assert _shop.project != _payment.project
                assert _get(_payment.url('web', 8080)).text.strip() == 'from-payment'
            # taking payment down left shop alone
            assert _get(_shop.url('web', 8080)).text.strip() == 'from-shop'
            with stack.compose(str(tmp_path / 'shop' / 'compose.yaml')) as _again:
                assert _again.project != _shop.project          # the same file twice at once
            assert _get(_shop.url('web', 8080)).text.strip() == 'from-shop'

    def test_logs_that_cannot_be_kept_do_not_end_the_run(self, tmp_path, monkeypatch):
        from ipandora.core.runner import run

        def _broken(nodeid, since):
            raise ValueError('docker printed something unexpected')
        monkeypatch.setattr(stack, 'active', lambda: [object()])
        monkeypatch.setattr(stack, 'keep_logs', _broken)
        (tmp_path / 's').mkdir()
        (tmp_path / 's' / 'test_x.py').write_text('def test_fails():\n    assert 1 == 2\n\n'
                                                   'def test_after():\n    assert 1\n', encoding='utf-8')
        _result = run(str(tmp_path / 's'), persist=False, quiet=True, baseline='')
        assert {_c.nodeid.split('::')[-1]: _c.outcome for _c in _result.cases} == {
            'test_fails': 'failed', 'test_after': 'passed'}
