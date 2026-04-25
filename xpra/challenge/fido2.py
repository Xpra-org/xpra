# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import json
import time
import binascii
import base64
from hashlib import sha256

from xpra.challenge.handler import AuthenticationHandler, notify
from xpra.util.env import osexpand, envint
from xpra.util.io import load_binary_file
from xpra.util.str_fn import strtobytes
from xpra.log import Logger

log = Logger("auth")

APP_ID = os.environ.get("XPRA_FIDO_APP_ID", "Xpra")
POLLING_TIME = envint("XPRA_FIDO2_POLLING_TIME", 10)


class Handler(AuthenticationHandler):

    def __init__(self, **kwargs):
        self.protocol = kwargs["protocol"]
        self.app_id = kwargs.get("app_id", "") or os.environ.get("XPRA_FIDO_APP_ID", "") or APP_ID

    def __repr__(self):
        return "fido2"

    def get_digest(self) -> str:
        return "fido2"

    def handle(self, challenge: bytes, digest: str, prompt: str) -> tuple[bytes, bytes] | None:
        if not digest.startswith("fido2:"):
            log("%s is not a fido2 challenge", digest)
            return None
        try:
            from fido2.hid import CtapHidDevice
            from fido2.ctap1 import Ctap1, ApduError, APDU
        except ImportError as e:
            log.warn("Warning: cannot use fido2 authentication handler")
            log.warn(" %s", e)
            return None
        key_handle = self.get_key_handle()
        if not key_handle:
            return None
        devices = list(CtapHidDevice.list_devices())
        if not devices:
            log.warn("Warning: no FIDO2 device found")
            return None
        origin = self.app_id
        # build client_data matching what the server reconstructs in fido2_check
        challenge_b64 = base64.urlsafe_b64encode(challenge).decode().rstrip("=")
        client_data = {
            "challenge": challenge_b64,
            "origin": origin,
            "typ": "navigator.id.getAssertion",
        }
        client_data_hash = sha256(json.dumps(client_data, sort_keys=True).encode("utf-8")).digest()
        app_param = sha256(self.app_id.encode("utf-8")).digest()
        notify("activate your FIDO2 device for authentication")
        # CTAP1/U2F devices return APDU.USE_NOT_SATISFIED until the user
        # touches the device — poll each one for up to 10 seconds.
        deadline = time.monotonic() + POLLING_TIME
        while time.monotonic() < deadline:
            for dev in devices:
                try:
                    ctap1 = Ctap1(dev)
                    # SignatureData is a bytes subclass: [user_presence 1B][counter 4B BE][sig]
                    # that layout is exactly what the server's fido2_check parses
                    response = ctap1.authenticate(client_data_hash, app_param, key_handle)
                    log("fido2 authenticate response: user_presence=%s, counter=%s",
                        response.user_presence, response.counter)
                    return bytes(response), strtobytes(origin)
                except ApduError as e:
                    if e.code == APDU.USE_NOT_SATISFIED:
                        continue
                    log("fido2 authenticate failed on %s: %s", dev, e)
                except Exception as e:
                    log("fido2 authenticate failed on %s: %s", dev, e)
            time.sleep(0.25)
        log.warn("Warning: fido2 authentication failed on all devices")
        return None

    def get_key_handle(self) -> bytes:
        key_handle_str = os.environ.get("XPRA_FIDO2_KEY_HANDLE", "")
        log("get_key_handle XPRA_FIDO2_KEY_HANDLE=%s", key_handle_str)
        if not key_handle_str:
            from xpra.platform.paths import get_user_conf_dirs
            info = self.protocol.get_info()
            key_handle_filenames = []
            for hostinfo in ("-%s" % info.get("host", ""), ""):
                for d in get_user_conf_dirs():
                    key_handle_filenames.append(os.path.join(d, f"fido2-keyhandle{hostinfo}.hex"))
            for filename in key_handle_filenames:
                p = osexpand(filename)
                data = load_binary_file(p)
                if data:
                    key_handle_str = data.rstrip(b" \n\r").decode("latin1")
                    log("key_handle_str(%s)=%s", p, key_handle_str)
                    break
            if not key_handle_str:
                log.warn("Warning: no FIDO2 key handle found")
                return b""
        return binascii.unhexlify(key_handle_str)
