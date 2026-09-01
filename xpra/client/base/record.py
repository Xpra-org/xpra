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
from xpra.platform.paths import initial_cwd
from xpra.util.env import envint
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("client", "encoding")

GLib = gi_import("GLib")

REFRESH = envint("XPRA_RECORD_REFRESH", 10)
SYNC_GAP = envint("XPRA_SYNC_GAP", 1)

NO_GEOMETRY = (0, 0, 0, 0)

# window types which never take the keyboard focus when they are mapped:
NO_FOCUS_WINDOW_TYPES = (
    "DESKTOP", "DOCK", "SPLASH", "MENU", "DROPDOWN_MENU", "POPUP_MENU",
    "TOOLTIP", "NOTIFICATION", "COMBO", "DND",
)
# metadata flags which prevent a window from taking the focus:
NO_FOCUS_FLAGS = ("override-redirect", "tray", "below", "iconic", "shaded")


def can_focus(metadata: typedict) -> bool:
    """
    Should this window take the keyboard focus when it is mapped?
    The server does not tell us, so this is a heuristic:
    windows that are kept below, unmapped or of a type that never
    receives input are assumed not to steal the focus.
    """
    if any(metadata.boolget(flag) for flag in NO_FOCUS_FLAGS):
        return False
    window_types = metadata.strtupleget("window-type")
    return not any(wt in NO_FOCUS_WINDOW_TYPES for wt in window_types)


