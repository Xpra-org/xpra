# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import json
import os.path
from time import monotonic, time
from typing import Any
from collections.abc import Sequence

from xpra.client.base.gobject import GObjectClientAdapter
from xpra.exit_codes import ExitValue
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.net.packet_type import WINDOW_DRAW_ACK, WINDOW_REFRESH
from xpra.util.env import envint
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("client", "encoding")

GLib = gi_import("GLib")

REFRESH = envint("XPRA_RECORD_REFRESH", 10)
SYNC_GAP = envint("XPRA_SYNC_GAP", 1)


def save_json(path: str, data: dict) -> None:
    with open(path, "w") as f:
        f.write(json.dumps(data))


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

    def __init__(self, wid: int, geom: tuple[int, int, int, int], override_redirect: bool,
                 directory: str, start: float):
        self.wid = wid
        self.override_redirect = override_redirect
        self.metadata = {}
        self.geometry = geom
        self.directory = directory
        self.event_no = 0
        self.start = start
        self.sync_timer = 0
        if not os.path.exists(directory):
            os.mkdir(directory, 0o755)

    def update_metadata(self, metadata) -> None:
        self.metadata.update(metadata)

    def record(self, event: str, **kwargs) -> None:
        data = {
            "event": event,
            "wid": self.wid,
            "timestamp": int((monotonic() - self.start) * 1000),
            "time": int(time() * 1000),
        }
        # remove bytes data and store as a separate file
        # (ie: `encoding` in `draw` packets or `pixels` in `cursor_data` packets)
        for key, value in dict(kwargs).items():
            if isinstance(value, (bytes, memoryview)):
                bin_data = bytes(kwargs.pop(key, b""))
                path = os.path.join(self.directory, f"{self.event_no}.{key}")
                with open(path, "wb") as f:
                    f.write(bin_data)
        # everything else is added to the dictionary:
        data.update(kwargs)
        path = os.path.join(self.directory, f"{self.event_no}.json")
        save_json(path, data)
        log("recorded: %s : %r", event, data)
        self.event_no += 1
        if event != "sync" and not self.sync_timer:
            self.sync_timer = GLib.timeout_add(SYNC_GAP * 1000, self.record_sync)

    def record_sync(self) -> bool:
        self.sync_timer = 0
        self.record("sync", metatada=self.metadata, geometry=self.geometry)
        return False


