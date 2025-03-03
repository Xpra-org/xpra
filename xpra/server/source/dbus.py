# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.util.objects import typedict

GLib = gi_import("GLib")


class DBUS_Mixin(StubSourceMixin):
    """
    Expose the ClientConnection using a dbus service
    """
    PREFIX = "dbus"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        # the DBUSSource we create is only useful if the client
        # supports one of the mixins it exposes:
        return caps.boolget("windows", False) or caps.boolget("sound", False) or caps.get("audio", False)

    def __init__(self):
        self.dbus_control = False
        self.dbus_server = None

    def init_from(self, _protocol, server) -> None:
        self.dbus_control = server.dbus_control

    def init_state(self) -> None:
        if self.dbus_control:
            # pylint: disable=import-outside-toplevel
            from xpra.server.dbus.common import dbus_exception_wrap

            def make_dbus_server():
                import os
                from xpra.server.dbus.source import DBUS_Source
                return DBUS_Source(self, os.environ.get("DISPLAY", "").lstrip(":"))

            self.dbus_server = dbus_exception_wrap(make_dbus_server, "setting up client dbus instance")

    def cleanup(self) -> None:
        ds = self.dbus_server
        if ds:
            self.dbus_server = None
            GLib.idle_add(ds.cleanup)