def save_json(path: str, data: dict) -> None:
    def tostr(obj) -> str:
        # this should not happen: binary data is saved as separate blob files,
        # but a lossy event is still better than a hole in the event sequence:
        log.warn("Warning: cannot serialize %s value, saving it as a string", type(obj))
        return str(obj)
    try:
        text = json.dumps(data, default=tostr)
    except (TypeError, ValueError):
        log.error("Error writing %r to %r", data, path, exc_info=True)
        return
    with open(path, "w") as f:
        f.write(text)


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
        self.cursor_data = ()
        self.geometry = geom
        self.directory = directory
        self.event_no = 0
        self.start = start
        self.sync_timer = 0
        # does this window have the keyboard focus? (see `RecordClient.set_focused`)
        self.focused = False
        if not os.path.exists(directory):
            os.mkdir(directory, 0o755)

    def update_metadata(self, metadata) -> None:
        self.metadata.update(metadata)

    def extract_blobs(self, data: dict) -> dict:
        """
        json cannot store binary data, so it is saved as a separate file
        named after the event and the key it was found in
        (ie: `encoding` in `draw` packets or `pixels` in `cursor_data` packets).
        `sync` events embed the cursor data, so nested dictionaries are
        parsed too - and since those dictionaries are shared with the other
        windows, a copy is returned rather than modifying them in place.
        """
        filtered: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, (bytes, memoryview)):
                path = os.path.join(self.directory, f"{self.event_no}.{key}")
                with open(path, "wb") as f:
                    f.write(bytes(value))
            elif isinstance(value, dict):
                filtered[key] = self.extract_blobs(value)
            else:
                filtered[key] = value
        return filtered

    def record(self, event: str, **kwargs) -> None:
        data = {
            "event": event,
            "wid": self.wid,
            "timestamp": int((monotonic() - self.start) * 1000),
            "time": int(time() * 1000),
            "index": self.event_no,
        }
        # binary data is stored in separate files,
        # everything else is added to the dictionary:
        data.update(self.extract_blobs(kwargs))
        path = os.path.join(self.directory, f"{self.event_no}.json")
        save_json(path, data)
        log("recorded: %s : %r", event, data)
        self.event_no += 1
        if event == "destroy":
            self.cancel_sync_timer()
        elif event != "sync":
            self.schedule_sync()

    def schedule_sync(self) -> None:
        if not self.sync_timer:
            self.sync_timer = GLib.timeout_add(SYNC_GAP * 1000, self.record_sync)

    def cancel_sync_timer(self) -> None:
        if st := self.sync_timer:
            self.sync_timer = 0
            GLib.source_remove(st)

    def record_sync(self) -> bool:
        self.sync_timer = 0
        kwargs: dict[str, Any] = {
            "metadata": self.metadata,
            "cursor-data": self.cursor_data,
            "focused": self.focused,
        }
        if self.geometry != NO_GEOMETRY:
            kwargs["geometry"] = self.geometry
        self.record("sync", **kwargs)
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
        self.record_directory = os.path.join(initial_cwd, "record")
        self.sequence = 0
        self.refresh_needed: set[int] = set()
        self.refresh_timer = 0
        self.start = monotonic()
        # the window which currently has the keyboard focus, 0 for none:
        self.focused = 0

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
        if rt := self.refresh_timer:
            self.refresh_timer = 0
            self.source_remove(rt)

    def client_toolkit(self) -> str:
        return "offscreen-recorder"

    def make_hello(self) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if self.windows:
            window_caps = {"enabled": True, "record": True, "restack": True}
            caps = {
                "window": window_caps,
                "encoding": self.encoding_options,
                "share": True,
                "keyboard": {"record": True},
                "cursor": {"encodings": ("png", ), "backwards-compatible": False},
                "pointer": {"record": True},
                "clipboard": {"record": True},
                "display": {"record": True},
            }
            if BACKWARDS_COMPATIBLE:
                # older servers read these from the plural namespace:
                caps["windows"] = window_caps
        return caps

    def server_connection_established(self, caps: typedict) -> bool:
        for cc in CLIENT_BASES:
            if not cc.parse_server_capabilities(self, caps):
                return False
        # this will call do_command()
        return super().server_connection_established(caps)

    def _process_startup_complete(self, packet: Packet) -> None:
        self.refresh_timer = self.timeout_add(REFRESH * 1000, self.request_refresh)
        # create the "desktop" window:
        geom = NO_GEOMETRY
        wid = 0
        directory = os.path.join(self.record_directory, "%x" % wid)
        if not os.path.exists(directory):
            os.mkdir(directory, 0o755)
        window = WindowModel(wid, geom, False, directory, self.start)
        window.record("new")
        self._id_to_window[wid] = window

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

    def _process_encoding_set(self, packet: Packet) -> None:
        encodings = typedict(packet.get_dict(1)).dictget("encodings", {}).get("core", ())
        common = tuple(set(self.encodings) & set(encodings))
        log("server encodings=%s, common=%s", encodings, common)

    def _process_setting_change(self, packet: Packet) -> None:
        """ we don't have any settings to update, just log it """
        log("setting-change: %s=%s", packet.get_str(1), packet[2])

    def _process_desktop_size(self, packet: Packet) -> None:
        """ the recorder has no screen to resize, just log it """
        log("desktop-size: %s", packet[1:])

    def get_window(self, wid: int) -> WindowModel | None:
        return self._id_to_window.get(wid)

    def set_focused(self, wid: int) -> None:
        """
        Update the window which has the keyboard focus.
        The focus state is saved at sync points, so both the window losing
        the focus and the one gaining it must record a new one.
        """
        if self.focused == wid:
            return
        log("set_focused(%#x) previous focus: %#x", wid, self.focused)
        if self.focused > 0 and (window := self.get_window(self.focused)):
            window.focused = False
            window.schedule_sync()
        self.focused = wid
        if wid > 0 and (window := self.get_window(wid)):
            window.focused = True
            window.schedule_sync()

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
        if wid in self._id_to_window:
            raise ValueError("we already have a window %#x: %s" % (wid, self.get_window(wid)))
        if w < 1 or h < 1:
            log.error("Error: window %#x dimensions %ix%i are invalid", wid, w, h)
            w, h = 1, 1
        rel_pos = metadata.inttupleget("relative-position")
        parent = metadata.intget("parent")
        log("relative-position=%s (parent=%s)", rel_pos, parent)
        if parent and rel_pos:
            if pwin := self._id_to_window.get(parent):
                x = pwin.geometry[0] + rel_pos[0]
                y = pwin.geometry[1] + rel_pos[1]
                log("relative position(%s)=%s", rel_pos, (x, y))
        geom = (x, y, w, h)
        directory = os.path.join(self.record_directory, "%x" % wid)
        if not os.path.exists(directory):
            os.mkdir(directory, 0o755)
        window = WindowModel(wid, geom, override_redirect, directory, self.start)
        window.update_metadata(metadata)
        self._id_to_window[wid] = window
        # new windows usually steal the focus:
        if can_focus(metadata):
            self.set_focused(wid)
        # `new` events are sync points, so they must carry the focus state too:
        window.record("new", geometry=(x, y, w, h), metadata=metadata, focused=window.focused)

    def _process_window_initiate_moveresize(self, packet: Packet) -> None:
        # should not be received!
        pass

    def _process_window_metadata(self, packet: Packet) -> None:
        wid = packet.get_wid()
        metadata = packet.get_dict(2)
        if window := self.get_window(wid):
            window.update_metadata(metadata)
            if self.focused == wid and typedict(metadata).boolget("iconic"):
                # an iconified window cannot keep the focus:
                self.set_focused(0)
            window.record("metadata", metadata=metadata)

    def _process_window_move_resize(self, packet: Packet) -> None:
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        w = packet.get_u16(4)
        h = packet.get_u16(5)
        if window := self.get_window(wid):
            window.geometry = (x, y, w, h)
            window.record("move-resize", geometry=(x, y, w, h))

    def _process_window_resized(self, packet: Packet) -> None:
        wid = int(packet[1])
        w = int(packet[2])
        h = int(packet[3])
        if window := self.get_window(wid):
            x, y = window.geometry[:2]
            window.geometry = (x, y, w, h)
            window.record("resize", size=(w, h))

    def _process_window_raise(self, packet: Packet) -> None:
        wid = packet.get_wid()
        if window := self.get_window(wid):
            # the server only raises windows that gained the focus
            # (see the `sync-focus` capability):
            self.set_focused(wid)
            window.record("raise")

    def _process_window_restack(self, packet: Packet) -> None:
        wid = packet.get_wid()
        detail = packet.get_i16(2)
        other_wid = packet.get_wid(3)
        if window := self.get_window(wid):
            if detail == 0 and not other_wid:
                # raised to the top of the stack:
                self.set_focused(wid)
            elif detail != 0 and self.focused == wid:
                # lowered: it cannot have the focus any more
                self.set_focused(0)
            window.record("restack", detail=detail, other=other_wid)

    def _process_configure_override_redirect(self, packet: Packet) -> None:
        self._process_window_move_resize(packet)

    def _process_window_destroy(self, packet: Packet) -> None:
        wid = packet.get_wid()
        if window := self.get_window(wid):
            assert window is not None
            del self._id_to_window[wid]
            if self.focused == wid:
                # we don't know which window gets the focus next:
                self.set_focused(0)
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
            "options": options,
            coding: data,
        }
        if rowstride:
            kwargs["rowstride"] = rowstride
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
        if not window:
            log.warn("Warning: window %#x not found!", wid)
            return
        record = packet.get_dict(2)
        if record:
            window.record("key", key=record)

    def _process_clipboard_record(self, packet: Packet) -> None:
        # example packet:
        # 'clipboard-record', 'client', 'clipboard-contents', 6, 'CLIPBOARD', 'UTF8_STRING', 8, 'bytes', b'foo', 0
        window = self.get_window(0)
        subpacket_type = packet.get_str(2)
        record = list(packet[1:])
        kwargs: dict[str, Any] = {
            "record": record,
        }
        if subpacket_type == "clipboard-contents" and isinstance(record[7], bytes):
            kwargs["contents"] = record[7]
            record[7] = ''
        window.record("clipboard", **kwargs)

    def _process_window_bell(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: window %#x not found!", wid)
            return
        device = packet.get_u16(2)
        percent = packet.get_i8(3)
        pitch = packet.get_i32(4)
        duration = packet.get_i32(5)
        bell_class = packet.get_u32(6)
        bell_id = packet.get_u32(7)
        bell_name = packet.get_str(8)
        window.record("bell", device=device, percent=percent, pitch=pitch, duration=duration,
                      bell_class=bell_class, bell_id=bell_id, bell_name=bell_name)

    def _process_cursor_default(self, packet: Packet) -> None:
        for window in self._id_to_window.values():
            window.cursor_data = {}
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
        cursor_data = {
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
            window.cursor_data = cursor_data
            window.record("cursor-data", **cursor_data)

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
        window.record("pointer-motion", position=(x, y, rx, ry))

    def _process_pointer_motion(self, packet: Packet) -> None:
        device_id = packet.get_i64(1)
        seq = packet.get_u64(2)
        wid = packet.get_wid(3)
        pdata = packet.get_ints(4)
        props = packet.get_dict(5)
        x, y = pdata[:2]
        rx, ry = pdata[2:4] if len(pdata) >= 4 else (-1, -1)
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: window %#x not found!", wid)
            return
        window.record("pointer-motion", position=(x, y, rx, ry), device_id=device_id, sequence=seq, props=props)

    def _process_pointer_button(self, packet: Packet) -> None:
        device_id = packet.get_i64(1)
        seq = packet.get_u64(2)
        wid = packet.get_wid(3)
        button = packet.get_u8(4)
        pressed = packet.get_bool(5)
        pointer = packet.get_ints(6)
        props = packet.get_dict(7)
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: window %#x not found!", wid)
            return
        window.record("pointer-button", position=pointer, device_id=device_id, sequence=seq, props=props,
                      button=button, pressed=pressed)

    def _process_pointer_wheel(self, packet: Packet) -> None:
        wid = packet.get_wid()
        button = packet.get_u8(2)
        distance = packet.get_i64(3)
        pointer = packet.get_ints(4)
        modifiers = packet.get_strs(5)
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: window %#x not found!", wid)
            return
        window.record("pointer-wheel", position=pointer, button=button, distance=distance, modifiers=tuple(modifiers))

    def init_authenticated_packet_handlers(self) -> None:
        super().init_authenticated_packet_handlers()
        self.add_packets("startup-complete", "encoding-set", main_thread=True)
        self.add_legacy_alias("encodings", "encoding-set")
        if BACKWARDS_COMPATIBLE:
            self.add_packets("new-override-redirect")
            self.add_legacy_alias("raise-window", "window-raise")
            self.add_legacy_alias("new-window", "window-create")
            self.add_legacy_alias("restack-window", "window-restack")
            self.add_legacy_alias("initiate-moveresize", "window-initiate-moveresize")
            self.add_legacy_alias("lost-window", "window-destroy")
            self.add_legacy_alias("configure-override-redirect", "window-move-resize")
            self.add_legacy_alias("draw", "window-draw")
            self.add_legacy_alias("bell", "window-bell")
        self.add_packets(
            "window-create",
            "window-raise",
            "window-restack",
            "window-initiate-moveresize",
            "window-move-resize",
            "window-resized",
            "window-metadata",
            "window-destroy",
            "window-draw",
            "window-bell",
            "eos",
            "keyboard-record",
            "cursor-data",
            "cursor-default",
            "pointer-position",
            "pointer-button",
            "pointer-motion",
            "pointer-wheel",
            "clipboard-record",
            # nothing to record, but we must not close the connection on them:
            "setting-change",
            "desktop_size",
        )
