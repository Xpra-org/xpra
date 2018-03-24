#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import json
import glob
import struct
import os.path
import binascii
import base64
from collections import OrderedDict
from hashlib import sha256

#python-cryptography to verify signatures:
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography.hazmat.backends import default_backend

from xpra.util import csv, engs
from xpra.os_util import hexstr, osexpand, load_binary_file
from xpra.net.crypto import get_salt
from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
from xpra.platform.paths import get_user_conf_dirs
assert init and log #tests will disable logging from here


PUB_KEY_DER_PREFIX = binascii.a2b_hex("3059301306072a8648ce3d020106082a8648ce3d030107034200")


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        self.app_id = kwargs.pop("app_id", "Xpra")
        key_hexstring = kwargs.pop("public_key", "")
        SysAuthenticator.__init__(self, username, **kwargs)
        self.public_keys = OrderedDict()
        key_strs = OrderedDict()
        if key_hexstring:
            log("u2f_auth: public key from configuration=%s", key_hexstring)
            key_strs["command-option"] = key_hexstring
        #try to load public keys from the user conf dir(s):
        conf_dirs = get_user_conf_dirs(self.get_uid())
        log("u2f: will try to load public keys from %s", csv(conf_dirs))
        for d in conf_dirs:
            ed = osexpand(d)
            if os.path.exists(ed) and os.path.isdir(ed):
                pub_keyfiles = glob.glob(os.path.join(ed, "u2f*-pub.hex"))
                log("u2f: keyfiles(%s)=%s", ed, pub_keyfiles)
                for f in sorted(pub_keyfiles):
                    key_hexstring = load_binary_file(f)
                    if key_hexstring:
                        key_hexstring = key_hexstring.rstrip(b" \n\r")
                        key_strs[f] = key_hexstring
                        log("u2f_auth: loaded public key from file '%s': %s", f, key_hexstring)
        for origin, key_hexstring in key_strs.items():
            try:
                key = binascii.unhexlify(key_hexstring)
            except Exception as e:
                log("unhexlify(%s)", key_hexstring, exc_info=True)
                log.warn("Warning: failed to parse key '%s'", origin)
                log.warn(" %s", e)
                continue
            log("u2f: trying to load DER public key %s", repr(key))
            if not key.startswith(PUB_KEY_DER_PREFIX):
                key = PUB_KEY_DER_PREFIX+key
            try:
                k = load_der_public_key(key, default_backend())
            except Exception as e:
                log("load_der_public_key(%r)", key, exc_info=True)
                log.warn("Warning: failed to parse key '%s'", origin)
                log.warn(" %s", e)
                continue
            self.public_keys[origin] = k
        if not self.public_keys:
            raise Exception("u2f authenticator requires at least one public key")

    def get_challenge(self, digests):
        if "u2f" not in digests:
            log.error("Error: client does not support u2f authentication")
            return None
        self.salt = get_salt()
        self.digest = "u2f:xor"
        self.challenge_sent = True
        return self.salt, self.digest

    def __repr__(self):
        return "u2f"

    def authenticate(self, challenge_response=None, client_salt=None):
        log("authenticate(%s, %s)", repr(challenge_response), repr(client_salt))
        user_presence, counter = struct.unpack(">BI", challenge_response[:5])
        sig = challenge_response[5:]
        log("u2f user_presence=%s, counter=%s, signature=%s", user_presence, counter, hexstr(sig))
        app_param = sha256(self.app_id.encode('utf8')).digest()
        server_challenge_b64 = base64.urlsafe_b64encode(self.salt).decode()
        server_challenge_b64 = server_challenge_b64.rstrip('=')
        log("challenge_b64(%s)=%s", repr(self.salt), server_challenge_b64)
        client_data = {
            "challenge" : server_challenge_b64,
            "origin"    : client_salt,
            "typ"       : "navigator.id.getAssertion",
            }
        client_param = sha256(json.dumps(client_data, sort_keys=True).encode('utf8')).digest()
        param = app_param + \
                struct.pack('>B', user_presence) + \
                struct.pack('>I', counter) + \
                client_param
        #check all the public keys:
        errors = OrderedDict()
        for origin, public_key in self.public_keys.items():
            verifier = public_key.verifier(sig, ec.ECDSA(hashes.SHA256()))
            verifier.update(param)
            try:
                verifier.verify()
                log("ECDSA SHA256 verification passed for '%s'", origin)
                return True
            except Exception as e:
                log("authenticate failed for '%s' / %s", origin, public_key, exc_info=True)
                errors[origin] = str(e) or type(e)
        log.error("Error: authentication failed,")
        log.error(" checked against %i key%s", len(self.public_keys), engs(self.public_keys))
        for origin, error in errors.items():
            log.error(" '%s': %s", origin, error)
        return False


def main(argv):
    from xpra.platform import program_context
    with program_context("U2F-Register", "U2F Registration Tool"):
        print("U2F Registration Tool")
        key_handle_filenames = [os.path.join(d, "u2f-keyhandle.hex") for d in get_user_conf_dirs()]
        assert len(key_handle_filenames)>0
        for filename in key_handle_filenames:
            p = osexpand(filename)
            key_handle_str = load_binary_file(p)
            if key_handle_str:
                print(" found an existing key handle in file '%s':" % p)
                print(" %s" % key_handle_str)
                print(" skipping registration")
                print(" delete this file if you want to register again")
                return 1
        public_key_filenames = []
        for d in get_user_conf_dirs():
            public_key_filenames += glob.glob(os.path.join(d, "u2f*.pub"))
        if public_key_filenames:
            print(" found %i existing public key%s" % (len(public_key_filenames, engs(public_key_filenames))))
            for x in public_key_filenames:
                print(" - %s" % x)

        #pick the first directory:
        conf_dir = osexpand(get_user_conf_dirs()[0])
        if not os.path.exists(conf_dir):
            os.mkdir(conf_dir)

        from pyu2f.u2f import GetLocalU2FInterface
        dev = GetLocalU2FInterface()

        print("activate your U2F device now to generate a new key")
        APP_ID = u"Xpra"
        registered_keys = []
        challenge= b'01234567890123456789012345678901'  #unused
        rr = dev.Register(APP_ID, challenge, registered_keys)
        b = rr.registration_data
        assert b[0]==5
        pubkey = bytes(b[1:66])
        khl = b[66]
        key_handle = bytes(b[67:67 + khl])

        #save to files:
        key_handle_filename = osexpand(key_handle_filenames[0])
        print("key handle=%s" % hexstr(key_handle))
        print("saving key handle to file '%s'" % key_handle_filename)
        f = open(key_handle_filename, "wb")
        f.write(hexstr(key_handle))
        f.close
        print("public key=%s" % hexstr(pubkey))
        #find a filename we can use for this public key:
        i = 1
        while True:
            c = ""
            if i>1:
                c = "-%i"
            public_key_filename = os.path.join(conf_dir, "u2f%s-pub.hex" % c)
            if not os.path.exists(public_key_filename):
                break
        print("saving public key to file '%s'" % public_key_filename)
        f = open(public_key_filename, "wb")
        f.write(hexstr(pubkey))
        f.close
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
