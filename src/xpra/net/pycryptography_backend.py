# This file is part of Xpra.
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import strtobytes
from xpra.log import Logger
log = Logger("network", "crypto")

__all__ = ("get_info", "get_key", "get_encryptor", "get_decryptor", "ENCRYPTION_CIPHERS")

ENCRYPTION_CIPHERS = []
backend = None


def patch_crypto_be_discovery():
    """
    Monkey patches cryptography's backend detection.
    Objective: support pyinstaller / cx_freeze / pyexe / py2app freezing.
    """
    from cryptography.hazmat import backends
    try:
        from cryptography.hazmat.backends.commoncrypto.backend import backend as be_cc
    except ImportError:
        log("failed to import commoncrypto", exc_info=True)
        be_cc = None
    try:
        import _ssl
        log("loaded _ssl=%s", _ssl)
    except ImportError:
        log("failed to import _ssl", exc_info=True)
        be_ossl = None
    try:
        from cryptography.hazmat.backends.openssl.backend import backend as be_ossl
    except ImportError:
        log("failed to import openssl backend", exc_info=True)
        be_ossl = None
    backends._available_backends_list = [
        be for be in (be_cc, be_ossl) if be is not None
    ]

def init():
    import sys
    from xpra.os_util import OSX
    if getattr(sys, 'frozen', False) or OSX:
        patch_crypto_be_discovery()
    global backend, ENCRYPTION_CIPHERS
    import cryptography
    assert cryptography
    from cryptography.hazmat.backends import default_backend
    backend = default_backend()
    log("default_backend()=%s", backend)
    log("backends=%s", getattr(backend, "_backends", []))
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import hashes
    assert Cipher and algorithms and modes and hashes
    ENCRYPTION_CIPHERS[:] = ["AES"]

def get_info():
    import cryptography
    return {"backend"                       : "python-cryptography",
            "python-cryptography"           : {
                ""          : True,
                "version"   : cryptography.__version__,
                }
            }

def get_key(password, key_salt, block_size, iterations):
    global backend
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=block_size, salt=strtobytes(key_salt), iterations=iterations, backend=backend)
    key = kdf.derive(strtobytes(password))
    return key

def _get_cipher(key, iv):
    global backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    return Cipher(algorithms.AES(key), modes.CBC(strtobytes(iv)), backend=backend)

def get_encryptor(key, iv):
    encryptor = _get_cipher(key, iv).encryptor()
    encryptor.encrypt = encryptor.update
    return encryptor

def get_decryptor(key, iv):
    decryptor = _get_cipher(key, iv).decryptor()
    decryptor.decrypt = decryptor.update
    return decryptor


def main():
    from xpra.platform import program_context
    from xpra.util import print_nested_dict
    import sys
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()
    with program_context("Encryption Properties"):
        init()
        print_nested_dict(get_info())


if __name__ == "__main__":
    main()
