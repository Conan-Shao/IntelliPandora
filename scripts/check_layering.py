#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enforce that core/ never depends on ai/.

LLM support is optional and disabled by default. If core/ could import ai/,
the framework's basic capability would quietly acquire a paid, latent,
non-reproducible dependency. See docs/design/03-LLM接入边界.md.

Detection is AST-based: it looks at real import statements, so documentation
that *mentions* ipandora.ai -- which core/triage necessarily does, since it
owns the hook that ai/ plugs into -- does not trip it. A regex over the raw
text cannot tell those apart.

Usage: check_layering.py
"""
import ast
import pathlib
import re
import sys

CORE = pathlib.Path('src/ipandora/core')
FORBIDDEN_ROOT = 'ipandora.ai'

# AST cannot see through a runtime lookup, so catch the obvious dynamic form.
DYNAMIC_IMPORT = re.compile(
    r'''import_module\s*\(\s*['"]ipandora\.ai''')


def _is_forbidden(module: str) -> bool:
    return module == FORBIDDEN_ROOT or module.startswith(FORBIDDEN_ROOT + '.')


def violations_in(path: pathlib.Path):
    _source = path.read_text(encoding='utf-8')
    _found = []

    try:
        _tree = ast.parse(_source, filename=str(path))
    except SyntaxError as exc:
        return [(exc.lineno or 0, 'could not parse: {}'.format(exc))]

    for _node in ast.walk(_tree):
        if isinstance(_node, ast.Import):
            for _alias in _node.names:
                if _is_forbidden(_alias.name):
                    _found.append((_node.lineno, 'import {}'.format(_alias.name)))
        elif isinstance(_node, ast.ImportFrom):
            # level > 0 is a relative import, which cannot reach ai/ from core/
            if _node.level == 0 and _node.module and _is_forbidden(_node.module):
                _found.append((_node.lineno, 'from {} import ...'.format(_node.module)))

    for _number, _line in enumerate(_source.splitlines(), 1):
        if DYNAMIC_IMPORT.search(_line):
            _found.append((_number, 'dynamic import: {}'.format(_line.strip())))

    return _found


def main() -> int:
    if not CORE.is_dir():
        print('check_layering: {} not found, skipping'.format(CORE), file=sys.stderr)
        return 0

    _violations = []
    _checked = 0
    for _path in sorted(CORE.rglob('*.py')):
        _checked += 1
        for _line, _what in violations_in(_path):
            _violations.append((_path, _line, _what))

    for _path, _line, _what in _violations:
        print('{}:{}: core/ must not import ai/ -- {}'.format(_path, _line, _what),
              file=sys.stderr)

    if _violations:
        print('\nRegister an analyzer through core/triage/hooks.py instead, the way '
              'ipandora.ai.enable() does.\nSee docs/design/03-LLM接入边界.md',
              file=sys.stderr)
        return 1

    print('OK: core/ has no dependency on ai/ ({} files checked)'.format(_checked))
    return 0


if __name__ == '__main__':
    sys.exit(main())
