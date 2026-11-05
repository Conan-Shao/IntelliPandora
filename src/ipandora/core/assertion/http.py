# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : http.py
@Time  : 2026-08-01
"""
import hashlib
import json
from typing import Any, Optional

from ipandora.core.assertion.check import Check, Source, brief
from ipandora.core.assertion.field import Field
from ipandora.core.assertion.jsonpath import MISSING, resolve
from ipandora.utils.match import same

_UNSET = object()


def raw_response(response: Any):
    """
    Accept either a ResponseHandler or a bare requests.Response.

    Checks read the transport response directly rather than going through
    ResponseHandler.fetch_all()/target, which mis-handles single-object,
    null and scalar payloads.
    """
    return getattr(response, 'response', response)


def status_code(response: Any) -> Optional[int]:
    return getattr(raw_response(response), 'status_code', None)


def json_value(response: Any, path: str):
    """
    Read one value out of a JSON response.

    Returns (value, reason). On failure value is MISSING and reason explains
    why -- unparseable body, or exactly where the path walk stopped. Never
    raises, so a custom check can turn the reason straight into a failed Check
    instead of blowing up and hiding the other checks in the same run.

        def fee_within_cap(resp, cap):
            fee, err = json_value(resp, 'data.fee')
            if err:
                return Check(name='手续费在上限内', ok=False, expr=err)
            ...
    """
    _body, _err = json_body(response)
    if _err:
        return MISSING, _err
    return resolve(_body, path)


def json_body(response: Any):
    """
    Parse the body as plain JSON. Returns (value, reason); reason is non-empty
    when the body could not be parsed.
    """
    _raw = raw_response(response)
    _content = getattr(_raw, 'content', None)
    if _content is None:
        _content = getattr(_raw, 'text', None)
    if _content is None:
        return MISSING, 'response has no body'
    if isinstance(_content, bytes):
        try:
            _content = _content.decode('utf-8')
        except UnicodeDecodeError as exc:
            return MISSING, 'body is not utf-8 ({})'.format(exc)
    try:
        return json.loads(_content), ''
    except (ValueError, TypeError) as exc:
        _preview = _content[:120] if isinstance(_content, str) else repr(_content)[:120]
        return MISSING, 'body is not JSON ({}): {!r}'.format(exc, _preview)


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------

def status_is(response: Any, expected: int, name: str = None) -> Check:
    """Assert an exact status code."""
    _actual = status_code(response)
    return Check(
        name=name or '状态码为 {}'.format(expected),
        ok=_actual == expected,
        expr='status = {} (expected {})'.format(_actual, expected),
        src=Source.API, claim='status == {}'.format(expected))


def status_ok(response: Any, name: str = None) -> Check:
    """
    Assert the request succeeded (2xx).

    Include this in every HTTP test. Without it a 500 is indistinguishable
    from a pass: nothing else in the stack looks at the status code.
    """
    _actual = status_code(response)
    _ok = _actual is not None and 200 <= _actual < 300
    return Check(
        name=name or '请求成功 (2xx)',
        ok=_ok,
        expr='status = {}'.format(_actual),
        src=Source.API, claim='status is 2xx')


def header_is(response: Any, header: str, expected: str, name: str = None) -> Check:
    _headers = getattr(raw_response(response), 'headers', {}) or {}
    _actual = _headers.get(header)
    return Check(
        name=name or '响应头 {} 为 {}'.format(header, expected),
        ok=_actual == expected,
        expr='{} = {} (expected {})'.format(header, brief(_actual), brief(expected)),
        src=Source.API, claim='header {} == {}'.format(header, brief(expected, 60)))


# --------------------------------------------------------------------------
# body
# --------------------------------------------------------------------------

def json_has(response: Any, path: str, name: str = None) -> Check:
    """Assert a field exists. Present-but-null counts as existing."""
    _label = name or '存在字段 {}'.format(path)
    _value, _reason = json_value(response, path)
    return Check(
        name=_label,
        ok=_value is not MISSING,
        expr='{} present'.format(path) if _value is not MISSING else _reason,
        src=Source.SCHEMA, claim='{} exists'.format(path))


def json_equals(response: Any, path: str, expected: Any, name: str = None) -> Check:
    """Assert a field equals an exact value."""
    _claim = '{} == {}'.format(path, brief(expected, 60))
    _label = name or _claim
    _value, _reason = json_value(response, path)
    if _value is MISSING:
        return Check(name=_label, ok=False, expr=_reason, src=Source.API, claim=_claim)
    return Check(
        name=_label,
        ok=same(_value, expected),
        expr='{} = {} (expected {})'.format(path, brief(_value), brief(expected)),
        src=Source.API, claim=_claim)


def field(response: Any, path: str, name: str = None) -> Field:
    """
    A JSON field to judge with Python operators. Each comparison is a Check:

        field(r, 'data.total') > 0
        field(r, 'data.fee') <= 100
        field(r, 'data.status').is_in(['ok', 'pending'])
        field(r, 'data.version').matches(r'^\\d+\\.\\d+$')
        field(r, 'data.items').len() > 0

    See core/assertion/field.py for the comparison rules: strict types, bool
    is not a number, and anything unjudgeable is a failed Check, never an
    exception. All of it deterministic and offline -- see
    docs/design/03-LLM接入边界.md.

    `name` replaces the generated check name ('data.fee <= 100') in reports.
    """
    _value, _reason = json_value(response, path)
    return Field(path, _value, _reason, name=name, src=Source.API)


def schema_conforms(response: Any, schema: dict, name: str = None) -> Check:
    """
    Validate the body against a JSON Schema.

    Contract-level checks belong here rather than in hand-written field
    assertions: a schema is generated from the spec and stays correct when
    the spec changes.
    """
    _label = name or '响应符合 schema'
    # the schema's own fingerprint, so a loosened schema shows up as a changed
    # judgement in the inventory instead of the same 'conforms' line
    _claim = 'body conforms to schema {}'.format(hashlib.sha1(
        json.dumps(schema, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:10])
    try:
        import jsonschema
    except ImportError:
        return Check(name=_label, ok=False,
                     expr="jsonschema is not installed (pip install jsonschema)",
                     src=Source.SCHEMA, claim=_claim)

    _body, _err = json_body(response)
    if _err:
        return Check(name=_label, ok=False, expr=_err, src=Source.SCHEMA, claim=_claim)

    try:
        jsonschema.validate(instance=_body, schema=schema)
    except jsonschema.ValidationError as exc:
        _where = '/'.join(str(_p) for _p in exc.absolute_path) or '<root>'
        return Check(name=_label, ok=False,
                     expr='at {}: {}'.format(_where, exc.message), src=Source.SCHEMA, claim=_claim)
    except jsonschema.SchemaError as exc:
        return Check(name=_label, ok=False,
                     expr='invalid schema: {}'.format(exc.message), src=Source.SCHEMA, claim=_claim)

    return Check(name=_label, ok=True, expr='conforms', src=Source.SCHEMA, claim=_claim)
