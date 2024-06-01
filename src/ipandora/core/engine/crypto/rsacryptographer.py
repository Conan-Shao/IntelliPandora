# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : rsacryptographer.py
@Time  : 2024-05-22
"""
import os
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from ipandora.core.engine.crypto.cryptoabc import CryptoABC
from ipandora.utils.log import logger
from ipandora.utils.pathutils import PathUtils


class RSACryptographer(CryptoABC):
    def __init__(self, private_key: str = 'rsa'):
        self._directory = os.path.join(PathUtils().pandora_path, 'conf/crypto')
        self.private_key, self.public_key = '', ''
        self.init_keys(private_key)

    def init_keys(self, key_file):
        if not key_file or key_file == 'rsa':
            key_file = 'rsa_private.pem'
        if os.path.exists(key_file):
            self.private_key = self.load_rsa_private_key(key_file)
        elif os.path.exists(os.path.join(self._directory, key_file)):
            self.private_key = self.load_rsa_private_key(os.path.join(self._directory, key_file))
        else:
            self.generate_and_save_rsa_keys(key_file)
        self.public_key = self.private_key.public_key()

    def encrypt(self, message):
        return self.public_key.encrypt(
            message.encode(),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

    def decrypt(self, encrypted):
        return self.private_key.decrypt(
            encrypted,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        ).decode()

    def generate_and_save_rsa_keys(self, _key_name='rsa'):
        if _key_name.endswith('.pem'):
            _key_file = os.path.splitext(_key_name)[0]
        private_key_file = os.path.join(self._directory, _key_file+'_private.pem')
        public_key_file = os.path.join(self._directory, _key_file+'_public.pem')

        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        # save private_key.pem
        with open(private_key_file, 'wb') as private_key_file:
            private_key_file.write(
                self.private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()  # 可选：可以使用密码加密
                )
            )
        self.public_key = self.private_key.public_key()
        # save public_key.pem
        with open(public_key_file, 'wb') as public_key_file:
            public_key_file.write(
                self.public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                )
            )
        return private_key_file, public_key_file

    @staticmethod
    def load_rsa_private_key(filename):
        logger.info("Load RSA private key from <{}>".format(filename))
        with open(filename, 'rb') as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
                backend=default_backend()
            )
        return private_key

    @staticmethod
    def load_rsa_public_key(filename):
        logger.info("Load RSA public key from <{}>".format(filename))
        with open(filename, 'rb') as key_file:
            public_key = serialization.load_pem_public_key(
                key_file.read(),
                backend=default_backend()
            )
        return public_key
