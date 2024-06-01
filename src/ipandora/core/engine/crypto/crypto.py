# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : crypto.py
@Time  : 2024-05-13
"""
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

from ipandora.core.engine.crypto.aescryptographer import AESCryptographer
from ipandora.core.engine.crypto.rsacryptographer import RSACryptographer
from ipandora.core.engine.crypto.fercryptographer import FernetCryptographer


# SHA-256 哈希类
class SHA256Hasher:
    @staticmethod
    def hash(message):
        digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
        digest.update(message.encode())
        return digest.finalize()


# 工厂类
class CryptoFactory:
    """
    Factory class for creating different types of cryptographers.
    You usually don't need to pass in a key. It will be generated automatically.
    """
    def __init__(self, key=None):
        self._fernet = None
        self._aes = None
        self._rsa = None
        self._sha256 = None
        self._key = key

    @property
    def aes(self):
        if not self._aes:
            self._aes = AESCryptographer(self._key)
        return self._aes

    @property
    def rsa(self):
        if not self._rsa:
            self._rsa = RSACryptographer(self._key)
        return self._rsa

    @property
    def fernet(self):
        if not self._fernet:
            self._fernet = FernetCryptographer(self._key)
        return self._fernet

    @property
    def sha256(self):
        if not self._sha256:
            self._sha256 = SHA256Hasher()
        return self._sha256

    @staticmethod
    def get_cryptographer(algorithm, key = None):
        if algorithm == "AES":
            return AESCryptographer(key)
        elif algorithm == "RSA":
            return RSACryptographer(key)
        elif algorithm == "SHA256":
            return SHA256Hasher()
        elif algorithm == "Fernet":
            return FernetCryptographer(key)
        else:
            raise ValueError("Unsupported algorithm")


# 使用示例
if __name__ == "__main__":
    factory = CryptoFactory()
    mail_pwd_encrypt = 'IvDxMPS+BjIozlMICPmPrSqwcjEM7NhLJXcrt2ChyMc='
    print(factory.aes.key)
    print(factory.aes.decrypt(mail_pwd_encrypt))
