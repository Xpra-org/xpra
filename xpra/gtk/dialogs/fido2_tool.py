#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import glob
import time
import os.path
from hashlib import sha256

from xpra.exit_codes import ExitCode
from xpra.util.env import osexpand, envint
from xpra.util.io import load_binary_file, use_gui_prompt
from xpra.util.str_fn import hexstr
from xpra.platform.paths import get_user_conf_dirs
from xpra.log import Logger, consume_verbose_argv

log = Logger("auth", "util")

APP_ID = os.environ.get("XPRA_FIDO_APP_ID", "Xpra")
POLLING_TIME = envint("XPRA_FIDO2_POLLING_TIME", 60)


def printmsgs(*msgs: str) -> None:
    for x in msgs:
        print(x)


def main(argv: list[str]) -> int:
    from xpra.platform import program_context
    with program_context("FIDO2-Register", "Xpra FIDO2 Registration Tool"):
        consume_verbose_argv(argv, "fido2")
        if use_gui_prompt():
            from xpra.os_util import gi_import
            Gtk = gi_import("Gtk")
            GLib = gi_import("GLib")

            def show_dialog(message_type: Gtk.MessageType, *msgs: str):
                dialog = Gtk.MessageDialog(transient_for=None, flags=0,
                                           message_type=message_type, buttons=Gtk.ButtonsType.CLOSE,
                                           text="\n".join(msgs))
                dialog.set_title("Xpra FIDO2 Registration Tool")
                dialog.run()
                dialog.destroy()
                # run the main loop long enough to destroy the dialog:
                GLib.idle_add(Gtk.main_quit)
                Gtk.main()
                return ExitCode.OK

            def error(*msgs: str) -> int:
                return show_dialog(Gtk.MessageType.ERROR, *msgs)

            def info(*msgs: str) -> int:
                return show_dialog(Gtk.MessageType.INFO, *msgs)
        else:
            print("FIDO2 Registration Tool")
            error = info = printmsgs

        key_handle_filenames = [os.path.join(d, "fido2-keyhandle.hex") for d in get_user_conf_dirs()]
        assert key_handle_filenames
        for filename in key_handle_filenames:
            p = osexpand(filename)
            data = load_binary_file(p)
            if data and data.strip():
                error(" found an existing key handle in file '%s':" % p,
                      " skipping FIDO2 registration",
                      " delete this file if you want to register again")
                return ExitCode.IO_ERROR
        public_key_filenames = []
        for d in get_user_conf_dirs():
            public_key_filenames += glob.glob(os.path.join(d, "fido2*-pub.hex"))
        if public_key_filenames:
            info(" found %i existing public keys" % len(public_key_filenames),
                 *((" - %s" % x) for x in public_key_filenames))

        # pick the first directory:
        conf_dir = osexpand(get_user_conf_dirs()[0])
        if not os.path.exists(conf_dir):
            os.mkdir(conf_dir)

        try:
            from fido2.hid import CtapHidDevice
            from fido2.ctap1 import Ctap1, ApduError, APDU
        except ImportError as e:
            error("Failed to import fido2 library:", "%s" % e)
            return ExitCode.COMPONENT_MISSING

        devices = list(CtapHidDevice.list_devices())
        if not devices:
            error("No FIDO2 HID device found")
            return ExitCode.DEVICE_NOT_FOUND

        print("Please activate your FIDO2 device now to generate a new key")
        print("(touch your security key — waiting up to 60 seconds)")

        app_param = sha256(APP_ID.encode("utf-8")).digest()
        client_data_hash = os.urandom(32)

        ctap1 = Ctap1(devices[0])
        # CTAP1/U2F devices return APDU.USE_NOT_SATISFIED (0x6985) until the
        # user touches the device — poll until that goes away or we time out.
        deadline = time.monotonic() + POLLING_TIME
        b = None
        while True:
            try:
                # RegistrationData layout: [0x05][pubkey 65B][khl 1B][key_handle khl B][cert][sig]
                b = ctap1.register(client_data_hash, app_param)
                break
            except ApduError as e:
                if e.code == APDU.USE_NOT_SATISFIED and time.monotonic() < deadline:
                    time.sleep(0.25)
                    continue
                error("Failed to register FIDO2 device:", "%s" % (str(e) or type(e)))
                return ExitCode.AUTHENTICATION_FAILED
            except Exception as e:
                error("Failed to register FIDO2 device:", "%s" % (str(e) or type(e)))
                return ExitCode.AUTHENTICATION_FAILED

        assert b[0] == 5
        pubkey = bytes(b[1:66])
        khl = b[66]
        key_handle = bytes(b[67:67 + khl])

        # save key handle:
        key_handle_filename = osexpand(key_handle_filenames[0])
        with open(key_handle_filename, "wb") as f:
            f.write(hexstr(key_handle).encode("latin1"))

        # find an unused filename for this public key:
        i = 1
        while True:
            c = "" if i == 1 else "-%i" % i
            public_key_filename = os.path.join(conf_dir, "fido2%s-pub.hex" % c)
            if not os.path.exists(public_key_filename):
                break
            i += 1
        with open(public_key_filename, "wb") as f:
            f.write(hexstr(pubkey).encode("latin1"))

        info(
            "key handle saved to file:",
            f"{key_handle_filename!r}",
            "public key saved to file:",
            f"{public_key_filename!r}",
        )
        return ExitCode.OK


if __name__ == "__main__":
    sys.exit(int(main(sys.argv)))
