# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
import os.path
from time import monotonic
from typing import Any
from collections.abc import Sequence

from xpra.client.base.gobject import GObjectClientAdapter
from xpra.exit_codes import ExitValue
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.log import Logger

log = Logger("client", "encoding")

EXT_ALIASES = {"jpg": "jpeg"}


def get_client_base_classes() -> tuple[type, ...]:
    classes: list[type] = []
    # Warning: MmapClient must come first,
    # so it is initialized by the time XpraClientBase creates the hello packet
    from xpra.client.base import features
    if features.mmap:
        from xpra.client.subsystem.mmap import MmapClient
        classes.append(MmapClient)
    if features.ping:
        from xpra.client.subsystem.ping import PingClient
        classes.append(PingClient)
    # ServerInfoClient?
    # ClipboardClient, KeyboardClient, PointerClient, NotificationClient, Encodings -> emulate it
    # TrayClient -> use custom tray instead
    from xpra.client.base.command import XpraClientBase
    classes.append(XpraClientBase)
    log("RecordClient base classes=%s", csv(classes))
    return tuple(classes)


CLIENT_BASES = get_client_base_classes()
ClientBaseClass = type('ClientBaseClass', CLIENT_BASES, {})


class WindowModel:

    def __init__(self, wid: int, geom: tuple[int, int, int, int], override_redirect: bool, directory: str):
        self.wid = wid
        self.override_redirect = override_redirect
        self.metadata = {}
        self.geometry = geom
        self.directory = directory

    def update_metadata(self, metadata) -> None:
        self.metadata.update(metadata)


