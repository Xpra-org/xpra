#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#
# Interactive test for xpra/auth/fido2.py using a real hardware FIDO/U2F key.
#
# Usage:
#   python3 tests/xpra/test_fido2_hardware.py register   # one-time: save public key
#   python3 tests/xpra/test_fido2_hardware.py auth        # verify a full auth round-trip

import sys
import json
import base64
import time
from hashlib import sha256

APP_ID = "Xpra"
TOUCH_TIMEOUT = 30   # seconds to wait for user to touch the key


def poll_until_touch(fn, *args, **kwargs):
    """Retry *fn* until the user touches the key or TOUCH_TIMEOUT is exceeded.
    U2F keys return SW_CONDITIONS_NOT_SATISFIED (0x6985) while waiting for touch.
    """
    from fido2.ctap1 import ApduError
    deadline = time.monotonic() + TOUCH_TIMEOUT
    while time.monotonic() < deadline:
        try:
            return fn(*args, **kwargs)
        except ApduError as e:
            if e.code == 0x6985:
                time.sleep(0.2)
                continue
            raise
    raise TimeoutError(f"Key not touched within {TOUCH_TIMEOUT} seconds")


def find_device():
    from fido2.hid import CtapHidDevice
    devices = list(CtapHidDevice.list_devices())
    if not devices:
        print("No FIDO/U2F HID device found — is the key plugged in?")
        sys.exit(1)
    if len(devices) > 1:
        print(f"Multiple devices found, using the first: {devices[0]}")
    dev = devices[0]
    print(f"Using device: {dev}")
    return dev


def do_register():
    """
    Perform a U2F registration and save the public key to
    ~/.xpra/fido2-hardware-pub.hex so the Authenticator can load it.
    """
    from fido2.ctap1 import Ctap1

    dev = find_device()
    ctap = Ctap1(dev)

    app_param = sha256(APP_ID.encode()).digest()
    # use a fixed client_param for registration (value doesn't matter)
    client_param = sha256(b"xpra-registration").digest()

    print(f"Touch your key to register (within {TOUCH_TIMEOUT}s)...")
    reg = poll_until_touch(ctap.register, client_param, app_param)

    # public_key is the 65-byte uncompressed EC point (0x04 || x || y)
    pub_hex = reg.public_key.hex()
    print(f"Public key ({len(reg.public_key)} bytes): {pub_hex}")
    print(f"Key handle ({len(reg.key_handle)} bytes): {reg.key_handle.hex()}")

    # save public key
    import os
    conf_dir = os.path.expanduser("~/.xpra")
    os.makedirs(conf_dir, exist_ok=True)
    pub_path = os.path.join(conf_dir, "fido2-hardware-pub.hex")
    with open(pub_path, "w") as f:
        f.write(pub_hex + "\n")
    print(f"Saved public key to {pub_path}")

    # save key handle (needed for authentication)
    kh_path = os.path.join(conf_dir, "fido2-hardware.kh")
    with open(kh_path, "wb") as f:
        f.write(reg.key_handle)
    print(f"Saved key handle to {kh_path}")


def do_auth():
    """
    Perform a full authentication round-trip using the real hardware key
    and verify it through xpra.auth.fido2.Authenticator.
    """
    import os
    from fido2.ctap1 import Ctap1

    conf_dir = os.path.expanduser("~/.xpra")
    kh_path = os.path.join(conf_dir, "fido2-hardware.kh")
    if not os.path.exists(kh_path):
        print(f"Key handle not found at {kh_path} — run 'register' first")
        sys.exit(1)
    with open(kh_path, "rb") as f:
        key_handle = f.read()

    # instantiate the server-side authenticator (loads public key from ~/.xpra/)
    from xpra.auth.fido2 import Authenticator
    auth = Authenticator(connection=None, username="testuser", app_id=APP_ID)
    print(f"Loaded public keys: {list(auth.public_keys.keys())}")

    # get the server challenge
    salt, digest = auth.get_challenge(["fido2"])
    print(f"Challenge: {salt.hex()}  digest: {digest}")

    # build the U2F client_data and its hash (client_param)
    server_b64 = base64.urlsafe_b64encode(salt).decode().rstrip("=")
    origin = "hardware-test"
    client_data = {
        "challenge": server_b64,
        "origin":    origin,
        "typ":       "navigator.id.getAssertion",
    }
    client_param = sha256(json.dumps(client_data, sort_keys=True).encode()).digest()
    app_param    = sha256(APP_ID.encode()).digest()

    # authenticate with the hardware key
    dev = find_device()
    ctap = Ctap1(dev)
    print(f"Touch your key to authenticate (within {TOUCH_TIMEOUT}s)...")
    sig_data = poll_until_touch(ctap.authenticate, client_param, app_param, key_handle)
    # sig_data bytes layout: user_presence(1) + counter(4) + ecdsa_sig
    print(f"user_presence={sig_data.user_presence}  counter={sig_data.counter}")

    # verify through the authenticator
    from xpra.util.objects import typedict
    caps = typedict({
        "challenge_response": bytes(sig_data),
        "challenge_client_salt": origin,
    })
    result = auth.fido2_check(caps)
    if result:
        print("Authentication PASSED")
    else:
        print("Authentication FAILED")
    return result


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auth"
    if cmd == "register":
        do_register()
    elif cmd == "auth":
        return 0 if do_auth() else 1
    else:
        print(f"Usage: {sys.argv[0]} register|auth")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
