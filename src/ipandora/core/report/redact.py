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
from urllib.parse import unquote_plus

MASK = '***REDACTED***'

# Header names whose value is always a credential.
SECRET_HEADERS = frozenset({
    'authorization', 'proxy-authorization', 'cookie', 'set-cookie',
    'x-api-key', 'x-auth-token', 'x-access-token', 'x-csrf-token',
    'x-session-token', 'api-key', 'auth-token', 'private-token',
})

MAX_DEPTH = 20
"""Deeper than this, a structure is masked whole rather than walked."""

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

_KEY_WORDS = (r'password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|'
              r'privatekey|mnemonic|seed[_-]?phrase|credential|signature|signed[_-]?tx|'
              r'session[_-]?id|refresh[_-]?token')

# `'password': 'x'`, `"token": "x"`, `password: x` -- a dict repr or a JSON
# fragment inside an error message, a YAML line in a log. Only key=value pairs
# and whole JSON bodies were masked; a message quoting the request dict
# published the password as written.
COLON_KEY = re.compile(
    r'(?<![A-Za-z0-9_\'"-])(?P<q>[\'"]?)(?P<name>[A-Za-z0-9_-]{1,64})(?P=q)[ \t]*:[ \t]*')
COLON_VALUE = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|[^\s,;}\])\'"]+')
# Two steps, not one pattern with the key words inside a [A-Za-z0-9_-]* run:
# that backtracked quadratically, and a 16 KB token followed by a colon took
# 17 seconds to redact. The key is a bounded token that must start at a word
# boundary; whether it names a credential is decided afterwards.

# `Cookie: sid=...; theme=dark` -- a header line quoted in text: the whole
# rest of the line is the credential.
HEADER_LINE = re.compile(
    r'(?im)^(?P<key>[ \t>*-]*(?:' + '|'.join(sorted(re.escape(_h) for _h in (
        'authorization', 'proxy-authorization', 'cookie', 'set-cookie', 'x-api-key',
        'x-auth-token', 'x-access-token', 'x-csrf-token', 'x-session-token', 'api-key',
        'auth-token', 'private-token'))) + r'))(?P<sep>[ \t]*:[ \t]*)(?P<val>\S[^\r\n]*)')


# Field names whose value is a credential wherever it appears.
SECRET_KEYS = re.compile(r'(?i)(' + _KEY_WORDS + r')')


def _redact_colon_pairs(text: str) -> str:
    def _header(match):
        return match.group('key') + match.group('sep') + MASK

    text = HEADER_LINE.sub(_header, text)
    _out, _pos = [], 0
    for _key in COLON_KEY.finditer(text):
        if _key.start() < _pos or not SECRET_KEYS.search(_key.group('name')):
            continue
        _value = COLON_VALUE.match(text, _key.end())
        if _value is None:
            continue
        _val = _value.group(0)
        if _val[:1] in ('"', "'"):
            if len(_val) <= 2:
                continue                        # empty string: nothing to hide
            _masked = _val[0] + MASK + _val[0]
        else:
            if _val == MASK:
                continue
            _masked = MASK
        _out.append(text[_pos:_value.start()])
        _out.append(_masked)
        _pos = _value.end()
    _out.append(text[_pos:])
    return ''.join(_out)


# One key=value run of a form body, a query string or a cookie line:
# `password=hunter2` in `username=alice&password=hunter2`.
SEGMENT = re.compile(r'[^&?;\s]+')


def _redact_pairs(text: str) -> str:
    """
    Mask the value of every key=value pair whose key names a credential.

    A form-encoded login body went through the value-shape patterns only, and
    `password=hunter2` has no shape -- so it reached the report as written,
    exactly where it is most likely to appear. The key is what gives it away,
    the same rule JSON bodies already followed. Only the value is replaced;
    the rest of the text is left byte for byte.
    """
    def _segment(match):
        _seg = match.group(0)
        if '=' not in _seg:
            return _seg
        # split on every '=': `body=password=hunter2` hides a pair inside a
        # value, and base64 padding (`token=abc==`) belongs to the value
        _parts = _seg.split('=')
        for _i, _key in enumerate(_parts[:-1]):
            if _key and _is_secret_key(unquote_plus(_key)):
                if not '='.join(_parts[_i + 1:]).strip('='):
                    return _seg                 # `token=`: nothing to hide
                return '{}={}'.format('='.join(_parts[:_i + 1]), MASK)
        return _seg
    return SEGMENT.sub(_segment, text)


def redact_text(value: str) -> str:
    """Mask credential-shaped substrings in free text, and credential-named key=value pairs."""
    if not isinstance(value, str) or not value:
        return value
    _out = value
    for _pattern in VALUE_PATTERNS:
        _out = _pattern.sub(MASK, _out)
    _out = MNEMONIC.sub(MASK, _out)
    if '=' in _out:
        _out = _redact_pairs(_out)
    if ':' in _out:
        _out = _redact_colon_pairs(_out)
    return _out


def redact_body(body: Any) -> Any:
    """
    Redact a request or response body.

    A body arrives as text, and text only ever went through the value-shape
    patterns -- so `{"token": "..."}` came out untouched, because the rule that
    knows `token` is a credential only ever looked at dict keys. Bodies are the
    single largest thing a report stores, and the likeliest place for a real
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
        # different key order, a different hash -- for no gain.
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
    if _depth > MAX_DEPTH:
        # Cycles are impossible in JSON data, but a hand-built structure could
        # nest pathologically; stop rather than recurse forever. Masked, not
        # returned as it was: everything below this depth used to be published
        # unredacted, and a deeply nested API response is not unusual.
        return MASK if isinstance(value, (dict, list, tuple, str)) else value

    if isinstance(value, dict):
        return {_k: (MASK if _is_secret_key(_k) else redact(_v, _depth + 1))
                for _k, _v in value.items()}
    if isinstance(value, (list, tuple)):
        _items = [redact(_v, _depth + 1) for _v in value]
        return type(value)(_items) if isinstance(value, tuple) else _items
    if isinstance(value, str):
        return redact_text(value)
    return value
