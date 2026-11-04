#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Block hardcoded credentials from being committed.

Motivation: a username/password pair sat in core/schedule/runtime.py from the
first public commit, and therefore shipped in every tagged release and every
PyPI wheel -- 1.0.6 through 1.1.0 still carry it, and the repo is public, so
neither deleting the lines nor rewriting history takes it back. Config-driven
secrets (conf/config.yaml + AES via CryptoFactory) were already supported --
they just were not used there.

What the 2026-11 audit found this check could not see:

  * the username. The field `user_name`, holding `ficus-ci`, leaked alongside
    the password and matched no pattern here, because only `password`-ish
    names were listed.
  * key *files*. The framework generates its own AES key under a `BEGIN aes
    KEY` header, and its own Fernet key as raw bytes with
    no header at all. The old private-key pattern required the literal words
    `PRIVATE KEY`, so both walked straight past -- as they did past
    pre-commit's `detect-private-key`, which knows only the standard headers.
  * anything outside src/. CI ran a separate, weaker inline grep over `src/`
    alone; this script only ever ran in pre-commit, which is opt-in per
    machine. The two have been collapsed into this one, and CI now runs it
    over every tracked file.

Deliberate fixtures (tests for the redaction layer need realistic-looking
credentials) mark themselves with `pragma: allowlist secret` on the same line.
That marker is the point: it makes "this is fake" a claim someone wrote down
and a reviewer can see in the diff, rather than a gap in a regex.

Usage: check_secrets.py FILE [FILE ...]
"""
import os
import re
import sys

# name = "literal"  where the literal looks like a real value
ASSIGNMENT = re.compile(
    r"""(?i)\b(password|passwd|pwd|api_key|apikey|secret|token|access_key"""
    r"""|secret_key|client_secret|private_key|access_token|auth_token"""
    r"""|credential|user_name|username)\b"""
    r"""\s*[:=]\s*['"]([^'"]{6,})['"]"""
)

# Values that are obviously not credentials.
PLACEHOLDER = re.compile(
    r"""(?i)^(none|null|changeme|your[-_ ]?\w+|<[^>]+>|\{\{.*\}\}|\$\{.*\}|"""
    r"""x{3,}|\*{3,}|placeholder|example|dummy|fake|test|sample|redact\w*)""",
)

# Reading a secret is fine; only literals are a problem.
SAFE_SOURCE = re.compile(r"os\.environ|getenv|safe_get|config|settings|decrypt")

# Any PEM-ish key block, not just the ones whose header says "PRIVATE KEY".
# A `BEGIN aes KEY` header is what this framework writes.
KEY_BLOCK = re.compile(r"-----BEGIN [A-Za-z0-9 ]{0,24}KEY( BLOCK)?-----")

# A file that is key material regardless of what is inside it -- the Fernet key
# is raw bytes, so no content pattern can describe it.
KEY_FILENAME = re.compile(
    r"""(?i)(^|[./])(id_rsa|id_dsa|id_ecdsa|id_ed25519)([._-]|$)"""
    r"""|\.(pem|key|p12|pfx|jks|keystore|ppk)$"""
)

ALLOWLIST = re.compile(r"pragma:\s*allowlist\s+secret")

# Reading every byte of a binary blob to regex it is pointless; a key file is
# caught by name, and this keeps the gate fast enough to stay in pre-commit.
SKIP_SUFFIXES = ('.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.whl',
                 '.tar', '.gz', '.zip', '.so', '.pyc', '.jar', '.woff',
                 '.woff2', '.ttf', '.eot', '.mo')


def scan(path: str) -> list:
    _name = os.path.basename(path)
    if KEY_FILENAME.search(_name):
        return [(0, 'file is key material by name ({})'.format(_name))]
    if path.lower().endswith(SKIP_SUFFIXES):
        return []

    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
            lines = fh.readlines()
    except OSError:
        return []

    hits = []
    for number, line in enumerate(lines, 1):
        if ALLOWLIST.search(line):
            continue

        if KEY_BLOCK.search(line):
            hits.append((number, 'key material'))
            continue

        match = ASSIGNMENT.search(line)
        if not match:
            continue
        value = match.group(2)
        if PLACEHOLDER.match(value) or SAFE_SOURCE.search(line):
            continue
        hits.append((number, '{} = "{}…"'.format(match.group(1), value[:3])))
    return hits


def main(argv: list) -> int:
    failed = False
    for path in argv:
        for number, why in scan(path):
            print('{}:{}: possible hardcoded secret -- {}'.format(path, number, why),
                  file=sys.stderr)
            failed = True
    if failed:
        print('\nPut secrets in conf/config.yaml (AES-encrypted, see CryptoFactory) '
              'or an environment variable, then read them via Runtime.\n'
              'A key file does not belong in the repo at all -- the framework '
              'keeps its own under ~/.ipandora/crypto.\n'
              'If the value is a deliberate test fixture, say so on the line: '
              '# pragma: allowlist secret', file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
