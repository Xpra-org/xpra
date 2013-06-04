# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk
import gobject
import socket

from xpra.log import Logger
log = Logger()

from xpra.net.protocol import Compressed
from xpra.server.window_source import DamageBatchConfig
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.gtk_common.pixbuf_to_rgb import get_rgb_rawdata


def take_root_screenshot():
    log("grabbing screenshot")
    root = gtk.gdk.get_default_root_window()
    w,h = root.get_size()
    pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, w, h)
    pixbuf = pixbuf.get_from_drawable(root, root.get_colormap(), 0, 0, 0, 0, w, h)
    def save_to_memory(data, buf):
        buf.append(data)
    buf = []
    pixbuf.save_to_callback(save_to_memory, "png", {}, buf)
    rowstride = w*3
    return w, h, "png", rowstride, "".join(buf)


class RootWindowModel(object):

    def __init__(self, root_window):
        self.window = root_window

    def is_managed(self):
        return True

    def is_tray(self):
        return False

    def is_OR(self):
        return False

    def has_alpha(self):
        return False

    def acknowledge_changes(self):
        pass

    def get_rgb_rawdata(self, x, y, width, height):
        v = get_rgb_rawdata(self.window, x, y, width, height, logger=log)
        if v is None:
            return None
        return ImageWrapper(*v)

    def get_client_contents(self):
        return self.window

    def get_property(self, prop):
        if prop=="title":
            return self.window.get_screen().get_display().get_name()
        elif prop=="client-machine":
            return socket.gethostname()
        elif prop=="window-type":
            return ["NORMAL"]
        elif prop=="size-hints":
            from xpra.util import AdHocStruct
            size = self.window.get_size()
            size_hints = AdHocStruct()
            size_hints.max_size = size
            size_hints.min_size = size
            size_hints.base_size = size
            for x in ("resize_inc", "min_aspect", "max_aspect", "min_aspect_ratio", "max_aspect_ratio"):
                setattr(size_hints, x, None)
            return size_hints
        else:
            raise Exception("invalid property: %s" % prop)
        return None

    def get_dimensions(self):
        return self.window.get_size()


class ShadowServerBase(object):

    def __init__(self):
        self.root = gtk.gdk.get_default_root_window()
        self.mapped_at = None
        self.pulseaudio = False
        self.sharing = False
        DamageBatchConfig.ALWAYS = True             #always batch
        DamageBatchConfig.MIN_DELAY = 50            #never lower than 50ms
        DamageBatchConfig.RECALCULATE_DELAY = 0.1   #re-compute delay 10 times per second at most

    def watch_keymap_changes(self):
        pass

    def calculate_workarea(self):
        pass

    def start_refresh(self):
        gobject.timeout_add(50, self.refresh)

    def refresh(self):
        if not self.mapped_at:
            return False
        w, h = self.root.get_size()
        self._damage(self.root_window_model, 0, 0, w, h)
        return True

    def sanity_checks(self, proto, capabilities):
        server_uuid = capabilities.get("server_uuid")
        if server_uuid:
            if server_uuid==self.uuid:
                log.warn("Warning: shadowing your own display can be quite confusing")
                clipboard = self._clipboard_helper and capabilities.get("clipboard", True)
                if clipboard:
                    log.warn("clipboard sharing cannot be enabled! (consider using the --no-clipboard option)")
                    capabilities["clipboard"] = False
            else:
                log.warn("This client is running within the Xpra server %s", server_uuid)
        return True

    def set_keyboard_repeat(self, key_repeat):
        """ don't override the existing desktop """
        pass

    def set_best_screen_size(self):
        """ we don't change resolutions when shadowing """
        return gtk.gdk.get_default_root_window().get_size()

    def set_keymap(self, server_source, force=False):
        log.info("shadow server: not setting keymap")

    def load_existing_windows(self, system_tray):
        log("loading existing windows")
        self.root_window_model = self.makeRootWindowModel()
        self._add_new_window(self.root_window_model)

    def makeRootWindowModel(self):
        return RootWindowModel(self.root)

    def send_windows_and_cursors(self, ss):
        log("send_windows_and_cursors(%s) will send: %s", ss, self._id_to_window)
        for wid in sorted(self._id_to_window.keys()):
            window = self._id_to_window[wid]
            assert window == self.root_window_model
            w, h = self.root.get_size()
            props = ("title", "client-machine", "size-hints", "window-type", "has-alpha")
            ss.new_window("new-window", wid, window, 0, 0, w, h, props, self.client_properties.get(ss.uuid))
        #ss.send_cursor(self.cursor_data)


    def _add_new_window(self, window):
        self._add_new_window_common(window)
        self._send_new_window_packet(window)

    def _send_new_window_packet(self, window):
        assert window == self.root_window_model
        geometry = self.root.get_geometry()[:4]
        metadata = {}
        self._do_send_new_window_packet("new-window", window, geometry, metadata)


    def _process_window_common(self, wid):
        window = self._id_to_window.get(wid)
        assert window is not None
        assert window == self.root_window_model
        return window

    def _process_map_window(self, proto, packet):
        wid, x, y, width, height = packet[1:6]
        window = self._process_window_common(wid)
        self.mapped_at = x, y, width, height
        self._damage(window, 0, 0, width, height)
        if len(packet)>=7:
            self._set_client_properties(proto, wid, packet[6])
        self.start_refresh()

    def _process_unmap_window(self, proto, packet):
        wid = packet[1]
        window = self._process_window_common(wid)
        self._cancel_damage(wid, window)
        self.mapped_at = None

    def _process_configure_window(self, proto, packet):
        wid, x, y, w, h = packet[1:6]
        window = self._process_window_common(wid)
        self.mapped_at = x, y, w, h
        self._damage(window, 0, 0, w, h)
        if len(packet)>=7:
            self._set_client_properties(proto, wid, packet[6])

    def _process_move_window(self, proto, packet):
        wid, x, y = packet[1:4]
        self._process_window_common(wid)
        assert self.mapped_at
        w, h = self.mapped_at[2:4]
        self.mapped_at = x, y, w, h

    def _process_resize_window(self, proto, packet):
        wid = packet[1]
        self._process_window_common(wid)
        #wid, w, h = packet[1:4]
        #window = self._process_window_common(wid)
        #self._cancel_damage(wid, window)
        #self._damage(window, 0, 0, w, h)

    def _process_close_window(self, proto, packet):
        wid = packet[1]
        self._process_window_common(wid)
        self.disconnect_client(proto, "closed the only window")

    def make_screenshot_packet(self):
        w, h, encoding, rowstride, data = take_root_screenshot()
        assert encoding=="png"  #use fixed encoding for now
        return ["screenshot", w, h, encoding, rowstride, Compressed(encoding, data)]
