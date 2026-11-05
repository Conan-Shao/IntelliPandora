#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gate: every third-party component is admitted, licensed and unexpired.

Usage: check_components.py                 # registry vs declarations, exceptions
       check_components.py --licenses      # also: licenses of the installed env
       check_components.py --ignore-args   # print --ignore-vuln args for pip-audit
       check_components.py --licenses-json # licenses of the installed env, as JSON
                                           # (read by scripts/security_report.py)

Three checks, all offline:

1. **Registry matches reality.** Everything declared -- setup.cfg
   install_requires, setup.py extras, requirements/*.in, and every `uses:` in
   .github/workflows -- must appear in docs/security/components.md with the
   same version spec. An entry the code no longer uses fails too: a registry
   that drifts from the code is a registry nobody can trust. This is what
   makes "admitted before it is introduced" enforceable rather than a
   convention (docs/design/decisions/15 §3).
2. **Licenses are on the allowlist**, for every distribution in the current
   environment -- transitive ones included, since that is what ships.
3. **Vulnerability exceptions have not expired.** docs/security/exceptions.md
   lets a known, unfixable advisory through with a reason and a date. Past the
   date it fails, or an exception quietly becomes a permanent waiver.
"""
import argparse
import ast
import configparser
import datetime
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(REPO, 'docs', 'security', 'components.md')
EXCEPTIONS = os.path.join(REPO, 'docs', 'security', 'exceptions.md')

# SPDX-ish tokens a license string may contain. Matching is on tokens so
# "Apache-2.0 OR BSD-3-Clause" and the classifier "Apache Software License"
# both pass. Copyleft is not here on purpose -- see docs/design/decisions/15 §3.
ALLOWED = ('MIT', 'BSD', 'Apache', 'ISC', 'MPL-2.0', 'Mozilla Public License 2.0',
           'PSF', 'Python Software Foundation', 'HPND', 'Unlicense', 'CC0',
           'Zlib', '0BSD')
DENIED = ('GPL', 'AGPL', 'LGPL', 'SSPL', 'Commons Clause', 'BUSL')

# Distributions whose metadata does not state a license in a parseable way,
# checked by hand against their repository. Each needs a reason.
LICENSE_OVERRIDES = {
    # the project itself; Apache-2.0, see LICENSE
    'intellipandora': 'Apache-2.0',
}

# Licenses outside the allowlist, accepted one by one after a review: the
# license as we use it, and why. Each is shown as such in the public report.
# docs/design/decisions/15 §3: copyleft never enters the core; an optional group needs
# its own review -- this is where that review is written down.
REVIEWED_LICENSES = {
    'text-unidecode': (
        'Artistic-1.0 OR GPL-2.0-or-later (used under Artistic-1.0)',
        'only with the optional [web] group, via pytest-playwright -> python-slugify, '
        'which uses it to transliterate test ids into artifact folder names. Dual '
        'licensed; we take the Artistic License, not the GPL. Reviewed 2026-11-05'),
}


def norm(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def split_req(req: str):
    req = req.split(';', 1)[0].split('#', 1)[0].strip()
    _m = re.match(r'^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$', req)
    if not _m:
        return None
    return norm(_m.group(1)), _m.group(3).replace(' ', '')


# -- declarations ----------------------------------------------------------

def declared():
    """{name: (category, spec)} from every place a dependency can be declared."""
    _out = {}
    _cfg = configparser.ConfigParser()
    _cfg.read(os.path.join(REPO, 'setup.cfg'), encoding='utf-8')
    for _line in _cfg.get('options', 'install_requires', fallback='').splitlines():
        _r = split_req(_line)
        if _r:
            _out[_r[0]] = ('runtime', _r[1])

    _tree = ast.parse(open(os.path.join(REPO, 'setup.py'), encoding='utf-8').read())
    for _node in ast.walk(_tree):
        if isinstance(_node, ast.keyword) and _node.arg == 'extras_require':
            for _key, _value in zip(_node.value.keys, _node.value.values):
                for _elt in _value.elts:
                    _r = split_req(_elt.value)
                    if _r:
                        _out[_r[0]] = ('extra:' + _key.value, _r[1])

    for _path, _category in (('requirements/build.in', 'build'), ('requirements/tools.in', 'tool')):
        for _line in open(os.path.join(REPO, _path), encoding='utf-8'):
            _r = split_req(_line)
            if _r and _r[0] not in _out:
                _out[_r[0]] = (_category, _r[1])

    for _wf in sorted(glob.glob(os.path.join(REPO, '.github', 'workflows', '*.yml'))):
        for _line in open(_wf, encoding='utf-8'):
            _m = re.match(r'^\s*-?\s*uses:\s*([^@\s]+)@([0-9a-f]{40})\s*#\s*(v[\w.]+)', _line)
            if _m:
                _out[norm(_m.group(1))] = ('action', '{}@{}'.format(_m.group(3), _m.group(2)))
            elif re.match(r'^\s*-?\s*uses:\s*\S+@', _line) and 'uses: ./' not in _line:
                _out['!unpinned:' + _line.strip()] = ('action', 'NOT PINNED TO A SHA')
    return _out


def registry():
    """{name: (category, spec)} parsed from the registry's tables."""
    _out = {}
    for _line in open(REGISTRY, encoding='utf-8'):
        _cells = [_c.strip() for _c in _line.strip().strip('|').split('|')]
        if len(_cells) != 7 or _cells[0] in ('组件', '') or set(_cells[0]) <= set('-'):
            continue
        _out[norm(_cells[0])] = (_cells[1], _cells[2].replace(' ', ''))
    return _out


def check_registry():
    _problems = []
    _declared, _registered = declared(), registry()
    for _name, (_category, _spec) in sorted(_declared.items()):
        if _name.startswith('!unpinned:'):
            _problems.append('action not pinned to a commit SHA: {}'.format(_name[10:]))
            continue
        if _name not in _registered:
            _problems.append('not in the registry: {} ({} {})'.format(_name, _category, _spec))
            continue
        _reg_cat, _reg_spec = _registered[_name]
        if (_reg_cat, _reg_spec) != (_category, _spec):
            _problems.append('registry says {} {} but the code declares {} {}: {}'.format(
                _reg_cat, _reg_spec, _category, _spec, _name))
    for _name in sorted(set(_registered) - set(_declared)):
        _problems.append('in the registry but no longer used: {}'.format(_name))
    return _problems


# -- licenses ----------------------------------------------------------------

def license_of(dist) -> str:
    _meta = dist.metadata
    _expr = (_meta.get('License-Expression') or '').strip()
    if _expr:
        return _expr
    _classifiers = [_c.split('::')[-1].strip() for _c in (_meta.get_all('Classifier') or [])
                    if _c.startswith('License ::') and 'OSI Approved' != _c.split('::')[-1].strip()]
    if _classifiers:
        return ' / '.join(_classifiers)
    return (_meta.get('License') or '').strip().splitlines()[0] if _meta.get('License') else ''


def license_ok(text: str):
    if any(_d.lower() in text.lower() for _d in DENIED):
        return False
    return any(_a.lower() in text.lower() for _a in ALLOWED)


def check_licenses():
    """(problems, {name: (version, license text)}) for the running interpreter."""
    import importlib.metadata as md
    _problems, _seen = [], {}
    for _dist in md.distributions():
        _name = norm(_dist.metadata['Name'] or '')
        if not _name or _name in _seen:
            continue
        if _name in REVIEWED_LICENSES:
            _seen[_name] = (_dist.version, REVIEWED_LICENSES[_name][0])
            continue
        _text = LICENSE_OVERRIDES.get(_name) or license_of(_dist)
        _seen[_name] = (_dist.version, _text)
        if not _text:
            _problems.append('no license stated: {} {}'.format(_name, _dist.version))
        elif not license_ok(_text):
            _problems.append('license not on the allowlist: {} {} ({})'.format(
                _name, _dist.version, _text))
    return _problems, _seen


# -- exceptions --------------------------------------------------------------

def exceptions():
    _out = []
    for _line in open(EXCEPTIONS, encoding='utf-8'):
        _cells = [_c.strip() for _c in _line.strip().strip('|').split('|')]
        if len(_cells) != 4 or _cells[0] in ('漏洞编号', '') or set(_cells[0]) <= set('-'):
            continue
        _out.append({'id': _cells[0], 'component': _cells[1], 'reason': _cells[2],
                     'expires': _cells[3]})
    return _out


def check_exceptions(today: datetime.date = None):
    _today = today or datetime.date.today()
    _problems = []
    for _e in exceptions():
        try:
            _expiry = datetime.date.fromisoformat(_e['expires'])
        except ValueError:
            _problems.append('exception {} has no valid expiry date: {!r}'.format(
                _e['id'], _e['expires']))
            continue
        if not _e['reason']:
            _problems.append('exception {} gives no reason'.format(_e['id']))
        if _expiry < _today:
            _problems.append('exception {} for {} expired on {}: upgrade, or re-review and '
                             'renew it with a new reason'.format(_e['id'], _e['component'],
                                                                 _e['expires']))
    return _problems


def ignore_args(today: datetime.date = None):
    _today = today or datetime.date.today()
    _args = []
    for _e in exceptions():
        try:
            if datetime.date.fromisoformat(_e['expires']) >= _today:
                _args += ['--ignore-vuln', _e['id']]
        except ValueError:
            pass
    return _args


def main(argv) -> int:
    _p = argparse.ArgumentParser()
    _p.add_argument('--licenses', action='store_true')
    _p.add_argument('--ignore-args', action='store_true')
    _p.add_argument('--licenses-json', action='store_true')
    _opts = _p.parse_args(argv)
    if _opts.ignore_args:
        print(' '.join(ignore_args()))
        return 0
    if _opts.licenses_json:
        import json
        _, _seen = check_licenses()
        print(json.dumps({_n: {'version': _v, 'license': _t,
                               'allowed': _n in REVIEWED_LICENSES or license_ok(_t),
                               'reviewed': REVIEWED_LICENSES.get(_n, ('', ''))[1]}
                          for _n, (_v, _t) in sorted(_seen.items())}, ensure_ascii=False))
        return 0

    _problems = check_registry() + check_exceptions()
    if _opts.licenses:
        _license_problems, _seen = check_licenses()
        _problems += _license_problems
        print('licenses: {} distributions checked'.format(len(_seen)))
    for _problem in _problems:
        print('  ' + _problem, file=sys.stderr)
    if _problems:
        print('\nSee docs/design/decisions/15-第三方组件安全准入与漏洞扫描.md: a component is admitted '
              '(and registered in docs/security/components.md) before it is introduced.',
              file=sys.stderr)
        return 1
    print('OK: {} components declared, all registered; exceptions current'.format(
        len(declared())))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
