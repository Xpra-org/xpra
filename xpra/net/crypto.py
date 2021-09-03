# This file is part of Xpra.
# Copyright (C) 2011-2021 Antoine Martin <antoine@xpra.org>
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
DEFAULT_KEYSIZE = envint("XPRA_CRYPTO_KEYSIZE", 32)
#these were made configurable in xpra 4.3:
MIN_ITERATIONS = envint("XPRA_CRYPTO_STRETCH_MIN_ITERATIONS", 100)
MAX_ITERATIONS = envint("XPRA_CRYPTO_STRETCH_MIN_ITERATIONS", 10000)
DEFAULT_MODE = os.environ.get("XPRA_CRYPTO_MODE", "CBC")
DEFAULT_KEY_HASH = os.environ.get("XPRA_CRYPTO_KEY_HASH", "SHA1")
DEFAULT_KEY_STRETCH = "PBKDF2"

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
MODES = []
KEY_HASHES = []
KEY_STRETCHING = []
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
        MODES[:] = list(pycryptography_backend.MODES)
        KEY_HASHES[:] = list(pycryptography_backend.KEY_HASHES)
        KEY_STRETCHING[:] = list(pycryptography_backend.KEY_STRETCHING)
        backend = pycryptography_backend
        return
    except ImportError:
        log("crypto backend init failure", exc_info=True)
        log.error("Error: cannot import python-cryptography")
    except Exception:
        log.error("Error: cannot initialize python-cryptography", exc_info=True)
    backend = None

def validate_backend(try_backend):
    log("validate_backend(%s) will validate AES modes: %s", try_backend, try_backend.MODES)
    try_backend.init()
    message = b"some message1234"*8
    password = "this is our secret"
    key_salt = DEFAULT_SALT
    iterations = DEFAULT_ITERATIONS
    for mode in try_backend.MODES:
        log("testing AES-%s", mode)
        key = None
        for key_hash in try_backend.KEY_HASHES:
            key = try_backend.get_key(password, key_salt, key_hash, DEFAULT_KEYSIZE, iterations)
            assert key
        block_size = try_backend.get_block_size(mode)
        log(" key=%s, block_size=%s", hexstr(key), block_size)
        assert key is not None, "backend %s failed to generate a key" % try_backend
        enc = try_backend.get_encryptor(key, DEFAULT_IV, mode)
        log(" encryptor=%s", enc)
        assert enc is not None, "backend %s failed to generate an encryptor" % enc
        dec = try_backend.get_decryptor(key, DEFAULT_IV, mode)
        log(" decryptor=%s", dec)
        assert dec is not None, "backend %s failed to generate a decryptor" % enc
        test_messages = [message*(1+block_size)]
        if block_size==0:
            test_messages.append(message[:29])
        else:
            test_messages.append(message[:block_size])
        for m in test_messages:
            ev = enc.encrypt(m)
            evs = hexstr(ev)
            log(" encrypted(%s)=%s", m, evs)
            dv = dec.decrypt(ev)
            log(" decrypted(%s)=%s", evs, dv)
            assert dv==m, "expected %r but got %r" % (m, dv)
            log(" test passed")


def pad(padding, size):
    if padding==PADDING_LEGACY:
        return b" "*size
    if padding==PADDING_PKCS7:
        return pack("B", size)*size
    raise Exception("invalid padding: %s" % padding)

def choose_padding(options):
    if PREFERRED_PADDING in options:
        return PREFERRED_PADDING
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


def new_cipher_caps(proto, cipher, cipher_mode, encryption_key, padding_options) -> dict:
    assert backend
    iv = get_iv()
    key_salt = get_salt()
    key_size = DEFAULT_KEYSIZE
    key_hash = DEFAULT_KEY_HASH
    key_stretch = DEFAULT_KEY_STRETCH
    iterations = get_iterations()
    padding = choose_padding(padding_options)
    proto.set_cipher_in(cipher+"-"+cipher_mode, iv, encryption_key,
                        key_salt, key_hash, key_size, iterations, padding)
    return {
         "cipher"                       : cipher,
         "cipher.mode"                  : cipher_mode,
         "cipher.mode.options"          : MODES,
         "cipher.iv"                    : iv,
         "cipher.key_salt"              : key_salt,
         "cipher.key_hash"              : key_hash,
         "cipher.key_size"              : key_size,
         "cipher.key_stretch"           : key_stretch,
         "cipher.key_stretch.options"   : KEY_STRETCHING,
         "cipher.key_stretch_iterations": iterations,
         "cipher.padding"               : padding,
         "cipher.padding.options"       : PADDING_OPTIONS,
         }

def get_crypto_caps() -> dict:
    if not backend:
        return {}
    caps = {
            "padding"       : {"options"    : PADDING_OPTIONS},
            "modes"         : {"options"    : MODES},
            "stretch"       : {"options"    : KEY_STRETCHING},
            }
    caps.update(backend.get_info())
    return caps


def get_encryptor(ciphername : str, iv, password, key_salt, key_hash : str, key_size : int, iterations : int):
    log("get_encryptor%s", (ciphername, iv, password, hexstr(key_salt), key_hash, key_size, iterations))
    if not ciphername:
        return None, 0
    assert key_size>=16
    assert MIN_ITERATIONS<=iterations<=MAX_ITERATIONS, "invalid number of iterations %i" % iterations
    assert ciphername.startswith("AES")
    assert password and iv, "password or iv missing"
    mode = (ciphername+"-").split("-")[1] or DEFAULT_MODE
    key = backend.get_key(password, key_salt, key_hash, key_size, iterations)
    return backend.get_encryptor(key, iv, mode), backend.get_block_size(mode)

def get_decryptor(ciphername : str, iv, password, key_salt, key_hash : str, key_size : int, iterations : int):
    log("get_decryptor%s", (ciphername, iv, password, hexstr(key_salt), key_hash, key_size, iterations))
    if not ciphername:
        return None, 0
    assert key_size>=16
    assert MIN_ITERATIONS<=iterations<=MAX_ITERATIONS, "invalid number of iterations %i" % iterations
    assert ciphername.startswith("AES")
    assert password and iv, "password or iv missing"
    mode = (ciphername+"-").split("-")[1] or DEFAULT_MODE
    key = backend.get_key(password, key_salt, key_hash, key_size, iterations)
    return backend.get_decryptor(key, iv, mode), backend.get_block_size(mode)


def main():
    from xpra.util import print_nested_dict
    from xpra.platform import program_context
    import sys
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()
    with program_context("Encryption Properties"):
        crypto_backend_init()
        print_nested_dict(get_crypto_caps())

if __name__ == "__main__":
    main()
