# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import secrets
from struct import pack
from typing import Any
from collections.abc import Iterable, Sequence

from xpra.util.str_fn import csv, print_nested_dict, strtobytes, hexstr
from xpra.util.env import envint, envbool
from xpra.util.version import parse_version
from xpra.net.digest import get_salt
from xpra.log import Logger, consume_verbose_argv

log = Logger("network", "crypto")

cryptography = None

ENCRYPT_FIRST_PACKET = envbool("XPRA_ENCRYPT_FIRST_PACKET", False)

DEFAULT_IV = os.environ.get("XPRA_CRYPTO_DEFAULT_IV", "0000000000000000")
DEFAULT_SALT = os.environ.get("XPRA_CRYPTO_DEFAULT_SALT", "0000000000000000").encode("latin1")
DEFAULT_ITERATIONS = envint("XPRA_CRYPTO_DEFAULT_ITERATIONS", 10000)
DEFAULT_KEYSIZE = envint("XPRA_CRYPTO_KEYSIZE", 32)
if DEFAULT_KEYSIZE not in (16, 24, 32):
    log.warn("Warning: default key size %i (%i bits) is not supported",
             DEFAULT_KEYSIZE, DEFAULT_KEYSIZE * 8)
# these were made configurable in xpra 4.3:
MIN_ITERATIONS = envint("XPRA_CRYPTO_STRETCH_MIN_ITERATIONS", 1000)
MAX_ITERATIONS = envint("XPRA_CRYPTO_STRETCH_MIN_ITERATIONS", 1000000)
DEFAULT_MODE = os.environ.get("XPRA_CRYPTO_MODE", "CBC")
DEFAULT_KEY_HASH = os.environ.get("XPRA_CRYPTO_KEY_HASH", "SHA1")
DEFAULT_ALWAYS_PAD = envbool("XPRA_CRYPTO_ALWAYS_PAD", False)
DEFAULT_STREAM = envbool("XPRA_CRYPTO_STREAM", True)
DEFAULT_KEY_STRETCH = "PBKDF2"

PADDING_PKCS7 = "PKCS#7"
ALL_PADDING_OPTIONS = (PADDING_PKCS7, )
INITIAL_PADDING = os.environ.get("XPRA_CRYPTO_INITIAL_PADDING", PADDING_PKCS7)
DEFAULT_PADDING = PADDING_PKCS7
PREFERRED_PADDING = os.environ.get("XPRA_CRYPTO_PREFERRED_PADDING", PADDING_PKCS7)
if PREFERRED_PADDING not in ALL_PADDING_OPTIONS:
    raise ValueError(f"invalid preferred padding: {PREFERRED_PADDING}")
if INITIAL_PADDING not in ALL_PADDING_OPTIONS:
    raise ValueError(f"invalid padding: {INITIAL_PADDING}")


# make sure the preferred one is first in the list:


def get_padding_options() -> Sequence[str]:
    options = [PREFERRED_PADDING]
    for x in ALL_PADDING_OPTIONS:
        if x not in options:
            options.append(x)
    return tuple(options)


PADDING_OPTIONS: Sequence[str] = get_padding_options()

# pylint: disable=import-outside-toplevel
CIPHERS: Sequence[str] = ()
MODES: Sequence[str] = ()
KEY_HASHES: Sequence[str] = ()
KEY_STRETCHING: Sequence[str] = ()


def crypto_backend_init():
    global cryptography, CIPHERS, MODES, KEY_HASHES, KEY_STRETCHING
    if cryptography:
        log("cryptography %s found in %s", cryptography.__version__, cryptography)
        return cryptography
    try:
        import cryptography as pc
        cryptography = pc
        MODES = tuple(x for x in os.environ.get(
            "XPRA_CRYPTO_MODES",
            "CBC,CFB,CTR").split(",") if x in ("CBC", "CFB", "CTR"))
        KEY_HASHES = ("SHA1", "SHA224", "SHA256", "SHA384", "SHA512")
        KEY_STRETCHING = ("PBKDF2",)
        CIPHERS = ("AES",)
        from cryptography.hazmat.backends import default_backend
        backend = default_backend()
        log("default_backend()=%s", backend)
        log("backends=%s", getattr(backend, "_backends", []))
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import hashes
        assert Cipher and algorithms and modes and hashes  # type: ignore[truthy-function]
        validate_backend()
        name = getattr(backend, "name", "")
        if name:
            log.info(f"cryptography {cryptography.__version__} using {name!r} backend")
        return cryptography
    except ImportError:
        log("crypto backend init failure", exc_info=True)
        log.error("Error: cannot import python-cryptography")
    except Exception:
        log.error("Error: cannot initialize python-cryptography", exc_info=True)
    cryptography = None
    CIPHERS = MODES = KEY_HASHES = KEY_STRETCHING = ()
    return None


def get_ciphers() -> Sequence[str]:
    return CIPHERS


def get_modes() -> Sequence[str]:
    return MODES


def get_key_hashes() -> Sequence[str]:
    return KEY_HASHES


