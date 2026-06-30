# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Any, NoReturn

from xpra.util.env import envbool
from xpra.util.objects import typedict
from xpra.exit_codes import ExitValue
from xpra.net.compression import Compressed
from xpra.net.common import ClientPacketHandlerType, PacketElement

# when running the unit tests,
# we inject the signal emitter into the signal hierarchy,
# whereas regular client classes inherit the signal methods from GObjectClientAdapter
if envbool("XPRA_UNIT_TEST"):
    from xpra.util.signal_emitter import SignalEmitter
    from xpra.util.glib_scheduler import GLibScheduler
    superclass = type("StubSignalScheduler", (SignalEmitter, GLibScheduler), {})
else:
    superclass = object


class StubClientMixin(superclass):
    __signals__: list[str] = []
    # every concrete subsystem should declare a non-empty PREFIX,
    # used as the key in `client.subsystems`:
    PREFIX: str = ""

    @property
    def client(self):
        # while subsystems are still mixed into a single client object,
        # `self.client` is the client itself.
        # Phase 2 (composition) will set `_client` to the owning client instance.
        return getattr(self, "_client", None) or self

    @client.setter
    def client(self, value) -> None:
        self._client = value

    def get_subsystem(self, name: str):
        """ look up a peer subsystem on the owning client """
        return getattr(self.client, "subsystems", {}).get(name)

    def get_window(self, wid: int):
        """ look up a window by id on the `window` subsystem """
        window = self.get_subsystem("window")
        return window.get_window(wid) if window else None

    def get_windows(self) -> tuple:
        """ all the windows currently registered with the `window` subsystem """
        window = self.get_subsystem("window")
        return tuple(window._id_to_window.values()) if window else ()

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

    def load(self) -> None:
        """
        Slower initialization that may load external components
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

    def send(self, packet_type: str, *parts: PacketElement) -> None:
        """
        Send a packet to the server, dummy implementation.
        """

    def send_now(self, packet_type: str, *parts: PacketElement) -> None:
        """
        Send a packet to the server,
        this takes precedence over packets sent via send().
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
