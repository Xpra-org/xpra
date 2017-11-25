# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.gtk_common.gobject_compat import import_gtk, import_glib
gtk = import_gtk()
glib = import_glib()
glib.threads_init()

from xpra.client.gtk_base.sessions_gui import SessionsGUI
from xpra.gtk_common.gtk_util import gtk_main
from xpra.net.mdns import XPRA_MDNS_TYPE, get_listener_class
from xpra.util import envbool
from xpra.log import Logger
log = Logger("mdns", "util")


HIDE_IPV6 = envbool("XPRA_HIDE_IPV6", False)


class mdns_sessions(SessionsGUI):

    def __init__(self, options):
        SessionsGUI.__init__(self, options)
        listener_class = get_listener_class()
        assert listener_class
        self.listener = listener_class(XPRA_MDNS_TYPE, mdns_found=None, mdns_add=self.mdns_add, mdns_remove=self.mdns_remove)
        log("%s%s=%s", listener_class, (XPRA_MDNS_TYPE, None, self.mdns_add, self.mdns_remove), self.listener)
        self.listener.start()


    def mdns_remove(self, r_interface, r_protocol, r_name, r_stype, r_domain, r_flags):
        log("mdns_remove%s", (r_interface, r_protocol, r_name, r_stype, r_domain, r_flags))
        old_recs = self.records
        self.records = [(interface, protocol, name, stype, domain, host, address, port, text) for
                        (interface, protocol, name, stype, domain, host, address, port, text) in self.records
                        if (interface!=r_interface or protocol!=r_protocol or name!=r_name or stype!=r_stype or domain!=r_domain)]
        if old_recs!=self.records:
            glib.idle_add(self.populate_table)

    def mdns_add(self, interface, protocol, name, stype, domain, host, address, port, text):
        log("mdns_add%s", (interface, protocol, name, stype, domain, host, address, port, text))
        if HIDE_IPV6 and address.find(":")>=0:
            return
        text = text or {}
        self.records.append((interface, protocol, name, stype, domain, host, address, port, text))
        glib.idle_add(self.populate_table)


def do_main(opts):
    from xpra.platform import program_context, command_error
    from xpra.log import enable_color
    with program_context("Xpra-Session-Browser", "Xpra Session Browser"):
        enable_color()
        if not get_listener_class():
            command_error("no mDNS support in this build")
            return 1
        gui = mdns_sessions(opts)
        gtk_main()
        return gui.exit_code

def main():
    from xpra.scripts.config import make_defaults_struct
    opts = make_defaults_struct()
    return do_main(opts)


if __name__ == "__main__":
    r = main()
    sys.exit(r)
