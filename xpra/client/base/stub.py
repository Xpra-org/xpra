# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Any, NoReturn

from xpra.util.objects import typedict
from xpra.exit_codes import ExitValue
from xpra.net.compression import Compressed
from xpra.net.common import ClientPacketHandlerType, PacketElement


class StubClientMixin:
    __signals__: list[str] = []

    def init(self, opts) -> None:
        """
        Initialize this instance with the options given.
        Options are usually obtained by parsing the command line,
        or using a default configuration object.
        """

    def init_ui(self, opts) -> None:
        """
        Initialize the user interface,
        creating windows and widgets if needed.
        """

    def run(self) -> ExitValue:
        """
        run the main loop.
        """

    def quit(self, exit_code: ExitValue) -> NoReturn:  # pragma: no cover
        """
        Terminate the client with the given exit code.
        (the exit code is ignored if we already have one)
        """
        self.exit_code = exit_code
        sys.exit(exit_code)

    def cleanup(self) -> None:
        """
        Free up any resources.
        """

    def send(self, *_args) -> None:
        """
        Send a packet to the server, dummy implementation.
        """

    def send_now(self, packet_type: str, *parts: PacketElement) -> None:
        """
        Send a packet to the server,
        this takes precedence over packets sent via send().
        """

    def emit(self, *_args, **_kwargs) -> None:
        """
        Emit a signal, dummy implementation overridden by gobject.
        """

    def setup_connection(self, _conn) -> None:
        """
        Prepare to run using this connection to the server.
        """

    def get_caps(self) -> dict[str, Any]:
        """
        Return the capabilities provided by this mixin.
        """
        return {}

    def get_info(self) -> dict[str, Any]:
        """
        Information contained in this mixin
        """
        return {}

    def parse_server_capabilities(self, c: typedict) -> bool:  # pylint: disable=unused-argument
        """
        Parse server attributes specified in the hello capabilities.
        This runs in a non-UI thread.
        """
        return True

    def process_ui_capabilities(self, caps: typedict) -> None:
        """
        Parse server attributes specified in the hello capabilities.
        This runs in the UI thread.
        """

    def startup_complete(self) -> None:
        """
        The client and server have exchanged hello packets,
        and now the server has announced "startup-complete".
        """

    # noinspection PyMethodMayBeStatic
    def compressed_wrapper(self, datatype, data, level=5, **_kwargs) -> Compressed:
        """
        Dummy utility method for compressing data.
        Actual client implementations will provide compression
        based on the client and server capabilities (ie: lz4, brotli).
        subclasses should override this method.
        """
        assert level >= 0
        return Compressed("raw %s" % datatype, data)

    def init_packet_handlers(self) -> None:
        """
        Register the packet types that this mixin can handle, even before authentication.
        """

    def init_authenticated_packet_handlers(self) -> None:
        """
        Register the packet types that this mixin can handle after authentication.
        """

    def add_packet_handler(self, packet_type: str, handler: ClientPacketHandlerType,
                           main_thread=True) -> None:  # pragma: no cover
        raise NotImplementedError()

    def add_packet_handlers(self, defs: dict[str, ClientPacketHandlerType], main_thread=True) -> None:  # pragma: no cover
        raise NotImplementedError()

    def show_progress(self, pct, text="") -> None:
        """
        The GTK client may use the splash screen here
        """

    def suspend(self) -> None:
        """
        The client is going to suspend, take appropriate measures for this subsystem
        """

    def resume(self) -> None:
        """
        The client is going to resume
        """

    def pause(self) -> None:
        """
        Updates should be temporarily reduced
        """

    def unpause(self) -> None:
        """
        Updates can proceed at the normal rate
        """
