# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : config.py
@Time  : 2026-11-05

Where configuration comes from, and how layers combine.

Layers, lowest first:

  1. the package's own conf/config.yaml        -- shipped defaults
  2. <project conf dir>/config.yaml            -- the suite's own settings
  3. <project conf dir>/<env>.yaml             -- one environment, per run

The project conf dir is $IPANDORA_CONFIG_DIR when set, otherwise ./conf in the
working directory. Before this existed the only config.yaml read was the one
inside the installed package, so changing a timeout meant editing
site-packages, and `-e staging` only found a staging.yaml placed there too.

Layers are merged recursively: an overlay that says `ai: {enabled: true}`
turns AI on and leaves `ai.model` alone. The merge used to be a shallow
dict.update, which replaced the whole `ai` section and silently dropped the
model.
"""
import copy
import os
from typing import List, Optional

import yaml

from ipandora.utils.log import logger
from ipandora.utils.pathutils import PathUtils

ENV_VAR = 'IPANDORA_CONFIG_DIR'
BASE_NAME = 'config.yaml'


def package_conf_dir() -> str:
    return os.path.join(PathUtils().pandora_path, 'conf')


def project_conf_dir() -> str:
    """$IPANDORA_CONFIG_DIR if set, else ./conf under the working directory."""
    _explicit = os.environ.get(ENV_VAR, '').strip()
    if _explicit:
        return os.path.abspath(os.path.expanduser(_explicit))
    return os.path.abspath('conf')


def deep_merge(base: Optional[dict], overlay: Optional[dict]) -> dict:
    """
    A new dict: `overlay` on top of `base`, recursing into nested dicts.

    A non-dict value in the overlay -- including an explicit null -- replaces
    what was there. Neither argument is modified.
    """
    _merged = copy.deepcopy(base) if isinstance(base, dict) else {}
    for _key, _value in (overlay or {}).items():
        if isinstance(_value, dict) and isinstance(_merged.get(_key), dict):
            _merged[_key] = deep_merge(_merged[_key], _value)
        else:
            _merged[_key] = copy.deepcopy(_value)
    return _merged


def read_yaml(path: str) -> dict:
    """
    Load one yaml file as a mapping. An empty file is {}.

    Anything else at the top level is an error rather than being ignored: a
    config that parses to a list or a string was not going to configure
    anything, and running on defaults while the user believes otherwise is
    the failure this module exists to prevent.
    """
    with open(path, 'r', encoding='utf-8') as _f:
        _data = yaml.safe_load(_f)
    if _data is None:
        return {}
    if not isinstance(_data, dict):
        raise ValueError('{}: top level must be a mapping, got {}'.format(
            path, type(_data).__name__))
    return _data


def load_base() -> dict:
    """Package defaults, with the project's config.yaml merged over them."""
    _settings = {}
    _package = os.path.join(package_conf_dir(), BASE_NAME)
    if os.path.isfile(_package):
        _settings = read_yaml(_package)

    _dir = project_conf_dir()
    if os.environ.get(ENV_VAR, '').strip() and not os.path.isdir(_dir):
        # Asked for explicitly, so its absence is a mistake, not a default.
        logger.warning('%s=%s does not exist; using package defaults only',
                       ENV_VAR, _dir)
    _project = os.path.join(_dir, BASE_NAME)
    if os.path.isfile(_project) and os.path.abspath(_project) != os.path.abspath(_package):
        _settings = deep_merge(_settings, read_yaml(_project))
    return _settings


def env_candidates(env: str) -> List[str]:
    """Where <env>.yaml is looked for, in order. The first that exists wins."""
    _name = '{}.yaml'.format(env)
    _paths = [os.path.join(project_conf_dir(), _name),
              # Legacy location: inside the installed package. Kept so an
              # existing setup keeps working; nothing new should go here.
              os.path.join(package_conf_dir(), _name)]
    _unique = []
    for _path in _paths:
        if os.path.abspath(_path) not in [os.path.abspath(_p) for _p in _unique]:
            _unique.append(_path)
    return _unique


def find_env_file(env: str) -> str:
    """
    The yaml for `env`, or '' if there is none.

    A missing file is logged as a warning that names every place searched.
    It used to be a debug line, so a mistyped `-e stagnig` ran the whole
    suite against defaults while the report said "stagnig".
    """
    if not env:
        return ''
    if os.sep in env or '/' in env or env.startswith('.'):
        raise ValueError('env must be a plain name, got {!r}'.format(env))

    _candidates = env_candidates(env)
    for _index, _path in enumerate(_candidates):
        if os.path.isfile(_path):
            if _index:  # not the project dir, so the legacy package one
                logger.warning('env %r loaded from inside the installed package (%s); '
                               'move it to %s', env, _path, project_conf_dir())
            return _path

    logger.warning('env %r: no config found, running on base settings. Searched: %s',
                   env, ', '.join(_candidates))
    return ''
