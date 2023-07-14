# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import secrets
from struct import pack
from typing import Dict, Tuple, Any, Iterable, List

from xpra.util import envint, envbool, csv
from xpra.version_util import parse_version
from xpra.os_util import hexstr, strtobytes, memoryview_to_bytes, OSX
from xpra.net.digest import get_salt
from xpra.log import Logger

log = Logger("network", "crypto")

cryptography = None

ENCRYPT_FIRST_PACKET = envbool("XPRA_ENCRYPT_FIRST_PACKET", False)

DEFAULT_IV = os.environ.get("XPRA_CRYPTO_DEFAULT_IV", "0000000000000000")
DEFAULT_SALT = os.environ.get("XPRA_CRYPTO_DEFAULT_SALT", "0000000000000000")
DEFAULT_ITERATIONS = envint("XPRA_CRYPTO_DEFAULT_ITERATIONS", 1000)
DEFAULT_KEYSIZE = envint("XPRA_CRYPTO_KEYSIZE", 32)
if DEFAULT_KEYSIZE not in (16, 24, 32):
    log.warn("Warning: default key size %i (%i bits) is not supported",
             DEFAULT_KEYSIZE, DEFAULT_KEYSIZE*8)
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
if PREFERRED_PADDING not in ALL_PADDING_OPTIONS:
    raise ValueError(f"invalid preferred padding: {PREFERRED_PADDING}")
if INITIAL_PADDING not in ALL_PADDING_OPTIONS:
    raise ValueError(f"invalid padding: {INITIAL_PADDING}")
#make sure the preferred one is first in the list:
def get_padding_options() -> Tuple[str,...]:
    options = [PREFERRED_PADDING]
    for x in ALL_PADDING_OPTIONS:
        if x not in options:
            options.append(x)
    return tuple(options)
PADDING_OPTIONS : Tuple[str,...] = get_padding_options()


# pylint: disable=import-outside-toplevel
CIPHERS : Tuple[str,...] = ()
MODES : Tuple[str,...] = ()
KEY_HASHES : Tuple[str,...] = ()
KEY_STRETCHING : Tuple[str,...] = ()
def crypto_backend_init():
    global cryptography, CIPHERS, MODES, KEY_HASHES, KEY_STRETCHING
    log("crypto_backend_init() pycryptography=%s", cryptography)
    if cryptography:
        return cryptography
    try:
        if getattr(sys, 'frozen', False) or OSX:
            patch_crypto_be_discovery()
        import cryptography as pc
        cryptography = pc
        MODES = tuple(x for x in os.environ.get("XPRA_CRYPTO_MODES", "CBC,GCM,CFB,CTR").split(",")
              if x in ("CBC", "GCM", "CFB", "CTR"))
        KEY_HASHES = ("SHA1", "SHA224", "SHA256", "SHA384", "SHA512")
        KEY_STRETCHING = ("PBKDF2", )
        CIPHERS = ("AES", )
        from cryptography.hazmat.backends import default_backend
        backend = default_backend()
        log("default_backend()=%s", backend)
        log("backends=%s", getattr(backend, "_backends", []))
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import hashes
        assert Cipher and algorithms and modes and hashes   # type: ignore[truthy-function]
        validate_backend()
        return cryptography
    except ImportError:
        log("crypto backend init failure", exc_info=True)
        log.error("Error: cannot import python-cryptography")
    except Exception:
        log.error("Error: cannot initialize python-cryptography", exc_info=True)
    cryptography = None
    CIPHERS = MODES = KEY_HASHES = KEY_STRETCHING = ()
    return None

def patch_crypto_be_discovery() -> None:
    """
    Monkey patches cryptography's backend detection.
    Objective: support pyinstaller / cx_freeze / pyexe / py2app freezing.
    """
    from cryptography.hazmat import backends
    available : List = []
    try:
        from cryptography.hazmat.backends.commoncrypto.backend import backend as be_cc
        available.append(be_cc)
    except ImportError:
        log("failed to import commoncrypto", exc_info=True)
    try:
        import _ssl
        log("loaded _ssl=%s", _ssl)
    except ImportError:
        log("failed to import _ssl", exc_info=True)
    try:
        from cryptography.hazmat.backends.openssl.backend import backend as be_ossl
        available.append(be_ossl)
    except ImportError:
        log("failed to import openssl backend", exc_info=True)
    setattr(backends, "_available_backends_list", [
        be for be in available if be is not None
    ])

