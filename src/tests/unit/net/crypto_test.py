#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest

from xpra.net.crypto import DEFAULT_SALT, DEFAULT_ITERATIONS, DEFAULT_BLOCKSIZE, DEFAULT_IV


def log(message):
    #print(message)
    pass

class TestCrypto(unittest.TestCase):

    def setUp(self):
        self.backends = []
        try:
            from xpra.net import pycrypto_backend
            self.backends.append(pycrypto_backend)
        except:
            print("Warning: python-crypto backend not tested!")
        try:
            from xpra.net import pycryptography_backend
            self.backends.append(pycryptography_backend)
        except:
            print("Warning: python-cryptography backend not tested!")
        assert len(self.backends)>0, "no backends to test!"
        if len(self.backends)<2:
            print("Only one backend we can test, cannot compare results..")

    def do_test_backend(self, backends, message="some message1234", encrypt_count=1, decrypt_count=1):
        def mustequ(l):
            v = l[0]
            for i in range(len(l)):
                assert l[i]==v

        password = "this is our secret"
        key_salt = DEFAULT_SALT
        iterations = DEFAULT_ITERATIONS
        block_size = DEFAULT_BLOCKSIZE
        #test key stretching:
        secrets = []
        for b in backends:
            log("%s:%s" % (type(b), dir(b)))
            args = password, key_salt, block_size, iterations
            v = b.get_key(*args)
            log("%s%s=%s" % (b.get_key, args, v.encode('hex')))
            assert v is not None
            secrets.append(v)
        mustequ(secrets)
        #test creation of encryptors and decryptors:
        iv = DEFAULT_IV
        encryptors = []
        decryptors = []
        for i, b in enumerate(backends):
            args = secrets[i], iv
            enc = b.get_encryptor(*args)
            log("%s%s=%s" % (b.get_encryptor, args, enc))
            assert enc is not None
            encryptors.append(enc)
            dec = b.get_decryptor(*args)
            log("%s%s=%s" % (b.get_decryptor, args, dec))
            assert dec is not None
            decryptors.append(dec)
        #test encoding of a message:
        encrypted = []
        for i in range(encrypt_count):
            for enc in encryptors:
                v = enc.encrypt(message)
                #print("%s%s=%s" % (enc.encrypt, (message,), v.encode('hex')))
                assert v is not None
                if i==0:
                    encrypted.append(v)
        mustequ(encrypted)
        #test decoding of the message:
        decrypted = []
        for i in range(decrypt_count):
            for dec in decryptors:
                v = dec.decrypt(encrypted[0])
                log("%s%s=%s" % (dec.decrypt, (encrypted[0],), v.encode('hex')))
                assert v is not None
                if i==0:
                    decrypted.append(v)
        mustequ(decrypted)
        mustequ([decrypted[0], message])

    def test_backends(self):
        self.do_test_backend(self.backends)

    def test_perf(self):
        if len(self.backends)<2:
            return
        for b in self.backends:
            start = time.time()
            self.do_test_backend([b], "0123456789ABCDEF"*1024*4, 20, 20)
            end = time.time()
            i = b.get_info()
            print("%s took %ims" % (i.get("backend"), (end-start)*1000))

def main():
    unittest.main()

if __name__ == '__main__':
    main()
