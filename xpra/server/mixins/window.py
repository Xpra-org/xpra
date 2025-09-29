# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

from typing import Dict, Any, Optional, Tuple

from xpra.util import typedict
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.server.source.windows import WindowsMixin
from xpra.net.common import PacketType
from xpra.log import Logger

log = Logger("window")
focuslog = Logger("focus")
metalog = Logger("metadata")
geomlog = Logger("geometry")
eventslog = Logger("events")


class WindowServer(StubServerMixin):
    """
    Mixin for servers that forward windows.
    """

    def __init__(self):
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1
        self._window_to_id : Dict[Any,int] = {}
        self._id_to_window : Dict[int,Any] = {}
        self.window_filters = []
        self.window_min_size = 0, 0
        self.window_max_size = 2**15-1, 2**15-1

    def init(self, opts) -> None:
        def parse_window_size(v, default_value=(0, 0)):
            try:
                #split on "," or "x":
                pv = tuple(int(x.strip()) for x in v.replace(",", "x").split("x", 1))
                assert len(pv)==2
                w, h = pv
                if w<=0 or h<=0 or w>=32768 or h>=32768:
                    raise ValueError(f"invalid window size {w}x{h}")
                return w, h
            except Exception:
                return default_value
        self.window_min_size = parse_window_size(opts.min_size, (0, 0))
        self.window_max_size = parse_window_size(opts.max_size, (2**15-1, 2**15-1))
        minw, minh = self.window_min_size
        maxw, maxh = self.window_max_size
        self.update_size_constraints(minw, minh, maxw, maxh)

    def setup(self) -> None:
        self.load_existing_windows()
        self.add_init_thread_callback(self.reinit_window_encoders)

    def cleanup(self) -> None:
        for window in tuple(self._window_to_id.keys()):
            window.unmanage()
        #this can cause errors if we receive packets during shutdown:
        #self._window_to_id = {}
        #self._id_to_window = {}


    def reinit_window_encoders(self) -> None:
        #any window mapped before the threaded init completed
        #may need to re-initialize its list of encoders:
        log("reinit_window_encoders()")
        for ss in self._server_sources.values():
            if isinstance(ss, WindowsMixin):
                ss.reinit_encoders()


    def last_client_exited(self) -> None:
        self._focus(None, 0, [])


    def get_server_features(self, _source) -> Dict[str,Any]:
        return {
            "window_refresh_config" : True,     #v4 clients assume this is available
            "window-filters"        : True,     #v4 clients assume this is available
            }

    def get_info(self, _proto) -> Dict[str,Any]:
        return {
            "state" : {
                "windows" : sum(int(window.is_managed()) for window in tuple(self._id_to_window.values())),
                },
            "filters" : tuple((uuid,repr(f)) for uuid, f in self.window_filters),
            }

    def get_ui_info(self, _proto, _client_uuids=None, wids=None, *_args) -> Dict[str,Any]:
        """ info that must be collected from the UI thread
            (ie: things that query the display)
        """
        return {"windows" : self.get_windows_info(wids)}


    def parse_hello(self, ss, caps:typedict, send_ui) -> None:
        if send_ui:
            self.parse_hello_ui_window_settings(ss, caps)

    def parse_hello_ui_window_settings(self, ss, c:typedict) -> None:
        pass


    def add_new_client(self, *_args) -> None:
        minw, minh = self.window_min_size
        maxw, maxh = self.window_max_size
        for ss in tuple(self._server_sources.values()):
            if not isinstance(ss, WindowsMixin):
                continue
            cminw, cminh = ss.window_min_size
            cmaxw, cmaxh = ss.window_max_size
            minw = max(minw, cminw)
            minh = max(minh, cminh)
            if cmaxw>0:
                maxw = min(maxw, cmaxw)
            if cmaxh>0:
                maxh = min(maxh, cmaxh)
        maxw = max(1, maxw)
        maxh = max(1, maxh)
        if minw>0 and minw>maxw:
            maxw = minw
        if minh>0 and minh>maxh:
            maxh = minh
        self.update_size_constraints(minw, minh, maxw, maxh)

    def update_size_constraints(self, minw:int, minh:int, maxw:int, maxh:int) -> None:
        #subclasses may update the window models
        pass


    def send_initial_data(self, ss, caps, send_ui:bool, share_count:int) -> None:
        if not send_ui:
            return
        if not isinstance(ss, WindowsMixin):
            return
        self.send_initial_windows(ss, share_count>0)
        self.send_initial_cursors(ss, share_count>0)


    def is_shown(self, _window) -> bool:
        return True


    def get_window_id(self, _gdkwindow) -> int:
        #the X11 server can find the model from the window's xid
        return 0


    def reset_window_filters(self) -> None:
        self.window_filters = []


    def get_windows_info(self, window_ids) -> Dict[int,Dict[str,Any]]:
        info = {}
        for wid, window in self._id_to_window.items():
            if window_ids is not None and wid not in window_ids:
                continue
            info[wid] = self.get_window_info(window)
        return info

    def get_window_info(self, window) -> Dict[str,Any]:
        from xpra.server.window.metadata import make_window_metadata
        info = {}
        for prop in window.get_property_names():
            if prop=="icons" or prop is None:
                continue
            metadata = make_window_metadata(window, prop, skip_defaults=False)
            info.update(metadata)
        for prop in window.get_internal_property_names():
            metadata = make_window_metadata(window, prop, skip_defaults=False)
            info.update(metadata)
        info.update({
             "override-redirect"    : window.is_OR(),
             "tray"                 : window.is_tray(),
             "size"                 : window.get_dimensions(),
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
            return  #window is already gone
        for ss in self._server_sources.values():
            if isinstance(ss, WindowsMixin):
                ss.window_metadata(wid, window, pspec.name)


    def _remove_window(self, window) -> int:
        wid = self._window_to_id[window]
        log("remove_window: %s - %s", wid, window)
        for ss in self._server_sources.values():
            if isinstance(ss, WindowsMixin):
                ss.lost_window(wid, window)
        del self._window_to_id[window]
        del self._id_to_window[wid]
        for ss in self._server_sources.values():
            if isinstance(ss, WindowsMixin):
                ss.remove_window(wid, window)
        self.client_properties.pop(wid, None)
        return wid

    def _add_new_window_common(self, window) -> int:
        wid = self._max_window_id
        self.do_add_new_window_common(wid, window)
        return wid

    def do_add_new_window_common(self, wid:int, window) -> None:
        self._max_window_id = max(self._max_window_id, wid+1)
        props = window.get_dynamic_property_names()
        metalog("add_new_window_common(%s) watching for dynamic properties: %s", window, props)
        for prop in props:
            window.managed_connect("notify::%s" % prop, self._update_metadata)
        self._window_to_id[window] = wid
        self._id_to_window[wid] = window

    def _do_send_new_window_packet(self, ptype, window, geometry) -> None:
        wid = self._window_to_id[window]
        for ss in tuple(self._server_sources.values()):
            if not isinstance(ss, WindowsMixin):
                continue
            wprops = self.client_properties.get(wid, {}).get(ss.uuid)
            x, y, w, h = geometry
            #adjust if the transient-for window is not mapped in the same place by the client we send to:
            if "transient-for" in window.get_property_names():
                transient_for = window.get_property("transient-for")
                if transient_for:
                    window_tf = self.get_window_id(transient_for)
                    parent = self._id_to_window.get(window_tf)
                    parent_ws = ss.get_window_source(window_tf)
                    pos = self.get_window_position(parent)
                    geomlog("transient-for=%s : %s, ws=%s, pos=%s", transient_for, parent, parent_ws, pos)
                    if pos and parent and parent_ws:
                        mapped_at = parent_ws.mapped_at
                        if mapped_at:
                            wx, wy = pos
                            cx, cy = mapped_at[:2]
                            if wx!=cx or wy!=cy:
                                dx, dy = cx-wx, cy-wy
                                if dx or dy:
                                    geomlog("adjusting new window position for client window offset: %s", (dx, dy))
                                    x += dx
                                    y += dy
            ss.new_window(ptype, wid, window, x, y, w, h, wprops)

    def _process_damage_sequence(self, proto, packet : PacketType) -> None:
        packet_sequence, wid, width, height, decode_time = packet[1:6]
        if len(packet)>=7:
            message = packet[6]
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

    def _process_buffer_refresh(self, proto, packet : PacketType) -> None:
        """ can be used for requesting a refresh, or tuning batch config, or both """
        wid, _, qual = packet[1:4]
        if len(packet)>=6:
            options = typedict(packet[4])
            client_properties = packet[5]
        else:
            options = typedict({})
            client_properties = {}
        if wid==-1:
            wid_windows = self._id_to_window
        elif wid in self._id_to_window:
            wid_windows = {wid : self._id_to_window.get(wid)}
        else:
            #may have been destroyed since the request was made
            log("invalid window specified for refresh: %s", wid)
            return
        log("process_buffer_refresh for windows: %s options=%s, client_properties=%s",
            wid_windows, options, client_properties)
        batch_props = options.dictget("batch", {})
        if batch_props or client_properties:
            #change batch config and/or client properties
            self.update_batch_config(proto, wid_windows, typedict(batch_props), client_properties)
        #default to True for backwards compatibility:
        if options.get("refresh-now", True):
            refresh_opts = {"quality"           : qual,
                            "override_options"  : True}
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
        self.idle_add(self._refresh_windows, proto, self._id_to_window, {})

    def refresh_all_windows(self) -> None:
        for ss in tuple(self._server_sources.values()):
            if not isinstance(ss, WindowsMixin):
                self.do_refresh_windows(ss, self._id_to_window)

    def get_window_position(self, _window) -> Optional[Tuple[int,int]]:
        #where the window is actually mapped on the server screen:
        return None

    def _window_mapped_at(self, proto, wid:int, window, coords=None) -> None:
        #record where a window is mapped by a client
        #(in order to support multiple clients and different offsets)
        ss = self.get_server_source(proto)
        if not ss:
            return
        if coords:
            ss.map_window(wid, window, coords)
        else:
            ss.unmap_window(wid, window)


    def _process_map_window(self, proto, packet : PacketType) -> None:
        log.info("_process_map_window(%s, %s)", proto, packet)

    def _process_unmap_window(self, proto, packet : PacketType) -> None:
        log.info("_process_unmap_window(%s, %s)", proto, packet)

    def _process_close_window(self, proto, packet : PacketType) -> None:
        log.info("_process_close_window(%s, %s)", proto, packet)

    def _process_configure_window(self, proto, packet : PacketType) -> None:
        log.info("_process_configure_window(%s, %s)", proto, packet)

    def _get_window_dict(self, wids) -> Dict[int,Any]:
        wd = {}
        for wid in wids:
            window = self._id_to_window.get(wid)
            if window:
                wd[wid] = window
        return wd

    def _process_suspend(self, proto, packet : PacketType) -> None:
        eventslog("suspend(%s)", packet[1:])
        ui = bool(packet[1])
        wd = self._get_window_dict(packet[2])
        ss = self.get_server_source(proto)
        if ss:
            ss.suspend(ui, wd)

    def _process_resume(self, proto, packet : PacketType) -> None:
        eventslog("resume(%s)", packet[1:])
        ui = bool(packet[1])
        wd = self._get_window_dict(packet[2])
        ss = self.get_server_source(proto)
        if ss:
            ss.resume(ui, wd)


    def send_initial_windows(self, ss, sharing=False) -> None:
        raise NotImplementedError()


    def send_initial_cursors(self, ss, sharing=False) -> None:
        pass


    ######################################################################
    # focus:
    def _process_focus(self, proto, packet : PacketType) -> None:
        if self.readonly:
            return
        wid = packet[1]
        focuslog("process_focus: wid=%s", wid)
        if len(packet)>=3:
            modifiers = packet[2]
        else:
            modifiers = None
        ss = self.get_server_source(proto)
        if ss:
            self._focus(ss, wid, modifiers)
            #if the client focused one of our windows, count this as a user event:
            if wid>0:
                ss.user_event()

    def _focus(self, _server_source, wid, modifiers) -> None:
        focuslog("_focus(%s,%s)", wid, modifiers)

    def get_focus(self) -> int:
        #can be overridden by subclasses that do manage focus
        #(ie: not shadow servers which only have a single window)
        #default: no focus
        return -1


    def init_packet_handlers(self) -> None:
        self.add_packet_handlers({
            "map-window" :          self._process_map_window,
            "unmap-window" :        self._process_unmap_window,
            "configure-window" :    self._process_configure_window,
            "close-window" :        self._process_close_window,
            "focus" :               self._process_focus,
            "damage-sequence" :     self._process_damage_sequence,
            "buffer-refresh" :      self._process_buffer_refresh,
            "suspend" :             self._process_suspend,
            "resume" :              self._process_resume,
            })
