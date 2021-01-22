# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import logging
import binascii

from xpra.os_util import bytestostr, load_binary_file, osexpand
from xpra.log import Logger, is_debug_enabled

log = Logger("auth")


class Handler:

    def __init__(self, client, **_kwargs):
        self.client = client

    def __repr__(self):
        return "u2f"

    def get_digest(self) -> str:
        return "u2f"

    def handle(self, packet) -> bool:
        digest = bytestostr(packet[3])
        if not digest.startswith("u2f:"):
            log("%s is not a u2f challenge", digest)
            return False
        try:
            from pyu2f import model                     #@UnresolvedImport
            from pyu2f.u2f import GetLocalU2FInterface  #@UnresolvedImport
        except ImportError as e:
            log.warn("Warning: cannot use u2f authentication handler")
            log.warn(" %s", e)
            return False
        if not is_debug_enabled("auth"):
            logging.getLogger("pyu2f.hardware").setLevel(logging.INFO)
            logging.getLogger("pyu2f.hidtransport").setLevel(logging.INFO)
        dev = GetLocalU2FInterface()
        APP_ID = os.environ.get("XPRA_U2F_APP_ID", "Xpra")
        key_handle = self.get_key_handle()
        if not key_handle:
            return False
        key = model.RegisteredKey(key_handle)
        #use server salt as challenge directly
        challenge = packet[1]
        log.info("activate your U2F device for authentication")
        response = dev.Authenticate(APP_ID, challenge, [key])
        sig = response.signature_data
        client_data = response.client_data
        log("process_challenge_u2f client data=%s, signature=%s", client_data, binascii.hexlify(sig))
        self.client.do_send_challenge_reply(bytes(sig), client_data.origin)
        return True

    def get_key_handle(self) -> bytes:
        key_handle_str = os.environ.get("XPRA_U2F_KEY_HANDLE")
        log("process_challenge_u2f XPRA_U2F_KEY_HANDLE=%s", key_handle_str)
        if not key_handle_str:
            #try to load the key handle from the user conf dir(s):
            from xpra.platform.paths import get_user_conf_dirs
            info = self.client._protocol.get_info(False)
            key_handle_filenames = []
            for hostinfo in ("-%s" % info.get("host", ""), ""):
                for d in get_user_conf_dirs():
                    key_handle_filenames.append(os.path.join(d, "u2f-keyhandle%s.hex" % hostinfo))
            for filename in key_handle_filenames:
                p = osexpand(filename)
                key_handle_str = load_binary_file(p)
                log("key_handle_str(%s)=%s", p, key_handle_str)
                if key_handle_str:
                    key_handle_str = key_handle_str.rstrip(b" \n\r")
                    break
            if not key_handle_str:
                log.warn("Warning: no U2F key handle found")
                return None
        log("process_challenge_u2f key_handle=%s", key_handle_str)
        return binascii.unhexlify(key_handle_str)
