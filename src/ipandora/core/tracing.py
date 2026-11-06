# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : tracing.py
@Time  : 2026-11-06

Cross-service trace evidence (docs/design/decisions/14 §12, D7): every HTTP
request a case sends carries a W3C `traceparent` header, all of one case under
one trace id, so the services' own spans -- in Jaeger, Tempo, any backend
that reads W3C Trace Context -- line up under the case that caused them. The
report shows each request's trace id and, with `tracing.link`, links to it.

    # conf/config.yaml
    tracing:
      enabled: true
      link: http://jaeger.test:16686/trace/{trace_id}

Integrate, not wrap: no tracing SDK, no spans exported by the framework. The
framework only starts the trace; the services record it. A server sees a
parent span it never receives -- backends show the services' spans as the
trace's roots, which is all a reader of a failed case needs.

A `traceparent` the case set itself, or that a request instrumentation
(OpenTelemetry's) writes when the request is sent, wins: the evidence reads
the header that actually went out, never the one this module meant to send.
"""
import re
import secrets
import threading
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

HEADER = 'traceparent'

_TRACEPARENT = re.compile(r'^\s*([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})\s*$')
_GUARD = threading.Lock()


def _settings() -> Dict[str, Any]:
    from ipandora.common.dictutils import DictUtils
    from ipandora.core.schedule.runtime import Runtime
    return DictUtils.safe_get(Runtime.settings, 'tracing') or {}


def enabled() -> bool:
    """Whether requests carry a traceparent: `tracing.enabled: true`. Off by default."""
    return _settings().get('enabled') is True


def _hex(n: int) -> str:
    # never all zeros: W3C calls such an id invalid and receivers drop it
    while True:
        _h = secrets.token_hex(n)
        if _h.strip('0'):
            return _h


def trace_id() -> str:
    """
    The trace id of the case running now -- one per case, shared by the
    threads concurrently() starts for it -- or a fresh one outside a case.
    """
    from ipandora.core.evidence import recorder
    _evidence = recorder.current()
    if _evidence is None:
        return _hex(16)
    with _GUARD:
        if not _evidence.trace_id:
            _evidence.trace_id = _hex(16)
        return _evidence.trace_id


def traceparent() -> str:
    """A new span of the current case's trace, as a `traceparent` header value (sampled)."""
    return '00-{}-{}-01'.format(trace_id(), _hex(8))


def parse(value: Any) -> Optional[Dict[str, str]]:
    """{'trace_id', 'span_id'} of a traceparent header value, or None for anything malformed."""
    _m = _TRACEPARENT.match(str(value or '').lower())
    if not _m or _m.group(1) == 'ff' or not _m.group(2).strip('0') or not _m.group(3).strip('0'):
        return None
    return {'trace_id': _m.group(2), 'span_id': _m.group(3)}


def of_headers(headers: Any) -> str:
    """The trace id in these request headers ('' without a valid traceparent)."""
    for _k, _v in dict(headers or {}).items():
        if str(_k).lower() == HEADER:
            return (parse(_v) or {}).get('trace_id', '')
    return ''


_OURS = '_ipandora_traceparent'


def inject(request, renew: bool = False) -> None:
    """
    Put a traceparent on `request` (a RequestObject), unless tracing is off
    or the request already has one that is not ours. `renew`: a replay of the
    same request gets a span of its own.
    """
    if not enabled():
        return
    _headers = request.kwargs.get('headers')
    if _headers is None:
        _headers = request.kwargs['headers'] = {}
    _existing = next((_v for _k, _v in _headers.items() if str(_k).lower() == HEADER), None)
    _ours = getattr(request, _OURS, None)
    if _existing is not None and (_existing != _ours or not renew):
        return
    # one the case put on its session counts as its own: the session's headers
    # are copied into a request only when it sets no Content-Type, and a
    # request-level header of ours would have replaced it at send time
    _session = getattr(getattr(request, 'option', None), 'obj', None)
    if _ours is None and any(str(_k).lower() == HEADER for _k in (getattr(_session, 'headers', None) or {})):
        return
    for _k in [_k for _k in _headers if str(_k).lower() == HEADER]:
        del _headers[_k]
    _value = traceparent()
    _headers[HEADER] = _value
    setattr(request, _OURS, _value)


def _netloc(address: str) -> str:
    _address = str(address or '').strip().lower()
    if '://' not in _address:
        _address = 'http://' + _address
    _parts = urlsplit(_address)
    _port = _parts.port or {'http': 80, 'https': 443}.get(_parts.scheme)
    return '{}:{}'.format(_parts.hostname or '', _port) if _parts.hostname else ''


def browser(context, base_url: str = '') -> bool:
    """
    Make the pages of a Playwright browser context send a traceparent on
    each request to the application -- the host of `base_url`, and those in
    `tracing.hosts` -- a new span of the running case's trace each time.
    Never to other hosts: a CDN or an analytics service is not the system
    under test, and has no business seeing the trace. Returns whether it did.

    A route handler, so Playwright stops using its HTTP cache for the
    context: only when tracing is on. A request that already carries a
    traceparent (the page's own instrumentation) keeps it.
    """
    if not enabled():
        return False
    _hosts = {_netloc(_h) for _h in list(_settings().get('hosts') or []) + [base_url]} - {''}
    if not _hosts:
        return False

    def _handle(route):
        _request = route.request
        _headers = dict(_request.headers)
        if _netloc(_request.url) not in _hosts or any(_k.lower() == HEADER for _k in _headers):
            route.fallback()
            return
        _headers[HEADER] = traceparent()
        _mark()
        route.fallback(headers=_headers)
    context.route('**/*', _handle)
    return True


def _mark() -> None:
    """The case's trace went out from a browser: the report shows it even without any API request."""
    from ipandora.core.evidence import recorder
    _evidence = recorder.current()
    if _evidence is not None:
        _evidence.trace_shown = True


def link(trace: str) -> str:
    """`tracing.link` with the trace id filled in, or '' without one."""
    _template = str(_settings().get('link') or '').strip()
    # a web page only: the report renders it as a link someone will click
    if not trace or '{trace_id}' not in _template or not _template.lower().startswith(('http://', 'https://')):
        return ''
    return _template.replace('{trace_id}', trace)


__all__ = ['enabled', 'trace_id', 'traceparent', 'parse', 'of_headers', 'inject', 'link', 'HEADER']
