# This file is part of Xpra.
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import strtobytes
from xpra.log import Logger
log = Logger("network", "crypto")

import Crypto
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Cipher import AES
ENCRYPTION_CIPHERS = ["AES"]

__all__ = ("get_info", "get_key", "get_encryptor", "get_decryptor", ENCRYPTION_CIPHERS)


def get_info():
    caps = {"backend"           : "pycrypto",
            "pycrypto"          : "True",
            "pycrypto.version"  : Crypto.__version__}
    try:
        from Crypto.PublicKey import _fastmath
    except:
        _fastmath = None
    caps["pycrypto.fastmath"] = _fastmath is not None
    return caps


def get_key(password, key_salt, block_size, iterations):
    assert (AES and PBKDF2), "pycrypto is missing!"
    #stretch the password:
    key = PBKDF2(strtobytes(password), strtobytes(key_salt), dkLen=block_size, count=iterations)
    return key

def get_encryptor(secret, iv):
    return AES.new(secret, AES.MODE_CBC, iv)

def get_decryptor(secret, iv):
    return AES.new(secret, AES.MODE_CBC, iv)



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