def validate_backend() -> None:
    log("validate_backend() will validate AES modes: " + csv(MODES))
    message = b"some message1234" * 8
    key_data = b"this is our secret"
    key_salt = DEFAULT_SALT
    iterations = DEFAULT_ITERATIONS
    for mode in MODES:
        log("testing AES-%s", mode)
        key = None
        for key_hash in KEY_HASHES:
            key = get_key(key_data, key_salt, key_hash, DEFAULT_KEYSIZE, iterations)
            assert key
        block_size = get_block_size(mode)
        log(" key=%s, block_size=%s", hexstr(key), block_size)
        assert key is not None, "pycryptography failed to generate a key"
        iv = strtobytes(DEFAULT_IV)
        enc_cipher = get_cipher(key, iv, mode)
        log(" encryptor cipher=%s", enc_cipher)
        assert enc_cipher is not None, "pycryptography failed to generate an encryptor"
        dec_cipher = get_cipher(key, iv, mode)
        log(" decryptor cipher=%s", dec_cipher)
        assert dec_cipher is not None, "pycryptography failed to generate a decryptor"
        test_messages = [message * (1 + block_size)]
        if block_size == 0:
            test_messages.append(message[:29])
        else:
            test_messages.append(message[:block_size])
        try:
            for m in test_messages:
                enc = enc_cipher.encryptor()
                ev = enc.update(m) + enc.finalize()
                evs = hexstr(ev)
                log(" encrypted(%s)=%s", m, evs)
                dec = dec_cipher.decryptor()
                dv = dec.update(ev) + dec.finalize()
                log(" decrypted(%s)=%s", evs, dv)
                if dv != m:
                    raise RuntimeError(f"expected {m!r} but got {dv!r}")
                log(" test passed")
        except ValueError:
            print(f"test error on {mode=}")
            raise


def pad(padding: str, size: int) -> bytes:
    if padding != PADDING_PKCS7:
        raise ValueError(f"invalid padding: {padding!r}")
    return pack("B", size) * size


def choose_padding(options: Iterable[str]) -> str:
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


def new_cipher_caps(proto, cipher: str, cipher_mode: str, encryption_key,
                    padding_options, always_pad: bool, stream: bool) -> dict[str, Any]:
    iv = get_iv()
    key_salt = get_salt()
    key_size = DEFAULT_KEYSIZE
    key_hash = DEFAULT_KEY_HASH
    key_stretch = DEFAULT_KEY_STRETCH
    iterations = get_iterations()
    padding = choose_padding(padding_options)
    proto.set_cipher_in(cipher + "-" + cipher_mode, strtobytes(iv),
                        encryption_key, key_salt, key_hash, key_size,
                        iterations, padding, always_pad, stream)
    return {
        "cipher": cipher,
        "mode": cipher_mode,
        "mode.options": MODES,
        "iv": iv,
        "key_salt": key_salt,
        "key_hash": key_hash,
        "key_size": key_size,
        "key_stretch": key_stretch,
        "key_stretch.options": KEY_STRETCHING,
        "key_stretch_iterations": iterations,
        "stream": stream,
        "padding": padding,
        "padding.options": PADDING_OPTIONS,
    }


def get_crypto_caps(full=True) -> dict[str, Any]:
    crypto_backend_init()
    caps: dict[str, Any] = {
        "padding": {"options": PADDING_OPTIONS},
        "modes": {"options": MODES},
        "stretch": {"options": KEY_STRETCHING},
    }
    if full and cryptography:
        caps["python-cryptography"] = {
            "": True,
            "version": parse_version(cryptography.__version__),
        }
    return caps


def get_mode(ciphername: str) -> str:
    mode = (ciphername + "-").split("-")[1] or DEFAULT_MODE
    if not ciphername.startswith("AES"):
        raise ValueError(f"unsupported cipher {ciphername!r}")
    if mode not in MODES:
        raise ValueError(f"unsupported AES mode {mode!r}")
    return mode


def get_cipher(key: bytes, iv: bytes, mode: str = DEFAULT_MODE):
    if not iv:
        raise ValueError("missing encryption iv")
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    mode_class = getattr(modes, mode, None)
    if mode_class is None:
        raise ValueError(f"no {mode} mode in this version of python-cryptography")
    from cryptography.hazmat.backends import default_backend
    return Cipher(algorithms.AES(key), mode_class(iv), backend=default_backend())


def get_block_size(mode: str) -> int:
    if mode == "CBC":
        # older versions require 32
        return 16
    return 0


def get_key(key_data: bytes, key_salt: bytes, key_hash: str, key_size: int, iterations: int) -> bytes:
    assert key_size >= 16
    if iterations < MIN_ITERATIONS or iterations > MAX_ITERATIONS:
        raise ValueError(f"invalid number of iterations {iterations}, range is {MIN_ITERATIONS} to {MAX_ITERATIONS}")
    if not key_data:
        raise ValueError("missing encryption key data")
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    if key_hash.upper() not in KEY_HASHES:
        raise ValueError(f"invalid key hash {key_hash.upper()!r}, should be one of: " + csv(KEY_HASHES))
    algorithm = getattr(hashes, key_hash.upper(), None)
    if not algorithm:
        raise ValueError(f"{key_hash.upper()!r} not found in cryptography hashes")
    hash_algo = algorithm()
    from cryptography.hazmat.backends import default_backend
    kdf = PBKDF2HMAC(algorithm=hash_algo, length=key_size,
                     salt=strtobytes(key_salt), iterations=iterations,
                     backend=default_backend())
    key = kdf.derive(key_data)
    return key


def main():
    from xpra.platform import program_context
    with program_context("Encryption Properties"):
        consume_verbose_argv(sys.argv, "crypto")
        crypto_backend_init()
        print_nested_dict(get_crypto_caps())


if __name__ == "__main__":
    main()
