# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : error.py
# @Time  : 2024-04-17
from requests import exceptions as _requests_exceptions
class PandoraError(Exception):
    """Base class for FusionPandora Framework errors.

    Do not raise this method but use more specific errors instead.
    """

    def __init__(self, message='', details=''):
        super().__init__(message)
        self.details = details

    @property
    def message(self):
        return str(self)


class FrameworkError(PandoraError):
    """Can be used when the core framework goes to unexpected state.

    It is good to explicitly raise a FrameworkError if some framework
    component is used incorrectly. This is pretty much same as
    'Internal Error' and should of course never happen.
    """


class DataError(PandoraError):
    """Used when the provided test data is invalid.

    DataErrors are not caught by keywords that run other keywords
    (e.g. `Run Keyword And Expect Error`).
    """


class VariableError(DataError):
    """Used when variable does not exist.

    VariableErrors are caught by keywords that run other keywords
    (e.g. `Run Keyword And Expect Error`).
    """


class FileError(DataError):
    """Used when exception occurred while processing the file.

    VariableErrors are caught by keywords that run other keywords
    (e.g. `Run Keyword And Expect Error`).
    """


class CommandError(Exception):
    pass


class CryptoError(PandoraError):
    """
    Used when exception occurred while Encryption and decryption.
    """


class TransportError(PandoraError):
    """
    A request never produced a response.

    Distinct from a response the test dislikes: there is nothing to assert on.
    Subclasses also inherit from the matching requests exception, so existing
    `except requests.exceptions.Timeout` handlers keep working.
    """

    def __init__(self, message='', details='', url='', method='', elapsed=None):
        super().__init__(message, details)
        self.url = url
        self.method = method
        self.elapsed = elapsed


class HttpTimeoutError(TransportError, _requests_exceptions.Timeout):
    """
    The peer did not answer within the configured timeout.

    Also a requests.exceptions.Timeout: before timeouts were enforced this
    could never fire, but keeping the dual identity means no caller has to
    learn a new exception to keep working.
    """


class HttpConnectionError(TransportError, _requests_exceptions.ConnectionError):
    """
    The connection could not be established, or was dropped mid-flight.

    Also a requests.exceptions.ConnectionError -- this one *did* surface
    before, so existing `except requests.exceptions.ConnectionError` handlers
    must keep catching it.
    """


class PreconditionNotMet(PandoraError):
    """
    A test could not run because its setup was unsatisfied -- not because the
    system under test is wrong. Raised by `require` when pytest is unavailable
    to skip with; under pytest the test is skipped instead.
    """


class AIError(PandoraError):
    """
    Base class for AI/LLM related errors.
    """


class AIProviderError(AIError):
    """
    Used when an AI provider fails to respond, is misconfigured, or its
    SDK dependency is missing.
    """


class MCPError(PandoraError):
    """
    Used when exception occurred while serving or calling MCP tools.
    """