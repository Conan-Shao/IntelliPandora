# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_config.py
@Time  : 2026-11-05
"""
import logging
import os

import pytest

from ipandora.core.schedule import config


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A suite directory with no conf/ yet, as the working directory."""
    monkeypatch.delenv(config.ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestDeepMerge:
    def test_nested_keys_survive(self):
        # dict.update replaced the whole `ai` section and dropped the model
        merged = config.deep_merge({'ai': {'enabled': False, 'model': 'm'}},
                                   {'ai': {'enabled': True}})
        assert merged == {'ai': {'enabled': True, 'model': 'm'}}

    def test_new_keys_and_sections_are_added(self):
        merged = config.deep_merge({'http': {'a': 1}}, {'http': {'b': 2}, 'base_url': 'x'})
        assert merged == {'http': {'a': 1, 'b': 2}, 'base_url': 'x'}

    def test_non_dict_replaces(self):
        assert config.deep_merge({'a': {'b': 1}}, {'a': None}) == {'a': None}
        assert config.deep_merge({'a': [1, 2]}, {'a': [3]}) == {'a': [3]}
        assert config.deep_merge({'a': 1}, {'a': {'b': 2}}) == {'a': {'b': 2}}

    def test_inputs_are_not_modified(self):
        base, overlay = {'a': {'b': 1}}, {'a': {'c': 2}}
        merged = config.deep_merge(base, overlay)
        merged['a']['b'] = 99
        assert base == {'a': {'b': 1}} and overlay == {'a': {'c': 2}}

    def test_none_on_either_side(self):
        assert config.deep_merge(None, {'a': 1}) == {'a': 1}
        assert config.deep_merge({'a': 1}, None) == {'a': 1}


class TestReadYaml:
    def test_empty_file_is_empty_mapping(self, tmp_path):
        assert config.read_yaml(str(_write(tmp_path / 'e.yaml', ''))) == {}

    def test_non_mapping_is_an_error(self, tmp_path):
        with pytest.raises(ValueError, match='mapping'):
            config.read_yaml(str(_write(tmp_path / 'l.yaml', '- a\n- b\n')))

    def test_utf8(self, tmp_path):
        _file = _write(tmp_path / 'u.yaml', '# 中文注释\nname: 测试\n')
        assert config.read_yaml(str(_file)) == {'name': '测试'}


class TestBaseSettings:
    def test_package_defaults_alone(self, project):
        base = config.load_base()
        assert base['http']['read_timeout'] == 30
        assert base['ai']['enabled'] is False

    def test_project_config_overrides_without_editing_site_packages(self, project):
        _write(project / 'conf' / 'config.yaml',
               'http:\n  read_timeout: 5\nai:\n  enabled: true\n')
        base = config.load_base()
        assert base['http']['read_timeout'] == 5
        assert base['http']['connect_timeout'] == 10      # untouched default
        assert base['ai']['enabled'] is True
        assert base['ai']['model']                          # not wiped

    def test_explicit_dir_wins_over_cwd(self, project, tmp_path_factory, monkeypatch):
        _write(project / 'conf' / 'config.yaml', 'http:\n  read_timeout: 5\n')
        _elsewhere = tmp_path_factory.mktemp('elsewhere')
        _write(_elsewhere / 'config.yaml', 'http:\n  read_timeout: 7\n')
        monkeypatch.setenv(config.ENV_VAR, str(_elsewhere))
        assert config.load_base()['http']['read_timeout'] == 7

    def test_explicit_dir_that_does_not_exist_warns(self, project, monkeypatch, caplog):
        monkeypatch.setenv(config.ENV_VAR, str(project / 'nope'))
        with caplog.at_level(logging.WARNING):
            base = config.load_base()
        assert base['http']['read_timeout'] == 30
        assert 'does not exist' in caplog.text and 'nope' in caplog.text


class TestFindEnvFile:
    def test_project_dir(self, project):
        _file = _write(project / 'conf' / 'staging.yaml', 'a: 1\n')
        assert os.path.samefile(config.find_env_file('staging'), _file)

    def test_explicit_dir(self, project, tmp_path_factory, monkeypatch):
        _dir = tmp_path_factory.mktemp('cfg')
        _file = _write(_dir / 'staging.yaml', 'a: 1\n')
        _write(project / 'conf' / 'staging.yaml', 'a: 2\n')    # not consulted
        monkeypatch.setenv(config.ENV_VAR, str(_dir))
        assert os.path.samefile(config.find_env_file('staging'), _file)

    def test_missing_is_a_visible_warning_naming_where_it_looked(self, project, caplog):
        # used to be a debug line: a typo'd -e ran on defaults, silently
        with caplog.at_level(logging.WARNING):
            assert config.find_env_file('stagnig') == ''
        assert 'stagnig' in caplog.text
        assert os.path.join(str(project), 'conf', 'stagnig.yaml') in caplog.text
        assert os.path.join(config.package_conf_dir(), 'stagnig.yaml') in caplog.text

    def test_no_env_is_not_a_lookup(self, project, caplog):
        with caplog.at_level(logging.WARNING):
            assert config.find_env_file('') == ''
        assert caplog.text == ''

    def test_legacy_package_location_still_works_but_warns(self, project, caplog):
        _legacy = os.path.join(config.package_conf_dir(), 'zz_legacy_env.yaml')
        with open(_legacy, 'w', encoding='utf-8') as _f:
            _f.write('a: 1\n')
        try:
            with caplog.at_level(logging.WARNING):
                assert config.find_env_file('zz_legacy_env') == _legacy
            assert 'inside the installed package' in caplog.text
        finally:
            os.remove(_legacy)

    def test_project_dir_shadows_legacy(self, project):
        _legacy = os.path.join(config.package_conf_dir(), 'zz_both_env.yaml')
        with open(_legacy, 'w', encoding='utf-8') as _f:
            _f.write('a: 1\n')
        try:
            _file = _write(project / 'conf' / 'zz_both_env.yaml', 'a: 2\n')
            assert os.path.samefile(config.find_env_file('zz_both_env'), _file)
        finally:
            os.remove(_legacy)

    @pytest.mark.parametrize('env', ['../etc', 'a/b', '.hidden'])
    def test_env_is_a_name_not_a_path(self, project, env):
        with pytest.raises(ValueError, match='plain name'):
            config.find_env_file(env)
