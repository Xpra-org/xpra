# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from time import monotonic
from typing import Any, NoReturn
from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.server.subsystem.stub import StubServerMixin
from xpra.server.source.window import WindowsConnection
from xpra.server.common import get_sources_by_type
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.net.constants import ConnectionMessage
from xpra.net.packet_type import WINDOW_CREATE
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("window")
focuslog = Logger("focus")
metalog = Logger("metadata")
geomlog = Logger("geometry")
eventslog = Logger("events")


def control_error(*args, **kwargs) -> NoReturn:
    from xpra.net.control.common import ControlError
    raise ControlError(*args, **kwargs)


class WindowServer(StubServerMixin):
    """
    Mixin for servers that forward windows.
    """
    PREFIX = "window"

    def __init__(self):
        StubServerMixin.__init__(self)
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1
        self._window_to_id: dict[Any, int] = {}
        self._id_to_window: dict[int, Any] = {}
        self._counter = 0
        self.window_filters = []
        self.window_min_size = 0, 0
        self.window_max_size = 2 ** 15 - 1, 2 ** 15 - 1

    def init(self, opts) -> None:
        def parse_window_size(v, default_value=(0, 0)):
            try:
                # split on "," or "x":
                pv = tuple(int(x.strip()) for x in v.replace(",", "x").split("x", 1))
                assert len(pv) == 2
                w, h = pv
                if w <= 0 or h <= 0 or w >= 32768 or h >= 32768:
                    raise ValueError(f"invalid window size {w}x{h}")
                return w, h
            except Exception:
                return default_value

        self.window_min_size = parse_window_size(opts.min_size, (0, 0))
        self.window_max_size = parse_window_size(opts.max_size, (2 ** 15 - 1, 2 ** 15 - 1))

    def setup(self) -> None:
        minw, minh = self.window_min_size
        maxw, maxh = self.window_max_size
        self.update_size_constraints(minw, minh, maxw, maxh)
        # when the main loop runs, load the windows:
        GLib.idle_add(self.load_existing_windows)
        self.connect("last-client-exited", self.reset_focus)
        self.add_window_control_commands()

    def add_window_control_commands(self) -> None:
        from xpra.util.parsing import parse_scaling_value, from0to100
        from xpra.net.control.common import parse_boolean_value, parse_4intlist
        ac = self.args_control
        ac("focus", "give focus to the window id", validation=[int])
        ac("map", "maps the window id", validation=[int])
        ac("unmap", "unmaps the window id", validation=[int])
        ac("suspend", "suspend screen updates", max_args=0)
        ac("resume", "resume screen updates", max_args=0)
        ac("ungrab", "cancels any grabs", max_args=0)
        ac("workspace", "move a window to a different workspace", min_args=2, max_args=2, validation=[int, int])
        ac("close", "close a window", min_args=1, max_args=1, validation=[int])
        ac("delete", "delete a window", min_args=1, max_args=1, validation=[int])
        ac("move", "move a window", min_args=3, max_args=3, validation=[int, int, int])
        ac("resize", "resize a window", min_args=3, max_args=3, validation=[int, int, int])
        ac("moveresize", "move and resize a window", min_args=5, max_args=5, validation=[int, int, int, int, int])
        ac("scaling-control", "set the scaling-control aggressiveness (from 0 to 100)", min_args=1, validation=[from0to100])
        ac("scaling", "set a specific scaling value", min_args=1, validation=[parse_scaling_value])
        ac("auto-refresh", "set a specific auto-refresh value", min_args=1, validation=[float])
        ac("refresh", "refresh some or all windows", min_args=0)
        ac("encoding", "picture encoding", min_args=2)
        ac("request-update", "request a screen update using a specific encoding", min_args=3)
        ac("video-region-enabled", "enable video region", min_args=2, max_args=2, validation=[int, parse_boolean_value])
        ac("video-region-detection", "enable video detection", min_args=2, max_args=2, validation=[int, parse_boolean_value])
        ac("video-region-exclusion-zones",
           "set window regions to exclude from video regions: 'WID,(x,y,w,h),(x,y,w,h),..', ie: '1 (0,10,100,20),(200,300,20,20)'",
           min_args=2, max_args=2, validation=[int, parse_4intlist])
        ac("video-region", "set the video region", min_args=5, max_args=5, validation=[int, int, int, int, int])
        ac("reset-video-region", "reset video region heuristics", min_args=1, max_args=1, validation=[int]),
        ac("lock-batch-delay", "set a specific batch delay for a window", min_args=2, max_args=2, validation=[int, int]),
        ac("unlock-batch-delay",
           "let the heuristics calculate the batch delay again for a window (following a 'lock-batch-delay')",
           min_args=1, max_args=1, validation=[int]),
        ac("remove-window-filters", "remove all window filters", min_args=0, max_args=0),
        ac("add-window-filter", "add a window filter", min_args=4, max_args=5)
        ac("image-filter", "configure the image filter", min_args=2, max_args=2, validation=[str, parse_boolean_value])
        # encoding bits:
        for name in (
                "quality", "min-quality", "max-quality",
                "speed", "min-speed", "max-speed",
        ):
            ac(name, "set encoding %s (from 0 to 100)" % name, min_args=1, validation=[from0to100])

    def cleanup(self) -> None:
        for window in tuple(self._window_to_id.keys()):
            window.unmanage()
        # this can cause errors if we receive packets during shutdown:
        # self._window_to_id = {}
        # self._id_to_window = {}

    def load_existing_windows(self) -> None:
        """ this method is overriden by most types of servers """

    def get_server_features(self, _source) -> dict[str, Any]:
        return {}

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "state": {
                "windows": sum(int(window.is_managed()) for window in tuple(self._id_to_window.values())),
            },
            "filters": tuple((uuid, repr(f)) for uuid, f in self.window_filters),
        }

    def get_ui_info(self, _proto, **kwargs) -> dict[str, Any]:
        """ info that must be collected from the UI thread
            (ie: things that query the display)
        """
        wids = kwargs.get("wids", ())
        return {"windows": self.get_windows_info(wids)}

    def parse_hello(self, ss, caps: typedict) -> str | ConnectionMessage:
        self.parse_hello_ui_window_settings(ss, caps)
        return ""

    def parse_hello_ui_window_settings(self, ss, c: typedict) -> None:
        """
        this method is overriden by the `seamless` server to set frame extents
        """

    def add_new_client(self, *_args) -> None:
        minw, minh = self.window_min_size
        maxw, maxh = self.window_max_size
        for ss in tuple(self._server_sources.values()):
            if not isinstance(ss, WindowsConnection):
                continue
            cminw, cminh = ss.window_min_size
            cmaxw, cmaxh = ss.window_max_size
            minw = max(minw, cminw)
            minh = max(minh, cminh)
            if cmaxw > 0:
                maxw = min(maxw, cmaxw)
            if cmaxh > 0:
                maxh = min(maxh, cmaxh)
        maxw = max(1, maxw)
        maxh = max(1, maxh)
        if minw > 0 and minw > maxw:
            maxw = minw
        if minh > 0 and minh > maxh:
            maxh = minh
        self.update_size_constraints(minw, minh, maxw, maxh)

    def update_size_constraints(self, minw: int, minh: int, maxw: int, maxh: int) -> None:
        # subclasses may update the window models
        pass

    def send_initial_data(self, ss) -> None:
        iswc = isinstance(ss, WindowsConnection)
        if iswc:
            windows_clients = get_sources_by_type(self, WindowsConnection, ss)
            self.send_initial_windows(ss, len(windows_clients) > 0)

    def is_shown(self, _window) -> bool:
        return True

    def reset_window_filters(self) -> None:
        self.window_filters = []

    def get_window(self, wid: int):
        return self._id_to_window.get(wid)

    def get_windows_info(self, window_ids=()) -> dict[int, dict[str, Any]]:
        copy = self._id_to_window.copy()
        info = {
            "count": len(copy),
            "total": self._counter,
        }
        for wid, window in copy.items():
            if window_ids and wid not in window_ids:
                continue
            info[wid] = self.get_window_info(window)
        return info

    def get_window_info(self, window) -> dict[str, Any]:
        from xpra.server.window.metadata import make_window_metadata
        info = {}
        for prop in window.get_property_names():
            if prop == "icons" or prop is None:
                continue
            metadata = make_window_metadata(window, prop, skip_defaults=False)
            info.update(metadata)
        for prop in window.get_internal_property_names():
            metadata = make_window_metadata(window, prop, skip_defaults=False)
            info.update(metadata)
        info.update({
            "override-redirect": window.is_OR(),
            "tray": window.is_tray(),
            "size": window.get_dimensions(),
            "xshm": window.uses_xshm(),
        })
        if wid := self._window_to_id.get(window):
            if wprops := self.client_properties.get(wid):
                info["client-properties"] = wprops
        return info

    def _update_metadata(self, window, pspec) -> None:
        metalog("updating metadata on %s: %s", window, pspec)
        wid = self._window_to_id.get(window)
        if not wid:
            return  # window is already gone
        for ss in self._server_sources.values():
            if isinstance(ss, WindowsConnection):
                ss.window_metadata(wid, window, pspec.name)

    def _remove_window(self, window) -> int:
        wid = self._window_to_id[window]
        self.do_remove_window(wid, window)
        return wid

    def _remove_wid(self, wid: int) -> None:
        window = self._id_to_window[wid]
        self.do_remove_window(wid, window)

    def do_remove_window(self, wid: int, window) -> int:
        log("remove_window: %#x - %s", wid, window)
        for ss in self._server_sources.values():
            if isinstance(ss, WindowsConnection):
                ss.lost_window(wid, window)
        del self._window_to_id[window]
        del self._id_to_window[wid]
        for ss in self._server_sources.values():
            if isinstance(ss, WindowsConnection):
                ss.remove_window(wid, window)
        self.client_properties.pop(wid, None)
        return wid

    def _add_new_window_common(self, window) -> int:
        wid = self.allocate_wid(window)
        if not wid:
            raise RuntimeError(f"failed to get window id for new window {window!r}")
        self.do_add_new_window_common(wid, window)
        return wid

    def allocate_wid(self, _window) -> int:
        wid = self._max_window_id
        self._max_window_id = max(self._max_window_id, wid + 1)
        return wid

    def do_add_new_window_common(self, wid: int, window) -> None:
        props = window.get_dynamic_property_names()
        metalog("add_new_window_common(%s) watching for dynamic properties: %s", window, props)
        for prop in props:
            window.managed_connect("notify::%s" % prop, self._update_metadata)
        self._window_to_id[window] = wid
        self._id_to_window[wid] = window
        self._counter += 1

    def _do_send_new_window_packet(self, ptype: str, window, geometry: Sequence[int]) -> None:
        wid = self._window_to_id[window]
        for ss in tuple(self._server_sources.values()):
            if not isinstance(ss, WindowsConnection):
                continue
            wprops = self.client_properties.get(wid, {}).get(ss.uuid, {})
            x, y, w, h = geometry
            # adjust if the transient-for window is not mapped in the same place by the client we send to:
            if "transient-for" in window.get_property_names():
                transient_for = window.get_property("transient-for")
                if transient_for:
                    parent = self._id_to_window.get(transient_for)
                    parent_ws = ss.get_window_source(transient_for)
                    pos = self.get_window_position(parent)
                    geomlog("transient-for=%s : %#x, ws=%s, pos=%s", transient_for, parent, parent_ws, pos)
                    if pos and parent and parent_ws:
                        mapped_at = parent_ws.mapped_at
                        if mapped_at:
                            wx, wy = pos
                            cx, cy = mapped_at[:2]
                            if wx != cx or wy != cy:
                                dx, dy = cx - wx, cy - wy
                                if dx or dy:
                                    geomlog("adjusting new window position for client window offset: %s", (dx, dy))
                                    x += dx
                                    y += dy
            ss.new_window(ptype, wid, window, x, y, w, h, wprops)

    def _process_window_draw_ack(self, proto, packet: Packet) -> None:
        packet_sequence = packet.get_u64(1)
        wid = packet.get_wid(2)
        width = packet.get_u16(3)
        height = packet.get_u16(4)
        decode_time = packet.get_i32(5)
        if len(packet) >= 7:
            message = packet.get_str(6)
        else:
            message = ""
        if ss := self.get_server_source(proto):
            ss.client_ack_damage(packet_sequence, wid, width, height, decode_time, message)

    def refresh_window(self, window) -> None:
        ww, wh = window.get_dimensions()
        self.refresh_window_area(window, 0, 0, ww, wh)

    def refresh_window_area(self, window, x, y, width, height, options=None) -> None:
        wid = self._window_to_id[window]
        for ss in tuple(self._server_sources.values()):
            damage = getattr(ss, "damage", None)
            if damage:
                damage(wid, window, x, y, width, height, options)

    def _process_buffer_refresh(self, proto, packet: Packet) -> None:
        self._process_window_refresh(proto, packet)

    def _process_window_refresh(self, proto, packet: Packet) -> None:
        """ can be used for requesting a refresh, or tuning batch config, or both """
        wid = packet.get_wid()
        qual = packet.get_u8(3)
        if len(packet) >= 6:
            options = typedict(packet.get_dict(4))
            client_properties = packet.get_dict(5)
        else:
            options = typedict({})
            client_properties = {}
        if wid == -1 and BACKWARDS_COMPATIBLE:
            wid_windows = self._id_to_window
        elif wid == 0:
            wid_windows = self._id_to_window
        elif wid in self._id_to_window:
            wid_windows = {wid: self.get_window(wid)}
        else:
            # may have been destroyed since the request was made
            log("invalid window specified for refresh: %#x", wid)
            return
        eventslog("process_buffer_refresh for windows: %s options=%s, client_properties=%s",
                  wid_windows, options, client_properties)
        batch_props = options.dictget("batch", {})
        if batch_props or client_properties:
            # change batch config and/or client properties
            self.update_batch_config(proto, wid_windows, typedict(batch_props), client_properties)
        # default to True for backwards compatibility:
        if options.get("refresh-now", True):
            refresh_opts = {"quality": qual,
                            "override_options": True}
            self._refresh_windows(proto, wid_windows, refresh_opts)

    def update_batch_config(self, proto, wid_windows, batch_props, client_properties) -> None:
        ss = self.get_server_source(proto)
        if ss is None:
            return
        for wid, window in wid_windows.items():
            if window is None or not window.is_managed():
                continue
            self._set_client_properties(proto, wid, window, client_properties)
            ss.update_batch(wid, window, batch_props)

    def _refresh_windows(self, proto, wid_windows, opts=None) -> None:
        if ss := self.get_server_source(proto):
            self.do_refresh_windows(ss, wid_windows, opts)

    def do_refresh_windows(self, ss, wid_windows, opts=None) -> None:
        for wid, window in wid_windows.items():
            if window is None or not window.is_managed():
                continue
            if not self.is_shown(window):
                log("window is no longer shown, ignoring buffer refresh which would fail")
                continue
            ss.refresh(wid, window, opts)

    def _idle_refresh_all_windows(self, proto) -> None:
        GLib.idle_add(self._refresh_windows, proto, self._id_to_window, {})

    def refresh_all_windows(self) -> None:
        for ss in tuple(self._server_sources.values()):
            if not isinstance(ss, WindowsConnection):
                self.do_refresh_windows(ss, self._id_to_window)

    def get_window_position(self, _window) -> tuple[int, int] | None:
        # where the window is actually mapped on the server screen:
        return None

    def _window_mapped_at(self, proto, wid: int, window, coords=None) -> None:
        # record where a window is mapped by a client
        # (in order to support multiple clients and different offsets)
        ss = self.get_server_source(proto)
        if not ss:
            return
        if coords:
            ss.map_window(wid, window, coords)
        else:
            ss.unmap_window(wid, window)

    def _process_window_close(self, proto, packet: Packet) -> None:
        log.info("_process_window_close(%s, %s)", proto, packet)

    def _process_window_map(self, proto, packet: Packet) -> None:
        log.info("_process_window_map(%s, %s)", proto, packet)

    def _process_window_unmap(self, proto, packet: Packet) -> None:
        log.info("_process_window_unmaps, %s)", proto, packet)

    def _process_close_window(self, proto, packet: Packet) -> None:
        log.info("_process_close_window(%s, %s)", proto, packet)

    def _process_configure_window(self, proto, packet: Packet) -> None:
        assert BACKWARDS_COMPATIBLE
        wid = packet.get_wid()
        window = self.get_window(wid)
        if not window:
            geomlog("cannot configure window %#x: not found, already removed?", wid)
            return
        config = {}
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        w = packet.get_u16(4)
        h = packet.get_u16(5)
        skip_geometry = (len(packet) >= 10 and packet.get_bool(9)) or window.is_OR()
        if not skip_geometry:
            config["geometry"] = (x, y, w, h)
        if len(packet) >= 8:
            config["resize-counter"] = packet.get_u64(7)
        if len(packet) >= 7:
            cprops = packet.get_dict(6)
            if cprops:
                config["properties"] = cprops
        if len(packet) >= 9:
            config["state"] = packet.get_dict(8)
        if len(packet) >= 13:
            pwid = packet.get_wid(10)
            position = packet.get_ints(11)
            modifiers = packet.get_strs(12)
            config["pointer"] = {
                "wid": pwid,
                "position": position,
                "modifiers": modifiers,
            }
        self.do_process_window_configure(proto, wid, typedict(config))

    def _process_window_configure(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        config = typedict(packet.get_dict(2))
        self.do_process_window_configure(proto, wid, config)

    def do_process_window_configure(self, proto, wid, config: typedict) -> None:
        log.info("do_process_window_configure(%s, %i, %s)", proto, wid, config)

    def _process_window_action(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        action = packet.get_str(2)
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: invalid window %#x", wid)
            return
        log.info("received window action %r on window %#x from %s", action, wid, proto)
        window.emit("action", action)

    def send_initial_windows(self, ss, sharing=False) -> None:
        # We send the new-window packets sorted by id because this sorts them
        # from oldest to newest -- and preserving window creation order means
        # that the earliest override-redirect windows will be on the bottom,
        # which is usually how things work.  (I don't know that anyone cares
        # about this kind of correctness at all, but hey, doesn't hurt.)
        log("send_initial_windows(%s, %s) will send: %s", ss, sharing, self._id_to_window)
        for wid in sorted(self._id_to_window.keys()):
            window = self._id_to_window[wid]
            if not window.is_managed():
                # we keep references to windows that aren't meant to be displayed..
                continue
            # most of the code here is duplicated from the send functions,
            # so we can send just to the new client and request damage
            # just for the new client too:
            if window.is_tray():
                # code more or less duplicated from _send_new_tray_window_packet:
                w, h = window.get_dimensions()
                if ss.system_tray:
                    ss.new_tray(wid, window, w, h)
                    ss.damage(wid, window, 0, 0, w, h)
                elif not sharing:
                    # park it outside the visible area
                    window.move_resize(-200, -200, w, h)
            else:
                # code more or less duplicated from _send_new_window_packet:
                if not sharing and not window.is_OR():
                    window.hide()
                x, y, w, h = window.get_property("geometry")
                wprops = self.client_properties.get(wid, {}).get(ss.uuid, {})
                packet_type = "new-override-redirect" if (window.is_OR() and BACKWARDS_COMPATIBLE) else WINDOW_CREATE
                ss.new_window(packet_type, wid, window, x, y, w, h, wprops)
                ss.damage(wid, window, 0, 0, w, h)

    ######################################################################
    # focus:
    def reset_focus(self, *args) -> None:
        log("reset_focus%s", args)
        self._focus(None, 0, [])

    def _process_window_focus(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not ss:
            return
        wid = packet.get_wid()
        focuslog("process_window_focus: wid=%#x", wid)
        modifiers = None
        if len(packet) >= 3:
            modifiers = packet.get_strs(2)
        self._focus(ss, wid, modifiers)
        # if the client focused one of our windows, count this as a user event:
        if wid > 0:
            ss.emit("user-event", "focus")

    def _focus(self, _server_source, wid: int, modifiers) -> None:
        focuslog("_focus(%#x, %s)", wid, modifiers)

    def get_focus(self) -> int:
        # can be overridden by subclasses that do manage focus
        # (ie: not shadow servers which only have a single window)
        # default: no focus
        return -1

    def init_packet_handlers(self) -> None:
        if BACKWARDS_COMPATIBLE:
            self.add_legacy_alias("map-window", "window-map")
            self.add_legacy_alias("unmap-window", "window-unmap")
            self.add_legacy_alias("close-window", "window-close")
            self.add_legacy_alias("focus", "window-focus")
            self.add_legacy_alias("damage-sequence", "window-draw-ack")
            # some packet mangling needed:
            self.add_packets("buffer-refresh", "configure-window", main_thread=True)
        self.add_packets(
            "window-map",
            "window-unmap",
            "window-configure",
            "window-close",
            "window-focus",
            "window-refresh",
            "window-action",
            "window-draw-ack",
            main_thread=True)

    #########################################
    # Control Commands
    #########################################

    def control_command_focus(self, wid: int) -> str:
        if self.readonly:
            return "focus request denied by readonly mode"
        if not isinstance(wid, int):
            raise ValueError(f"argument should have been an int, but found {type(wid)}")
        self._focus(None, wid, None)
        return f"gave focus to window {wid:#x}"

    def control_command_map(self, wid: int) -> str:
        if self.readonly:
            return "map request denied by readonly mode"
        if not isinstance(wid, int):
            raise ValueError(f"argument should have been an int, but found {type(wid)}")
        window = self.get_window(wid)
        assert window, f"window {wid:#x} not found"
        if window.is_tray():
            return f"cannot map tray window {wid:#x}"
        if window.is_OR():
            return f"cannot map override redirect window {wid:#x}"
        window.show()
        # window.set_owner(dm)
        # iconic = window.get_property("iconic")
        # if iconic:
        #    window.set_property("iconic", False)
        # w, h = window.get_geometry()[2:4]
        # self.refresh_window_area(window, 0, 0, w, h)
        self.repaint_root_overlay()
        return "mapped window %s" % wid

    def control_command_unmap(self, wid: int) -> str:
        if self.readonly:
            return "unmap request denied by readonly mode"
        if not isinstance(wid, int):
            raise ValueError(f"argument should have been an int, but found {type(wid)}")
        window = self.get_window(wid)
        assert window, f"window {wid:#x} not found"
        if window.is_tray():
            return f"cannot unmap tray window {wid:#x}"
        if window.is_OR():
            return f"cannot unmap override redirect window {wid:#x}"
        window.hide()
        self.repaint_root_overlay()
        return f"unmapped window {wid:#x}"

    def control_command_suspend(self) -> str:
        for csource in tuple(self._server_sources.values()):
            csource.suspend(True, self._id_to_window)
        count = len(self._server_sources)
        return f"suspended {count} clients"

    def control_command_resume(self) -> str:
        for csource in tuple(self._server_sources.values()):
            csource.resume(True, self._id_to_window)
        count = len(self._server_sources)
        return f"resumed {count} clients"

    def control_command_ungrab(self) -> str:
        for csource in tuple(self._server_sources.values()):
            csource.pointer_ungrab(-1)
        count = len(self._server_sources)
        return f"ungrabbed {count} clients"

    def control_command_workspace(self, wid: int, workspace: int) -> str:
        window = self.get_window(wid)
        if not window:
            control_error(f"window {wid:#x} does not exist")
        if "workspace" not in window.get_property_names():
            control_error(f"cannot set workspace on window {window}")
        if workspace < 0:
            control_error(f"invalid workspace value: {workspace}")
        window.set_property("workspace", workspace)
        return f"window {wid:#x} moved to workspace {workspace}"

    def control_command_close(self, wid: int) -> str:
        window = self.get_window(wid)
        if not window:
            control_error(f"window {wid:#x} does not exist")
        window.request_close()
        return f"requested window {window} closed"

    def control_command_delete(self, wid: int) -> str:
        window = self.get_window(wid)
        if not window:
            control_error(f"window {wid:#x} does not exist")
        window.send_delete()
        return f"requested window {window} deleted"

    def control_command_move(self, wid: int, x: int, y: int) -> str:
        window = self.get_window(wid)
        if not window:
            control_error(f"window {wid:#x} does not exist")
        ww, wh = window.get_dimensions()
        count = 0
        for source in tuple(self._server_sources.values()):
            move_resize_window = getattr(source, "move_resize_window", None)
            if move_resize_window:
                move_resize_window(wid, window, x, y, ww, wh)
                count += 1
        return f"window {wid:#x} moved to {x},{y} for {count} clients"

    def control_command_resize(self, wid: int, w: int, h: int) -> str:
        window = self.get_window(wid)
        if not window:
            control_error(f"window {wid:#x} does not exist")
        count = 0
        for source in tuple(self._server_sources.values()):
            resize_window = getattr(source, "resize_window", None)
            if resize_window:
                resize_window(wid, window, w, h)
                count += 1
        return f"window {wid:#x} resized to {w}x{h} for {count} clients"

    def control_command_moveresize(self, wid: int, x: int, y: int, w: int, h: int) -> str:
        window = self.get_window(wid)
        if not window:
            control_error(f"window {wid:#x} does not exist")
        count = 0
        for source in tuple(self._server_sources.values()):
            move_resize_window = getattr(source, "move_resize_window", None)
            if move_resize_window:
                move_resize_window(wid, window, x, y, w, h)
                count += 1
        return f"window {wid:#x} moved to {x},{y} and resized to {w}x{h} for {count} clients"

    def _ws_from_args(self, *args):
        # converts the args to valid window ids,
        # then returns all the window sources for those wids
        from xpra.net.control.common import ControlError, control_get_sources
        if len(args) == 0 or len(args) == 1 and args[0] == "*":
            # default to all if unspecified:
            wids = tuple(self._id_to_window.keys())
        else:
            wids = []
            for x in args:
                try:
                    wid = int(x)
                except ValueError:
                    raise ControlError(f"invalid window id: {x!r}") from None
                if wid in self._id_to_window:
                    wids.append(wid)
                else:
                    log(f"window id {wid:#x} does not exist")
        wss = []
        for csource in tuple(control_get_sources(self)):
            for wid in wids:
                ws = csource.window_sources.get(wid)
                window = self.get_window(wid)
                if window and ws:
                    wss.append(ws)
        return wss

    def _set_encoding_property(self, name: str, value, *wids) -> str:
        for ws in self._ws_from_args(*wids):
            fn = getattr(ws, "set_" + name.replace("-", "_"))  # ie: "set_quality"
            fn(value)
        # now also update the defaults:
        for csource in tuple(self._server_sources.values()):
            csource.default_encoding_options[name] = value
        return f"{name} set to {value}"

    def control_command_quality(self, quality: int, *wids) -> str:
        return self._set_encoding_property("quality", quality, *wids)

    def control_command_min_quality(self, min_quality: int, *wids) -> str:
        return self._set_encoding_property("min-quality", min_quality, *wids)

    def control_command_max_quality(self, max_quality: int, *wids) -> str:
        return self._set_encoding_property("max-quality", max_quality, *wids)

    def control_command_speed(self, speed: int, *wids) -> str:
        return self._set_encoding_property("speed", speed, *wids)

    def control_command_min_speed(self, min_speed: int, *wids) -> str:
        return self._set_encoding_property("min-speed", min_speed, *wids)

    def control_command_max_speed(self, max_speed: int, *wids) -> str:
        return self._set_encoding_property("max-speed", max_speed, *wids)

    def control_command_auto_refresh(self, auto_refresh, *wids) -> str:
        delay = int(float(auto_refresh) * 1000.0)  # ie: 0.5 -> 500 (milliseconds)
        for ws in self._ws_from_args(*wids):
            ws.set_auto_refresh_delay(auto_refresh)
        return f"auto-refresh delay set to {delay}ms for windows {wids}"

    def control_command_refresh(self, *wids) -> str:
        for ws in self._ws_from_args(*wids):
            ws.full_quality_refresh({})
        return f"refreshed windows {wids}"

    def control_command_scaling_control(self, scaling_control, *wids) -> str:
        for ws in tuple(self._ws_from_args(*wids)):
            ws.set_scaling_control(scaling_control)
            ws.refresh()
        return f"scaling-control set to {scaling_control} on windows {wids}"

    def control_command_scaling(self, scaling, *wids) -> str:
        for ws in tuple(self._ws_from_args(*wids)):
            ws.set_scaling(scaling)
            ws.refresh()
        return f"scaling set to {scaling} on windows {wids}"

    def control_command_encoding(self, encoding: str, *args) -> str:
        if encoding in ("add", "remove"):
            cmd = encoding
            assert len(args) > 0
            encoding = args[0]
            wids = args[1:]
            for ws in tuple(self._ws_from_args(*wids)):
                encodings = list(ws.encodings)
                core_encodings = list(ws.core_encodings)
                for enc_list in (encodings, core_encodings):
                    if cmd == "add" and encoding not in enc_list:
                        log(f"adding {encoding} to {enc_list} for {ws}")
                        enc_list.append(encoding)
                    elif cmd == "remove" and encoding in enc_list:
                        log(f"removing {encoding} to {enc_list} for {ws}")
                        enc_list.remove(encoding)
                    else:
                        continue
                ws.encodings = tuple(encodings)
                ws.core_encodings = tuple(core_encodings)
                ws.do_set_client_properties(typedict())
                ws.refresh()
            return ["removed", "added"][cmd == "add"] + " " + encoding

        strict = None  # means no change
        if encoding in ("strict", "nostrict"):
            strict = encoding == "strict"
            encoding = args[0]
            wids = args[1:]
        elif len(args) > 0 and args[0] in ("strict", "nostrict"):
            # remove "strict" marker
            strict = args[0] == "strict"
            wids = args[1:]
        else:
            wids = args
        for ws in tuple(self._ws_from_args(*wids)):
            ws.set_new_encoding(encoding, strict)
            ws.refresh()
        return f"set encoding to {encoding}%s for windows {wids}" % ["", " (strict)"][int(strict or 0)]

    def control_command_request_update(self, encoding: str, geom, *args) -> str:
        wids = args
        now = monotonic()
        options = {
            "auto_refresh": True,
            "av-delay": 0,
        }
        log("request-update using %r, geometry=%s, windows(%s)=%s", encoding, geom, wids, self._ws_from_args(*wids))
        for ws in tuple(self._ws_from_args(*wids)):
            if geom == "all":
                x = y = 0
                w, h = ws.window_dimensions
            else:
                x, y, w, h = (int(x) for x in geom.split(","))
            ws.process_damage_region(now, x, y, w, h, encoding, options)
        return "damage requested"

    def _control_video_subregions_from_wid(self, wid: int) -> list:
        if wid not in self._id_to_window:
            from xpra.net.control.common import ControlError
            raise ControlError(f"invalid window {wid:#x}")
        video_subregions = []
        for ws in self._ws_from_args(wid):
            vs = getattr(ws, "video_subregion", None)
            if not vs:
                log.warn(f"Warning: cannot set video region enabled flag on window {wid:#x}")
                log.warn(f" no video subregion attribute found in {type(ws)}")
                continue
            video_subregions.append(vs)
        # log("_control_video_subregions_from_wid(%s)=%s", wid, video_subregions)
        return video_subregions

    def control_command_video_region_enabled(self, wid: int, enabled: bool) -> str:
        for vs in self._control_video_subregions_from_wid(wid):
            vs.set_enabled(enabled)
        return "video region %s for window %i" % (["disabled", "enabled"][int(enabled)], wid)

    def control_command_video_region_detection(self, wid: int, detection) -> str:
        for vs in self._control_video_subregions_from_wid(wid):
            vs.set_detection(detection)
        return "video region detection %s for window %i" % (["disabled", "enabled"][int(detection)], wid)

    def control_command_video_region(self, wid: int, x: int, y: int, w: int, h: int) -> str:
        for vs in self._control_video_subregions_from_wid(wid):
            vs.set_region(x, y, w, h)
        return "video region set to %s for window %i" % ((x, y, w, h), wid)

    def control_command_video_region_exclusion_zones(self, wid: int, zones) -> str:
        for vs in self._control_video_subregions_from_wid(wid):
            vs.set_exclusion_zones(zones)
        return f"video exclusion zones set to {zones} for window {wid:#x}"

    def control_command_reset_video_region(self, wid: int) -> str:
        for vs in self._control_video_subregions_from_wid(wid):
            vs.reset()
        return f"reset video region heuristics for window {wid:#x}"

    def control_command_lock_batch_delay(self, wid: int, delay: int) -> str:
        for ws in self._ws_from_args(wid):
            ws.lock_batch_delay(delay)
        return f"batch delay locked to {delay}"

    def control_command_unlock_batch_delay(self, wid: int) -> str:
        for ws in self._ws_from_args(wid):
            ws.unlock_batch_delay()
        return "batch delay unlocked"

    def control_command_image_filter(self, wid: str, enabled: bool) -> str:
        for ws in self._ws_from_args(wid):
            ws.image_filter.enabled = enabled
            ws.refresh()
        return "image filter %s" % ("enabled" if enabled else "disabled")