class RecordClient(GObjectClientAdapter, ClientBaseClass):

    def __init__(self, options):
        GObjectClientAdapter.__init__(self)
        for cc in CLIENT_BASES:
            cc.__init__(self)
        self.client_type = "recorder"
        self.windows = options.windows
        self._id_to_window: dict[int, Any] = {}
        self.encodings: Sequence[str] = ("png", "webp", "jpeg")
        self.encoding_options = {}
        self.record_directory = os.path.join(os.path.abspath(os.getcwd()), "record")
        self.sequence = 0
        self.refresh_needed: set[int] = set()
        self.refresh_timer = 0
        self.start = monotonic()

    def init(self, opts) -> None:
        for cc in CLIENT_BASES:
            cc.init(self, opts)
        if opts.encoding and opts.encoding not in self.encodings:
            self.encodings = tuple(list(self.encodings) + [opts.encoding])
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

    def cleanup(self):
        self.cancel_refresh()
        super().cleanup()

    def cancel_refresh(self) -> None:
        rt = self.refresh_timer
        if rt:
            self.refresh_timer = 0
            self.source_remove(rt)

    def client_toolkit(self) -> str:
        raise "offscreen-recorder"

    def make_hello(self) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if self.windows:
            caps = {
                "windows": True,
                "encoding": self.encoding_options,
                "share": True,
                "keyboard": {"record": True},
                "cursor": {"encodings": ("png", ), "backwards-compatible": False},
                "pointer": {"record": True},
            }
        return caps

    def server_connection_established(self, c: typedict) -> bool:
        for cc in CLIENT_BASES:
            if not cc.parse_server_capabilities(self, c):
                return False
        # this will call do_command()
        return super().server_connection_established(c)

    def _process_startup_complete(self, packet: Packet) -> None:
        self.refresh_timer = self.timeout_add(REFRESH * 1000, self.request_refresh)

    def print_server_info(self, c: typedict) -> None:
        log.info("recording from:")
        super().print_server_info(c)

    def request_refresh(self) -> bool:
        quality = 100
        options = {"refresh-now": True}
        client_properties = {}
        for wid in tuple(self.refresh_needed):
            self.send(WINDOW_REFRESH, wid, 0, quality, options, client_properties)
        self.refresh_needed = set()
        return True

    def _process_encodings(self, packet: Packet) -> None:
        encodings = typedict(packet.get_dict(1)).dictget("encodings", {}).get("core", ())
        common = tuple(set(self.encodings) & set(encodings))
        log("server encodings=%s, common=%s", encodings, common)

    def get_window(self, wid: int) -> WindowModel | None:
        return self._id_to_window.get(wid)

    def _process_window_create(self, packet: Packet) -> None:
        self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet: Packet) -> None:
        assert BACKWARDS_COMPATIBLE
        self._process_new_common(packet, True)

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
        metadata["override_redirect"] = override_redirect
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
        directory = os.path.join(self.record_directory, "%x" % wid)
        if not os.path.exists(directory):
            os.mkdir(directory, 0o755)
        window = WindowModel(wid, geom, override_redirect, directory, self.start)
        window.update_metadata(metadata)
        self._id_to_window[wid] = window
        window.record("new", geometry=(x, y, w, h), metadata=metadata)

    def _process_window_initiate_moveresize(self, packet: Packet) -> None:
        # should not be received!
        pass

    def _process_window_metadata(self, packet: Packet) -> None:
        wid = packet.get_wid()
        metadata = packet.get_dict(2)
        window = self.get_window(wid)
        if window:
            window.update_metadata(metadata)
            window.record("metadata", metadata=metadata)

    def _process_window_move_resize(self, packet: Packet) -> None:
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        w = packet.get_u16(4)
        h = packet.get_u16(5)
        window = self.get_window(wid)
        if window:
            window.geometry = (x, y, w, h)
            window.record("move-resize", geometry=(x, y, w, h))

    def _process_window_resized(self, packet: Packet) -> None:
        wid = int(packet[1])
        w = int(packet[2])
        h = int(packet[3])
        window = self.get_window(wid)
        if window:
            x, y = window.geometry[:2]
            window.geometry = (x, y, w, h)
            window.record("resized", geometry=(x, y, w, h))

    def _process_raise_window(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if window:
            window.record("raise")

    def _process_window_restack(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if window:
            window.record("restack")

    def _process_configure_override_redirect(self, packet: Packet) -> None:
        self._process_window_move_resize(packet)

    def _process_window_destroy(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if window:
            assert window is not None
            del self._id_to_window[wid]
            window.record("destroy")

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
        options = {}
        if len(packet) > 10:
            options = packet.get_dict(10)
        log("record: %ix%i %s update", width, height, coding)
        kwargs = {
            "geometry": (x, y, width, height),
            "encoding": coding,
            "packet_sequence": packet_sequence,
            "rowstride": rowstride,
            "options": options,
            coding: data,
        }
        window.record("draw", **kwargs)
        decode_time = 0
        message = ""
        self.send(WINDOW_DRAW_ACK, packet_sequence, wid, width, height, decode_time, message)
        if x != 0 or y != 0 or (width, height) != window.geometry[2:4] or options.get("quality", 100) != 100:
            self.refresh_needed.add(wid)

    def _process_eos(self, packet: Packet) -> None:
        pass

    def _process_keyboard_record(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        record = packet.get_dict(2)
        if record:
            window.record("key-event", key=record)

    def _process_cursor_default(self, packet: Packet) -> None:
        for window in self._id_to_window.values():
            window.cursor = ()
            window.record("cursor-default")

    def _process_cursor_data(self, packet: Packet) -> None:
        encoding = packet.get_str(1)
        w = packet.get_u16(2)
        h = packet.get_u16(3)
        xhot = packet.get_u16(4)
        yhot = packet.get_u16(5)
        serial = packet.get_u64(6)
        pixels = packet.get_bytes(7)
        name = packet.get_str(8)
        kwargs = {
            "encoding": encoding,
            "w": w,
            "h": h,
            "xhot": xhot,
            "yhot": yhot,
            "serial": serial,
            encoding: pixels,
            "name": name,
        }
        for window in self._id_to_window.values():
            window.record("cursor-data", **kwargs)

    def _process_pointer_position(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: window %#x not found!", wid)
            return
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        if len(packet) >= 6:
            rx = packet.get_i16(4)
            ry = packet.get_i16(5)
        else:
            rx, ry = -1, -1
        window.record("pointer-position", position=(x, y, rx, ry))

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
            "startup-complete",
            "window-create",
            "window-restack",
            "window-initiate-moveresize",
            "window-move-resize",
            "window-resized",
            "window-metadata",
            "window-destroy",
            "window-draw",
            "eos",
            "keyboard-record",
            "cursor-data",
            "cursor-default",
            "pointer-position",
        )
