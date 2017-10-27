# This file is part of Xpra.
# Copyright (C) 2011-2016 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import hmac
import hashlib
from xpra.util import envint, envbool, xor
from xpra.os_util import strtobytes, memoryview_to_bytes
from xpra.log import Logger
log = Logger("network", "crypto")

ENABLE_CRYPTO = envbool("XPRA_ENABLE_CRYPTO", True)
ENCRYPT_FIRST_PACKET = envbool("XPRA_ENCRYPT_FIRST_PACKET", False)

DEFAULT_IV = os.environ.get("XPRA_CRYPTO_DEFAULT_IV", "0000000000000000")
DEFAULT_SALT = os.environ.get("XPRA_CRYPTO_DEFAULT_SALT", "0000000000000000")
DEFAULT_ITERATIONS = envint("XPRA_CRYPTO_DEFAULT_ITERATIONS", 1000)
DEFAULT_BLOCKSIZE = envint("XPRA_CRYPTO_BLOCKSIZE", 32)      #fixme: can we derive this?

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
PADDING_OPTIONS = [PREFERRED_PADDING]
for x in ALL_PADDING_OPTIONS:
    if x not in PADDING_OPTIONS:
        PADDING_OPTIONS.append(x)
CRYPTO_LIBRARY = os.environ.get("XPRA_CRYPTO_BACKEND", "python-cryptography")    #pycrypto


ENCRYPTION_CIPHERS = []
backend = False
def crypto_backend_init():
    global backend, ENCRYPTION_CIPHERS
    log("crypto_backend_init() backend=%s", backend)
    if backend is not False:
        return
    try_backends = []
    if CRYPTO_LIBRARY=="python-cryptography":
        try_backends = ["python-cryptography", "pycrypto"]
    elif CRYPTO_LIBRARY=="pycrypto":
        try_backends = ["pycrypto", "python-cryptography"]
    else:
        raise ImportError("invalid crypto library specified: '%s'" % CRYPTO_LIBRARY)
    errors = {}
    for tb in try_backends:
        try:
            if tb=="python-cryptography":
                from xpra.net import pycryptography_backend
                try_backend = pycryptography_backend
            else:
                assert tb=="pycrypto"
                from xpra.net import pycrypto_backend
                try_backend = pycrypto_backend

            #validate it:
            validate_backend(try_backend)
            ENCRYPTION_CIPHERS[:] = try_backend.ENCRYPTION_CIPHERS[:]
            backend = try_backend
            break
        except ImportError as e:
            errors[tb] = e
            log("%s import failure", tb, exc_info=True)
        except Exception as e:
            errors[tb] = e
            log("%s validation failure", tb, exc_info=True)
    if errors:
        if backend:
            log.warn("Warning: using fallback encryption library %s", tb)
            for k,e in errors.items():
                log.warn(" %s is not available:", k)
                log.warn(" %s", e)
        else:
            log.error("Error: no encryption libraries could be loaded")
            for k,e in errors.items():
                log.error(" %s is not available: %s", k, e)
    log("crypto_backend_init() backend=%s, ENCRYPTION_CIPHERS=%s", backend, ENCRYPTION_CIPHERS)

def validate_backend(try_backend):
    import binascii
    try_backend.init()
    message = b"some message1234"
    password = "this is our secret"
    key_salt = DEFAULT_SALT
    iterations = DEFAULT_ITERATIONS
    block_size = DEFAULT_BLOCKSIZE
    key = try_backend.get_key(password, key_salt, block_size, iterations)
    log("validate_backend(%s) key=%s", try_backend, binascii.hexlify(key))
    assert key is not None, "backend %s failed to generate a key" % try_backend
    enc = try_backend.get_encryptor(key, DEFAULT_IV)
    log("validate_backend(%s) encryptor=%s", try_backend, enc)
    assert enc is not None, "backend %s failed to generate an encryptor" % enc
    dec = try_backend.get_decryptor(key, DEFAULT_IV)
    log("validate_backend(%s) decryptor=%s", try_backend, dec)
    assert dec is not None, "backend %s failed to generate a decryptor" % enc
    ev = enc.encrypt(message)
    evs = binascii.hexlify(strtobytes(ev))
    log("validate_backend(%s) encrypted(%s)=%s", try_backend, message, evs)
    dv = dec.decrypt(ev)
    log("validate_backend(%s) decrypted(%s)=%s", try_backend, evs, dv)
    assert dv==message
    log("validate_backend(%s) passed", try_backend)


