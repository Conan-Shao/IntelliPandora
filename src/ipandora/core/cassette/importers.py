# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : importers.py
@Time  : 2026-08-03

Turning traffic somebody else captured into a cassette.

The framework does not capture production traffic and should not try: the
traffic is at the service, not in the test process, and goreplay, mitmproxy,
envoy's tap filter and nginx's mirror module all do that job better than a test
framework would. What the framework owns is the format on the other side of
that handoff -- which is this file.

Two rules run through all of it.

**Redaction happens on the way in.** Imported traffic is real users: phone
numbers, addresses, tokens, amounts. It goes through the same redaction as a
recorded exchange, at the moment it touches disk, so the un-redacted version
never exists inside the framework's directory at all.

**A tape with no response bodies is refused rather than written.** Most access
logs do not record bodies, and a cassette without them cannot be replayed and
cannot be diffed -- but it looks exactly like a good one: right count, right
URLs, green import. That silent uselessness is the thing to prevent, so the
importer reports the shortfall and, by default, will not write the tape.
"""
import base64
import binascii
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from ipandora.core.cassette.model import Manifest, Record
from ipandora.core.cassette.store import CassetteStore
from ipandora.utils.log import logger

MIN_BODY_RATIO = 0.5
"""
How many imported exchanges must carry a response body for the tape to be
usable without an explicit override.

Not 1.0: a 204 or a redirect legitimately has no body. Well under 1.0 means the
capture was not configured to record bodies at all, which is the common case
and the one worth refusing.
"""


@dataclass
class ImportReport:
    """What an import produced, and what it could not."""
    source: str = ''
    read: int = 0
    imported: int = 0
    skipped: List[str] = field(default_factory=list)
    with_response_body: int = 0
    with_request_body: int = 0

    @property
    def body_ratio(self) -> float:
        return (self.with_response_body / self.imported) if self.imported else 0.0

    @property
    def usable(self) -> bool:
        return self.imported > 0 and self.body_ratio >= MIN_BODY_RATIO

    def describe(self) -> str:
        _lines = ['来源 {} · 读入 {} 条 · 导入 {} 条'.format(
            self.source, self.read, self.imported)]
        _lines.append('  含响应体 {}/{}（{:.0%}）· 含请求体 {}'.format(
            self.with_response_body, self.imported, self.body_ratio,
            self.with_request_body))
        if self.skipped:
            _lines.append('  跳过 {} 条：{}'.format(
                len(self.skipped), '；'.join(self.skipped[:3])))
        if self.imported and not self.usable:
            _lines.append(
                '  ⚠ 响应体覆盖率过低——这样的磁带既回放不了也比对不了。'
                '采集端多半没开 body 记录。')
        return '\n'.join(_lines)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _headers_from_pairs(pairs, name_key='name', value_key='value') -> Dict[str, str]:
    """HAR and envoy both use lists of pairs, with different key names."""
    _out = {}
    for _pair in pairs or ():
        if not isinstance(_pair, dict):
            continue
        _name = _pair.get(name_key) or _pair.get('key') or ''
        if _name:
            _out[str(_name)] = str(_pair.get(value_key, ''))
    return _out


def _decode(text, encoding: str = '') -> Optional[str]:
    """
    A body as text.

    base64 shows up in both HAR (`content.encoding`) and envoy (`as_bytes`).
    Binary that will not decode is described rather than mangled -- a cassette
    full of replacement characters is worse than one that admits the body was
    not text.
    """
    if text is None:
        return None
    if encoding == 'base64':
        try:
            _raw = base64.b64decode(text)
        except (binascii.Error, ValueError):
            return None
        try:
            return _raw.decode('utf-8')
        except UnicodeDecodeError:
            return '<{} binary bytes>'.format(len(_raw))
    return text if isinstance(text, str) else str(text)


def _absolute(url: str, host: str = '', scheme: str = 'https') -> str:
    if not url:
        return ''
    if url.startswith(('http://', 'https://')):
        return url
    if not host:
        # Matching ignores the host by default, so a path-only URL still
        # replays -- but it has to be well-formed for urlsplit.
        return '{}://imported.invalid{}'.format(scheme, url if url.startswith('/')
                                                else '/' + url)
    return '{}://{}{}'.format(scheme, host, url if url.startswith('/') else '/' + url)


# --------------------------------------------------------------------------
# HAR
# --------------------------------------------------------------------------

def from_har(path: str) -> Iterator[Tuple[Optional[Record], str]]:
    """
    HAR 1.2, as produced by Chrome DevTools, Charles, Fiddler and mitmproxy.

    Yields (record, skip_reason); exactly one of the two is set.
    """
    with open(path, 'r', encoding='utf-8') as fh:
        _data = json.load(fh)

    for _index, _entry in enumerate((_data.get('log') or {}).get('entries') or []):
        _request = _entry.get('request') or {}
        _response = _entry.get('response') or {}
        if not _request.get('url'):
            yield None, 'entry {} 没有 url'.format(_index)
            continue

        _content = _response.get('content') or {}
        _post = _request.get('postData') or {}

        yield Record(
            at=str(_entry.get('startedDateTime') or ''),
            method=str(_request.get('method') or 'GET').upper(),
            url=str(_request['url']),
            request_headers=_headers_from_pairs(_request.get('headers')),
            request_body=_decode(_post.get('text'), _post.get('encoding') or ''),
            status=int(_response.get('status') or 0),
            reason=str(_response.get('statusText') or ''),
            response_headers=_headers_from_pairs(_response.get('headers')),
            response_body=_decode(_content.get('text'),
                                  _content.get('encoding') or ''),
            ms=float(_entry.get('time') or 0.0),
            source='import:har'), ''


# --------------------------------------------------------------------------
# nginx
# --------------------------------------------------------------------------

NGINX_FIELDS = {
    'method': 'request_method',
    'url': 'request_uri',
    'host': 'host',
    'status': 'status',
    'ms': 'request_time',
    'request_body': 'request_body',
    'response_body': 'response_body',
    'at': 'time_iso8601',
}
"""
Default field names for a JSON `log_format`.

