# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger
log = Logger("window")
focuslog = Logger("focus")
metalog = Logger("metadata")
geomlog = Logger("geometry")

from xpra.util import typedict
from xpra.server.mixins.stub_server_mixin import StubServerMixin


"""
Mixin for servers that forward windows.
"""
class WindowServer(StubServerMixin):

    def __init__(self):
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1
        self._window_to_id = {}
        self._id_to_window = {}
        self.window_filters = []

    def setup(self):
        self.load_existing_windows()

    def cleanup(self):
        pass
        #this can cause errors if we receive packets during shutdown:
        #self._window_to_id = {}
        #self._id_to_window = {}


    def get_server_features(self, _source):
        return {
            #legacy flags:
            "window_refresh_config" : True,
            "window_unmap"          : True,
            "suspend-resume"        : True,
            #newer flags:
            "window.configure.skip-geometry"    : True,
            "window-filters"        : True,
            }

    def get_info(self, _proto):
        return {
            "state" : {
                "windows" : len([window for window in tuple(self._id_to_window.values()) if window.is_managed()]),
                }
            }

    def parse_hello_ui_window_settings(self, ss, c):
        pass


    def is_shown(self, _window):
        return True


    def add_windows_info(self, info, window_ids):
        winfo = info.setdefault("window", {})
        for wid, window in self._id_to_window.items():
            if window_ids is not None and wid not in window_ids:
                continue
            winfo.setdefault(wid, {}).update(self.get_window_info(window))

    def get_window_info(self, window):
        from xpra.server.window.metadata import make_window_metadata
        info = {}
        for prop in window.get_property_names():
            if prop=="icon" or prop is None:
                continue
            metadata = make_window_metadata(window, prop, get_transient_for=self.get_transient_for)
            info.update(metadata)
        for prop in window.get_internal_property_names():
            metadata = make_window_metadata(window, prop)
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

    def _update_metadata(self, window, pspec):
        metalog("updating metadata on %s: %s", window, pspec)
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.window_metadata(wid, window, pspec.name)


    def _add_new_window_common(self, window):
        props = window.get_dynamic_property_names()
        metalog("add_new_window_common(%s) watching for dynamic properties: %s", window, props)
        for prop in props:
            window.managed_connect("notify::%s" % prop, self._update_metadata)
        wid = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = wid
        self._id_to_window[wid] = window
        return wid

    def _do_send_new_window_packet(self, ptype, window, geometry):
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            wprops = self.client_properties.get(wid, {}).get(ss.uuid)
            x, y, w, h = geometry
            #adjust if the transient-for window is not mapped in the same place by the client we send to:
            if "transient-for" in window.get_property_names():
                transient_for = self.get_transient_for(window)
                if transient_for>0:
                    parent = self._id_to_window.get(transient_for)
                    parent_ws = ss.get_window_source(transient_for)
                    pos = self.get_window_position(parent)
                    geomlog("transient-for=%s : %s, ws=%s, pos=%s", transient_for, parent, parent_ws, pos)
                    if parent and parent_ws and parent_ws.mapped_at and pos:
                        cx, cy = parent_ws.mapped_at[:2]
                        px, py = pos
                        x += cx-px
                        y += cy-py
            ss.new_window(ptype, wid, window, x, y, w, h, wprops)

    def _process_damage_sequence(self, proto, packet):
        packet_sequence, wid, width, height, decode_time = packet[1:6]
        if len(packet)>=7:
            message = packet[6]
        else:
            message = ""
        ss = self._server_sources.get(proto)
        if ss:
            ss.client_ack_damage(packet_sequence, wid, width, height, decode_time, message)

    def _damage(self, window, x, y, width, height, options=None):
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.damage(wid, window, x, y, width, height, options)

    def _process_buffer_refresh(self, proto, packet):
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
        log("process_buffer_refresh for windows: %s options=%s, client_properties=%s", wid_windows, options, client_properties)
        batch_props = options.dictget("batch", {})
        if batch_props or client_properties:
            #change batch config and/or client properties
            self.update_batch_config(proto, wid_windows, typedict(batch_props), client_properties)
        #default to True for backwards compatibility:
        if options.get("refresh-now", True):
            refresh_opts = {"quality"           : qual,
                            "override_options"  : True}
            self.refresh_windows(proto, wid_windows, refresh_opts)


    def update_batch_config(self, proto, wid_windows, batch_props, client_properties):
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        for wid, window in wid_windows.items():
            if window is None or not window.is_managed():
                continue
            self._set_client_properties(proto, wid, window, client_properties)
            ss.update_batch(wid, window, batch_props)

    def refresh_windows(self, proto, wid_windows, opts={}):
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        for wid, window in wid_windows.items():
            if window is None or not window.is_managed():
                continue
            if not self.is_shown(window):
                log("window is no longer shown, ignoring buffer refresh which would fail")
                continue
            ss.refresh(wid, window, opts)

    def _idle_refresh_all_windows(self, proto):
        self.idle_add(self.refresh_windows, proto, self._id_to_window)


    def get_window_position(self, _window):
        #where the window is actually mapped on the server screen:
        return None

    def _window_mapped_at(self, proto, wid, window, coords=None):
        #record where a window is mapped by a client
        #(in order to support multiple clients and different offsets)
        ss = self._server_sources.get(proto)
        if not ss:
            return
        ws = ss.make_window_source(wid, window)
        ws.mapped_at = coords
        #log("window %i mapped at %s for client %s", wid, coords, ss)

    def get_transient_for(self, _window):
        return  None

    def _process_map_window(self, proto, packet):
        log.info("_process_map_window(%s, %s)", proto, packet)

    def _process_unmap_window(self, proto, packet):
        log.info("_process_unmap_window(%s, %s)", proto, packet)

    def _process_close_window(self, proto, packet):
        log.info("_process_close_window(%s, %s)", proto, packet)

    def _process_configure_window(self, proto, packet):
        log.info("_process_configure_window(%s, %s)", proto, packet)

    def _get_window_dict(self, wids):
        wd = {}
        for wid in wids:
            window = self._id_to_window.get(wid)
            if window:
                wd[wid] = window
        return wd

    def _process_suspend(self, proto, packet):
        log("suspend(%s)", packet[1:])
        ui = packet[1]
        wd = self._get_window_dict(packet[2])
        ss = self._server_sources.get(proto)
        if ss:
            ss.suspend(ui, wd)

    def _process_resume(self, proto, packet):
        log("resume(%s)", packet[1:])
        ui = packet[1]
        wd = self._get_window_dict(packet[2])
        ss = self._server_sources.get(proto)
        if ss:
            ss.resume(ui, wd)


    def send_initial_windows(self, ss, sharing=False):
        raise NotImplementedError()


    def send_initial_cursors(self, ss, sharing=False):
        pass


    ######################################################################
    # focus:
    def _process_focus(self, proto, packet):
        if self.readonly:
            return
        wid = packet[1]
        focuslog("process_focus: wid=%s", wid)
        if len(packet)>=3:
            modifiers = packet[2]
        else:
            modifiers = None
        ss = self._server_sources.get(proto)
        if ss:
            self._focus(ss, wid, modifiers)
            #if the client focused one of our windows, count this as a user event:
            if wid>0:
                ss.user_event()

    def _focus(self, _server_source, wid, modifiers):
        focuslog("_focus(%s,%s)", wid, modifiers)

    def get_focus(self):
        #can be overriden by subclasses that do manage focus
        #(ie: not shadow servers which only have a single window)
        #default: no focus
        return -1


    def init_packet_handlers(self):
        self._authenticated_ui_packet_handlers.update({
            "map-window":                           self._process_map_window,
            "unmap-window":                         self._process_unmap_window,
            "configure-window":                     self._process_configure_window,
            "close-window":                         self._process_close_window,
            "focus":                                self._process_focus,
            "damage-sequence":                      self._process_damage_sequence,
            "buffer-refresh":                       self._process_buffer_refresh,
            "suspend":                              self._process_suspend,
            "resume":                               self._process_resume,
            })
