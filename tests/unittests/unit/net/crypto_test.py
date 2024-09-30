#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2024 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from time import monotonic
from xpra.util.str_fn import hexstr
from xpra.util.env import envbool

from xpra.net.crypto import (
    DEFAULT_SALT, DEFAULT_ITERATIONS, DEFAULT_KEYSIZE, DEFAULT_KEY_HASH, DEFAULT_IV,
    crypto_backend_init,
)

SHOW_PERF = envbool("XPRA_SHOW_PERF", False)


def log(_message) -> None:
    # print(message[:256])
    pass


def all_identical(*items: bytes) -> None:
    first = items[0]
    size = len(items)
    for i in range(size):
        assert items[i] == first


class TestCrypto(unittest.TestCase):

    def test_crypto(self) -> None:
        from xpra.net.crypto import get_modes
        for mode in get_modes():
            self.do_test_roundtrip(mode=mode)
            self.do_test_fixed_output(mode=mode)

    def do_test_fixed_output(self, mode) -> None:
        enc_data = self.do_test_roundtrip(mode=mode)[0]
        expected = {
            "CBC": "ad1e476da9b779bfb4c8743b72055fd8",
            "GCM": "dfc2744ae0dacf082c04424017b07131",
            "CFB": "78c310e4ea81652172d522d4a6388765",
            "CTR": "78c310e4ea81652172d522d4a6388765",
        }.get(mode)
        if not expected:
            print(f"warning: no fixed output test data recorded for {mode!r}")
            print(f" got {hexstr(enc_data)}")
            return
        if hexstr(enc_data) != expected:
            raise RuntimeError(f"expected encryted data {hexstr(expected)} but got {hexstr(enc_data)} for {mode!r}")

    def do_test_roundtrip(self, message=b"some message1234",
                          encrypt_count=1,
                          decrypt_count=1,
                          mode="CBC") -> list[bytes]:
        from xpra.net.crypto import get_cipher_encryptor, get_cipher_decryptor, get_key

        key_data = b"this is our secret"
        key_salt = DEFAULT_SALT
        key_hash = DEFAULT_KEY_HASH
        iterations = DEFAULT_ITERATIONS
        block_size = DEFAULT_KEYSIZE
        # test key stretching:
        args = key_data, key_salt, key_hash, block_size, iterations
        secret = get_key(*args)
        log("%s%s=%s" % (get_key, args, hexstr(secret)))
        assert secret is not None
        # test creation of encryptors and decryptors:
        iv = DEFAULT_IV
        args = secret, iv, mode
        enc = get_cipher_encryptor(*args)
        log("%s%s=%s" % (get_cipher_encryptor, args, enc))
        assert enc is not None
        dec = get_cipher_decryptor(*args)
        log("%s%s=%s" % (get_cipher_decryptor, args, dec))
        assert dec is not None
        # test encoding of a message:
        encrypted: list[bytes] = []
        for i in range(encrypt_count):
            v = enc.update(message)
            # print("%s%s=%s" % (enc.encrypt, (message,), hexstr(v)))
            assert v is not None
            if i < 10:
                encrypted.append(v)
        assert encrypted
        # test decoding of the message:
        decrypted: list[bytes] = []
        for i in range(decrypt_count):
            v = dec.update(encrypted[i % len(encrypted)])
            log("%s%s=%s" % (dec.update, (encrypted[0],), hexstr(v)))
            assert v is not None
            if i < 10:
                decrypted.append(v)
        if decrypted:
            all_identical([message] + decrypted)
        return encrypted

    def do_test_perf(self, size=1024 * 4, enc_iterations=20, dec_iterations=20) -> list[float]:
        asize = (size + 15) // 16
        times = []
        data = b"0123456789ABCDEF" * asize
        start = monotonic()
        self.do_test_roundtrip(data, enc_iterations, dec_iterations)
        end = monotonic()
        elapsed = max(0.0001, end - start)
        speed = (asize * 16) * (enc_iterations + dec_iterations) / elapsed
        iter_time = elapsed * 1000 / (enc_iterations + dec_iterations)
        print("%10iKB: %5.1fms: %16iMB/s" % (asize * 16 // 1024, iter_time, speed // 1024 // 1024))
        times.append(end - start)
        return times

    def test_perf(self) -> None:
        if not SHOW_PERF:
            return
        RANGE = (1024, 1024 * 1024)
        print("Python Cryptography:")
        print("  Encryption:")
        for i in RANGE:
            self.do_test_perf(i, 10, 0)
        print("  Decryption:")
        for i in RANGE:
            self.do_test_perf(i, 1, 10)
        print("  Overall:")
        for i in RANGE:
            self.do_test_perf(i, 10, 10)

    def setUp(self):
        assert crypto_backend_init(), "failed to initialize python-cryptography"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
