#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest
import binascii
from xpra.os_util import strtobytes
from xpra.util import envbool

from xpra.net.crypto import DEFAULT_SALT, DEFAULT_ITERATIONS, DEFAULT_BLOCKSIZE, DEFAULT_IV

SHOW_PERF = envbool("XPRA_SHOW_PERF")


def log(message):
    #print(message[:256])
    pass

def hexstr(v):
    return binascii.hexlify(strtobytes(v))


class TestCrypto(unittest.TestCase):

    def setUp(self):
        self.backends = []
        try:
            from xpra.net import pycrypto_backend
            pycrypto_backend.init()
            self.backends.append(pycrypto_backend)
        except:
            print("Warning: python-crypto backend not tested!")
        try:
            from xpra.net import pycryptography_backend
            pycryptography_backend.init()
            self.backends.append(pycryptography_backend)
        except:
            print("Warning: python-cryptography backend not tested!")
        assert len(self.backends)>0, "no backends to test!"
        if len(self.backends)<2:
            print("Only one backend we can test, cannot compare results..")

    def do_test_backend(self, backends, message=b"some message1234", encrypt_count=1, decrypt_count=1):
        def mustequ(l):
            if len(l)==0:
                return
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
            log("%s%s=%s" % (b.get_key, args, hexstr(v)))
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
        #print("init took %ims", (time.time()-start)//1000)
        #test encoding of a message:
        encrypted = []
        for i in range(encrypt_count):
            for enc in encryptors:
                v = enc.encrypt(message)
                #print("%s%s=%s" % (enc.encrypt, (message,), hexstr(v)))
                assert v is not None
                if i==0:
                    encrypted.append(v)
        mustequ(encrypted)
        #test decoding of the message:
        decrypted = []
        for i in range(decrypt_count):
            for dec in decryptors:
                v = dec.decrypt(encrypted[0])
                log("%s%s=%s" % (dec.decrypt, (encrypted[0],), hexstr(v)))
                assert v is not None
                if i==0:
                    decrypted.append(v)
        mustequ(decrypted)
        if decrypted:
            mustequ([decrypted[0], message])

    def test_backends(self):
        self.do_test_backend(self.backends)

    def do_test_perf(self, size=1024*4, enc_iterations=20, dec_iterations=20):
        asize = (size+15)//16
        print("test_perf: size: %i Bytes" % (asize*16))
        if len(self.backends)<2:
            return
        times = []
        data = b"0123456789ABCDEF"*asize
        for b in self.backends:
            start = time.time()
            self.do_test_backend([b], data, enc_iterations, dec_iterations)
            end = time.time()
            i = b.get_info()
            elapsed = end-start
            speed = (asize*16) * (enc_iterations + dec_iterations) / elapsed
            print("%-32s took %5.1fms: %16iKB/s" % (i.get("backend"), elapsed*1000/(enc_iterations + dec_iterations), speed/1024))
            times.append(end-start)
        return times

    def test_perf(self):
        if not SHOW_PERF:
            return
        #RANGE = (1, 256, 1024, 1024*1024, 1024*1024*16)
        RANGE = (1, 1024, 1024*1024)
        print("Encryption Performance:")
        for i in RANGE:
            self.do_test_perf(i, 10, 0)
        print("Decryption Performance:")
        for i in RANGE:
            self.do_test_perf(i, 1, 10)
        print("Global Performance:")
        for i in RANGE:
            self.do_test_perf(i, 10, 10)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
