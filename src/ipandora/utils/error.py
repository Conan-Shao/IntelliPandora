# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : error.py
# @Time  : 2024-04-17
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