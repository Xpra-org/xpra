# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
from typing import Final

from xpra.util.str_fn import std, single_line, truncate
from xpra.util.env import envint
from xpra.log import Logger

metalog = Logger("metadata")

# the window title and icon title we accept from the server:
MAX_TITLE = envint("XPRA_MAX_WINDOW_TITLE", 512)

UNKNOWN_MACHINE: Final[str] = "<unknown machine>"


def validhostname(value):
    if value in (
            "localhost",
            "localhost.localdomain",
            "",
            None,
    ):
        return None
    return value


def window_title_str(value) -> str:
    # bidi controls could hide or reverse the parts of the title that do not come from the server,
    # ie: the default title is "@title@ on @hostinfo@"
    return truncate(single_line(str(value)), MAX_TITLE)


def do_get_window_title(client, wid: int, metadata: dict) -> str:
    title = client.title.replace("\0", "")
    if title.find("@") < 0:
        return title
    # perform metadata variable substitutions:
    remote_info = client.get_subsystem("remote-info")
    display_info = client.get_subsystem("display")
    mmap_info = client.get_subsystem("mmap")
    remote_hostname = remote_info._remote_hostname if remote_info else None
    remote_display = remote_info._remote_display if remote_info else None
    if remote_display:
        # ie: "1\\WinSta0\\Default" -> 1-WinSta0-Default
        remote_display = remote_display.replace("\\", "-")
    default_values: dict[str, str] = {
        "title": "<untitled window>",
        "client-machine": UNKNOWN_MACHINE,
        "windowid": str(wid),
        "server-machine": std(remote_hostname) or UNKNOWN_MACHINE,
        "server-display": std(remote_display) or "<unknown display>",
    }
    metalog(f"default values: {default_values}")

    def getvar(var) -> str:
        # "hostname" is magic:
        # we try harder to find a useful value to show:
        if var in ("hostname", "hostinfo"):
            server_display = display_info.server_display if display_info else None
            mmap_read_area = mmap_info.mmap_read_area if mmap_info else None
            mmap_enabled = bool(mmap_read_area and mmap_read_area.enabled)
            if var == "hostinfo" and mmap_enabled and server_display:
                # this is a local connection for sure and we can specify the display directly:
                return server_display
            import socket
            local_hostname = validhostname(socket.gethostname())
            # try to find the hostname:
            proto = getattr(client, "_protocol", None)
            target = None
            if proto:
                conn = getattr(proto, "_conn", None)
                if conn:
                    hostname = conn.info.get("host")
                    target = str(conn.target)
                    if hostname:
                        if local_hostname == hostname and server_display:
                            return server_display
                        return hostname
            for m in ("client-machine", "server-machine"):
                value = validhostname(getvar(m))
                if value and value != local_hostname:
                    return value
            if server_display:
                return server_display
            if target:
                return target
            return UNKNOWN_MACHINE
        value = metadata.get(var)
        if value is None:
            return default_values.get(var, "<unknown %s>" % var)
        return window_title_str(value)

    def metadata_replace(match) -> str:
        atvar = match.group(0)  # ie: '@title@'
        var = atvar[1:len(atvar) - 1]  # ie: 'title'
        if not var:
            # atvar = "@@"
            return "@"
        return getvar(var)

    sub = r"@[\w\-]*@"
    replaced = re.sub(sub, metadata_replace, title)
    metalog("re.sub%s=%s", (sub, metadata_replace, title), replaced)
    return replaced
