# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.common import BACKWARDS_COMPATIBLE
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.server.subsystem.stub import StubServerMixin
from xpra.server.source.window import WindowsConnection
from xpra.net.common import Packet
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("window")
focuslog = Logger("focus")
metalog = Logger("metadata")
geomlog = Logger("geometry")
eventslog = Logger("events")


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

    def cleanup(self) -> None:
        for window in tuple(self._window_to_id.keys()):
            window.unmanage()
        # this can cause errors if we receive packets during shutdown:
        # self._window_to_id = {}
        # self._id_to_window = {}

    def load_existing_windows(self) -> None:
        """ this method is overriden by most types of servers """

    def last_client_exited(self) -> None:
        self._focus(None, 0, [])

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

    def parse_hello(self, ss, caps: typedict, send_ui) -> None:
        if send_ui:
            self.parse_hello_ui_window_settings(ss, caps)

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

    def send_initial_data(self, ss, caps, send_ui: bool, share_count: int) -> None:
        if not send_ui:
            return
        if not isinstance(ss, WindowsConnection):
            return
        self.send_initial_windows(ss, share_count > 0)

    def is_shown(self, _window) -> bool:
        return True

    def reset_window_filters(self) -> None:
        self.window_filters = []

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
        wid = self._window_to_id.get(window)
        if wid:
            wprops = self.client_properties.get(wid)
            if wprops:
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
        if "xid" in window.get_property_names():
            wid = window.get_property("xid")
            if not wid:
                raise RuntimeError(f"failed to get window id for new window {window!r}")
        else:
            wid = self._max_window_id
            self._max_window_id = max(self._max_window_id, wid + 1)
        self.do_add_new_window_common(wid, window)
        return wid

    def do_add_new_window_common(self, wid: int, window) -> None:
        props = window.get_dynamic_property_names()
        metalog("add_new_window_common(%s) watching for dynamic properties: %s", window, props)
        for prop in props:
            window.managed_connect("notify::%s" % prop, self._update_metadata)
        self._window_to_id[window] = wid
        self._id_to_window[wid] = window
        self._counter += 1

    def _do_send_new_window_packet(self, ptype, window, geometry) -> None:
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

    def _process_damage_sequence(self, proto, packet: Packet) -> None:
        packet_sequence = packet.get_u64(1)
        wid = packet.get_wid(2)
        width = packet.get_u16(3)
        height = packet.get_u16(4)
        decode_time = packet.get_i32(5)
        if len(packet) >= 7:
            message = packet.get_str(6)
        else:
            message = ""
        ss = self.get_server_source(proto)
        if ss:
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
            wid_windows = {wid: self._id_to_window.get(wid)}
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
        ss = self.get_server_source(proto)
        if ss:
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

    def _process_map_window(self, proto, packet: Packet) -> None:
        log.info("_process_map_window(%s, %s)", proto, packet)

    def _process_unmap_window(self, proto, packet: Packet) -> None:
        log.info("_process_unmap_window(%s, %s)", proto, packet)

    def _process_close_window(self, proto, packet: Packet) -> None:
        log.info("_process_close_window(%s, %s)", proto, packet)

    def _process_configure_window(self, proto, packet: Packet) -> None:
        log.info("_process_configure_window(%s, %s)", proto, packet)

    def _process_window_action(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        action = packet.get_str(2)
        window = self._id_to_window.get(wid)
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
            elif window.is_OR():
                # code more or less duplicated from _send_new_or_window_packet:
                x, y, w, h = window.get_property("geometry")
                wprops = self.client_properties.get(wid, {}).get(ss.uuid, {})
                ss.new_window("new-override-redirect", wid, window, x, y, w, h, wprops)
                ss.damage(wid, window, 0, 0, w, h)
            else:
                # code more or less duplicated from send_new_window_packet:
                if not sharing:
                    window.hide()
                x, y, w, h = window.get_property("geometry")
                wprops = self.client_properties.get(wid, {}).get(ss.uuid, {})
                ss.new_window("new-window", wid, window, x, y, w, h, wprops)

    ######################################################################
    # focus:
    def _process_focus(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not ss:
            return
        wid = packet.get_wid()
        focuslog("process_focus: wid=%#x", wid)
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
        self.add_packets(
            "map-window", "unmap-window",
            "configure-window", "close-window",
            "focus",
            "damage-sequence", "buffer-refresh",
            "window-action",
            main_thread=True)
