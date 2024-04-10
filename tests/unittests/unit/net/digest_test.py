#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=line-too-long

import unittest

from xpra.net.digest import (
    get_digests, get_digest_module,
    choose_digest, gendigest, verify_digest,
    get_salt,
)


class TestDigest(unittest.TestCase):

    def test_invalid_digest(self):
        for invalid_digest in (None, "foo", "hmac", "hmac+INVALID_HASH_ALGO"):
            try:
                assert get_digest_module(invalid_digest) is None
            except TypeError:
                pass
            try:
                assert not gendigest(invalid_digest, "bar", b"0"*16)
            except TypeError:
                pass

    # noinspection PyTypeChecker
    def test_all_digests(self):
        for digest in get_digests():
            if digest.startswith("hmac"):
                m = get_digest_module(digest)
                assert m is not None, "digest module not found for '%s'" % digest
            salt = get_salt(32)
            password = "secret"
            d = gendigest(digest, password, salt)
            assert d is not None

            def nvd(password=password, salt=salt, response=d):
                try:
                    r = verify_digest(digest, password, salt, response)
                    assert not r
                except TypeError:
                    pass
            nvd(password=None)
            nvd(salt=None)
            nvd(response=None)
            # truncated:
            nvd(password=password[1:])
            nvd(salt=salt[1:])
            nvd(response=d[1:])
            assert verify_digest(digest, password, salt, d)

    def test_choose_digest(self):
        for h in ("hmac+sha512", "hmac+sha384", "hmac+sha256", "hmac+sha224",
                  "xor", "des"):
            assert choose_digest((h,))==h
            assert choose_digest((h, "hmac+sha512"))=="hmac+sha512"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
