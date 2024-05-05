# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : niceline.py
# @Time  : 2024-04-17
from typing import Union


class NiceLine(object):

    def __init__(self, line):
        self.line = line  # type:Union[str,bytes]

    @property
    def str(self) -> str:
        return self.line.decode('utf-8') \
            if isinstance(self.line, bytes) else str(self.line)

    @property
    def bytes(self) -> bytes:
        return self.line.encode('utf-8') \
            if isinstance(self.line, str) else bytes(self.line)