# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("network", "crypto")

from xpra.os_util import get_hex_uuid


try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
except Exception as e:
    AES, PBKDF2 = None, None
    log("pycrypto is missing: %s", e)


def get_iv():
    IV = None
    #IV = "0000000000000000"
    return IV or get_hex_uuid()[:16]

def get_salt():
    KEY_SALT = None
    #KEY_SALT = "0000000000000000"
    return KEY_SALT or (get_hex_uuid()+get_hex_uuid())

def get_iterations():
    return 1000


def new_cipher_caps(proto, cipher, encryption_key):
    iv = get_iv()
    key_salt = get_salt()
    iterations = get_iterations()
    proto.set_cipher_in(cipher, iv, encryption_key, key_salt, iterations)
    return {
                 "cipher"           : cipher,
                 "cipher.iv"        : iv,
                 "cipher.key_salt"  : key_salt,
                 "cipher.key_stretch_iterations" : iterations
                 }

def get_crypto_caps():
    caps = {}
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
