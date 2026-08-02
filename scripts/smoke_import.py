#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Import every module under `ipandora` and fail if any of them raises.

This exists because v1.1.0 shipped two modules that raised NameError at import
time (teststeprepository / testcasetagsrepository referenced dataclasses that
did not exist in the module they imported from). Nothing in the repo would have
caught it -- there was no CI and no test touched those modules.

Run: python scripts/smoke_import.py
"""
import importlib
import pkgutil
import sys

import ipandora


def main() -> int:
    failures = []
    checked = 0
    for module in pkgutil.walk_packages(ipandora.__path__, 'ipandora.'):
        checked += 1
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # noqa: BLE001 - any import failure is a failure
            failures.append((module.name, '{}: {}'.format(type(exc).__name__, exc)))

    print('smoke: imported {} module(s), {} failure(s)'.format(checked, len(failures)))
    for name, err in failures:
        print('  FAIL {} -> {}'.format(name, err), file=sys.stderr)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
