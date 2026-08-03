# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : replay.py
@Time  : 2026-08-02

Recording and replaying at the transport adapter.

The framework already mounts a custom HTTPAdapter on every session to carry the
retry policy, and `HTTPAdapter.send` is the last place a request passes through
before urllib3 -- the only spot above the socket that sees both the finished
PreparedRequest and the finished Response. That existing seam is where replay
belongs: no monkey-patching of requests, no change to any test, no new global.

Recording here also captures the wire form -- after serialisation, before
compression -- which is what faithful replay needs. The evidence recorder that
feeds the report sits a layer higher and keeps working untouched.
"""
import io
import threading
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3 import HTTPResponse

from ipandora.core.cassette.cassette import Cassette, Mode
from ipandora.utils.log import logger


class _Session:
    """
    The mode for this process, and the tape it is using.

    Process-wide rather than per-session because the choice is made once by the
    command line and every session in the run has to obey it -- including
    sessions built later on other threads.
    """

    def __init__(self):
        self.mode = Mode.OFF
        self.cassette = None  # type: Optional[Cassette]
        self._lock = threading.RLock()

    def activate(self, mode: str, cassette: Cassette) -> None:
        with self._lock:
            self.mode, self.cassette = mode, cassette

    def deactivate(self) -> None:
        with self._lock:
            self.mode, self.cassette = Mode.OFF, None

    @property
    def active(self) -> bool:
        return self.mode != Mode.OFF and self.cassette is not None


session = _Session()


def _text_of(body) -> Optional[str]:
    if body is None or isinstance(body, str):
        return body
    if isinstance(body, bytes):
        try:
            return body.decode('utf-8')
        except UnicodeDecodeError:
            return '<{} bytes>'.format(len(body))
    return str(body)


def build_response(record, request) -> requests.Response:
    """
    Turn a stored record back into a Response requests will accept.

    Built through urllib3's HTTPResponse rather than by setting attributes on a
    bare Response, so that everything downstream -- .text, .json(), .headers,
    .raise_for_status(), streaming -- behaves as it would for a real call. A
    hand-assembled Response works until the first caller touches something we
    forgot to set.
    """
    _body = (record.response_body or '').encode('utf-8')
    _headers = dict(record.response_headers or {})
    # The stored length describes the recorded body; after redaction the bytes
    # are a different size, and a wrong Content-Length breaks .text.
    _headers.pop('Content-Length', None)
    _headers.pop('content-length', None)
    # Bodies are stored decoded, so any encoding header would send requests
    # looking for a gzip stream that is not there.
    _headers.pop('Content-Encoding', None)
    _headers.pop('content-encoding', None)

    _raw = HTTPResponse(
        body=io.BytesIO(_body),
        headers=_headers,
        status=record.status,
        reason=record.reason or '',
        preload_content=False,
        original_response=None)

    _response = requests.Response()
    _response.status_code = record.status
    _response.reason = record.reason or ''
    _response.headers.update(_headers)
    _response.url = record.url or (request.url if request else '')
    _response.request = request
    _response.raw = _raw
    _response.encoding = 'utf-8'
    return _response


class ReplayAdapter(HTTPAdapter):
    """
    An HTTPAdapter that consults the tape before the network.

    Off by default and inert when off: `send` falls straight through to the
    parent, so a run with no cassette behaves exactly as it did before this
    file existed.
    """

    def send(self, request, **kwargs):
        if not session.active:
            return super().send(request, **kwargs)

        _cassette = session.cassette
        _body = _text_of(getattr(request, 'body', None))

        if session.mode == Mode.VERIFY:
            _start = time.perf_counter()
            _response = super().send(request, **kwargs)
            self._verify(_cassette, request, _body, _response)
            return _response

        if session.mode == Mode.REPLAY:
            _record = _cassette.play(request.method, request.url, _body)
            if _record is not None:
                return build_response(_record, request)
            # play() returned None: passthrough was configured
            return super().send(request, **kwargs)

        _start = time.perf_counter()
        _response = super().send(request, **kwargs)
        if session.mode == Mode.RECORD:
            self._record(_cassette, request, _body, _response,
                         (time.perf_counter() - _start) * 1000.0)
        return _response

    @staticmethod
    def _verify(cassette, request, body, response) -> None:
        """
        Compare the live response with the tape and file the verdict.

        The difference is pushed to the evidence recorder as a Check, so it
        lands on the case that made the call and shows up in the report next to
        that case's own assertions -- no separate diff view to go and find, and
        it counts in the by-source breakdown like any other judgement.

        The Check does not fail the test. Whether a difference fails the *run*
        is the command's call, not the transport's: a layer this deep deciding
        verdicts is how a reporting concern ends up able to turn a suite red.
        """
        try:
            from ipandora.core.assertion.check import Check, Source
            from ipandora.core.evidence import add_checks

            _result = cassette.verify(
                request.method, request.url, body,
                response.status_code, dict(response.headers or {}), response.text)

            if _result is None:
                add_checks([Check(
                    name='基线中有此请求', ok=False, src=Source.DIFF,
                    expr='{} {} 在基线里没有对应记录，本次调用无从比较'.format(
                        request.method, request.url))])
                return

            _where = '{} {}'.format(request.method, request.url)

            if _result.identical:
                add_checks([Check(
                    name='响应与基线一致', ok=True, src=Source.DIFF,
                    expr='{} · {}'.format(_where, _result.summary()))])
                return

            # One check per difference rather than one per exchange. The report
            # renders check lists well, so each change gets its own readable
            # row -- and the by-source count then means "how many things
            # changed" instead of "how many calls had something change", which
            # is the number anyone actually wants. Bounded already: the diff
            # engine caps differences per exchange.
            add_checks([Check(
                name='{} 与基线一致'.format(_difference.path),
                ok=False, src=Source.DIFF,
                expr='{} · {}'.format(_where, _difference.describe()))
                for _difference in _result.real])
        except Exception as exc:  # noqa: BLE001 - comparison must not break the call
            logger.warning('could not verify %s %s: %s',
                           request.method, request.url, exc)

    @staticmethod
    def _record(cassette, request, body, response, ms) -> None:
        """
        Store the exchange. Never raises: recording is an observation, and a
        failure to write the tape must not turn a passing call into an error.
        """
        try:
            cassette.record(
                method=request.method, url=request.url,
                request_headers=dict(request.headers or {}), request_body=body,
                status=response.status_code, reason=response.reason or '',
                response_headers=dict(response.headers or {}),
                response_body=response.text, ms=ms)
        except Exception as exc:  # noqa: BLE001 - see docstring
            logger.warning('could not record %s %s: %s',
                           request.method, request.url, exc)
