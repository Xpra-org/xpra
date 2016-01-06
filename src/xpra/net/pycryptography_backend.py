# This file is part of Xpra.
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("network", "crypto")

import cryptography
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
ENCRYPTION_CIPHERS = ["AES"]

__all__ = ("get_info", "get_key", "get_encryptor", "get_decryptor", ENCRYPTION_CIPHERS)


def get_info():
    return {"backend"                       : "python-cryptography",
            "python-cryptography"           : True,
            "python-cryptography.version"   : cryptography.__version__}

def get_key(password, key_salt, block_size, iterations):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=block_size, salt=key_salt, iterations=iterations, backend=default_backend())
    key = kdf.derive(password)
    log("python_cryptography.get_key(..) secret=%s, block_size=%s", key.encode('hex'), block_size)
    return key

def get_encryptor(key, iv):
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encryptor.encrypt = encryptor.update
    return encryptor

def get_decryptor(key, iv):
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decryptor.decrypt = decryptor.update
    return decryptor


def main():
    from xpra.platform import program_context
    import sys
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()
    with program_context("Encryption Properties"):
        for k,v in sorted(get_info().items()):
            print(k.ljust(32)+": "+str(v))

if __name__ == "__main__":
    main()
