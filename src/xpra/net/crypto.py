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


AES, PBKDF2 = None, None
ENCRYPTION_CIPHERS = []
if ENABLE_CRYPTO:
    try:
        from Crypto.Protocol.KDF import PBKDF2
        from Crypto.Cipher import AES
        ENCRYPTION_CIPHERS.append("AES")
    except Exception as e:
        AES, PBKDF2 = None, None
        log("pycrypto is missing: %s", e)


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
    caps = {
            "padding.options"       : PADDING_OPTIONS,
            }
    try:
        import Crypto
        caps["pycrypto"] = True
        caps["pycrypto.version"] = Crypto.__version__
        try:
            from Crypto.PublicKey import _fastmath
        except:
            _fastmath = None
        caps["pycrypto.fastmath"] = _fastmath is not None
    except:
        caps["pycrypto"] = False
    return caps


def get_cipher(ciphername, iv, password, key_salt, iterations):
    log("get_cipher(%s, %s, %s, %s, %s)", ciphername, iv, password, key_salt, iterations)
    if not ciphername:
        return None, 0
    assert iterations>=100
    assert ciphername=="AES"
    assert password and iv
    assert (AES and PBKDF2), "pycrypto is missing!"
    #stretch the password:
    block_size = 32         #fixme: can we derive this?
    secret = PBKDF2(password, key_salt, dkLen=block_size, count=iterations)
    log("get_cipher(..) secret=%s, block_size=%s", secret.encode('hex'), block_size)
    return AES.new(secret, AES.MODE_CBC, iv), block_size
