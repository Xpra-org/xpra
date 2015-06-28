# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import socket

from xpra.log import Logger
log = Logger("shadow")

from xpra.net.compression import Compressed
from xpra.server.batch_config import DamageBatchConfig
from xpra.util import prettify_plug_name, DONE

DEFAULT_DELAY = 50              #50ms refresh


class RootWindowModel(object):

    def __init__(self, root_window):
        self.window = root_window
        self.property_names = ["title", "class-instance", "client-machine", "window-type", "size-hints", "icon"]
        self.dynamic_property_names = []

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

    def is_shadow(self):
        return True

    def get_default_window_icon(self):
        return None

    def acknowledge_changes(self):
        pass

    def get_image(self, x, y, width, height):
        raise NotImplementedError()

    def get_property_names(self):
        return self.property_names

    def get_dynamic_property_names(self):
        return self.dynamic_property_names

    def get_generic_os_name(self):
        for k,v in {"linux"     : "linux",
                    "darwin"    : "osx",
                    "win"       : "win32",
                    "freebsd"   : "freebsd"}.items():
            if sys.platform.startswith(k):
                return v
        return sys.platform

    def get_property(self, prop):
        if prop=="title":
            return prettify_plug_name(self.window.get_screen().get_display().get_name())
        elif prop=="client-machine":
            return socket.gethostname()
        elif prop=="window-type":
            return ["NORMAL"]
        elif prop=="fullscreen":
            return False
        elif prop=="scaling":
            return None
        elif prop=="opacity":
            return None
        elif prop=="size-hints":
            size = self.window.get_size()
            return {"maximum-size"  : size,
                    "minimum-size"  : size,
                    "base-size" : size}
        elif prop=="class-instance":
            osn = self.get_generic_os_name()
            return ("xpra-%s" % osn, "Xpra-%s" % osn.upper())
        elif prop=="icon":
            #convert it to a cairo surface..
            #because that's what the property is expected to be
            try:
                import gtk.gdk
                from xpra.platform.paths import get_icon
                icon_name = self.get_generic_os_name()+".png"
                icon = get_icon(icon_name)
                log("icon(%s)=%s", icon_name, icon)
                if not icon:
                    return None
                import cairo
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, icon.get_width(), icon.get_height())
                gc = gtk.gdk.CairoContext(cairo.Context(surf))
                gc.set_source_pixbuf(icon, 0, 0)
                gc.paint()
                log("icon=%s", surf)
                return surf
            except:
                log("failed to return window icon")
                return None
        else:
            raise Exception("invalid property: %s" % prop)
        return None

    def connect(self, *args):
        log.warn("ignoring signal connect request: %s", args)

    def disconnect(self, *args):
        log.warn("ignoring signal disconnect request: %s", args)

    def get_dimensions(self):
        return self.window.get_size()

    def get_position(self):
        return 0, 0


class ShadowServerBase(object):

    def __init__(self, root_window):
        self.root = root_window
        self.mapped_at = None
        self.pulseaudio = False
        self.sharing = False
        DamageBatchConfig.ALWAYS = True             #always batch
        DamageBatchConfig.MIN_DELAY = 50            #never lower than 50ms

    def get_server_mode(self):
        return "shadow"

    def make_hello(self, source):
        return {"shadow" : True}


    def get_cursor_data(self):
        return None

    def watch_keymap_changes(self):
        pass

    def start_refresh(self, delay=DEFAULT_DELAY):
        self.timeout_add(delay, self.refresh)

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

    def do_parse_screen_info(self, ss):
        try:
            log.info("client root window size is %sx%s", *ss.desktop_size)
        except:
            log.info("unknown client desktop size")
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

    def load_existing_windows(self, system_tray):
        log("loading existing windows")
        self.root_window_model = self.makeRootWindowModel()
        self._add_new_window(self.root_window_model)

    def makeRootWindowModel(self):
        return RootWindowModel(self.root)

    def send_windows_and_cursors(self, ss, sharing=False):
        log("send_windows_and_cursors(%s, %s) will send: %s", ss, sharing, self._id_to_window)
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

    def _process_close_window(self, proto, packet):
        wid = packet[1]
        self._process_window_common(wid)
        self.disconnect_client(proto, DONE, "closed the only window")

    def make_screenshot_packet(self):
        w, h, encoding, rowstride, data = self.root_window_model.take_screenshot()
        assert encoding=="png"  #use fixed encoding for now
        return ["screenshot", w, h, encoding, rowstride, Compressed(encoding, data)]
