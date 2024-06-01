# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : cryptoabc.py
@Time  : 2024-05-22
"""
from abc import ABC, abstractmethod


class CryptoABC(ABC):
    @abstractmethod
    def encrypt(self, message):
        pass

    @abstractmethod
    def decrypt(self, encrypted):
        pass