# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.str_fn import bytestostr
from xpra.exit_codes import ExitValue


def run_list_mdns(error_cb, extra_args) -> ExitValue:
    from xpra.scripts.common import no_gtk
    no_gtk()
    mdns_wait = 5
    if len(extra_args) <= 1:
        try:
            mdns_wait = int(extra_args[0])
        except (IndexError, ValueError):
            pass
    else:
        error_cb("too many arguments for `list-mdns` mode")
    from xpra.net.mdns import XPRA_TCP_MDNS_TYPE, XPRA_UDP_MDNS_TYPE
    try:
        from xpra.net.mdns.zeroconf_listener import ZeroconfListener
    except ImportError:
        error_cb("'list-mdns' requires python-zeroconf")
    from xpra.dbus.common import loop_init
    GLib = gi_import("GLib")
    loop_init()
    found: dict[tuple[str, str, str], list] = {}
    shown = set()

    def show_new_found() -> None:
        new_found = [x for x in found.keys() if x not in shown]
        for uq in new_found:
            recs = found[uq]
            for i, rec in enumerate(recs):
                iface, _, _, host, address, port, text = rec
                uuid = text.strget("uuid")
                display = text.strget("display")
                mode = text.strget("mode")
                username = text.strget("username")
                session = text.strget("session")
                dtype = text.strget("type")
                if i == 0:
                    print(f"* user {username!r} on {host!r}")
                    if session:
                        print(f" {dtype} session {session!r}, {uuid=!r}")
                    elif uuid:
                        print(f" {uuid=!r}")
                iinfo = ""
                if iface:
                    iinfo = f", interface {iface}"
                print(f" + {mode} endpoint on host {address}, port {port}{iinfo}")
                dstr = ""
                if display.startswith(":"):
                    dstr = display[1:]
                uri = f"{mode}://{username}@{address}:{port}/{dstr}"
                print("   \"%s\"" % uri)
            shown.add(uq)

    def mdns_add(interface, _protocol, name, _stype, domain, host, address, port, text) -> None:
        text = typedict((bytestostr(k), bytestostr(v)) for k, v in (text or {}).items())
        iface = interface
        if iface is not None:
            try:
                iface = socket.if_indextoname(interface)
            except OSError:
                pass
        username = text.strget("username")
        uq = text.strget("uuid", str(len(found))), username, host
        found.setdefault(uq, []).append((iface or "", name, domain, host, address, port, text))
        GLib.timeout_add(1000, show_new_found)

    listeners = []

    def add(service_type: str) -> None:
        listener = ZeroconfListener(service_type, mdns_add=mdns_add)
        listeners.append(listener)

        def start() -> None:
            listener.start()

        GLib.idle_add(start)

    add(XPRA_TCP_MDNS_TYPE)
    add(XPRA_UDP_MDNS_TYPE)
    print("Looking for xpra services via mdns")
    try:
        loop = GLib.MainLoop()
        GLib.timeout_add(mdns_wait * 1000, loop.quit)
        loop.run()
    finally:
        for listener in listeners:
            listener.stop()
    if not found:
        print("no services found")
    else:
        print(f"{len(found)} services found")
    return 0
