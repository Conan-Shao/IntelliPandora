#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regenerate the hash-pinned lock files under requirements/.

Usage: update_locks.py [--cutoff YYYY-MM-DD]

What CI installs is resolved here, once, with three properties a plain
`pip install -e .[ai,mcp]` does not have:

- every version is pinned and every file is hashed, so CI installs exactly
  what was reviewed (`pip install --require-hashes`), never whatever the index
  serves that day;
- nothing published in the last COOLDOWN_DAYS days is eligible
  (`uv --exclude-newer`). Malicious releases are usually caught and yanked
  within days, which makes the newest release the riskiest one to adopt. The
  admission rule in docs/design/15 is enforced by the resolver, not by memory;
- one file covers Python 3.10-3.12 and every platform (`--universal`), so the
  CI matrix and a developer laptop install the same versions.

Needs uv, from requirements/tools.txt. A security fix newer than the cutoff
is taken with --cutoff and recorded as an exception (docs/security/).
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ = os.path.join(REPO, 'requirements')
COOLDOWN_DAYS = 14
PYTHON_FLOOR = '3.10'

# output -> (inputs, extras of the package itself)
LOCKS = {
    # `test` is httpretty, which test/testhttp imports. CI installed .[ai,mcp]
    # without it from 1.11.0 on and every run failed at collection.
    # `system` too: every extra a user can install is audited, used by tests or not.
    'ci.txt': (['setup.py', 'requirements/build.in'], ['ai', 'mcp', 'system', 'test']),
    'ci-noai.txt': (['setup.py', 'requirements/build.in'], ['mcp', 'test']),
    'tools.txt': (['requirements/tools.in'], []),
}


def cutoff(today: datetime.date = None) -> str:
    return ((today or datetime.date.today())
            - datetime.timedelta(days=COOLDOWN_DAYS)).isoformat()


def command(uv: str, inputs, extras, output, until: str):
    _cmd = [uv, 'pip', 'compile', *inputs, '--universal', '--python-version', PYTHON_FLOOR,
            '--generate-hashes', '--exclude-newer', until, '--quiet',
            '--custom-compile-command', 'python scripts/update_locks.py',
            '-o', os.path.join('requirements', output)]
    for _extra in extras:
        _cmd += ['--extra', _extra]
    return _cmd


def main(argv) -> int:
    _args = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    _args.add_argument('--cutoff', default=None,
                       help='newest upload date to accept (default: today - {} days)'.format(
                           COOLDOWN_DAYS))
    _args.add_argument('--uv', default=shutil.which('uv') or 'uv')
    _opts = _args.parse_args(argv)
    _until = _opts.cutoff or cutoff()
    for _output, (_inputs, _extras) in LOCKS.items():
        _cmd = command(_opts.uv, _inputs, _extras, _output, _until)
        print('$', ' '.join(_cmd))
        subprocess.run(_cmd, cwd=REPO, check=True)
    print('locks resolved with nothing newer than', _until)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
