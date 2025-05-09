# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.common import ConnectionMessage
from xpra.net.common import Packet
from xpra.server.runner.factory import get_server_base_classes
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server", "exec")

SERVER_BASES = get_server_base_classes()
ServerBaseClass = type("ServerBaseClass", SERVER_BASES, {})
log("ServerBaseClass%s", SERVER_BASES)


class RunnerServer(ServerBaseClass):

    def __init__(self):
        log("RunnerServer.__init__()")
        for bc in SERVER_BASES:
            bc.__init__(self)
        self.session_type = "runner"

    def __repr__(self):
        return "RunnerServer"

    def init(self, opts) -> None:
        for bc in SERVER_BASES:
            bc.init(self, opts)

    def cleanup(self) -> None:
        for bc in SERVER_BASES:
            bc.cleanup(self)

    def do_handle_hello_request(self, request: str, proto, caps: typedict) -> bool:
        if request == "command":
            # TBD:
            proto.send_now(Packet("hello", {"command": True}))
            # client is meant to close the connection itself, but just in case:
            GLib.timeout_add(5 * 1000, self.send_disconnect, proto, ConnectionMessage.DONE, "command started")
            return True
        return super().do_handle_hello_request(request, proto, caps)