There is no standard here -- every site names these differently -- so the map
is data rather than code and `--field` overrides it. Note `response_body`: stock
nginx cannot log one at all, it needs lua or a mirror to a collector. When it is
missing the import says so instead of producing a tape that cannot be replayed.
"""


def from_nginx(path: str, fields: Dict[str, str] = None,
               scheme: str = 'https') -> Iterator[Tuple[Optional[Record], str]]:
    """
    An nginx access log in JSON-per-line form.

    Plain text `log_format` is not supported on purpose: parsing it is a
    guessing game about quoting and escaping, and getting it subtly wrong
    produces a cassette that is wrong in ways nobody notices. Switching the
    log_format to JSON is a one-line change on the capture side.
    """
    _fields = dict(NGINX_FIELDS)
    _fields.update(fields or {})

    with open(path, 'r', encoding='utf-8') as fh:
        for _number, _line in enumerate(fh, 1):
            _line = _line.strip()
            if not _line:
                continue
            try:
                _row = json.loads(_line)
            except (TypeError, ValueError):
                yield None, 'line {} 不是 JSON'.format(_number)
                continue
            if not isinstance(_row, dict):
                yield None, 'line {} 不是对象'.format(_number)
                continue

            _url = _row.get(_fields['url']) or ''
            if not _url:
                yield None, 'line {} 没有 {}'.format(_number, _fields['url'])
                continue

            try:
                _status = int(_row.get(_fields['status']) or 0)
            except (TypeError, ValueError):
                _status = 0
            try:
                # nginx reports seconds; the cassette stores milliseconds
                _ms = float(_row.get(_fields['ms']) or 0.0) * 1000.0
            except (TypeError, ValueError):
                _ms = 0.0

            yield Record(
                at=str(_row.get(_fields['at']) or ''),
                method=str(_row.get(_fields['method']) or 'GET').upper(),
                url=_absolute(str(_url), str(_row.get(_fields['host']) or ''), scheme),
                request_body=_row.get(_fields['request_body']) or None,
                status=_status,
                response_headers={},
                response_body=_row.get(_fields['response_body']) or None,
                ms=round(_ms, 1),
                source='import:nginx'), ''


# --------------------------------------------------------------------------
# envoy tap
# --------------------------------------------------------------------------

def _envoy_body(body: Dict[str, Any]) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    if 'as_string' in body:
        return _decode(body.get('as_string'))
    if 'as_bytes' in body:
        return _decode(body.get('as_bytes'), 'base64')
    return None


def from_envoy(path: str) -> Iterator[Tuple[Optional[Record], str]]:
    """
    Envoy's tap filter output: one buffered trace per line, or a single trace.

    Pseudo-headers carry what would elsewhere be structure -- `:method`,
    `:path`, `:authority`, `:status` -- so they are lifted out and the rest
    kept as ordinary headers.
    """
    with open(path, 'r', encoding='utf-8') as fh:
        _text = fh.read()

    _traces = []
    try:
        _whole = json.loads(_text)
        _traces = _whole if isinstance(_whole, list) else [_whole]
    except (TypeError, ValueError):
        for _number, _line in enumerate(_text.splitlines(), 1):
            _line = _line.strip()
            if not _line:
                continue
            try:
                _traces.append(json.loads(_line))
            except (TypeError, ValueError):
                yield None, 'line {} 不是 JSON'.format(_number)

    for _index, _trace in enumerate(_traces):
        _buffered = (_trace or {}).get('http_buffered_trace') or _trace or {}
        _request = _buffered.get('request') or {}
        _response = _buffered.get('response') or {}
        _request_headers = _headers_from_pairs(_request.get('headers'), 'key', 'value')
        _response_headers = _headers_from_pairs(_response.get('headers'), 'key', 'value')

        _path = _request_headers.pop(':path', '')
        _method = _request_headers.pop(':method', 'GET')
        _authority = _request_headers.pop(':authority', '')
        _scheme = _request_headers.pop(':scheme', 'https')
        _status = _response_headers.pop(':status', '0')

        if not _path:
            yield None, 'trace {} 没有 :path'.format(_index)
            continue

        try:
            _status_code = int(_status)
        except (TypeError, ValueError):
            _status_code = 0

        yield Record(
            method=str(_method).upper(),
            url=_absolute(_path, _authority, _scheme),
            request_headers=_request_headers,
            request_body=_envoy_body(_request.get('body')),
            status=_status_code,
            response_headers=_response_headers,
            response_body=_envoy_body(_response.get('body')),
            source='import:envoy'), ''


FORMATS = {
    'har': from_har,
    'nginx': from_nginx,
    'envoy': from_envoy,
}  # type: Dict[str, Callable]


def sniff(path: str) -> str:
    """
    Guess the format from the file.

    A guess, and it says so by being overridable -- but getting it right in the
    common case removes one flag from the first thing anyone types.
    """
    _name = os.path.basename(path).lower()
    if _name.endswith('.har'):
        return 'har'
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            _head = fh.read(4096)
    except OSError:
        return 'har'
    if '"log"' in _head and '"entries"' in _head:
        return 'har'
    if 'http_buffered_trace' in _head or '":path"' in _head:
        return 'envoy'
    return 'nginx'


def import_into(name: str, path: str, fmt: str = '', directory: str = None,
                fields: Dict[str, str] = None, recorded_from: str = '',
                force: bool = False) -> ImportReport:
    """
    Read captured traffic into a cassette.

    Writes nothing when the result would not be usable, unless `force`. The
    check is the point of the function as much as the parsing is: an import
    that quietly produces an unreplayable tape costs far more than one that
    refuses and explains why.
    """
    _fmt = fmt or sniff(path)
    if _fmt not in FORMATS:
        raise ValueError('unknown format {!r}, expected one of {}'.format(
            _fmt, ', '.join(sorted(FORMATS))))

    _reader = FORMATS[_fmt]
    _report = ImportReport(source='{}:{}'.format(_fmt, os.path.basename(path)))

    _records = []
    for _record, _reason in (_reader(path, fields=fields) if _fmt == 'nginx'
                             else _reader(path)):
        _report.read += 1
        if _record is None:
            _report.skipped.append(_reason)
            continue
        _records.append(_record)
        _report.imported += 1
        if _record.response_body:
            _report.with_response_body += 1
        if _record.request_body:
            _report.with_request_body += 1

    if not _report.imported:
        return _report
    if not _report.usable and not force:
        return _report

    _store = CassetteStore(name, directory)
    _store.begin_recording()
    for _seq, _record in enumerate(_records, 1):
        _record.seq = _seq
        # Redaction happens inside append, before anything reaches disk or a
        # blob. Imported traffic is the case that makes that matter.
        _store.append(_record)

    _manifest = Manifest(name=name, count=_report.imported,
                         blobs=_store.blob_count(),
                         recorded_from=recorded_from or 'import:{}'.format(_fmt))
    _store.save_manifest(_manifest)
    logger.info('imported %d exchanges into %s', _report.imported, _store.root)
    return _report


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------

def to_har(name: str, directory: str = None, creator: str = 'IntelliPandora') -> dict:
    """
    A cassette as HAR, so existing tools can open it.

    The reason the internal format is not HAR: HAR is a single JSON document,
    which cannot be appended to while recording and has to be held whole in
    memory to read. Exporting keeps the tooling without paying that cost --
    the two goals were never actually in conflict.
    """
    _store = CassetteStore(name, directory)
    _entries = []
    for _record in _store.read():
        _body = _record.response_body or ''
        _entries.append({
            'startedDateTime': _record.at,
            'time': _record.ms,
            'request': {
                'method': _record.method,
                'url': _record.url,
                'httpVersion': 'HTTP/1.1',
                'headers': [{'name': _k, 'value': _v}
                            for _k, _v in (_record.request_headers or {}).items()],
                'queryString': [], 'cookies': [], 'headersSize': -1,
                'bodySize': len(_record.request_body or ''),
                **({'postData': {'mimeType': 'application/json',
                                 'text': _record.request_body}}
                   if _record.request_body else {}),
            },
            'response': {
                'status': _record.status,
                'statusText': _record.reason,
                'httpVersion': 'HTTP/1.1',
                'headers': [{'name': _k, 'value': _v}
                            for _k, _v in (_record.response_headers or {}).items()],
                'cookies': [], 'headersSize': -1, 'bodySize': len(_body),
                'redirectURL': '',
                'content': {'size': len(_body), 'mimeType':
                            (_record.response_headers or {}).get(
                                'Content-Type', 'application/json'),
                            'text': _body},
            },
            'cache': {},
            'timings': {'send': 0, 'wait': _record.ms, 'receive': 0},
        })

    return {'log': {'version': '1.2',
                    'creator': {'name': creator, 'version': '1'},
                    'entries': _entries}}
