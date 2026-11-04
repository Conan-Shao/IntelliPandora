# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_keystore.py
@Time  : 2026-11-04

Where the framework's own key material goes, and who can read it.

The 2026-11 audit found the generated key landing in `conf/crypto` *inside the
installed package* -- `src/ipandora/conf/crypto` in a checkout, i.e. inside the
tracked tree of a public repo -- with `.gitignore` not covering `*.pem` and
none of the three secret gates recognising either file. Nobody chose to put it
there; the framework writes it unprompted on first use.

These cases pin the three things that have to stay true: the key is outside any
checkout, only its owner can read it, and if it ever does appear in a checkout
both the gate and .gitignore catch it.
"""
import os
import stat
import subprocess
import sys

import pytest

from ipandora.core.engine.crypto.keystore import (DEFAULT_DIR, ENV_VAR,
                                                  keystore_dir, open_key_file)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def keys_dir(tmp_path, monkeypatch):
    _dir = tmp_path / 'keys'
    monkeypatch.setenv(ENV_VAR, str(_dir))
    return _dir


class TestTheKeyLivesOutsideTheCheckout:
    def test_the_default_is_under_the_home_directory(self, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        assert keystore_dir(create=False) == os.path.abspath(
            os.path.expanduser(DEFAULT_DIR))

    def test_the_default_is_not_inside_the_package(self, monkeypatch):
        """The regression. `conf/crypto` resolved into src/ipandora/."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        _dir = keystore_dir(create=False)
        import ipandora
        _package = os.path.dirname(os.path.abspath(ipandora.__file__))
        assert not _dir.startswith(_package), _dir
        assert not _dir.startswith(REPO + os.sep), _dir

    def test_the_location_is_overridable(self, keys_dir):
        assert keystore_dir(create=False) == str(keys_dir)

    def test_the_directory_is_created_on_demand(self, keys_dir):
        assert not keys_dir.exists()
        keystore_dir()
        assert keys_dir.is_dir()


class TestOnlyTheOwnerCanRead:
    def test_the_directory_is_owner_only(self, keys_dir):
        keystore_dir()
        assert stat.S_IMODE(os.stat(str(keys_dir)).st_mode) == 0o700

    def test_an_existing_loose_directory_is_narrowed(self, keys_dir):
        # makedivers' `mode` is ignored when the directory already exists, so a
        # 0755 inherited from an earlier version has to be fixed, not assumed.
        keys_dir.mkdir(parents=True)
        os.chmod(str(keys_dir), 0o755)
        keystore_dir()
        assert stat.S_IMODE(os.stat(str(keys_dir)).st_mode) == 0o700

    def test_a_key_file_is_owner_only(self, keys_dir):
        _path = os.path.join(keystore_dir(), 'k.pem')
        with open_key_file(_path) as fh:
            fh.write('x')
        assert stat.S_IMODE(os.stat(_path).st_mode) == 0o600

    def test_rewriting_a_loose_key_file_narrows_it(self, keys_dir):
        _path = os.path.join(keystore_dir(), 'k.pem')
        with open(_path, 'w') as fh:
            fh.write('old')
        os.chmod(_path, 0o644)
        # O_CREAT's mode does not apply to a file that already exists
        with open_key_file(_path) as fh:
            fh.write('new')
        assert stat.S_IMODE(os.stat(_path).st_mode) == 0o600


