# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : aescryptographer.py
@Time  : 2024-05-22
"""
import os
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from ipandora.core.engine.crypto.cryptoabc import CryptoABC
from ipandora.utils.pathutils import PathUtils


class AESCryptographer(CryptoABC):
    def __init__(self, key=None, key_size=32):
        self._directory = os.path.join(PathUtils().pandora_path, 'conf/crypto')
        self.block_size = 128  # aes block size in bits
        # aes key size in bytes (16 for 128-bit, 24 for 192-bit, 32 for 256-bit)
        self.key_size = key_size
        self.backend = default_backend()
        self.key = b''
        self.initialize_key(key)

    def initialize_key(self, key):
        """
        Initialize the key.
        :param key:
        :return:
        """
        _tag = key if key else 'aes_pandora'
        _key_files = self.select_key_with_tag(_tag)
        if _key_files:
            self.key = self.load_key_from_pem(_key_files[0])
        else:
            self.key = os.urandom(self.key_size)
            self.save_key_to_pem('aes_pandora.pem')

    def generate_key(self):
        """
        Generate a random key of the specified key size.
        :return:
        """
        return os.urandom(self.key_size)

    def encrypt(self, message):
        iv = os.urandom(16)  # aes block size in bytes
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv), backend=self.backend)
        encryptor = cipher.encryptor()

        # Padding the message
        padder = padding.PKCS7(self.block_size).padder()
        padded_data = padder.update(message.encode()) + padder.finalize()

        # Encrypting the data
        encrypted = encryptor.update(padded_data) + encryptor.finalize()

        # Returning IV + encrypted data, encoded in Base64
        return base64.b64encode(iv + encrypted).decode('utf-8')

    def decrypt(self, encrypted):
        encrypted = base64.b64decode(encrypted)
        iv = encrypted[:16]
        encrypted_message = encrypted[16:]

        cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv), backend=self.backend)
        decryptor = cipher.decryptor()

        # Decrypting the data
        decrypted_padded = decryptor.update(encrypted_message) + decryptor.finalize()

        # Unpadding the data
        unpadder = padding.PKCS7(self.block_size).unpadder()
        decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()

        return decrypted.decode('utf-8')

    def save_key_to_pem(self, file_path):
        """
        Save the aes key to a PEM file, encoded in Base64.
        :param file_path:
        :return:
        """
        _file_path_abs = os.path.join(self._directory, file_path)
        pem_key = base64.b64encode(self.key).decode('utf-8')
        with open(_file_path_abs, 'w') as f:
            f.write("-----BEGIN aes KEY-----\n")
            f.write(pem_key)
            f.write("\n-----END aes KEY-----\n")
        self.key = pem_key

    def load_key_from_pem(self, file_path):
        """
        Load the aes key from a PEM file.
        :param file_path:
        :return:
        """
        _file_path_abs = os.path.join(self._directory, file_path)
        with open(_file_path_abs, 'r') as f:
            pem_key = f.read().replace("-----BEGIN aes KEY-----", "").replace("-----END aes KEY-----", "").strip()
        return base64.b64decode(pem_key)

    def select_key_with_tag(self, tag='aes_pandora'):
        """
        Select key with the specified tag from the specified directory.
        :param tag:
        :return:
        """
        return PathUtils.filter_files_in_directory(self._directory, tag, '.pem')


if __name__ == '__main__':
    result = AESCryptographer().encrypt('test')
    print(result)
    result = AESCryptographer().encrypt('77777777')
    print(result)
