# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : redact.py
@Time  : 2026-08-01

Strip secrets before anything is written out.

This runs on the harness side, before serialisation -- not in the template.
A report gets downloaded, forwarded, and archived as a CI artifact; masking
at render time protects only the one view that happens to use that template,
and leaves the JSON behind it fully readable.

Bias is deliberately toward over-redaction. A masked value that turned out to
be harmless costs someone a re-run; a leaked credential does not get un-leaked.
"""
import json
import re
from typing import Any

MASK = '***REDACTED***'

# Header names whose value is always a credential.
SECRET_HEADERS = frozenset({
    'authorization', 'proxy-authorization', 'cookie', 'set-cookie',
    'x-api-key', 'x-auth-token', 'x-access-token', 'x-csrf-token',
    'x-session-token', 'api-key', 'auth-token', 'private-token',
})

# Field names whose value is a credential wherever it appears.
SECRET_KEYS = re.compile(
    r'(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|'
    r'private[_-]?key|privatekey|mnemonic|seed[_-]?phrase|credential|'
    r'signature|signed[_-]?tx|session[_-]?id|refresh[_-]?token)')

# Value shapes that are credentials regardless of what they are called.
VALUE_PATTERNS = (
    # a 32-byte hex key -- an ethereum private key, among other things
    re.compile(r'\b0x[a-fA-F0-9]{64}\b'),
    re.compile(r'(?<![a-fA-F0-9])[a-fA-F0-9]{64}(?![a-fA-F0-9])'),
    # JWT
    re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+'),
    # Authorization header values found inline in a log line
    re.compile(r'(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}'),
    # common provider key prefixes
    # sk_live_…, sk-proj-…: the separator is part of every real format,
    # so requiring 16 unbroken alphanumerics after it matches none of them
    re.compile(r'\b(sk|pk|rk)[-_][A-Za-z0-9][A-Za-z0-9_-]{14,}\b'),
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    # PEM blocks
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----'),
)

# BIP-39 style seed phrases: 12 or 24 lowercase words in a row.
MNEMONIC = re.compile(r'\b(?:[a-z]{3,8}\s+){11}[a-z]{3,8}\b')


def redact_text(value: str) -> str:
    """Mask credential-shaped substrings in free text."""
    if not isinstance(value, str) or not value:
        return value
    _out = value
    for _pattern in VALUE_PATTERNS:
        _out = _pattern.sub(MASK, _out)
    _out = MNEMONIC.sub(MASK, _out)
    return _out


def redact_body(body: Any) -> Any:
    """
    Redact a request or response body.

    A body arrives as text, and text only ever went through the value-shape
    patterns -- so `{"token": "..."}` came out untouched, because the rule that
    knows `token` is a credential only ever looked at dict keys. Bodies are the
    single largest thing a report or a cassette stores, and once cassettes get
    imported from production traffic they are the likeliest place for a real
    secret to sit. So JSON is parsed, redacted as a structure, and written
    back; anything that will not parse falls back to text redaction.

    The re-serialised form follows the input: indented if the input was, compact
    if it was not, so redaction does not silently reformat a stored body.
    """
    if not isinstance(body, str) or not body.strip():
        return redact(body)
    try:
        _parsed = json.loads(body)
    except (TypeError, ValueError):
        return redact_text(body)
    if not isinstance(_parsed, (dict, list)):
        return redact_text(body)

    _clean = redact(_parsed)
    if _clean == _parsed:
        # Nothing was secret, so hand back the original bytes. Re-serialising
        # anyway would rewrite every body in the archive -- different spacing,
        # different key order, a different hash -- for no gain. A cassette is
        # replayed and diffed; gratuitous reformatting is not free there.
        return body

    if '\n' in body:
        return json.dumps(_clean, ensure_ascii=False, indent=2)
    return json.dumps(_clean, ensure_ascii=False, separators=(',', ':'))


def _is_secret_key(key: Any) -> bool:
    _name = str(key)
    return _name.lower() in SECRET_HEADERS or bool(SECRET_KEYS.search(_name))


def redact(value: Any, _depth: int = 0) -> Any:
    """
    Recursively mask secrets in any JSON-shaped structure.

    Masks on two independent signals -- the *name* of a field and the *shape*
    of a value -- because either alone misses cases: a key called `token`
    holding something innocuous still should not be published, and a private
    key pasted into a free-text error message has no field name at all.
    """
    if _depth > 20:
        # cycles are impossible in JSON data, but a hand-built structure could
        # nest pathologically; stop rather than recurse forever
        return value

    if isinstance(value, dict):
        return {_k: (MASK if _is_secret_key(_k) else redact(_v, _depth + 1))
                for _k, _v in value.items()}
    if isinstance(value, (list, tuple)):
        _items = [redact(_v, _depth + 1) for _v in value]
        return type(value)(_items) if isinstance(value, tuple) else _items
    if isinstance(value, str):
        return redact_text(value)
    return value
