# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket

from xpra.log import Logger
log = Logger()

from xpra.net.protocol import Compressed
from xpra.server.batch_config import DamageBatchConfig
from xpra.util import AdHocStruct


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

    def uses_XShm(self):
        return False

    def acknowledge_changes(self):
        pass

    def get_image(self, x, y, width, height):
        raise NotImplementedError()

    def get_property_names(self):
        return ("title", "client-machine", "window-type", "size-hints")

    def get_property(self, prop):
        if prop=="title":
            return self.window.get_screen().get_display().get_name()
        elif prop=="client-machine":
            return socket.gethostname()
        elif prop=="window-type":
            return ["NORMAL"]
        elif prop=="fullscreen":
            return False
        elif prop=="scaling":
            return None
        elif prop=="size-hints":
            size = self.window.get_size()
            return RootSizeHints(size)
        else:
            raise Exception("invalid property: %s" % prop)
        return None

    def connect(self, *args):
        log("ignoring signal connect request: %s", args)

    def get_dimensions(self):
        return self.window.get_size()

    def get_position(self):
        return 0, 0

class RootSizeHints(AdHocStruct):

    def __init__(self, size):
        self.max_size = size
        self.min_size = size
        self.base_size = size
        for x in ("resize_inc", "min_aspect", "max_aspect", "min_aspect_ratio", "max_aspect_ratio"):
            setattr(self, x, None)

    def to_dict(self):
        return self.__dict__


class ShadowServerBase(object):

    def __init__(self, root_window):
        self.root = root_window
        self.mapped_at = None
        self.pulseaudio = False
        self.sharing = False
        DamageBatchConfig.ALWAYS = True             #always batch
        DamageBatchConfig.MIN_DELAY = 50            #never lower than 50ms
        DamageBatchConfig.RECALCULATE_DELAY = 0.1   #re-compute delay 10 times per second at most

    def get_server_type(self):
        return "shadow"


    def watch_keymap_changes(self):
        pass

    def calculate_workarea(self):
        pass

    def start_refresh(self):
        self.timeout_add(50, self.refresh)

    def timeout_add(self, *args):
        #usually done via gobject
        raise NotImplementedError("subclasses should define this method!")


    def refresh(self):
        if not self.mapped_at:
            return False
        w, h = self.root.get_size()
        self._damage(self.root_window_model, 0, 0, w, h)
        return True

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

    def set_keyboard_repeat(self, key_repeat):
        """ don't override the existing desktop """
        pass

    def set_best_screen_size(self):
        """ we don't change resolutions when shadowing """
        return self.root_window_model.get_dimensions()

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
        self.mapped_at = x, y, width, height
        self._damage(window, 0, 0, width, height)
        if len(packet)>=7:
            self._set_client_properties(proto, wid, self.root_window_model, packet[6])
        self.start_refresh()

    def _process_unmap_window(self, proto, packet):
        wid = packet[1]
        window = self._process_window_common(wid)
        for ss in self._server_sources.values():
            ss.unmap_window(wid, window)
        self.mapped_at = None

    def _process_configure_window(self, proto, packet):
        wid, x, y, w, h = packet[1:6]
        window = self._process_window_common(wid)
        self.mapped_at = x, y, w, h
        self._damage(window, 0, 0, w, h)
        if len(packet)>=7:
            self._set_client_properties(proto, wid, self.root_window_model, packet[6])

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
        w, h, encoding, rowstride, data = self.root_window_model.take_screenshot()
        assert encoding=="png"  #use fixed encoding for now
        return ["screenshot", w, h, encoding, rowstride, Compressed(encoding, data)]
