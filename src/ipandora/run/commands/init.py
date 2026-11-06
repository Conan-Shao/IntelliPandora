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


def templates():
    """(template path, project path) for every file of the project template."""
    from importlib import resources
    _root = resources.files('ipandora') / 'templates' / 'project'
    _out = []

    def _walk(node, prefix=''):
        for _child in sorted(node.iterdir(), key=lambda c: c.name):
            _rel = prefix + _child.name
            if _child.is_dir():
                if _child.name != '__pycache__':
                    _walk(_child, _rel + '/')
            else:
                _out.append((_rel, RENAMES.get(_rel, _rel), _child))
    _walk(_root)
    return _out


def generate(directory: str, force: bool = False):
    """Write the project template into `directory`. Returns (written, kept)."""
    from ipandora.version import get_latest_version
    _version = get_latest_version()
    _written, _kept = [], []
    for _rel, _target, _node in templates():
        _path = os.path.join(directory, *_target.split('/'))
        if os.path.exists(_path) and not force:
            _kept.append(_target)
            continue
        os.makedirs(os.path.dirname(_path) or '.', exist_ok=True)
        _text = _node.read_text(encoding='utf-8').replace('{{version}}', _version)
        with open(_path, 'w', encoding='utf-8') as _f:
            _f.write(_text)
        _written.append(_target)
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
        _written, _kept = generate(_dir, force=options.force)
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
            '--force', action='store_true',
            help='overwrite files that already exist. Without it they are kept')