def get_ciphers() -> Tuple[str, ...]:
    return CIPHERS

def get_modes() -> Tuple[str, ...]:
    return MODES

def get_key_hashes() -> Tuple[str, ...]:
    return KEY_HASHES

def validate_backend() -> None:
    log("validate_backend() will validate AES modes: "+csv(MODES))
    message = b"some message1234"*8
    password = "this is our secret"
    key_salt = DEFAULT_SALT
    iterations = DEFAULT_ITERATIONS
    for mode in MODES:
        log("testing AES-%s", mode)
        key = None
        for key_hash in KEY_HASHES:
            key = get_key(password, key_salt, key_hash, DEFAULT_KEYSIZE, iterations)
            assert key
        block_size = get_block_size(mode)
        log(" key=%s, block_size=%s", hexstr(key), block_size)
        assert key is not None, "pycryptography failed to generate a key"
        enc = get_cipher_encryptor(key, DEFAULT_IV, mode)
        log(" encryptor=%s", enc)
        assert enc is not None, "pycryptography failed to generate an encryptor"
        dec = get_cipher_decryptor(key, DEFAULT_IV, mode)
        log(" decryptor=%s", dec)
        assert dec is not None, "pycryptography failed to generate a decryptor"
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
            if dv!=m:
                raise RuntimeError(f"expected {m!r} but got {dv!r}")
            log(" test passed")


def pad(padding:str, size:int) -> bytes:
    if padding==PADDING_LEGACY:
        return b" "*size
    if padding==PADDING_PKCS7:
        return pack("B", size)*size
    raise ValueError(f"invalid padding: {padding}")

def choose_padding(options:Iterable[str]) -> str:
    if PREFERRED_PADDING in options:
        return PREFERRED_PADDING
    for x in options:
        if x in PADDING_OPTIONS:
            return x
    raise ValueError(f"cannot find a valid padding in {options}")


def get_iv() -> str:
    return secrets.token_urlsafe(16)[:16]

def get_iterations() -> int:
    return DEFAULT_ITERATIONS


def new_cipher_caps(proto, cipher:str, cipher_mode:str, encryption_key, padding_options) -> Dict[str,Any]:
    iv = get_iv()
    key_salt = get_salt()
    key_size = DEFAULT_KEYSIZE
    key_hash = DEFAULT_KEY_HASH
    key_stretch = DEFAULT_KEY_STRETCH
    iterations = get_iterations()
    padding = choose_padding(padding_options)
    proto.set_cipher_in(cipher+"-"+cipher_mode, iv, encryption_key,
                        key_salt, key_hash, key_size, iterations, padding)
    attrs = {
        "cipher"                : cipher,
        "mode"                  : cipher_mode,
        "mode.options"          : MODES,
        "iv"                    : iv,
        "key_salt"              : key_salt,
        "key_hash"              : key_hash,
        "key_size"              : key_size,
        "key_stretch"           : key_stretch,
        "key_stretch.options"   : KEY_STRETCHING,
        "key_stretch_iterations": iterations,
        "padding"               : padding,
        "padding.options"       : PADDING_OPTIONS,
        }
    #v5 onwards with namespace:
    caps : Dict[str,Any] = {"encryption" : attrs}
    #add unprefixed copy for older versions:
    for k,v in attrs.items():
        caps[f"cipher.{k}"] = v
    caps["cipher"] = cipher
    return caps

def get_crypto_caps(full=True) -> Dict[str,Any]:
    crypto_backend_init()
    caps : Dict[str,Any] = {
            "padding"       : {"options"    : PADDING_OPTIONS},
            "modes"         : {"options"    : MODES},
            "stretch"       : {"options"    : KEY_STRETCHING},
            }
    if full and cryptography:
        caps["python-cryptography"] = {
                ""          : True,
                "version"   : parse_version(cryptography.__version__),
                }
    return caps


