#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enforce that core/ never depends on ai/.

LLM support is optional and disabled by default. If core/ could import ai/,
the framework's basic capability would quietly acquire a paid, latent,
non-reproducible dependency. See docs/design/03-LLM接入边界.md.

Usage: check_layering.py
"""
import pathlib
import re
import sys

CORE = pathlib.Path('src/ipandora/core')
FORBIDDEN = re.compile(r'\bipandora\.ai\b|\bfrom\s+ipandora\s+import\s+.*\bai\b')


def main() -> int:
    if not CORE.is_dir():
        print('check_layering: {} not found, skipping'.format(CORE), file=sys.stderr)
        return 0

    violations = []
    for path in sorted(CORE.rglob('*.py')):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if line.lstrip().startswith('#'):
                continue
            if FORBIDDEN.search(line):
                violations.append((path, number, line.strip()))

    for path, number, line in violations:
        print('{}:{}: core/ must not import ai/ -- {}'.format(path, number, line),
              file=sys.stderr)

    if violations:
        print('\nSee docs/design/03-LLM接入边界.md', file=sys.stderr)
        return 1

    print('OK: core/ has no dependency on ai/')
    return 0


if __name__ == '__main__':
    sys.exit(main())
