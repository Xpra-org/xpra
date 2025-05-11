# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any
from collections.abc import Sequence

from xpra.common import FULL_INFO
from xpra.util.env import envbool
from xpra.net.socket_util import hosts
from xpra.net.common import get_ssh_port
from xpra.scripts.config import str_to_bool
from xpra.platform.info import get_username
from xpra.server.subsystem.stub import StubServerMixin
from xpra.util.background_worker import add_work_item
from xpra.log import Logger

log = Logger("server", "mdns")


class MdnsServer(StubServerMixin):
    """
        Publishes sockets using mDNS
    """

    def __init__(self):
        self.mdns = False
        self.mdns_publishers = {}
        # relies on these attributes duplicated from ServerCore:
        self._socket_info: dict = {}
        self.display = os.environ.get("DISPLAY", "")
        # self.socket_info: dict[Any, dict] = {}
        # self.socket_options: dict[Any, dict] = {}
        # self.socket_cleanup: list[Callable] = []

    def init(self, opts) -> None:
        log("ServerCore.init(%s)", opts)
        self.mdns = opts.mdns

    def setup(self) -> None:
        if self.mdns:
            add_work_item(self.mdns_publish)

    def cleanup(self) -> None:
        self.mdns_cleanup()

    def can_upgrade(self, socktype: str, tosocktype: str, options: dict[str, str]) -> bool:
        # `ServerCore` actually implements this method properly
        return False

    def mdns_publish(self) -> None:
        if not self.mdns:
            return
        # find all the records we want to publish:
        mdns_recs: dict[str, list[tuple[str, int]]] = {}
        for sock_def, options in self._socket_info.items():
            socktype, _, info, _ = sock_def
            socktypes = self.get_mdns_socktypes(socktype, options)
            mdns_option = options.get("mdns")
            if mdns_option:
                v = str_to_bool(mdns_option, False)
                if not v:
                    log("mdns_publish() mdns(%s)=%s, skipped", info, mdns_option)
                    continue
            log("mdns_publish() info=%s, socktypes(%s)=%s", info, socktype, socktypes)
            for st in socktypes:
                if st == "socket":
                    continue
                recs = mdns_recs.setdefault(st, [])
                if socktype == "socket":
                    if st != "ssh":
                        log.error(f"Error: unexpected {st!r} socket type for {socktype}")
                        continue
                    host = "*"
                    iport = get_ssh_port()
                    if not iport:
                        continue
                else:
                    host, iport = info
                for h in hosts(host):
                    rec = (h, iport)
                    if rec not in recs:
                        recs.append(rec)
                log("mdns_publish() recs[%s]=%s", st, recs)
        if not mdns_recs:
            return
        mdns_info = self.get_mdns_info()
        self.mdns_publishers = {}
        from xpra.net.mdns.util import mdns_publish
        for mdns_mode, listen_on in mdns_recs.items():
            info = dict(mdns_info)
            info["mode"] = mdns_mode
            aps = mdns_publish(self.display, listen_on, info)
            for ap in aps:
                ap.start()
                self.mdns_publishers[ap] = mdns_mode

    def get_mdns_socktypes(self, socktype: str, options: dict[str, str]) -> Sequence[str]:
        # for a given socket type,
        # what socket types we should expose via mdns
        if socktype in ("vsock", "named-pipe"):
            # cannot be accessed remotely
            return ()
        if socktype == "quic":
            return "quic", "webtransport"
        socktypes = [socktype]
        if socktype == "tcp":
            for tosocktype in ("ssl", "ws", "wss", "ssh", "rfb", "rdp"):
                if self.can_upgrade(socktype, tosocktype, options):
                    socktypes.append(tosocktype)
        elif socktype in ("ws", "ssl") and self.can_upgrade(socktype, "wss", options):
            socktypes.append("wss")
        elif socktype == "socket" and self.ssh_upgrade and get_ssh_port() > 0:
            socktypes = ["ssh"]
        return tuple(socktypes)

    def get_mdns_info(self) -> dict[str, Any]:
        mdns_info = {
            "display": self.display,
            "username": get_username(),
            "uuid": self.uuid,
            "platform": sys.platform,
            "type": self.session_type,
        }
        MDNS_EXPOSE_NAME = envbool("XPRA_MDNS_EXPOSE_NAME", True)
        if MDNS_EXPOSE_NAME and self.session_name:
            mdns_info["name"] = self.session_name
        return mdns_info

    def mdns_cleanup(self) -> None:
        if self.mdns_publishers:
            add_work_item(self.do_mdns_cleanup)

    def do_mdns_cleanup(self) -> None:
        mp = dict(self.mdns_publishers)
        self.mdns_publishers = {}
        for ap in tuple(mp.keys()):
            ap.stop()

    def mdns_update(self) -> None:
        if not self.mdns:
            return
        txt = self.get_mdns_info()
        for mdns_publisher, mode in dict(self.mdns_publishers).items():
            info = dict(txt)
            info["mode"] = mode
            try:
                mdns_publisher.update_txt(info)
            except Exception as e:
                log("mdns_update: %s(%s)", mdns_publisher.update_txt, info, exc_info=True)
                log.warn("Warning: mdns update failed")
                log.warn(" %s", e)

    def get_info(self, proto, *_args) -> dict[str, Any]:
        authenticated = proto and proto.authenticators
        full = FULL_INFO > 0 or authenticated
        if full:
            return {"mdns": self.mdns}
        return {}
