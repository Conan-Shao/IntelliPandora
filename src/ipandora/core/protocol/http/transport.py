# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : transport.py
@Time  : 2026-08-01

Transport policy: the reliability settings every request inherits.

Before this existed the framework had no timeout (a hung endpoint hung the
whole suite forever), no retry, and forced `verify=False` on every HTTPS
request -- which both hid certificate regressions the tests should have been
catching and made the suite unusable as evidence about a real environment.
"""
from dataclasses import dataclass
from typing import FrozenSet, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ipandora.utils.error import HttpConnectionError, HttpTimeoutError

# Retrying a non-idempotent verb can double-submit. Retry only where a repeat
# is safe by definition; POST/PATCH must opt in per call.
IDEMPOTENT_METHODS: FrozenSet[str] = frozenset(
    {'GET', 'HEAD', 'PUT', 'DELETE', 'OPTIONS', 'TRACE'})

# Transient by nature: rate limiting and upstream unavailability.
RETRY_STATUS: Tuple[int, ...] = (429, 502, 503, 504)


@dataclass(frozen=True)
class TransportPolicy:
    """
    Defaults are deliberately conservative: a test suite should fail fast and
    loudly rather than hang or silently paper over instability.
    """
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    verify: bool = True
    max_retries: int = 2
    backoff_factor: float = 0.3
    pool_maxsize: int = 10

    @property
    def timeout(self) -> Tuple[float, float]:
        """requests accepts (connect, read); separating them matters -- a slow
        endpoint and an unreachable one deserve different budgets."""
        return self.connect_timeout, self.read_timeout

    @classmethod
    def from_runtime(cls) -> 'TransportPolicy':
        from ipandora.core.schedule.runtime import Runtime
        return cls(
            connect_timeout=Runtime.Http.connect_timeout,
            read_timeout=Runtime.Http.read_timeout,
            verify=Runtime.Http.verify,
            max_retries=Runtime.Http.max_retries,
            backoff_factor=Runtime.Http.backoff_factor,
            pool_maxsize=Runtime.Http.pool_maxsize)


def build_adapter(policy: TransportPolicy = None) -> HTTPAdapter:
    """An HTTPAdapter carrying the retry policy and pool sizing."""
    policy = policy or TransportPolicy()
    _retry = Retry(
        total=policy.max_retries,
        connect=policy.max_retries,
        read=policy.max_retries,
        status=policy.max_retries,
        backoff_factor=policy.backoff_factor,
        status_forcelist=RETRY_STATUS,
        allowed_methods=IDEMPOTENT_METHODS,
        raise_on_status=False)
    return HTTPAdapter(
        max_retries=_retry,
        pool_connections=policy.pool_maxsize,
        pool_maxsize=policy.pool_maxsize)


def mount(session: requests.Session, policy: TransportPolicy = None) -> requests.Session:
    """Apply the policy to a session. Safe to call more than once."""
    _adapter = build_adapter(policy)
    session.mount('http://', _adapter)
    session.mount('https://', _adapter)
    return session


def translate_error(exc: Exception, url: str = '', method: str = '', elapsed=None):
    """
    Map a requests-level failure onto the framework's transport errors.

    Returns the exception to raise, or None when `exc` is not a transport
    failure and should propagate untouched. Callers keep the original as
    __cause__ so no diagnostic detail is lost.
    """
    _method = str(method).upper()
    if isinstance(exc, requests.exceptions.Timeout):
        return HttpTimeoutError(
            '{} {} timed out'.format(_method, url),
            details=str(exc), url=url, method=_method, elapsed=elapsed)
    if isinstance(exc, requests.exceptions.ConnectionError):
        return HttpConnectionError(
            '{} {} could not connect'.format(_method, url),
            details=str(exc), url=url, method=_method, elapsed=elapsed)
    return None
