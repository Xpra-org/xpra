# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable, Sequence
from typing import Any

from xpra.util.objects import typedict
from xpra.exit_codes import ExitValue
from xpra.net.compression import Compressed
from xpra.net.common import PacketElement
from xpra.net.dispatch import SubsystemPacketHandlers
from xpra.util.signal_emitter import SignalEmitter


class StubClientSubsystem(SubsystemPacketHandlers, SignalEmitter):
    """
    Base class for client subsystems.
    Packet handler registration is shared with the server's `StubSubsystem`
    through `SubsystemPacketHandlers`.
    """
    # `_signal_callbacks` and `main_loop` belong to `SignalEmitter`, but it cannot
    # declare them itself (see the note there), so they are declared here, where
    # the slots actually take effect:
    __slots__ = ("__weakref__", "_packet_handlers", "_signal_callbacks", "client", "idle_add", "main_loop",
                 "source_remove", "timeout_add")
    __signals__: list[str] = []
    # every concrete subsystem should declare a non-empty PREFIX,
    # used as the key in `client.subsystems`:
    PREFIX: str = ""

    def __init__(self, client=None) -> None:
        super().__init__()
        self.client = client
        # copy scheduler methods from client if present, GLib otherwise:
        source = client
        if not client:
            from xpra.util.glib_scheduler import GLibScheduler
            source = GLibScheduler
        self.idle_add: Callable = source.idle_add
        self.timeout_add: Callable = source.timeout_add
        self.source_remove: Callable = source.source_remove
        self._packet_handlers = {}

    def get_main_loop(self):
        client = self.client
        if client is not None:
            return getattr(client, "main_loop", None)
        return getattr(self, "main_loop", None)

    def get_subsystem(self, name: str):
        """ look up a peer subsystem on the owning client """
        return getattr(self.client, "subsystems", {}).get(name)

    def get_server_packet_types(self) -> Sequence[str]:
        network = self.get_subsystem("network")
        return getattr(network, "server_packet_types", ())

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

    def preload_decode(self) -> None:
        """
        Called on the decode thread before its seccomp filter is installed.
        Import here anything this subsystem will need when its work runs there:
        a first-time import on the filtered thread would hit `openat` and be blocked.
        (see `xpra/client/subsystem/decode.py` and `docs/Usage/Seccomp.md`)
        """

    def add_decode_work(self, fn: Callable, *args) -> None:
        """
        Queue `fn(*args)` for the decode thread, which decodes the untrusted data
        sent by the server (pixels, icons, cursors) under a seccomp filter.
        When there is no `decode` subsystem to defer to (bare / standalone use,
        eg: in a unit test), run it inline.
        """
        decode = self.get_subsystem("decode")
        if decode:
            decode.add_work(fn, *args)
        else:
            fn(*args)

    def run(self) -> ExitValue:
        """
        run the main loop.
        """

    def quit(self, exit_code: ExitValue) -> None:  # pragma: no cover
        """
        Terminate the client with the given exit code.
        (the exit code is ignored if we already have one)
        Delegates to the owning client (mirrors `send`/`send_now`): the real
        implementation lives on the concrete toolkit client (eg:
        `GObjectClientAdapter.quit`, which stops the main loop and runs
        `cleanup()`).
        """
        self.client.quit(exit_code)

    def cleanup(self) -> None:
        """
        Free up any resources.
        """

    def send(self, packet_type: str, *parts: PacketElement) -> None:
        """
        Send a packet to the server, via the owning client.
        (isolated tests inject their own `send`)
        """
        self.client.send(packet_type, *parts)

    def send_now(self, packet_type: str, *parts: PacketElement) -> None:
        """
        Send a packet to the server,
        this takes precedence over packets sent via send().
        Delegates to the owning client (see `send`).
        """
        self.client.send_now(packet_type, *parts)

    def setup_connection(self, _conn) -> None:
        """
        Prepare to run using this connection to the server.
        """

    def get_caps(self) -> dict[str, Any]:
        """
        Return the capabilities provided by this subsystem.
        """
        return {}

    def get_info(self) -> dict[str, Any]:
        """
        Information contained in this subsystem
        """
        return {}

    def parse_server_capabilities(self, c: typedict) -> bool:  # pylint: disable=unused-argument
        """
        Parse server attributes specified in the hello capabilities.
        This runs in a non-UI thread.
        """
        return True

    def compressed_wrapper(self, datatype, data, level=5, **kwargs) -> Compressed:
        """
        Compress data for sending to the server.
        Delegates to the `network` subsystem's real (lz4/brotli) implementation
        when one is available (mirrors `send`/`send_now`); otherwise (bare/
        standalone use, eg: in a unit test) falls back to an uncompressed
        wrapper below.
        """
        network = self.get_subsystem("network")
        if network:
            return network.compressed_wrapper(datatype, data, level=level, **kwargs)
        assert level >= 0
        return Compressed("raw %s" % datatype, data)

    def init_packet_handlers(self) -> None:
        """
        Register the packet types that this subsystem can handle, even before authentication.
        """

    def init_authenticated_packet_handlers(self) -> None:
        """
        Register the packet types that this subsystem can handle after authentication.
        """

    def get_packet_owner(self):
        """ packet registration goes through the owning client (see `SubsystemPacketHandlers`) """
        return self.client
