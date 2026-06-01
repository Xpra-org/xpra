# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket

from xpra.os_util import gi_import
from xpra.net.session_discovery import (
    SessionEndpoint,
    endpoint_uri,
    group_session_endpoints,
    mdns_txt_to_dict,
    normalize_mdns_host,
)
from xpra.exit_codes import ExitValue
from xpra.exit_codes import ExitCode
from xpra.scripts.config import InitExit


def run_list_mdns(extra_args) -> ExitValue:
    from xpra.scripts.common import no_gtk
    no_gtk()
    mdns_wait = 5
    if len(extra_args) <= 1:
        try:
            mdns_wait = int(extra_args[0])
        except (IndexError, ValueError):
            pass
    else:
        raise InitExit(ExitCode.ARGUMENT_MISMATCH, "too many arguments for `list-mdns` mode")
    from xpra.net.mdns import XPRA_TCP_MDNS_TYPE, XPRA_UDP_MDNS_TYPE
    try:
        from xpra.net.mdns.zeroconf_listener import ZeroconfListener
    except ImportError:
        raise InitExit(ExitCode.COMPONENT_MISSING, "'list-mdns' requires python-zeroconf") from None
    from xpra.dbus.common import loop_init
    GLib = gi_import("GLib")
    loop_init()
    endpoints: list[SessionEndpoint] = []
    shown = set()

    def show_new_found() -> None:
        groups = group_session_endpoints(endpoints)
        new_found = [x for x in groups if x not in shown]
        for key in new_found:
            group = groups[key]
            for i, endpoint in enumerate(group.endpoints):
                uuid = endpoint.uuid
                mode = endpoint.mode
                username = endpoint.username
                if i == 0:
                    print(f"* user {username!r} on {group.host!r}")
                    if group.session_name:
                        print(f" {group.session_type} session {group.session_name!r}, {uuid=!r}")
                    elif uuid:
                        print(f" {uuid=!r}")
                iinfo = ""
                if endpoint.interface:
                    iinfo = f", interface {endpoint.interface}"
                print(f" + {mode} endpoint on host {endpoint.address}, port {endpoint.port}{iinfo}")
                uri = endpoint_uri("", endpoint)
                print("   \"%s\"" % uri)
            shown.add(key)

    def mdns_add(interface, protocol, name, stype, domain, host, address, port, text) -> None:
        text_rec = mdns_txt_to_dict(text)
        iface = interface
        if iface is not None:
            try:
                iface = socket.if_indextoname(interface)
            except OSError:
                pass
        host = normalize_mdns_host(host, stype, domain, text_rec.get("mode", ""))
        endpoints.append(SessionEndpoint(
            source="mdns",
            interface=iface or "",
            protocol=protocol,
            name=name,
            stype=stype,
            domain=domain,
            host=host,
            address=address,
            port=port,
            text=text_rec,
        ))
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
    groups = group_session_endpoints(endpoints)
    if not groups:
        print("no services found")
    else:
        print(f"{len(groups)} services found")
    return 0