def get_digests():
    algos = getattr(hashlib, "algorithms_available", getattr(hashlib, "algorithms", ["md5", "sha1", "sha224", "sha256", "sha384", "sha512"]))
    digests = ["hmac", "xor"] + ["hmac+%s" % x for x in list(reversed(sorted(algos)))]
    return digests

def get_digest_module(digest):
    log("get_digest_module(%s)", digest)
    if not digest or not digest.startswith("hmac"):
        return None
    try:
        digest_module = digest.split("+")[1]        #ie: "hmac+sha512" -> "sha512"
    except:
        digest_module = "md5"
    try:
        return getattr(hashlib, digest_module)
    except AttributeError:
        return None

def choose_digest(options):
    assert len(options)>0, "no digest options"
    log("choose_digest(%s)", options)
    #prefer stronger hashes:
    for h in ("sha512", "sha384", "sha256", "sha224", "sha1", "md5"):
        hname = "hmac+%s" % h
        if hname in options:
            return hname
    #legacy name for "hmac+md5":
    if "hmac" in options:
        return "hmac"
    if "xor" in options:
        return "xor"
    raise Exception("no known digest options found in '%s'" % csv(options))

def gendigest(digest, password, salt):
    assert digest and password and salt
    salt = memoryview_to_bytes(salt)
    password = strtobytes(password)
    if digest=="xor":
        salt = salt.ljust(16, "\x00")[:len(password)]
        return memoryview_to_bytes(xor(password, salt))
    digestmod = get_digest_module(digest)
    if not digestmod:
        log("invalid digest module '%s': %s", digest)
        return None
        #warn_server_and_exit(EXIT_UNSUPPORTED, "server requested digest '%s' but it is not supported" % digest, "invalid digest")
    v = hmac.HMAC(strtobytes(password), strtobytes(salt), digestmod=digestmod).hexdigest()
    return v


def pad(padding, size):
    if padding==PADDING_LEGACY:
        return " "*size
    elif padding==PADDING_PKCS7:
        return chr(size)*size
    else:
        raise Exception("invalid padding: %s" % padding)

def choose_padding(options):
    for x in options:
        if x in PADDING_OPTIONS:
            return x
    #legacy name for "hmac+md5":
    if "hmac" in options:
        return "hmac"
    raise Exception("cannot find a valid padding in %s" % str(options))


def get_hex_uuid():
    from xpra.os_util import get_hex_uuid as ghu
    return ghu()

def get_iv():
    IV = None
    #IV = "0000000000000000"
    return IV or get_hex_uuid()[:16]

def get_rand_str(l):
    #too short: we would not feed enough random data to HMAC
    assert l>=32, "salt is too short: only %i bytes" % l
    #too long: limit the amount of random data we request from the system
    assert l<256, "salt is too long: %i bytes" % l
    #all server versions support a client salt,
    #they also tell us which digest to use:
    salt = get_hex_uuid()
    while len(salt)<l:
        salt += get_hex_uuid()
    return salt[:l]

def get_salt(l=64):
    return get_rand_str(l)

def get_iterations():
    return DEFAULT_ITERATIONS


def new_cipher_caps(proto, cipher, encryption_key, padding_options):
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

def get_crypto_caps():
    if not backend:
        return {}
    caps = {
            "padding"       : {"options"    : PADDING_OPTIONS},
            }
    caps.update(backend.get_info())
    return caps


def get_encryptor(ciphername, iv, password, key_salt, iterations):
    log("get_encryptor(%s, %s, %s, %s, %s)", ciphername, iv, password, key_salt, iterations)
    if not ciphername:
        return None, 0
    assert iterations>=100
    assert ciphername=="AES"
    assert password and iv
    block_size = DEFAULT_BLOCKSIZE
    key = backend.get_key(password, key_salt, block_size, iterations)
    return backend.get_encryptor(key, iv), block_size

def get_decryptor(ciphername, iv, password, key_salt, iterations):
    log("get_decryptor(%s, %s, %s, %s, %s)", ciphername, iv, password, key_salt, iterations)
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
