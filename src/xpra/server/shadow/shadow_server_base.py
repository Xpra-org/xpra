# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger("shadow")
notifylog = Logger("notify")

from xpra.server.window.batch_config import DamageBatchConfig
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.server.rfb.rfb_server import RFBServer
from xpra.notifications.common import parse_image_path
from xpra.platform.gui import get_native_notifier_classes, get_wm_name
from xpra.platform.paths import get_icon_dir
from xpra.util import envint, envbool, DONE


REFRESH_DELAY = envint("XPRA_SHADOW_REFRESH_DELAY", 50)
NATIVE_NOTIFIER = envbool("XPRA_NATIVE_NOTIFIER", True)


class ShadowServerBase(RFBServer):

    def __init__(self, root_window):
        self.root = root_window
        self.mapped = False
        self.pulseaudio = False
        self.sharing = True
        self.refresh_delay = REFRESH_DELAY
        self.refresh_timer = None
        self.notifications = False
        self.notifier = None
        DamageBatchConfig.ALWAYS = True             #always batch
        DamageBatchConfig.MIN_DELAY = 50            #never lower than 50ms
        RFBServer.init(self)

    def init(self, opts):
        self._rfb_upgrade = int(opts.rfb_upgrade)
        self.notifications = bool(opts.notifications)
        if self.notifications:
            self.make_notifier()

    def cleanup(self):
        self.stop_refresh()
        n = self.notifier
        if n:
            n.cleanup()
            self.notifier = None


    def guess_session_name(self, _procs):
        self.session_name = get_wm_name()

    def get_server_mode(self):
        return "shadow"

    def print_screen_info(self):
        w, h = self.root.get_geometry()[2:4]
        display = os.environ.get("DISPLAY")
        self.do_print_screen_info(display, w, h)

    def do_print_screen_info(self, display, w, h):
        if display:
            log.info(" on display %s of size %ix%i", display, w, h)
        else:
            log.info(" on display of size %ix%i", w, h)


    def make_hello(self, _source):
        return {"shadow" : True}

    def get_info(self, _proto=None):
        info = {
            "notifications" : self.notifications,
            }
        return info


    def get_window_position(self, _window):
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
    # notifications
    def notify_setup_error(self, exception):
        notifylog("notify_setup_error(%s)", exception)
        notifylog.info("notification forwarding is not available")

    def make_notifier(self):
        nc = self.get_notifier_classes()
        notifylog("make_notifier() notifier classes: %s", nc)
        for x in nc:
            try:
                self.notifier = x()
                notifylog("notifier=%s", self.notifier)
                break
            except:
                notifylog("failed to instantiate %s", x, exc_info=True)

    def get_notifier_classes(self):
        #subclasses will generally add their toolkit specific variants
        #by overriding this method
        #use the native ones first:
        if not NATIVE_NOTIFIER:
            return []
        return get_native_notifier_classes()

    def notify_new_user(self, ss):
        #overriden here so we can show the notification
        #directly on the screen we shadow
        notifylog("notify_new_user(%s) notifier=%s", ss, self.notifier)
        if self.notifier:
            tray = self.get_notification_tray()
            nid = 0
            title = "User '%s' connected to the session" % (ss.name or ss.username or ss.uuid)
            body = "\n".join(ss.get_connect_info())
            actions = []
            hints = {}
            icon = None
            icon_filename = os.path.join(get_icon_dir(), "user.png")
            if os.path.exists(icon_filename):
                icon = parse_image_path(icon_filename)
            self.notifier.show_notify("", tray, nid, "Xpra", 0, "", title, body, actions, hints, 10*1000, icon)

    def get_notification_tray(self):
        return None


    ############################################################################
    # refresh

    def start_refresh(self):
        self.mapped = True
        if not self.refresh_timer:
            self.refresh_timer = self.timeout_add(self.refresh_delay, self.refresh)

    def set_refresh_delay(self, v):
        assert v>0 and v<10000
        self.refresh_delay = v
        if self.mapped:
            self.cancel_refresh_timer()
            self.start_refresh()


    def stop_refresh(self):
        log("stop_refresh() mapped=%s", self.mapped)
        self.mapped = False
        self.cancel_refresh_timer()

    def cancel_refresh_timer(self):
        t = self.refresh_timer
        log("cancel_refresh_timer() timer=%s", t)
        if t:
            self.refresh_timer = None
            self.source_remove(t)

    def refresh(self):
        raise NotImplementedError()

    ############################################################################

    def sanity_checks(self, _proto, c):
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

    def parse_screen_info(self, ss):
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
        log("set_keymap%s", (server_source, force))
        log.info("shadow server: setting default keymap translation")
        self.keyboard_config = server_source.set_default_keymap()

    def load_existing_windows(self):
        self.min_mmap_size = 1024*1024*4*2
        for i,model in enumerate(self.makeRootWindowModels()):
            log("load_existing_windows() root window model %i: %s", i, model)
            self._add_new_window(model)
            #at least big enough for 2 frames of BGRX pixel data:
            w, h = model.get_dimensions()
            self.min_mmap_size = max(self.min_mmap_size, w*h*4*2)

    def makeRootWindowModels(self):
        return (RootWindowModel(self.root),)

    def send_initial_windows(self, ss, sharing=False):
        log("send_initial_windows(%s, %s) will send: %s", ss, sharing, self._id_to_window)
        for wid in sorted(self._id_to_window.keys()):
            window = self._id_to_window[wid]
            w, h = window.get_dimensions()
            ss.new_window("new-window", wid, window, 0, 0, w, h, self.client_properties.get(wid, {}).get(ss.uuid))


    def _add_new_window(self, window):
        self._add_new_window_common(window)
        self._send_new_window_packet(window)

    def _send_new_window_packet(self, window):
        geometry = window.get_geometry()
        self._do_send_new_window_packet("new-window", window, geometry)

    def _process_window_common(self, wid):
        window = self._id_to_window.get(wid)
        assert window is not None
        return window

    def _process_map_window(self, proto, packet):
        wid, x, y, width, height = packet[1:6]
        window = self._process_window_common(wid)
        self._window_mapped_at(proto, wid, window, (x, y, width, height))
        self._damage(window, 0, 0, width, height)
        if len(packet)>=7:
            self._set_client_properties(proto, wid, window, packet[6])
        self.start_refresh()

    def _process_unmap_window(self, proto, packet):
        wid = packet[1]
        window = self._process_window_common(wid)
        self._window_mapped_at(proto, wid, window, None)
        #TODO: deal with more than one window / more than one client
        #and stop refresh if all the windows are unmapped everywhere
        if len(self._server_sources)<=1 and len(self._id_to_window)<=1:
            self.stop_refresh()

    def _process_configure_window(self, proto, packet):
        wid, x, y, w, h = packet[1:6]
        window = self._process_window_common(wid)
        self._window_mapped_at(proto, wid, window, (x, y, w, h))
        self._damage(window, 0, 0, w, h)
        if len(packet)>=7:
            self._set_client_properties(proto, wid, window, packet[6])

    def _process_close_window(self, proto, packet):
        wid = packet[1]
        self._process_window_common(wid)
        self.disconnect_client(proto, DONE, "closed the only window")


    def do_make_screenshot_packet(self):
        raise NotImplementedError()


    def make_dbus_server(self):
        from xpra.server.shadow.shadow_dbus_server import Shadow_DBUS_Server
        return Shadow_DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))
