# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from gi.repository import GLib, Gtk

from xpra.client.gtk_base.sessions_gui import SessionsGUI
from xpra.net.mdns import XPRA_MDNS_TYPE, get_listener_class
from xpra.util import envbool
from xpra.log import Logger

log = Logger("mdns", "util")

HIDE_IPV6 = envbool("XPRA_HIDE_IPV6", False)


class mdns_sessions(SessionsGUI):

    def __init__(self, options):
        super().__init__(options)
        listener_class = get_listener_class()
        assert listener_class
        self.listener = listener_class(XPRA_MDNS_TYPE,
                                       mdns_found=None,
                                       mdns_add=self.mdns_add,
                                       mdns_remove=self.mdns_remove,
                                       mdns_update=self.mdns_update)
        log("%s%s=%s", listener_class, (XPRA_MDNS_TYPE, None, self.mdns_add, self.mdns_remove), self.listener)
        self.listener.start()


    def cleanup(self):
        self.listener.stop()
        super().cleanup()

    def mdns_update(self, r_name, r_type):
        log("mdns_update%s", (r_name, r_type))

    def mdns_remove(self, r_interface, r_protocol, r_name, r_stype, r_domain, r_flags):
        log("mdns_remove%s", (r_interface, r_protocol, r_name, r_stype, r_domain, r_flags))
        old_recs = self.records
        self.records = [(interface, protocol, name, stype, domain, host, address, port, text) for
                        (interface, protocol, name, stype, domain, host, address, port, text) in self.records
                        if (interface!=r_interface or
                            protocol!=r_protocol or
                            name!=r_name or
                            stype!=r_stype or
                            domain!=r_domain)]
        if old_recs!=self.records:
            GLib.idle_add(self.populate_table)

    def mdns_add(self, interface, protocol, name, stype, domain, host, address, port, text):
        log("mdns_add%s", (interface, protocol, name, stype, domain, host, address, port, text))
        if HIDE_IPV6 and address.find(":")>=0:
            return
        text = text or {}
        #strip service from hostname:
        #(win32 servers add it? why!?)
        if host:
            if stype and host.endswith(stype):
                host = host[:-len(stype)]
            elif stype and domain and host.endswith(stype+"."+domain):
                host = host[:-len(stype+"."+domain)]
            if text:
                mode = text.get("mode")
                if mode and host.endswith(mode+"."):
                    host = host[:-len(mode+".")]
            if host.endswith(".local."):
                host = host[:-len(".local.")]
        self.records.append((interface, protocol, name, stype, domain, host, address, port, text))
        GLib.idle_add(self.populate_table)


def do_main(opts):
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

def main():
    from xpra.scripts.config import make_defaults_struct
    opts = make_defaults_struct()
    return do_main(opts)


if __name__ == "__main__":
    r = main()
    sys.exit(r)
