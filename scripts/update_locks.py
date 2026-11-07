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
  admission rule in docs/design/decisions/15 is enforced by the resolver, not by memory;
- one file covers Python 3.10-3.12 and every platform (`--universal`), so the
  CI matrix and a developer laptop install the same versions.

Needs uv, from requirements/tools.txt. A security fix newer than the cutoff
is taken with --cutoff and recorded as an exception (docs/security/).
"""
import argparse
import datetime
import os
import re
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
    # `parallel` in both, so the parallel tests run in every CI job, with and
    # without ai/.
    # `inspect` only in ci.txt: ci-noai checks that nothing needs ai/, and
    # the Inspect path is tested where every extra is installed.
    'ci.txt': (['setup.py', 'requirements/build.in'],
               ['ai', 'android', 'inspect', 'mcp', 'parallel', 'system', 'test', 'visual', 'web']),
    'ci-noai.txt': (['setup.py', 'requirements/build.in'],
                    ['android', 'mcp', 'parallel', 'test', 'visual', 'web']),
    'tools.txt': (['requirements/tools.in'], []),
    # The Android comparison job only (M5c): the framework's android extra and
    # the Appium client, resolved together so the two cannot disagree on a
    # shared dependency.
    'bench.txt': (['setup.py', 'requirements/build.in', 'requirements/bench.in'], ['android']),
}

# npm projects whose package-lock.json is regenerated the same way: hashed
# (npm writes an sha512 `integrity` per tarball), and nothing published inside
# the cooldown -- `npm --before` applies it to every transitive package, not
# only the ones package.json names. No install scripts run while resolving.
NPM_PROJECTS = ('bench/android',)

# A later cutoff for one npm project, taken for a security fix newer than the
# cooldown (docs/design/decisions/15: taken, and written down). Used only while
# it is later than the default; once the default passes it, it does nothing.
NPM_SECURITY_CUTOFF = {
    # appium 3.8.0 / driver 8.7.0 (the newest past the cooldown) pulled in
    # shell-quote <1.11 (GHSA-pqg4-j6r4-53mv, critical), proxy-addr <2.0.8
    # (GHSA-jqcg-44mw-7w3h, critical), axios <1.20, body-parser <2.4 and
    # follow-redirects 1.16.0/1.16.1. appium 3.9.0 (2026-10-27) and driver
    # 8.7.3 (2026-10-28) fix all of them. What this lets in younger than 14
    # days is listed in docs/security/components.md.
    'bench/android': '2026-10-29T00:00:00Z',
}


def _instant(value: str) -> datetime.datetime:
    _v = value.strip().replace('Z', '+00:00')
    _t = datetime.datetime.fromisoformat(_v)
    return _t if _t.tzinfo else _t.replace(tzinfo=datetime.timezone.utc)


def npm_cutoff(project: str, default: str) -> str:
    """
    The later of the default cutoff and the project's security cutoff,
    compared as instants (CR19): as strings, a --cutoff written with an
    offset (2026-10-29T06:00:00+08:00) was ordered by its characters.
    """
    _security = NPM_SECURITY_CUTOFF.get(project)
    if not _security:
        return default
    return _security if _instant(_security) > _instant(default) else default


def npm_command(npm: str, until: str):
    return [npm, 'install', '--package-lock-only', '--ignore-scripts', '--no-audit', '--no-fund',
            '--before', until]


def cutoff(today: datetime.date = None) -> str:
    """
    Midnight UTC, COOLDOWN_DAYS ago, as a full timestamp.

    Not a bare date: uv reads `--exclude-newer 2026-10-22` as including the
    whole of that day, so a release uploaded that afternoon -- 13 days and
    some hours old -- got in. Found when playwright 1.64.1 did.
    """
    return ((today or datetime.date.today())
            - datetime.timedelta(days=COOLDOWN_DAYS)).isoformat() + 'T00:00:00Z'


def normalised_cutoff(value: str) -> str:
    """
    --cutoff as uv should read it. A bare date is midnight UTC at its start,
    the same rule as cutoff(): passed on as given, uv read `2026-10-22` as
    the whole of that day and a release from that afternoon got in.
    """
    _value = value.strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', _value):
        datetime.date.fromisoformat(_value)        # reject 2026-13-45
        return _value + 'T00:00:00Z'
    return _value


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
                       help='accept nothing uploaded at or after this moment: a date (midnight '
                            'UTC at its start) or a full timestamp (default: today - {} days)'.format(
                           COOLDOWN_DAYS))
    _args.add_argument('--uv', default=shutil.which('uv') or 'uv')
    _args.add_argument('--npm', default=shutil.which('npm') or 'npm')
    _args.add_argument('--only', action='append', default=None,
                       choices=sorted(LOCKS) + list(NPM_PROJECTS),
                       help='regenerate just this lock (repeatable); default: all of them')
    _opts = _args.parse_args(argv)
    _until = normalised_cutoff(_opts.cutoff) if _opts.cutoff else cutoff()
    for _output, (_inputs, _extras) in LOCKS.items():
        if _opts.only and _output not in _opts.only:
            continue
        _cmd = command(_opts.uv, _inputs, _extras, _output, _until)
        print('$', ' '.join(_cmd))
        subprocess.run(_cmd, cwd=REPO, check=True)
    for _project in NPM_PROJECTS:
        if _opts.only and _project not in _opts.only:
            continue
        _cmd = npm_command(_opts.npm, npm_cutoff(_project, _until))
        print('$ (cd {})'.format(_project), ' '.join(_cmd))
        subprocess.run(_cmd, cwd=os.path.join(REPO, _project), check=True)
    print('locks resolved with nothing newer than', _until)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
