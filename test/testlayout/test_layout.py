# -*- coding: utf-8 -*-
"""
ipandora check layout (docs/design/decisions/17 §3.3, plan L3).

Acceptance: a judgement written in apis/ is reported, with where it is.
"""
import os
import subprocess
import sys
import textwrap

from ipandora.core import layout


def write(root, rel, text):
    _p = root / rel
    _p.parent.mkdir(parents=True, exist_ok=True)
    _p.write_text(textwrap.dedent(text), encoding='utf-8')


def rules(root):
    return [(_f.path.replace(os.sep, '/'), _f.line, _f.rule) for _f in layout.check(str(root))]


def test_a_judgement_in_apis_is_reported_with_its_place(tmp_path):
    write(tmp_path, 'apis/orders.py', '''
        from ipandora.core.assertion import assert_all, status_ok

        class OrderApi:
            def get(self, r):
                assert_all(status_ok(r))
                assert r is not None
    ''')
    assert rules(tmp_path) == [('apis/orders.py', 6, 'judgement'), ('apis/orders.py', 7, 'judgement')]


def test_expect_in_pages_and_raises_in_flows(tmp_path):
    write(tmp_path, 'pages/cart.py', '''
        from playwright.sync_api import expect
        def check(page):
            expect(page.locator('#x')).to_be_visible()
    ''')
    write(tmp_path, 'flows/orders.py', '''
        import pytest
        from ipandora.core.assertion import require
        def make(api):
            require(api.ok())                        # a precondition: allowed
            with pytest.raises(ValueError):
                api.bad()
    ''')
    assert rules(tmp_path) == [('flows/orders.py', 6, 'judgement'), ('pages/cart.py', 4, 'judgement')]


def test_sleeps_requests_and_addresses(tmp_path):
    write(tmp_path, 'tests/test_x.py', '''
        import time
        import requests
        def test_x():
            time.sleep(1)
    ''')
    write(tmp_path, 'apis/users.py', '''
        BASE = 'https://staging.example.com/api'
        PATH = '{base}/users'                         # a template: fine
    ''')
    assert rules(tmp_path) == [('apis/users.py', 2, 'address'), ('tests/test_x.py', 3, 'requests'),
                               ('tests/test_x.py', 5, 'sleep')]


def test_judgements_in_tests_are_the_point(tmp_path):
    write(tmp_path, 'tests/test_ok.py', '''
        from ipandora.core.assertion import assert_all, that
        def test_ok():
            assert_all(that(1, 'x') == 1)
            assert 1 + 1 == 2
    ''')
    assert rules(tmp_path) == []


def test_the_generated_full_layout_passes(tmp_path):
    from ipandora.run.commands.init import generate
    generate(str(tmp_path), layout='full')
    assert rules(tmp_path) == []


def test_the_command_exits_one_on_findings(tmp_path):
    write(tmp_path, 'apis/a.py', 'assert True\n')
    _cli = [sys.executable, '-m', 'ipandora.run', 'check', 'layout', str(tmp_path)]
    _run = subprocess.run(_cli, capture_output=True, text=True)
    assert _run.returncode == 1 and 'apis/a.py:1: [judgement]' in _run.stdout.replace(os.sep, '/')
    assert subprocess.run(_cli + ['--warn-only'], capture_output=True).returncode == 0
    _empty = tmp_path / 'empty'
    _empty.mkdir()
    assert subprocess.run(_cli[:-1] + [str(_empty)], capture_output=True).returncode == 2
