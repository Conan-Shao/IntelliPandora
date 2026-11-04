# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : fercryptographer.py
@Time  : 2024-05-22
"""
import os
from cryptography.fernet import Fernet
from ipandora.core.engine.crypto.cryptoabc import CryptoABC
from ipandora.core.engine.crypto.keystore import keystore_dir, open_key_file
from ipandora.utils.error import CryptoError
from ipandora.utils.log import logger
from ipandora.utils.pathutils import PathUtils


class FernetCryptographer(CryptoABC):
    def __init__(self, key_name=None):
        self.key = b''
        # Not inside the package: see keystore.py for why that mattered.
        self._directory = keystore_dir()
        self.initialize_key(key_name)
        self.cipher = Fernet(self.key)

    def initialize_key(self, key_name):
        """
        Initialize the key.
        :param key_name:
        :return:
        """
        _tag = key_name if key_name else 'fernet_pandora'
        _key_files = self.select_key_with_tag(_tag)
        logger.info("Select key files with tag <{}>: {}".format(_tag, _key_files))
        if _key_files:
            self.key = self.load_key_from_pem(_key_files[0])
        else:
            self.key = Fernet.generate_key()
            self.save_key_to_pem('fernet_pandora.pem')

    @staticmethod
    def generate_key():
        """
        Generate a random key of the specified key size.
        :return:
        """
        return Fernet.generate_key()

    def encrypt(self, message):
        return self.cipher.encrypt(message.encode())

    def decrypt(self, encrypted):
        try:
            return self.cipher.decrypt(encrypted).decode()
        except Exception as e:
            logger.error("Failed to decrypt the message: {}".format(e))
            raise CryptoError("Failed to decrypt the message: {}".format(e))

    def save_key_to_pem(self, file_path):
        # The key is whatever the caller already put on self.key; generating a
        # second one here (as this used to) threw away the first for no reason.
        _file_path_abs = os.path.join(self._directory, file_path)
        with open_key_file(_file_path_abs, binary=True) as key_file:
            key_file.write(self.key)
        # The path, not the key: this line goes to the log file.
        logger.info("fernet key saved to <%s>" % _file_path_abs)
        return _file_path_abs

    def load_key_from_pem(self, filename):
        logger.info("Load aes key from <{}>".format(filename))
        _file_path_abs = os.path.join(self._directory, filename)
        with open(_file_path_abs, 'rb') as key_file:
            _key = key_file.read()
        return _key

    def select_key_with_tag(self, tag='fernet_pandora'):
        """
        Select key with the specified tag from the specified directory.
        :param tag:
        :return:
        """
        return PathUtils.filter_files_in_directory(self._directory, tag, '.pem')


if __name__ == '__main__':
    # A round trip, not a stored ciphertext: the one that used to be here was
    # encrypted with a key nobody has any more, so this could only ever raise.
    _crypto = FernetCryptographer()
    _token = _crypto.encrypt('Hello, GT!')
    print(_token)
    print(_crypto.decrypt(_token))

