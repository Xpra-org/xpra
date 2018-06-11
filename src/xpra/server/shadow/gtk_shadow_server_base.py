# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2016-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
traylog = Logger("tray")
mouselog = Logger("mouse")
notifylog = Logger("notify")
log = Logger("shadow")

from xpra.util import envbool
from xpra.os_util import POSIX, OSX
from xpra.gtk_common.gobject_compat import is_gtk3
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.server.gtk_server_base import GTKServerBase
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.codecs.codec_constants import TransientCodecException, CodecStateException
from xpra.net.compression import Compressed


MULTI_WINDOW = envbool("XPRA_SHADOW_MULTI_WINDOW", True)


class GTKShadowServerBase(ShadowServerBase, GTKServerBase):

    def __init__(self):
        from xpra.gtk_common.gtk_util import get_default_root_window
        ShadowServerBase.__init__(self, get_default_root_window())
        GTKServerBase.__init__(self)
        self.session_type = "shadow"
        #for managing the systray
        self.tray_menu = None
        self.tray_menu_shown = False
        self.tray_widget = None
        self.tray = False
        self.tray_icon = None

    def init(self, opts):
        GTKServerBase.init(self, opts)
        ShadowServerBase.init(self, opts)
        self.tray = opts.tray
        self.tray_icon = opts.tray_icon
        if self.tray:
            self.setup_tray()

    def cleanup(self):
        self.cleanup_tray()
        ShadowServerBase.cleanup(self)
        GTKServerBase.cleanup(self)


    def client_startup_complete(self, ss):
        GTKServerBase.client_startup_complete(self, ss)
        if not self.tray_icon:
            self.set_tray_icon("server-connected")

    def last_client_exited(self):
        log("last_client_exited() mapped=%s", self.mapped)
        for wid in tuple(self.mapped):
            self.stop_refresh(wid)
        #revert to default icon:
        if not self.tray_icon:
            self.set_tray_icon("server-notconnected")
        GTKServerBase.last_client_exited(self)


    def refresh(self):
        if not self.mapped:
            self.refresh_timer = None
            return False
        if self.capture:
            try:
                if not self.capture.refresh():
                    #capture doesn't have any screen updates,
                    #so we can skip calling damage
                    #(this shortcut is only used with nvfbc)
                    return False
            except TransientCodecException as e:
                log("refresh()", exc_info=True)
                log.warn("Warning: transient codec exception:")
                log.warn(" %s", e)
                self.recreate_window_models()
                return False
            except CodecStateException:
                log("refresh()", exc_info=True)
                log.warn("Warning: codec state exception:")
                log.warn(" %s", e)
                self.recreate_window_models()
                return False
        for window in self._id_to_window.values():
            w, h = window.get_dimensions()
            self._damage(window, 0, 0, w, h)
        return True


    ############################################################################
    # handle monitor changes

    def send_updated_screen_size(self):
        log("send_updated_screen_size")
        super(GTKShadowServerBase, self).send_updated_screen_size()
        from xpra.server import server_features
        if server_features.windows:
            self.recreate_window_models()

    def recreate_window_models(self):
        #remove all existing models and re-create them:
        for model in self._id_to_window.values():
            self._remove_window(model)
        self.cleanup_capture()
        for model in self.makeRootWindowModels():
            self._add_new_window(model)


    def setup_capture(self):
        raise NotImplementedError()

    def makeRootWindowModels(self):
        log("makeRootWindowModels() root=%s", self.root)
        self.capture = self.setup_capture()
        if not MULTI_WINDOW:
            return (RootWindowModel(self.root, self.capture),)
        models = []
        screen = self.root.get_screen()
        n = screen.get_n_monitors()
        for i in range(n):
            geom = screen.get_monitor_geometry(i)
            x, y, width, height = geom.x, geom.y, geom.width, geom.height
            try:
                scale_factor = screen.get_monitor_scale_factor(i)
            except Exception as e:
                log("no scale factor: %s", e)
            else:
                log("scale factor for monitor %i: %i", i, scale_factor)
            model = RootWindowModel(self.root, self.capture)
            if hasattr(screen, "get_monitor_plug_name"):
                plug_name = screen.get_monitor_plug_name(i)
                if plug_name or n>1:
                    model.title = plug_name or str(i)
            model.geometry = (x, y, width, height)
            models.append(model)
        log("makeRootWindowModels()=%s", models)
        return models


    def _adjust_pointer(self, proto, wid, pointer):
        window = self._id_to_window.get(wid)
        if not window:
            return None
        pointer = super(GTKShadowServerBase, self)._adjust_pointer(proto, wid, pointer)
        #the window may be at an offset (multi-window for multi-monitor):
        wx, wy, ww, wh = window.geometry
        #or maybe the pointer is off-screen:
        x, y = pointer
        ax = x+wx
        ay = y+wy
        if ax<0 or ax>=ww or ay<0 or ay>=wh:
            return None
        return ax, ay

    def get_pointer_position(self):
        return self.root.get_pointer()[-3:-1]


    def get_notification_tray(self):
        return self.tray_widget

    def get_notifier_classes(self):
        ncs = ShadowServerBase.get_notifier_classes(self)
        try:
            from xpra.gtk_common.gtk_notifier import GTK_Notifier
            ncs.append(GTK_Notifier)
        except Exception as e:
            notifylog("get_notifier_classes()", exc_info=True)
            notifylog.warn("Warning: cannot load GTK notifier:")
            notifylog.warn(" %s", e)
        return ncs


    ############################################################################
    # system tray methods, mostly copied from the gtk client...
    # (most of these should probably be moved to a common location instead)

    def cleanup_tray(self):
        tw = self.tray_widget
        traylog("cleanup_tray() tray_widget=%s", tw)
        if tw:
            self.tray_widget = None
            tw.cleanup()

    def setup_tray(self):
        try:
            from xpra.gtk_common.gobject_compat import import_gtk
            gtk = import_gtk()
            from xpra.gtk_common.gtk_util import popup_menu_workaround
            #menu:
            self.tray_menu = gtk.Menu()
            self.tray_menu.set_title("Xpra Server")
            from xpra.gtk_common.about import about
            self.tray_menu.append(self.traymenuitem("About Xpra", "information.png", None, about))
            self.tray_menu.append(self.traymenuitem("Exit", "quit.png", None, self.tray_exit_callback))
            self.tray_menu.append(self.traymenuitem("Close Menu", "close.png", None, self.close_tray_menu))
            #maybe add: session info, clipboard, sharing, etc
            #control: disconnect clients
            self.tray_menu.connect("deactivate", self.tray_menu_deactivated)
            popup_menu_workaround(self.tray_menu, self.close_tray_menu)
            self.tray_widget = self.make_tray_widget()
            self.set_tray_icon(self.tray_icon  or "server-notconnected")
        except ImportError as e:
            traylog.warn("Warning: failed to load systemtray:")
            traylog.warn(" %s", e)
        except Exception as e:
            traylog.error("Error setting up system tray", exc_info=True)

    def make_tray_widget(self):
        raise NotImplementedError()


    def set_tray_icon(self, filename):
        if not self.tray_widget:
            return
        try:
            self.tray_widget.set_icon(filename)
        except Exception as e:
            traylog.warn("Warning: failed to set tray icon to %s", filename)
            traylog.warn(" %s", e)


    def traymenuitem(self, title, icon_name=None, tooltip=None, cb=None):
        """ Utility method for easily creating an ImageMenuItem """
        from xpra.gtk_common.gtk_util import menuitem
        image = None
        if icon_name:
            from xpra.platform.gui import get_icon_size
            icon_size = get_icon_size()
            image = self.get_image(icon_name, icon_size)
        return menuitem(title, image, tooltip, cb)

    def get_pixbuf(self, icon_name):
        from xpra.platform.paths import get_icon_filename
        from xpra.gtk_common.gtk_util import pixbuf_new_from_file
        try:
            if not icon_name:
                traylog("get_pixbuf(%s)=None", icon_name)
                return None
            icon_filename = get_icon_filename(icon_name)
            traylog("get_pixbuf(%s) icon_filename=%s", icon_name, icon_filename)
            if icon_filename:
                return pixbuf_new_from_file(icon_filename)
        except:
            traylog.error("get_pixbuf(%s)", icon_name, exc_info=True)
        return  None

    def get_image(self, icon_name, size=None):
        from xpra.gtk_common.gtk_util import scaled_image
        try:
            pixbuf = self.get_pixbuf(icon_name)
            traylog("get_image(%s, %s) pixbuf=%s", icon_name, size, pixbuf)
            if not pixbuf:
                return  None
            return scaled_image(pixbuf, size)
        except:
            traylog.error("get_image(%s, %s)", icon_name, size, exc_info=True)
            return  None


    def tray_menu_deactivated(self, *_args):
        self.tray_menu_shown = False

    def tray_click_callback(self, button, pressed, time=0):
        traylog("tray_click_callback(%s, %s, %i) tray menu=%s, shown=%s", button, pressed, time, self.tray_menu, self.tray_menu_shown)
        if pressed:
            self.close_tray_menu()
        else:
            if is_gtk3():
                #status icon can give us a position function:
                #except this doesn't work and nothing happens!
                #position_menu = self.tray_widget.tray_widget.position_menu
                #pos = position_menu(self.tray_menu, x, y, self.tray_widget.tray_widget)
                if POSIX and not OSX:
                    self.tray_menu.popup_at_pointer()
                else:
                    self.tray_menu.popup(None, None, None, None, button, time)
            else:
                self.tray_menu.popup(None, None, None, button, time)
            self.tray_menu_shown = True

    def tray_exit_callback(self, *_args):
        self.clean_quit(False)

    def close_tray_menu(self, *_args):
        if self.tray_menu_shown:
            self.tray_menu.popdown()
            self.tray_menu_shown = False


    ############################################################################
    # screenshot
    def do_make_screenshot_packet(self):
        assert len(self._id_to_window)==1, "multi root window screenshot not implemented yet"
        rwm = self._id_to_window.values()[0]
        w, h, encoding, rowstride, data = rwm.take_screenshot()
        assert encoding=="png"  #use fixed encoding for now
        return ["screenshot", w, h, encoding, rowstride, Compressed(encoding, data)]
