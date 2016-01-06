# This file is part of Xpra.
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.log import Logger
log = Logger("network", "crypto")

ENABLE_CRYPTO = os.environ.get("XPRA_ENABLE_CRYPTO", "1")=="1"
ENCRYPT_FIRST_PACKET = os.environ.get("XPRA_ENCRYPT_FIRST_PACKET", "0")=="1"

DEFAULT_IV = os.environ.get("XPRA_CRYPTO_DEFAULT_IV", "0000000000000000")
DEFAULT_SALT = os.environ.get("XPRA_CRYPTO_DEFAULT_SALT", "0000000000000000")
DEFAULT_ITERATIONS = int(os.environ.get("XPRA_CRYPTO_DEFAULT_ITERATIONS", "1000"))
DEFAULT_BLOCKSIZE = int(os.environ.get("XPRA_CRYPTO_BLOCKSIZE", "32"))      #fixme: can we derive this?

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

CRYPTO_LIBRARY = os.environ.get("XPRA_CRYPTO_BACKEND", "pycrypto")    #pycrypto
try:
    if CRYPTO_LIBRARY=="pycryptography":
        from xpra.net import pycryptography_backend as backend
    elif CRYPTO_LIBRARY=="pycrypto":
        from xpra.net import pycrypto_backend as backend
    else:
        raise ImportError("invalid crypto library specified: '%s'" % CRYPTO_LIBRARY)
    ENCRYPTION_CIPHERS = ["AES"]
except ImportError as e:
    log.error("Error: encryption library is not available!")
    log.error(" %s", e)
    ENCRYPTION_CIPHERS = []


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
    raise Exception("cannot find a valid padding in %s" % str(options))


def get_hex_uuid():
    from xpra.os_util import get_hex_uuid as ghu
    return ghu()

def get_iv():
    IV = None
    #IV = "0000000000000000"
    return IV or get_hex_uuid()[:16]

def get_salt():
    KEY_SALT = None
    #KEY_SALT = "0000000000000000"
    return KEY_SALT or (get_hex_uuid()+get_hex_uuid())

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
    assert backend
    caps = {
            "padding.options"       : PADDING_OPTIONS,
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
    return backend.get_encryptor(key, iv)

def get_decryptor(ciphername, iv, password, key_salt, iterations):
    log("get_encryptor(%s, %s, %s, %s, %s)", ciphername, iv, password, key_salt, iterations)
    if not ciphername:
        return None, 0
    assert iterations>=100
    assert ciphername=="AES"
    assert password and iv
    block_size = DEFAULT_BLOCKSIZE
    key = backend.get_key(password, key_salt, block_size, iterations)
    return backend.get_decryptor(key, iv)


def main():
    from xpra.platform import program_context
    import sys
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()
    with program_context("Encryption Properties"):
        for k,v in sorted(get_crypto_caps().items()):
            print(k.ljust(32)+": "+str(v))
    #simple tests:
    try:
        password = "this is our secret"
        key_salt = DEFAULT_SALT
        iterations = DEFAULT_ITERATIONS
        block_size = DEFAULT_BLOCKSIZE
        #test key stretching:
        secrets = []
        from xpra.net import pycrypto_backend
        from xpra.net import pycryptography_backend
        backends = [pycrypto_backend, pycryptography_backend]
        for b in backends:
            print("%s:%s" % (type(b), dir(b)))
            args = password, key_salt, block_size, iterations
            v = b.get_key(*args)
            print("%s%s=%s" % (b.get_key, args, v.encode('hex')))
            assert v is not None
            secrets.append(v)
        assert secrets[0]==secrets[1]
        #test creation of encryptors and decryptors:
        iv = DEFAULT_IV
        encryptors = []
        decryptors = []
        for i, b in enumerate(backends):
            args = secrets[i], iv
            enc = b.get_encryptor(*args)
            print("%s%s=%s" % (b.get_encryptor, args, enc))
            assert enc is not None
            encryptors.append(enc)
            dec = b.get_decryptor(*args)
            print("%s%s=%s" % (b.get_decryptor, args, dec))
            assert dec is not None
            decryptors.append(dec)
        #test encoding of a message:
        message = "some message1234"
        encrypted = []
        for enc in encryptors:
            v = enc.encrypt(message)
            print("%s%s=%s" % (enc.encrypt, (message,), v.encode('hex')))
            assert v is not None
            encrypted.append(v)
        assert encrypted[0]==encrypted[1]
        #test decoding of the message:
        decrypted = []
        for dec in decryptors:
            v = dec.decrypt(encrypted[0])
            print("%s%s=%s" % (dec.decrypt, (encrypted[0],), v.encode('hex')))
            assert v is not None
            decrypted.append(v)
        assert decrypted[0]==decrypted[1]
        assert decrypted[0]==message
    except Exception as e:
        print("Error running tests: %s" % e)
        raise

if __name__ == "__main__":
    main()
