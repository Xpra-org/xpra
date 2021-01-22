# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from struct import pack

from xpra.util import envint, envbool
from xpra.log import Logger
from xpra.os_util import hexstr, get_hex_uuid
from xpra.net.digest import get_salt

log = Logger("network", "crypto")

ENABLE_CRYPTO = envbool("XPRA_ENABLE_CRYPTO", True)
ENCRYPT_FIRST_PACKET = envbool("XPRA_ENCRYPT_FIRST_PACKET", False)

DEFAULT_IV = os.environ.get("XPRA_CRYPTO_DEFAULT_IV", "0000000000000000")
DEFAULT_SALT = os.environ.get("XPRA_CRYPTO_DEFAULT_SALT", "0000000000000000")
DEFAULT_ITERATIONS = envint("XPRA_CRYPTO_DEFAULT_ITERATIONS", 1000)
DEFAULT_BLOCKSIZE = envint("XPRA_CRYPTO_BLOCKSIZE", 32)

#other option "PKCS#7", "legacy"
PADDING_LEGACY = "legacy"
PADDING_PKCS7 = "PKCS#7"
ALL_PADDING_OPTIONS = (PADDING_LEGACY, PADDING_PKCS7)
INITIAL_PADDING = os.environ.get("XPRA_CRYPTO_INITIAL_PADDING", PADDING_LEGACY)
DEFAULT_PADDING = PADDING_LEGACY
PREFERRED_PADDING = os.environ.get("XPRA_CRYPTO_PREFERRED_PADDING", PADDING_PKCS7)
assert PREFERRED_PADDING in ALL_PADDING_OPTIONS, "invalid preferred padding: %s" % PREFERRED_PADDING
assert INITIAL_PADDING in ALL_PADDING_OPTIONS, "invalid padding: %s" % INITIAL_PADDING
#make sure the preferred one is first in the list:
def get_padding_options():
    options = [PREFERRED_PADDING]
    for x in ALL_PADDING_OPTIONS:
        if x not in options:
            options.append(x)
    return options
PADDING_OPTIONS = get_padding_options()


ENCRYPTION_CIPHERS = []
backend = False
def crypto_backend_init():
    global backend, ENCRYPTION_CIPHERS
    log("crypto_backend_init() backend=%s", backend)
    if backend is not False:
        return
    try:
        from xpra.net import pycryptography_backend
        #validate it:
        validate_backend(pycryptography_backend)
        ENCRYPTION_CIPHERS[:] = pycryptography_backend.ENCRYPTION_CIPHERS[:]
        backend = pycryptography_backend
        return
    except ImportError:
        log("crypto backend init failure", exc_info=True)
        log.error("Error: cannot import python-cryptography")
    except Exception:
        log.error("Error: cannot initialize python-cryptography", exc_info=True)
    backend = None

def validate_backend(try_backend):
    try_backend.init()
    message = b"some message1234"
    password = "this is our secret"
    key_salt = DEFAULT_SALT
    iterations = DEFAULT_ITERATIONS
    block_size = DEFAULT_BLOCKSIZE
    key = try_backend.get_key(password, key_salt, block_size, iterations)
    log("validate_backend(%s) key=%s", try_backend, hexstr(key))
    assert key is not None, "backend %s failed to generate a key" % try_backend
    enc = try_backend.get_encryptor(key, DEFAULT_IV)
    log("validate_backend(%s) encryptor=%s", try_backend, enc)
    assert enc is not None, "backend %s failed to generate an encryptor" % enc
    dec = try_backend.get_decryptor(key, DEFAULT_IV)
    log("validate_backend(%s) decryptor=%s", try_backend, dec)
    assert dec is not None, "backend %s failed to generate a decryptor" % enc
    ev = enc.encrypt(message)
    evs = hexstr(ev)
    log("validate_backend(%s) encrypted(%s)=%s", try_backend, message, evs)
    dv = dec.decrypt(ev)
    log("validate_backend(%s) decrypted(%s)=%s", try_backend, evs, dv)
    assert dv==message
    log("validate_backend(%s) passed", try_backend)


def pad(padding, size):
    if padding==PADDING_LEGACY:
        return b" "*size
    if padding==PADDING_PKCS7:
        return pack("B", size)*size
    raise Exception("invalid padding: %s" % padding)

def choose_padding(options):
    for x in options:
        if x in PADDING_OPTIONS:
            return x
    raise Exception("cannot find a valid padding in %s" % str(options))


def get_iv():
    IV = None
    #IV = "0000000000000000"
    return IV or get_hex_uuid()[:16]

def get_iterations() -> int:
    return DEFAULT_ITERATIONS


def new_cipher_caps(proto, cipher, encryption_key, padding_options) -> dict:
    assert backend
    iv = get_iv()
    key_salt = get_salt()
    iterations = get_iterations()
    padding = choose_padding(padding_options)
    proto.set_cipher_in(cipher, iv, encryption_key, key_salt, iterations, padding)
    return {
         "cipher"                       : cipher,
         "cipher.iv"                    : iv,
         "cipher.key_salt"              : key_salt,
         "cipher.key_stretch_iterations": iterations,
         "cipher.padding"               : padding,
         "cipher.padding.options"       : PADDING_OPTIONS,
         }

def get_crypto_caps() -> dict:
    if not backend:
        return {}
    caps = {
            "padding"       : {"options"    : PADDING_OPTIONS},
            }
    caps.update(backend.get_info())
    return caps


def get_encryptor(ciphername, iv, password, key_salt, iterations):
    log("get_encryptor(%s, %s, %s, %s, %s)", ciphername, iv, password, hexstr(key_salt), iterations)
    if not ciphername:
        return None, 0
    assert iterations>=100
    assert ciphername=="AES"
    assert password and iv
    block_size = DEFAULT_BLOCKSIZE
    key = backend.get_key(password, key_salt, block_size, iterations)
    return backend.get_encryptor(key, iv), block_size

def get_decryptor(ciphername, iv, password, key_salt, iterations):
    log("get_decryptor(%s, %s, %s, %s, %s)", ciphername, iv, password, hexstr(key_salt), iterations)
    if not ciphername:
        return None, 0
    assert iterations>=100
    assert ciphername=="AES"
    assert password and iv
    block_size = DEFAULT_BLOCKSIZE
    key = backend.get_key(password, key_salt, block_size, iterations)
    return backend.get_decryptor(key, iv), block_size


def main():
    from xpra.util import print_nested_dict
    crypto_backend_init()
    from xpra.platform import program_context
    import sys
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()
    with program_context("Encryption Properties"):
        print_nested_dict(get_crypto_caps())

if __name__ == "__main__":
    main()
