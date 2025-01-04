# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.exit_codes import ExitValue
from xpra.scripts.config import XpraConfig
from xpra.gtk.dialogs.sessions_gui import SessionsGUI
from xpra.net.mdns import XPRA_TCP_MDNS_TYPE, XPRA_UDP_MDNS_TYPE, get_listener_class
from xpra.util.env import envbool
from xpra.util.str_fn import bytestostr
from xpra.os_util import gi_import
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("mdns", "util")

HIDE_IPV6 = envbool("XPRA_HIDE_IPV6", False)


class mdns_sessions(SessionsGUI):

    def __init__(self, options):
        super().__init__(options)
        listener_class = get_listener_class()
        assert listener_class
        self.listeners = []

        def add(service_type: str) -> None:
            instance = listener_class(service_type,
                                      mdns_found=None,
                                      mdns_add=self.mdns_add,
                                      mdns_remove=self.mdns_remove,
                                      mdns_update=self.mdns_update)
            log("%s%s=%s", listener_class, (service_type, None, self.mdns_add, self.mdns_remove), instance)
            self.listeners.append(instance)
            instance.start()

        add(XPRA_TCP_MDNS_TYPE)
        add(XPRA_UDP_MDNS_TYPE)

    def cleanup(self) -> None:
        for listener in self.listeners:
            listener.stop()
        super().cleanup()

    def mdns_update(self, r_name, r_type) -> None:
        log("mdns_update%s", (r_name, r_type))

    def mdns_remove(self, r_interface, r_protocol, r_name, r_stype, r_domain, r_flags) -> None:
        log("mdns_remove%s", (r_interface, r_protocol, r_name, r_stype, r_domain, r_flags))
        cmp = (r_interface, r_protocol, r_name, r_stype, r_domain)
        updated_recs = [rec for rec in self.records if rec[:5] != cmp]
        if self.records != updated_recs:
            self.records = updated_recs
            GLib.idle_add(self.populate_table)

    def mdns_add(self, interface, protocol, name, stype, domain, host, address, port, text) -> None:
        log("mdns_add%s", (interface, protocol, name, stype, domain, host, address, port, text))
        if HIDE_IPV6 and address.find(":") >= 0:
            return
        # text record may be received as byte strings...
        text_rec = {}
        if text:
            for key, value in text.items():
                text_rec[bytestostr(key)] = bytestostr(value)
        # strip service from hostname:
        # (win32 servers add it? why!?)
        if host:
            if stype and host.endswith(stype):
                host = host[:-len(stype)]
            elif stype and domain and host.endswith(stype + "." + domain):
                host = host[:-len(stype + "." + domain)]
            mode = text.get("mode")
            if mode and host.endswith(mode + "."):
                host = host[:-len(mode + ".")]
            if host.endswith(".local."):
                host = host[:-len(".local.")]
        self.records.append((interface, protocol, name, stype, domain, host, address, port, text_rec))
        GLib.idle_add(self.populate_table)


def do_main(opts: XpraConfig) -> ExitValue:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context, command_error
    from xpra.log import enable_color
    from xpra.platform.gui import init, set_default_icon
    with program_context("xpra-session-browser", "Xpra Session Browser"):
        enable_color()

        set_default_icon("mdns.png")
        init()

        if not get_listener_class():
            command_error("no mDNS support in this build")
            return 1
        mdns = opts.mdns
        if mdns:
            gui = mdns_sessions(opts)
        else:
            gui = SessionsGUI(opts)
        Gtk.main()
        return gui.exit_code


def main() -> ExitValue:
    # pylint: disable=import-outside-toplevel
    from xpra.scripts.config import make_defaults_struct
    opts = make_defaults_struct()
    return do_main(opts)


if __name__ == "__main__":
    r = main()
    sys.exit(r)
