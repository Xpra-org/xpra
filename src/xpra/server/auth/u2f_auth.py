#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import json
import glob
import struct
import os.path
import binascii
import base64
from collections import OrderedDict
from hashlib import sha256

from xpra.util import csv, engs
from xpra.os_util import hexstr, osexpand, load_binary_file, getuid, strtobytes, POSIX
from xpra.net.crypto import get_salt
from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
from xpra.platform.paths import get_user_conf_dirs
assert init and log #tests will disable logging from here


PUB_KEY_DER_PREFIX = binascii.a2b_hex("3059301306072a8648ce3d020106082a8648ce3d030107034200")
APP_ID = os.environ.get("XPRA_U2F_APP_ID", "Xpra")


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        self.app_id = kwargs.pop("app_id", APP_ID)
        key_hexstring = kwargs.pop("public_key", "")
        SysAuthenticator.__init__(self, username, **kwargs)
        self.public_keys = OrderedDict()
        key_strs = OrderedDict()
        if key_hexstring:
            log("u2f_auth: public key from configuration=%s", key_hexstring)
            key_strs["command-option"] = key_hexstring
        #try to load public keys from the user conf dir(s):
        if getuid()==0 and POSIX:
            #root: use the uid of the username specified:
            uid = self.get_uid()
        else:
            uid = getuid()
        conf_dirs = get_user_conf_dirs(uid)
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
        #load public keys:
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        from cryptography.hazmat.backends import default_backend
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
        user_presence, counter = struct.unpack(">BI", strtobytes(challenge_response)[:5])
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
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
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
