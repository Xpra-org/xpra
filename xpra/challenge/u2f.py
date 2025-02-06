# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import logging
import binascii

from xpra.challenge.handler import AuthenticationHandler
from xpra.util.env import osexpand
from xpra.util.io import load_binary_file
from xpra.util.str_fn import strtobytes
from xpra.log import Logger, is_debug_enabled

log = Logger("auth")


class Handler(AuthenticationHandler):

    def __init__(self, **kwargs):
        self.protocol = kwargs["protocol"]
        self.app_id = kwargs.get("APP_ID", "") or os.environ.get("XPRA_U2F_APP_ID", "") or "Xpra"

    def __repr__(self):
        return "u2f"

    def get_digest(self) -> str:
        return "u2f"

    def handle(self, challenge: bytes, digest: str, prompt: str) -> (
            tuple[bytes, bytes] | None):  # pylint: disable=unused-argument
        if not digest.startswith("u2f:"):
            log("%s is not a u2f challenge", digest)
            return None
        try:
            # pylint: disable=import-outside-toplevel
            from pyu2f import model
            from pyu2f.u2f import GetLocalU2FInterface
        except ImportError as e:
            log.warn("Warning: cannot use u2f authentication handler")
            log.warn(" %s", e)
            return None
        if not is_debug_enabled("auth"):
            logging.getLogger("pyu2f.hardware").setLevel(logging.INFO)
            logging.getLogger("pyu2f.hidtransport").setLevel(logging.INFO)
        dev = GetLocalU2FInterface()
        key_handle = self.get_key_handle()
        if not key_handle:
            return None
        key = model.RegisteredKey(key_handle)
        # use server salt as challenge directly
        log.info("activate your U2F device for authentication")
        log.info(f"prompt: {prompt!r}")
        response = dev.Authenticate(self.app_id, challenge, [key])
        sig = response.signature_data
        client_data = response.client_data
        log("process_challenge_u2f client data=%s, signature=%s", client_data, binascii.hexlify(sig))
        return bytes(sig), strtobytes(client_data.origin)

    def get_key_handle(self) -> bytes:
        key_handle_str = os.environ.get("XPRA_U2F_KEY_HANDLE")
        log("process_challenge_u2f XPRA_U2F_KEY_HANDLE=%s", key_handle_str)
        if not key_handle_str:
            # try to load the key handle from the user conf dir(s):
            from xpra.platform.paths import get_user_conf_dirs  # pylint: disable=import-outside-toplevel
            info = self.protocol.get_info(False)
            key_handle_filenames = []
            for hostinfo in ("-%s" % info.get("host", ""), ""):
                for d in get_user_conf_dirs():
                    key_handle_filenames.append(os.path.join(d, f"u2f-keyhandle{hostinfo}.hex"))
            for filename in key_handle_filenames:
                p = osexpand(filename)
                key_handle_str = load_binary_file(p).rstrip(b" \n\r").decode("latin1")
                log("key_handle_str(%s)=%s", p, key_handle_str)
                if key_handle_str:
                    break
            if not key_handle_str:
                log.warn("Warning: no U2F key handle found")
                return b""
        key_handle = binascii.unhexlify(key_handle_str)
        log("process_challenge_u2f key_handle=%s", key_handle)
        return key_handle
