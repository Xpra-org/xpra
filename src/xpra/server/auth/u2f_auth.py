#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import json
import struct
import binascii
import base64
from hashlib import sha256

#python-cryptography to verify signatures:
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography.hazmat.backends import default_backend

from xpra.os_util import hexstr
from xpra.net.crypto import get_salt
from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
assert init and log #tests will disable logging from here


PUB_KEY_DER_PREFIX = binascii.a2b_hex("3059301306072a8648ce3d020106082a8648ce3d030107034200")
#this won't work for anyone but me:
TEST_PUBLIC_KEY = "04df0a3c35cf3f4c68120e3d90a1106330b89ea80c8cb37cce25ea563692db0eec9b95792966efa699c40d9cab6017197a59288440a0ab80d818c0db2b110a29c7"


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        self.app_id = kwargs.pop("app_id", "Xpra")
        #TODO: load public key per user, from file?
        key_hexstring = kwargs.pop("public_key", TEST_PUBLIC_KEY)
        key = binascii.unhexlify(key_hexstring)
        log("u2f: trying to load DER public key %s", repr(key))
        if not key.startswith(PUB_KEY_DER_PREFIX):
            key = PUB_KEY_DER_PREFIX+key
        self.public_key = load_der_public_key(key, default_backend())
        SysAuthenticator.__init__(self, username, **kwargs)

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
        verifier = self.public_key.verifier(sig, ec.ECDSA(hashes.SHA256()))
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
        verifier.update(app_param+
                        struct.pack('>B', user_presence) +
                        struct.pack('>I', counter) +
                        client_param,
                        )
        try:
            verifier.verify()
            log("ECDSA SHA256 verification passed")
            return True
        except Exception as e:
            log("authenticate failed", exc_info=True)
            log.error("Error: authentication failed:")
            log.error(" %s", str(e) or type(e))
            return False


def main(argv):
    from xpra.platform import program_context
    with program_context("U2F-Register", "U2F Registration Tool"):
        from pyu2f.u2f import GetLocalU2FInterface
        dev = GetLocalU2FInterface()

        print("activate your U2F device to generate a new key")
        APP_ID = u"Xpra"
        registered_keys = []
        challenge= b'01234567890123456789012345678901'  #unused
        rr = dev.Register(APP_ID, challenge, registered_keys)
        b = rr.registration_data
        assert b[0]==5
        pubkey = bytes(b[1:66])
        khl = b[66]
        key_handle = bytes(b[67:67 + khl])
        print("XPRA_U2F_KEY_HANDLE=%s" % hexstr(key_handle))
        print("auth=u2f,public key=%s" % hexstr(pubkey))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
