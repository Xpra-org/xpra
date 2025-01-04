#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import json
import glob
import os.path
import binascii
import base64
from struct import pack, unpack
from hashlib import sha256
from collections.abc import Sequence

from xpra.util.objects import typedict
from xpra.util.str_fn import csv, strtobytes, hexstr
from xpra.os_util import getuid, POSIX
from xpra.util.env import osexpand
from xpra.util.io import load_binary_file
from xpra.net.digest import get_salt
from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.platform.paths import get_user_conf_dirs

PUB_KEY_DER_PREFIX = binascii.a2b_hex("3059301306072a8648ce3d020106082a8648ce3d030107034200")
APP_ID = os.environ.get("XPRA_U2F_APP_ID", "Xpra")


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        self.app_id = kwargs.pop("app_id", APP_ID)
        key_hexstring = kwargs.pop("public_key", "")
        super().__init__(**kwargs)
        self.public_keys = {}
        key_strs = {}
        if key_hexstring:
            log("u2f_auth: public key from configuration=" + key_hexstring)
            key_strs["command-option"] = key_hexstring
        # try to load public keys from the user conf dir(s):
        if getuid() == 0 and POSIX:
            # root: use the uid of the username specified:
            uid = self.get_uid()
        else:
            uid = getuid()
        conf_dirs = get_user_conf_dirs(uid)
        log("u2f: will try to load public keys from " + csv(conf_dirs))
        # load public keys:
        for d in conf_dirs:
            ed = osexpand(d)
            if os.path.exists(ed) and os.path.isdir(ed):
                pub_keyfiles = glob.glob(os.path.join(ed, "u2f*-pub.hex"))
                log(f"u2f: keyfiles({ed})={pub_keyfiles}")
                for f in sorted(pub_keyfiles):
                    key_hexstring = load_binary_file(f)
                    if key_hexstring:
                        key_hexstring = key_hexstring.rstrip(b" \n\r")
                        key_strs[f] = key_hexstring
                        log(f"u2f_auth: loaded public key from file {f!r}: {key_hexstring}")
        # parse public key data:
        # pylint: disable=import-outside-toplevel
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        from cryptography.hazmat.backends import default_backend
        for origin, key_hexstring in key_strs.items():
            try:
                key = binascii.unhexlify(key_hexstring)
            except Exception as e:
                log(f"unhexlify({key_hexstring})", exc_info=True)
                log.warn(f"Warning: failed to parse key {origin!r}")
                log.warn(f" {e}")
                continue
            log(f"u2f: trying to load DER public key {key!r}")
            if not key.startswith(PUB_KEY_DER_PREFIX):
                key = PUB_KEY_DER_PREFIX + key
            try:
                k = load_der_public_key(key, default_backend())
            except Exception as e:
                log("load_der_public_key(%r)", key, exc_info=True)
                log.warn(f"Warning: failed to parse key {origin!r}")
                log.warn(f" {e}")
                continue
            self.public_keys[origin] = k
        if not self.public_keys:
            raise RuntimeError("u2f authenticator requires at least one public key")
        self.authenticate_check = self.u2f_check

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        if "u2f" not in digests:
            log.error("Error: client does not support u2f authentication")
            return b"", ""
        self.salt = get_salt()
        self.digest = "u2f:xor"
        self.challenge_sent = True
        return self.salt, self.digest

    def __repr__(self):
        return "u2f"

    def u2f_check(self, caps: typedict) -> bool:
        challenge_response = caps.strget("challenge_response")
        client_salt = caps.strget("challenge_client_salt")
        log(f"authenticate_check: response={challenge_response}, client-salt={client_salt}")
        user_presence, counter = unpack(b">BI", strtobytes(challenge_response)[:5])
        sig = strtobytes(challenge_response[5:])
        log(f"u2f user_presence={user_presence}, counter={counter}, signature={hexstr(sig)}")
        app_param = sha256(self.app_id.encode('utf8')).digest()
        server_challenge_b64 = base64.urlsafe_b64encode(self.salt).decode()
        server_challenge_b64 = server_challenge_b64.rstrip('=')
        log("challenge_b64(%s)=%s", repr(self.salt), server_challenge_b64)
        client_data = {
            "challenge": server_challenge_b64,
            "origin": client_salt,
            "typ": "navigator.id.getAssertion",
        }
        client_param = sha256(json.dumps(client_data, sort_keys=True).encode('utf8')).digest()
        param = app_param + pack(b'>B', user_presence) + pack(b'>I', counter) + client_param
        # check all the public keys:
        # pylint: disable=import-outside-toplevel
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        errors = {}
        for origin, public_key in self.public_keys.items():
            try:
                public_key.verify(sig, param, ec.ECDSA(hashes.SHA256()))
                log(f"ECDSA SHA256 verification passed for {origin!r}")
                return True
            except Exception as e:
                log(f"authenticate failed for {origin!r} / {public_key}", exc_info=True)
                errors[origin] = str(e) or type(e)
        log.error("Error: authentication failed,")
        log.error(f" checked against {len(self.public_keys)} keys")
        for origin, error in errors.items():
            log.error(f" {origin!r}: {error}")
        return False