class RecordClient(GObjectClientAdapter, ClientBaseClass):

    def __init__(self, options):
        GObjectClientAdapter.__init__(self)
        for cc in CLIENT_BASES:
            cc.__init__(self)
        self.client_type = "recorder"
        self.windows = options.windows
        self._id_to_window: dict[int, Any] = {}
        self.encodings: Sequence[str] = ("png", "webp", "jpeg")
        self.record_directory = os.path.join(os.path.abspath(os.getcwd()), "record")

    def init(self, opts) -> None:
        for cc in CLIENT_BASES:
            cc.init(self, opts)
        if opts.encoding and opts.encoding not in self.encodings:
            self.encodings = tuple(list(self.encodings) + [opts.encoding])
        # why is this here!?
        self.encoding_options = {
            "options": self.encodings,
            "core": self.encodings,
            "setting": opts.encoding,
        }
        for attr, value in {
            "quality": opts.quality,
            "min-quality": opts.min_quality,
            "speed": opts.speed,
            "min-speed": opts.min_speed,
        }.items():
            if value > 0:
                self.encoding_options[attr] = value
        self.install_signal_handlers()

    def run(self) -> ExitValue:
        if not os.path.exists(self.record_directory):
            os.mkdir(self.record_directory, 0o755)
        return super().run()

    def client_toolkit(self) -> str:
        raise "offscreen-recorder"

    def make_hello(self) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if self.windows:
            caps["windows"] = True
            caps["encoding"] = self.encoding_options
            caps["share"] = True
        return caps

    def server_connection_established(self, c: typedict) -> bool:
        for cc in CLIENT_BASES:
            if not cc.parse_server_capabilities(self, c):
                return False
        # this will call do_command()
        return super().server_connection_established(c)

    def _process_startup_complete(self, packet: Packet) -> None:
        pass

    def print_server_info(self, c: typedict) -> None:
        log.info("recording from:")
        super().print_server_info(c)

    def _process_encodings(self, packet: Packet) -> None:
        encodings = typedict(packet.get_dict(1)).dictget("encodings", {}).get("core", ())
        common = tuple(set(self.encodings) & set(encodings))
        log("server encodings=%s, common=%s", encodings, common)

    def get_window(self, wid: int):
        return self._id_to_window.get(wid)

    def _process_window_create(self, packet: Packet) -> None:
        return self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet: Packet) -> None:
        assert BACKWARDS_COMPATIBLE
        return self._process_new_common(packet, True)

    def _process_new_common(self, packet: Packet, override_redirect: bool):
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        w = packet.get_u16(4)
        h = packet.get_u16(5)
        assert 0 <= w < 32768 and 0 <= h < 32768
        metadata = typedict(packet.get_dict(6))
        # newer versions use metadata only:
        override_redirect |= metadata.boolget("override-redirect", False)
        assert wid not in self._id_to_window, "we already have a window {}: {}".format(wid, self.get_window(wid))
        if w < 1 or h < 1:
            log.error("Error: window %#x dimensions %ix%i are invalid", wid, w, h)
            w, h = 1, 1
        rel_pos = metadata.inttupleget("relative-position")
        parent = metadata.intget("parent")
        log("relative-position=%s (parent=%s)", rel_pos, parent)
        if parent and rel_pos:
            pwin = self._id_to_window.get(parent)
            if pwin:
                x = pwin.geometry[0] + rel_pos[0]
                y = pwin.rel_pos[1] + rel_pos[1]
                log("relative position(%s)=%s", rel_pos, (x, y))
        geom = (x, y, w, h)
        directory = os.path.join(self.record_directory, "%i" % wid)
        if not os.path.exists(directory):
            os.mkdir(directory, 0o755)
        model = WindowModel(wid, geom, override_redirect, directory)
        model.update_metadata(metadata)
        self._id_to_window[wid] = model

    def _process_window_initiate_moveresize(self, packet: Packet) -> None:
        # should not be received!
        pass

    def _process_window_metadata(self, packet: Packet) -> None:
        wid = packet.get_wid()
        metadata = packet.get_dict(2)
        window = self.get_window(wid)
        if window:
            window.update_metadata(metadata)

    def _process_window_move_resize(self, packet: Packet) -> None:
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        w = packet.get_u16(4)
        h = packet.get_u16(5)
        window = self.get_window(wid)
        if window:
            window.geometry = (x, y, w, h)

    def _process_window_resized(self, packet: Packet) -> None:
        wid = int(packet[1])
        w = int(packet[2])
        h = int(packet[3])
        window = self.get_window(wid)
        if window:
            x, y = window.geometry[:2]
            window.geometry = (x, y, w, h)

    def _process_raise_window(self, packet: Packet) -> None:
        pass

    def _process_window_restack(self, packet: Packet) -> None:
        pass

    def _process_configure_override_redirect(self, packet: Packet) -> None:
        self._process_window_move_resize(packet)

    def _process_window_destroy(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if window:
            assert window is not None
            del self._id_to_window[wid]

    def _process_window_draw(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: window %#x not found!", wid)
            return
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        width = packet.get_u16(4)
        height = packet.get_u16(5)
        coding = packet.get_str(6)
        # mmap can send a tuple, otherwise it's a buffer, see #4496:
        data = packet[7]
        packet_sequence = packet.get_u64(8)
        rowstride = packet.get_u32(9)
        log.info("record: %ix%i %s update", width, height, coding)
        filename = os.path.join(window.directory, "%i.%s" % (monotonic(), coding))
        with open(filename, "wb") as f:
            f.write(data)

    def _process_eos(self, packet: Packet) -> None:
        pass

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets("startup-complete", "encodings", main_thread=True)
        if BACKWARDS_COMPATIBLE:
            self.add_packets("raise-window", "new-override-redirect")
            self.add_legacy_alias("new-window", "window-create")
            self.add_legacy_alias("restack-window", "window-restack")
            self.add_legacy_alias("initiate-moveresize", "window-initiate-moveresize")
            self.add_legacy_alias("lost-window", "window-destroy")
            self.add_legacy_alias("configure-override-redirect", "window-move-resize")
            self.add_legacy_alias("draw", "window-draw")
        self.add_packets(
            "window-create",
            "window-restack",
            "window-initiate-moveresize",
            "window-move-resize",
            "window-resized",
            "window-metadata",
            "window-destroy",
            "window-draw",
            "eos",
        )
