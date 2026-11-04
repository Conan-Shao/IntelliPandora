# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : keystore.py
@Time  : 2026-11-04

Where key material lives, and who may read it.

It used to live in `conf/crypto` *inside the installed package*. In a checkout
that resolves to `src/ipandora/conf/crypto` -- inside the tracked tree. The
framework generates a key there by itself on first use, so nobody chooses to
put it there; and three separate gates would have let `git add -A` commit it:

  * `.gitignore` did not cover `*.pem`
  * pre-commit's `detect-private-key` only knows the `BEGIN RSA/EC/OPENSSH/PGP
    PRIVATE KEY` headers -- the AES file's header is `BEGIN aes KEY`, and the
    Fernet file has no header at all, being raw bytes with a `.pem` name
  * CI's secret check looked for `password = "..."` assignments

The repo is public. So: outside any checkout, owner-only, and never guessed
from the package's own location.
"""
import os

ENV_VAR = 'IPANDORA_KEYS_DIR'
DEFAULT_DIR = '~/.ipandora/crypto'

DIR_MODE = 0o700
FILE_MODE = 0o600


def keystore_dir(create: bool = True) -> str:
    """The directory holding key material, created on demand."""
    _dir = os.path.abspath(os.path.expanduser(
        os.environ.get(ENV_VAR) or DEFAULT_DIR))
    if create:
        os.makedirs(_dir, mode=DIR_MODE, exist_ok=True)
        # `mode` applies only to the leaf makedirs actually creates, and not at
        # all when the directory is already there. Narrow it either way -- an
        # inherited 0755 on a key directory is the whole problem.
        _narrow(_dir)
    return _dir


def open_key_file(path: str, binary: bool = False):
    """
    Create or truncate `path` readable only by its owner, from the first byte.

    Opening normally and chmod'ing after leaves a window in which the key is
    world-readable; passing the mode to os.open closes it.
    """
    _fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    # O_CREAT's mode is ignored for a file that already exists, so a key
    # written once with loose permissions would keep them.
    _narrow(path, FILE_MODE)
    return os.fdopen(_fd, 'wb' if binary else 'w')


def _narrow(path: str, mode: int = DIR_MODE) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        # Windows, or a path we do not own. Losing the permission bits is worth
        # reporting but not worth refusing to encrypt over.
        pass
