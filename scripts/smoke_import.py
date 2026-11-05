#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Import every module under `ipandora` and fail if any of them raises.

This exists because v1.1.0 shipped two modules that raised NameError at import
time (teststeprepository / testcasetagsrepository referenced dataclasses that
did not exist in the module they imported from). Nothing in the repo would have
caught it -- there was no CI and no test touched those modules.

Modules that need an optional extra are allowed to fail on that extra alone,
so this also passes against a *minimal* install -- which is the install most
users get and the one nothing used to check. Anything else failing to import
is still a failure, including an optional module that breaks for some other
reason: `utils/log.py` once imported robot.api unguarded, and the mistake was
exactly this one made at package scope.

Run: python scripts/smoke_import.py
"""
import importlib
import pkgutil
import sys

import ipandora

# module prefix -> the third-party package it legitimately needs
OPTIONAL = {
    'ipandora.ai': 'anthropic',
    'ipandora.core.mcp': 'mcp',
}


def excused(name: str, exc: Exception) -> str:
    """The extra this module may be missing, or '' if it has no excuse."""
    if not isinstance(exc, ImportError):
        return ''
    _missing = getattr(exc, 'name', '') or ''
    for _prefix, _package in OPTIONAL.items():
        if name.startswith(_prefix) and _missing.split('.')[0] == _package:
            return _package
    return ''


def main() -> int:
    failures, skipped = [], []
    checked = 0
    for module in pkgutil.walk_packages(ipandora.__path__, 'ipandora.'):
        checked += 1
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # noqa: BLE001 - any import failure is a failure
            _extra = excused(module.name, exc)
            if _extra:
                skipped.append((module.name, _extra))
                continue
            failures.append((module.name, '{}: {}'.format(type(exc).__name__, exc)))

    print('smoke: imported {} module(s), {} failure(s){}'.format(
        checked, len(failures),
        ', {} needing an optional extra'.format(len(skipped)) if skipped else ''))
    for name, extra in skipped:
        print('  skip {} (needs {})'.format(name, extra))
    for name, err in failures:
        print('  FAIL {} -> {}'.format(name, err), file=sys.stderr)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
