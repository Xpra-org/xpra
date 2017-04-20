# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger("shadow")

from xpra.net.compression import Compressed
from xpra.server.window.batch_config import DamageBatchConfig
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.util import envint, DONE

REFRESH_DELAY = envint("XPRA_SHADOW_REFRESH_DELAY", 50)


class ShadowServerBase(object):

    def __init__(self, root_window):
        self.root = root_window
        self.root_window_model = None
        self.mapped = False
        self.pulseaudio = False
        self.sharing = False
        self.refresh_delay = REFRESH_DELAY
        self.timer = None
        DamageBatchConfig.ALWAYS = True             #always batch
        DamageBatchConfig.MIN_DELAY = 50            #never lower than 50ms

    def cleanup(self):
        self.stop_refresh()
        rwm = self.root_window_model
        if rwm:
            rwm.cleanup()
            self.root_window_model = None


    def get_server_mode(self):
        return "shadow"

    def print_screen_info(self):
        w, h = self.root_window_model.get_dimensions()
        display = os.environ.get("DISPLAY")
        self.do_print_screen_info(display, w, h)

    def do_print_screen_info(self, display, w, h):
        if display:
            log.info(" on display %s of size %ix%i", display, w, h)
        else:
            log.info(" on display of size %ix%i", w, h)

    def make_hello(self, source):
        return {"shadow" : True}

    def get_info(self, proto=None):
        if self.root_window_model:
            return {"root-window" : self.root_window_model.get_info()}
        return {}


    def get_window_position(self, window):
        #we export the whole desktop as a window:
        return 0, 0

    def get_cursor_data(self):
        return None

    def watch_keymap_changes(self):
        pass

    def timeout_add(self, *args):
        #usually done via gobject
        raise NotImplementedError("subclasses should define this method!")

    def source_remove(self, *args):
        #usually done via gobject
        raise NotImplementedError("subclasses should define this method!")

    ############################################################################
    # refresh

    def start_refresh(self):
        self.mapped = True
        self.timer = self.timeout_add(self.refresh_delay, self.refresh)

    def set_refresh_delay(self, v):
        assert v>0 and v<10000
        self.refresh_delay = v
        if self.mapped:
            if self.timer:
                self.source_remove(self.timer)
                self.timer = None
            self.start_refresh()


    def stop_refresh(self):
        log("stop_refresh() mapped=%s, timer=%s", self.mapped, self.timer)
        self.mapped = False
        if self.timer:
            self.source_remove(self.timer)
            self.timer = None

    def refresh(self):
        if not self.mapped:
            self.timer = None
            return False
        w, h = self.root.get_size()
        self._damage(self.root_window_model, 0, 0, w, h)
        return True

    ############################################################################

    def sanity_checks(self, proto, c):
        server_uuid = c.strget("server_uuid")
        if server_uuid:
            if server_uuid==self.uuid:
                log.warn("Warning: shadowing your own display can be quite confusing")
                clipboard = self._clipboard_helper and c.boolget("clipboard", True)
                if clipboard:
                    log.warn("clipboard sharing cannot be enabled! (consider using the --no-clipboard option)")
                    c["clipboard"] = False
            else:
                log.warn("This client is running within the Xpra server %s", server_uuid)
        return True

    def do_parse_screen_info(self, ss):
        try:
            log.info(" client root window size is %sx%s", *ss.desktop_size)
        except:
            log.info(" unknown client desktop size")
        return self.get_root_window_size()

    def _process_desktop_size(self, proto, packet):
        #just record the screen size info in the source
        ss = self._server_sources.get(proto)
        if ss and len(packet)>=4:
            ss.set_screen_sizes(packet[3])


    def set_keyboard_repeat(self, key_repeat):
        """ don't override the existing desktop """
        pass

    def set_keymap(self, server_source, force=False):
        log.info("shadow server: setting default keymap translation")
        self.keyboard_config = server_source.set_default_keymap()

    def load_existing_windows(self):
        log("loading existing windows")
        self.root_window_model = self.makeRootWindowModel()
        self._add_new_window(self.root_window_model)
        w, h = self.root_window_model.get_dimensions()
        self.min_mmap_size = w*h*4*2        #at least big enough for 2 frames of BGRX pixel data

    def makeRootWindowModel(self):
        return RootWindowModel(self.root)

    def send_initial_windows(self, ss, sharing=False):
        log("send_initial_windows(%s, %s) will send: %s", ss, sharing, self._id_to_window)
        for wid in sorted(self._id_to_window.keys()):
            window = self._id_to_window[wid]
            assert window == self.root_window_model, "expected window to be %s, but got %s" % (self.root_window_model, window)
            w, h = self.root.get_size()
            ss.new_window("new-window", wid, window, 0, 0, w, h, self.client_properties.get(ss.uuid))


    def _add_new_window(self, window):
        self._add_new_window_common(window)
        self._send_new_window_packet(window)

    def _send_new_window_packet(self, window):
        assert window == self.root_window_model
        geometry = self.root.get_geometry()[:4]
        self._do_send_new_window_packet("new-window", window, geometry)

    def _process_window_common(self, wid):
        window = self._id_to_window.get(wid)
        assert window is not None
        assert window == self.root_window_model
        return window

    def _process_map_window(self, proto, packet):
        wid, x, y, width, height = packet[1:6]
        window = self._process_window_common(wid)
        self._window_mapped_at(proto, wid, window, (x, y, width, height))
        self._damage(window, 0, 0, width, height)
        if len(packet)>=7:
            self._set_client_properties(proto, wid, self.root_window_model, packet[6])
        self.start_refresh()

    def _process_unmap_window(self, proto, packet):
        wid = packet[1]
        window = self._process_window_common(wid)
        for ss in self._server_sources.values():
            ss.unmap_window(wid, window)
        self._window_mapped_at(proto, wid, window, None)
        self.root_window_model.suspend()

    def _process_configure_window(self, proto, packet):
        wid, x, y, w, h = packet[1:6]
        window = self._process_window_common(wid)
        self._window_mapped_at(proto, wid, window, (x, y, w, h))
        self._damage(window, 0, 0, w, h)
        if len(packet)>=7:
            self._set_client_properties(proto, wid, self.root_window_model, packet[6])

    def _process_close_window(self, proto, packet):
        wid = packet[1]
        self._process_window_common(wid)
        self.disconnect_client(proto, DONE, "closed the only window")


    def do_make_screenshot_packet(self):
        w, h, encoding, rowstride, data = self.root_window_model.take_screenshot()
        assert encoding=="png"  #use fixed encoding for now
        return ["screenshot", w, h, encoding, rowstride, Compressed(encoding, data)]


    def make_dbus_server(self):
        from xpra.server.shadow.shadow_dbus_server import Shadow_DBUS_Server
        return Shadow_DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))
