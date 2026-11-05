#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build a wheel and assert the data files the framework needs are inside it.

Motivation: the 1.1.0 wheel on PyPI ships `ipandora/conf/__init__.py` and not
one of the data files beside it. No config.yaml, no report templates -- a
`pip install`ed copy cannot render a report. Verified by downloading it.

Why no test caught it: CI installs the repo in editable mode and reads those
files straight out of the source tree, where they obviously exist.

Why fixing MANIFEST.in is not the guarantee: its paths were wrong (they named
the distribution, `intellipandora`, instead of the package path under `src/`),
but current setuptools -- tested at 79.0.1 -- honours
`include_package_data=True` by taking every file inside a package directory,
so a build from this tree ships them even with MANIFEST.in deleted. The
published artifact therefore depended on the setuptools version of whichever
machine cut the release, and can regress again without a line of this repo
changing.

Which is the shape of bug this guards: correctness that lives outside the
source. The only way to know is to look inside the artifact.

Usage: check_packaging.py                 # builds into a temp dir
       check_packaging.py --no-isolation  # builds with the setuptools installed
                                          # here (CI: the hashed tools lock)
       check_packaging.py some.whl        # inspects a wheel already built
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files whose absence breaks a documented feature, not merely a nice-to-have.
REQUIRED = (
    'ipandora/conf/config.yaml',            # every Runtime lookup
    'ipandora/conf/static/report.html',     # ipandora run --report
    'ipandora/conf/static/history.html',    # the run history index
    'ipandora/conf/static/_style.html',     # shared by report.html and eval.html
    'ipandora/conf/static/eval.html',       # ipandora eval run
    'ipandora/templates/project/AGENTS.md',  # ipandora init
    'ipandora/templates/project/tests/test_example.py.tmpl',
    'ipandora/templates/project/_github/workflows/tests.yml.tmpl',
)

# Key material must never be packaged, whatever a stale checkout holds.
FORBIDDEN_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.jks')


def build_wheel(into: str, isolated: bool = True) -> str:
    # `include_package_data` resolves through *.egg-info/SOURCES.txt, which
    # setuptools reuses if it is already there. A wheel built over a SOURCES.txt
    # from an earlier, correct MANIFEST.in contains the data files no matter
    # what MANIFEST.in says now -- so this check would pass on a repo it should
    # fail. Verified: with the stale egg-info left in place, reintroducing the
    # original bug did not trip this script.
    for _stale in glob.glob(os.path.join(REPO, 'src', '*.egg-info')):
        shutil.rmtree(_stale, ignore_errors=True)
    # build/ for the same reason, worse: setuptools copies sources into
    # build/lib and never deletes what is already there. After core/cassette
    # was removed from src/, a wheel built over the old build/lib still shipped
    # all nine of its files -- deleted code, packaged and publishable.
    shutil.rmtree(os.path.join(REPO, 'build'), ignore_errors=True)

    # An isolated build fetches setuptools from the index, unhashed, at
    # whatever version pyproject.toml allows. CI and release pass
    # --no-isolation so the backend is the one from requirements/tools.txt.
    _cmd = [sys.executable, '-m', 'build', '--wheel', '--outdir', into]
    if not isolated:
        _cmd.append('--no-isolation')
    subprocess.run(_cmd, cwd=REPO, check=True, capture_output=True)
    _wheels = [f for f in os.listdir(into) if f.endswith('.whl')]
    if not _wheels:
        raise SystemExit('build produced no wheel')
    return os.path.join(into, _wheels[0])


def inspect(wheel: str) -> int:
    with zipfile.ZipFile(wheel) as zf:
        _names = set(zf.namelist())

    _problems = []
    for _path in REQUIRED:
        if _path not in _names:
            _problems.append('missing: {}'.format(_path))

    for _name in sorted(_names):
        if _name.lower().endswith(FORBIDDEN_SUFFIXES):
            _problems.append('key material packaged: {}'.format(_name))

    # Nothing in the wheel that is not in the source tree. Cleaning build/
    # above fixes the one way this is known to happen; this catches the rest,
    # including a wheel handed in from somewhere else.
    for _name in sorted(_names):
        if _name.startswith('ipandora/') and _name.endswith('.py'):
            if not os.path.isfile(os.path.join(REPO, 'src', _name)):
                _problems.append('not in src/, yet packaged: {}'.format(_name))

    print('{}: {} entries'.format(os.path.basename(wheel), len(_names)))
    for _problem in _problems:
        print('  {}'.format(_problem), file=sys.stderr)

    if _problems:
        print('\nA data file inside a package is picked up by '
              '`include_package_data=True` on current setuptools, and by '
              'MANIFEST.in on older versions -- so check the setuptools '
              'version doing the build first, then MANIFEST.in (its paths are '
              'relative to the project root, so a package under src/ needs '
              '`src/ipandora/...`; the distribution name is not a path).',
              file=sys.stderr)
        return 1

    print('OK: every required data file is in the wheel, nothing stale, no key material')
    return 0


def main(argv: list) -> int:
    _isolated = '--no-isolation' not in argv
    _wheels = [a for a in argv if a != '--no-isolation']
    if _wheels:
        return inspect(_wheels[0])
    with tempfile.TemporaryDirectory() as _tmp:
        return inspect(build_wheel(_tmp, _isolated))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
