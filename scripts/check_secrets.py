#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Block hardcoded credentials from being committed.

Motivation: a username/password pair sat in core/schedule/runtime.py from the
first public commit, and therefore shipped in every tagged release and every
PyPI sdist. Config-driven secrets (conf/config.yaml + AES via CryptoFactory)
were already supported -- they just were not used there.

Usage: check_secrets.py FILE [FILE ...]
"""
import re
import sys

# name = "literal"  where the literal looks like a real value
ASSIGNMENT = re.compile(
    r"""(?i)\b(password|passwd|pwd|api_key|apikey|secret|token|access_key)\b"""
    r"""\s*[:=]\s*['"]([^'"]{6,})['"]"""
)

# Values that are obviously not credentials.
PLACEHOLDER = re.compile(
    r"""(?i)^(none|null|changeme|your[-_ ]?\w+|<[^>]+>|\{\{.*\}\}|\$\{.*\}|"""
    r"""x{3,}|\*{3,}|placeholder|example|dummy|fake|test|sample|redact\w*)""",
)

# Reading a secret is fine; only literals are a problem.
SAFE_SOURCE = re.compile(r"os\.environ|getenv|safe_get|config|settings|decrypt")

PRIVATE_KEY = re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")


def scan(path: str) -> list:
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
            lines = fh.readlines()
    except OSError:
        return []

    hits = []
    for number, line in enumerate(lines, 1):
        if PRIVATE_KEY.search(line):
            hits.append((number, 'private key material'))
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
              'or an environment variable, then read them via Runtime.', file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
