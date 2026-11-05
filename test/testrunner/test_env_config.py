# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_env_config.py
@Time  : 2026-11-05

`env` is applied for one run and only that run.

The MCP server calls run() over and over in one process, so whatever a run
does to Runtime.settings is still there for the next one unless it is undone.
It was not: after a run with env=staging, a run with env=prod (no prod.yaml)
or with no env at all still read staging's values.
"""
import json
import textwrap

import pytest

from ipandora.core.runner import run
from ipandora.core.schedule import config
from ipandora.core.schedule.runtime import Runtime

# Records what the run actually saw, so the assertion is about the run and
# not about Runtime after the fact.
PROBE_SUITE = '''
    import json, os
    from ipandora.core.schedule.runtime import Runtime

    def test_probe():
        with open(os.environ['IPANDORA_PROBE_OUT'], 'w') as f:
            json.dump({'read_timeout': Runtime.Http.read_timeout,
                       'ai_enabled': Runtime.Ai.enabled,
                       'ai_model': Runtime.Ai.model,
                       'base_url': (Runtime.settings or {}).get('base_url')}, f)
'''


@pytest.fixture
def probe(tmp_path, monkeypatch):
    _suite = tmp_path / 'suite' / 'test_probe.py'
    _suite.parent.mkdir()
    _suite.write_text(textwrap.dedent(PROBE_SUITE), encoding='utf-8')
    _out = tmp_path / 'probe.json'
    monkeypatch.setenv('IPANDORA_PROBE_OUT', str(_out))

    def _run(env=''):
        if _out.exists():
            _out.unlink()
        _result = run(str(_suite), env=env, persist=False, quiet=True)
        assert _result.ok, _result.summary
        return json.loads(_out.read_text())
    return _run


@pytest.fixture
def conf_dir(tmp_path, monkeypatch):
    _dir = tmp_path / 'conf'
    _dir.mkdir()
    monkeypatch.setenv(config.ENV_VAR, str(_dir))
    _before = Runtime.settings
    yield _dir
    Runtime.settings = _before
    Runtime.reset()


def test_env_overlay_is_applied_during_the_run(probe, conf_dir):
    (conf_dir / 'staging.yaml').write_text(
        'base_url: https://staging.example\nhttp:\n  read_timeout: 99\n', encoding='utf-8')
    seen = probe('staging')
    assert seen['read_timeout'] == 99
    assert seen['base_url'] == 'https://staging.example'


def test_env_overlay_merges_deeply(probe, conf_dir):
    (conf_dir / 'aion.yaml').write_text('ai:\n  enabled: true\n', encoding='utf-8')
    seen = probe('aion')
    assert seen['ai_enabled'] is True
    assert seen['ai_model'] == Runtime.settings['ai']['model']   # survived


def test_nothing_leaks_into_the_next_run(probe, conf_dir):
    (conf_dir / 'staging.yaml').write_text(
        'base_url: https://staging.example\nhttp:\n  read_timeout: 99\n', encoding='utf-8')
    _before = Runtime.settings

    assert probe('staging')['read_timeout'] == 99
    # no prod.yaml: must be the base settings, not what staging left behind
    assert probe('prod')['read_timeout'] == 30
    assert probe('prod')['base_url'] is None
    assert probe('')['read_timeout'] == 30

    assert Runtime.settings is _before
    assert Runtime.Http.read_timeout == 30


def test_settings_are_restored_when_the_run_fails(conf_dir, tmp_path):
    (conf_dir / 'staging.yaml').write_text('http:\n  read_timeout: 99\n', encoding='utf-8')
    _suite = tmp_path / 'test_boom.py'
    _suite.write_text('def test_boom():\n    assert False\n', encoding='utf-8')
    _before = Runtime.settings
    assert not run(str(_suite), env='staging', persist=False, quiet=True).ok
    assert Runtime.settings is _before and Runtime.Http.read_timeout == 30


def test_missing_env_file_says_so(probe, conf_dir, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        probe('stagnig')
    assert 'stagnig' in caplog.text and 'no config found' in caplog.text