class TestAesRoundTrip:
    """
    `save_key_to_pem` used to end with `self.key = pem_key`, leaving the first
    run of a fresh install holding a 44-character base64 *str* where AES wants
    32 raw bytes. Nothing caught it because the key directory did not exist
    either, so the path died earlier still, in listdir.
    """

    def test_encrypt_works_on_a_brand_new_keystore(self, keys_dir):
        from ipandora.core.engine.crypto.aescryptographer import AESCryptographer
        _crypto = AESCryptographer()
        assert _crypto.decrypt(_crypto.encrypt('hello')) == 'hello'

    def test_the_key_survives_to_a_second_instance(self, keys_dir):
        from ipandora.core.engine.crypto.aescryptographer import AESCryptographer
        _token = AESCryptographer().encrypt('hello')
        # a separate instance has to load the saved key, not mint a new one
        assert AESCryptographer().decrypt(_token) == 'hello'

    def test_the_key_stays_raw_bytes_of_the_right_length(self, keys_dir):
        from ipandora.core.engine.crypto.aescryptographer import AESCryptographer
        _crypto = AESCryptographer()
        assert isinstance(_crypto.key, bytes)
        assert len(_crypto.key) == 32

    def test_the_key_file_is_written_where_we_said(self, keys_dir):
        from ipandora.core.engine.crypto.aescryptographer import AESCryptographer
        AESCryptographer()
        assert (keys_dir / 'aes_pandora.pem').is_file()


class TestFernetRoundTrip:
    def test_encrypt_works_on_a_brand_new_keystore(self, keys_dir):
        from ipandora.core.engine.crypto.fercryptographer import FernetCryptographer
        _crypto = FernetCryptographer()
        assert _crypto.decrypt(_crypto.encrypt('hello')) == 'hello'

    def test_the_key_survives_to_a_second_instance(self, keys_dir):
        from ipandora.core.engine.crypto.fercryptographer import FernetCryptographer
        _token = FernetCryptographer().encrypt('hello')
        assert FernetCryptographer().decrypt(_token) == 'hello'

    def test_the_saved_key_is_the_one_in_use(self, keys_dir):
        # save_key_to_pem used to mint a *second* key and store that, throwing
        # away the one initialize_key had just made. Both are valid random
        # keys and the file still matched self.key, so that was waste rather
        # than a defect -- this case passes either way and is here for the
        # property itself, not as a guard against that old shape.
        from ipandora.core.engine.crypto.fercryptographer import FernetCryptographer
        _crypto = FernetCryptographer()
        assert (keys_dir / 'fernet_pandora.pem').read_bytes() == _crypto.key


class TestTheGatesCatchWhatTheFrameworkWrites:
    """
    The key is outside the repo now, but "outside" is one env var away from
    "inside". These two are the backstop: if a generated key ever does land in
    a checkout, the secret gate fails the build and git refuses to stage it.
    """

    @pytest.fixture
    def generated_keys(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_VAR, str(tmp_path))
        from ipandora.core.engine.crypto.aescryptographer import AESCryptographer
        from ipandora.core.engine.crypto.fercryptographer import FernetCryptographer
        AESCryptographer()
        FernetCryptographer()
        return [str(tmp_path / 'aes_pandora.pem'),
                str(tmp_path / 'fernet_pandora.pem')]

    def test_check_secrets_rejects_both_key_files(self, generated_keys):
        for _path in generated_keys:
            _done = subprocess.run(
                [sys.executable, os.path.join(REPO, 'scripts', 'check_secrets.py'),
                 _path], capture_output=True, text=True, timeout=60)
            assert _done.returncode == 1, '{} passed the gate'.format(_path)
            assert 'key material' in _done.stderr

    def test_the_fernet_key_has_no_header_to_match_on(self, generated_keys):
        """Why the gate has to judge by filename as well as content: this file
        is raw bytes. `detect-private-key` and any header pattern miss it."""
        _raw = open(generated_keys[1], 'rb').read()
        assert b'BEGIN' not in _raw

    def test_gitignore_covers_a_key_dropped_into_the_repo(self):
        for _name in ('aes_pandora.pem', 'fernet_pandora.pem',
                      'src/ipandora/conf/crypto/aes_pandora.pem', 'id_rsa'):
            _done = subprocess.run(['git', 'check-ignore', '-q', _name],
                                   cwd=REPO, timeout=60)
            assert _done.returncode == 0, '{} is not gitignored'.format(_name)