def get_encryptor(ciphername : str, iv:str, password, key_salt, key_hash : str, key_size : int, iterations : int):
    log("get_encryptor%s", (ciphername, iv, password, hexstr(key_salt), key_hash, key_size, iterations))
    if not ciphername:
        return None, 0
    assert key_size>=16
    if iterations<MIN_ITERATIONS or iterations>MAX_ITERATIONS:
        raise ValueError(f"invalid number of iterations {iterations}, range is {MIN_ITERATIONS} to {MAX_ITERATIONS}")
    assert ciphername.startswith("AES")
    assert password and iv, "password or iv missing"
    mode = (ciphername+"-").split("-")[1] or DEFAULT_MODE
    key = get_key(password, key_salt, key_hash, key_size, iterations)
    return get_cipher_encryptor(key, iv, mode), get_block_size(mode)

def get_cipher_encryptor(key, iv:str, mode:str):
    encryptor = _get_cipher(key, iv, mode).encryptor()
    encryptor.encrypt = encryptor.update
    return encryptor

def get_decryptor(ciphername : str, iv:str, password, key_salt, key_hash : str, key_size : int, iterations : int):
    log("get_decryptor%s", (ciphername, iv, password, hexstr(key_salt), key_hash, key_size, iterations))
    if not ciphername:
        return None, 0
    assert key_size>=16
    if iterations<MIN_ITERATIONS or iterations>MAX_ITERATIONS:
        raise ValueError(f"invalid number of iterations {iterations}, range is {MIN_ITERATIONS} to {MAX_ITERATIONS}")
    assert ciphername.startswith("AES")
    assert password and iv, "password or iv missing"
    mode = (ciphername+"-").split("-")[1] or DEFAULT_MODE
    key = get_key(password, key_salt, key_hash, key_size, iterations)
    return get_cipher_decryptor(key, iv, mode), get_block_size(mode)

def get_cipher_decryptor(key, iv:str, mode:str):
    decryptor = _get_cipher(key, iv, mode).decryptor()
    def i(s):
        try:
            return int(s)
        except ValueError:
            return 0
    version = cryptography.__version__      # type: ignore[union-attr]
    supports_memoryviews = tuple(i(s) for s in version.split("."))>=(2, 5)
    log("get_decryptor(..) python-cryptography supports_memoryviews(%s)=%s",
        version, supports_memoryviews)
    if supports_memoryviews:
        decryptor.decrypt = decryptor.update
    else:
        _patch_decryptor(decryptor)
    return decryptor

def _patch_decryptor(decryptor):
    #with older versions of python-cryptography,
    #we have to copy the memoryview to a bytearray:
    def decrypt(v):
        return decryptor.update(memoryview_to_bytes(v))
    decryptor.decrypt = decrypt

def get_block_size(mode:str) -> int:
    if mode=="CBC":
        #16 would also work,
        #but older versions require 32
        return 32
    return 0

def get_key(password, key_salt, key_hash, block_size:int, iterations:int):
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    if key_hash.upper() not in KEY_HASHES:
        raise ValueError(f"invalid key hash {key_hash.upper()!r}, should be one of: "+csv(KEY_HASHES))
    algorithm = getattr(hashes, key_hash.upper(), None)
    if not algorithm:
        raise ValueError(f"{key_hash.upper()!r} not found in cryptography hashes")
    try:
        #newer versions (41 for sure) require us to instantiate the "constant"
        hash_algo = algorithm()
    except TypeError:
        #older versions are OK using it directly:
        hash_algo = algorithm
    from cryptography.hazmat.backends import default_backend
    kdf = PBKDF2HMAC(algorithm=hash_algo, length=block_size,
                     salt=strtobytes(key_salt), iterations=iterations,
                     backend=default_backend())
    key = kdf.derive(strtobytes(password))
    return key

def _get_cipher(key, iv:str, mode:str=DEFAULT_MODE):
    assert mode in MODES
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    mode_class = getattr(modes, mode, None)
    if mode_class is None:
        raise ValueError(f"no {mode} mode in this version of python-cryptography")
    from cryptography.hazmat.backends import default_backend
    return Cipher(algorithms.AES(key), mode_class(strtobytes(iv)), backend=default_backend())


def main():
    from xpra.util import print_nested_dict
    from xpra.platform import program_context
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()
    with program_context("Encryption Properties"):
        crypto_backend_init()
        print_nested_dict(get_crypto_caps())

if __name__ == "__main__":
    main()
