# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : init.py
@Time  : 2026-11-05
"""
import os
import sys
from argparse import Namespace

from ipandora.run.commandbase import CommandBase

# template path (under ipandora/templates/project) -> where it goes in the project
RENAMES = {
    'conftest.py.tmpl': 'conftest.py',
    'tests/test_example.py.tmpl': 'tests/test_example.py',
    '_github/workflows/tests.yml.tmpl': '.github/workflows/tests.yml',
    '_github/CODEOWNERS.tmpl': '.github/CODEOWNERS',
    'gitignore.tmpl': '.gitignore',
}


LAYOUTS = ('minimal', 'full')

# files of the minimal project that the full layout replaces with its own
FULL_DROPS = {'tests/test_example.py'}


def _target(rel: str) -> str:
    """Where a template file goes: `.tmpl` dropped, `_github` -> `.github`."""
    if rel in RENAMES:
        return RENAMES[rel]
    _out = rel[:-len('.tmpl')] if rel.endswith('.tmpl') else rel
    if _out.startswith('_github/'):
        _out = '.github/' + _out[len('_github/'):]
    return _out


def templates(layout: str = 'minimal'):
    """
    (template path, project path, resource) for every file of the project.

    `full` is the minimal project with the layered library on top -- apis/,
    flows/, pages/, data/, tests/api and tests/web, and the pytest.ini that
    lets cases import them (docs/design/decisions/17 §3).
    """
    if layout not in LAYOUTS:
        raise ValueError('unknown layout {!r}; use one of {}'.format(layout, ', '.join(LAYOUTS)))
    from importlib import resources
    _base = resources.files('ipandora') / 'templates'
    _out = {}

    def _walk(node, prefix=''):
        for _child in sorted(node.iterdir(), key=lambda c: c.name):
            _rel = prefix + _child.name
            if _child.is_dir():
                if _child.name != '__pycache__':
                    _walk(_child, _rel + '/')
            else:
                _out[_target(_rel)] = (_rel, _child)

    _walk(_base / 'project')
    if layout == 'full':
        for _drop in FULL_DROPS:
            _out.pop(_drop, None)
        _walk(_base / 'full')
    return [(_rel, _t, _node) for _t, (_rel, _node) in sorted(_out.items())]


def generate(directory: str, force: bool = False, layout: str = 'minimal'):
    """Write the project template into `directory`. Returns (written, kept)."""
    from ipandora.version import get_latest_version
    _version = get_latest_version()
    _written, _kept = [], []
    for _rel, _target_path, _node in templates(layout):
        _path = os.path.join(directory, *_target_path.split('/'))
        if os.path.exists(_path) and not force:
            _kept.append(_target_path)
            continue
        os.makedirs(os.path.dirname(_path) or '.', exist_ok=True)
        _text = _node.read_text(encoding='utf-8').replace('{{version}}', _version)
        with open(_path, 'w', encoding='utf-8') as _f:
            _f.write(_text)
        _written.append(_target_path)
    return _written, _kept


class Command(CommandBase):
    """
    Start a test project: config, an example that passes offline, the
    AGENTS.md that tells a coding agent the rules, and CI with the gate.

    Built-in templates (importlib.resources) rather than a scaffolding tool:
    one fewer component to admit, and nothing here needs upgrading templates
    in place. An existing file is never overwritten without --force -- running
    init in a project that already has a conftest.py must not replace it.
    """

    def handle(self, options: Namespace):
        _dir = os.path.abspath(options.directory)
        _written, _kept = generate(_dir, force=options.force, layout=options.layout)
        print('')
        for _f in _written:
            print('  写入  {}'.format(_f))
        for _f in _kept:
            print('  保留  {}（已存在，未覆盖；用 --force 覆盖）'.format(_f))
        print('')
        print('  下一步：')
        try:
            _shown = os.path.relpath(_dir)
        except ValueError:      # Windows: the target is on another drive
            _shown = _dir
        print('    cd {}'.format(_shown))
        print('    ipandora run tests                    # 跑示例用例')
        print('    ipandora run tests --update-baseline  # 接受判定，写入 conf/judgements.json')
        print('    git add conf/judgements.json          # 把基线和用例一起提交')
        print('')
        print('  给 agent 的规则在 AGENTS.md；把 .github/CODEOWNERS 里的 @your-team 换成真实的负责人。')
        print('')
        sys.exit(0)

    @property
    def help(self):
        return 'start a test project: config, a passing example, AGENTS.md and CI with the gate'

    @property
    def sub_command_name(self):
        return 'init'

    def add_arguments(self):
        self.parser.add_argument(
            'directory', nargs='?', default='.',
            help='where to create the project. Default: the current directory')
        self.parser.add_argument(
            '--layout', choices=LAYOUTS, default='minimal',
            help='minimal: one example file. full: a layered case library -- apis/, '
                 'flows/, pages/, data/, tests/api, tests/web, with pytest.ini -- '
                 'whose examples log in as buyer and seller')
        self.parser.add_argument(
            '--force', action='store_true',
            help='overwrite files that already exist. Without it they are kept')
