# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2016-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from gi.repository import Gtk   #pylint: disable=no-name-in-module

from xpra.util import envbool, prettify_plug_name, csv, parse_simple_dict, XPRA_APP_ID
from xpra.os_util import POSIX, OSX
from xpra.scripts.config import parse_bool
from xpra.server import server_features
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.server.gtk_server_base import GTKServerBase
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.codecs.codec_constants import TransientCodecException, CodecStateException
from xpra.gtk_common.gtk_util import get_screen_sizes, get_icon_pixbuf
from xpra.net.compression import Compressed
from xpra.log import Logger

traylog = Logger("tray")
mouselog = Logger("mouse")
notifylog = Logger("notify")
screenlog = Logger("screen")
log = Logger("shadow")

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
        GTKServerBase.cleanup(self)     #@UndefinedVariable


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


    def make_hello(self, source):
        caps = ShadowServerBase.make_hello(self, source)
        caps.update(GTKServerBase.make_hello(self, source))
        if source.wants_features:
            caps["screen_sizes"] = get_screen_sizes()
        return caps


    def refresh(self):
        log("refresh() mapped=%s, capture=%s", self.mapped, self.capture)
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
            self.refresh_window(window)
        return True


    ############################################################################
    # handle monitor changes

    def send_updated_screen_size(self):
        log("send_updated_screen_size")
        super().send_updated_screen_size()
        if server_features.windows:
            self.recreate_window_models()

    def recreate_window_models(self):
        #remove all existing models and re-create them:
        for model in tuple(self._window_to_id.keys()):
            self._remove_window(model)
        self.cleanup_capture()
        for model in self.makeRootWindowModels():
            self._add_new_window(model)


    def setup_capture(self):
        raise NotImplementedError()

    def get_root_window_model_class(self):
        return RootWindowModel

    def get_shadow_monitors(self):
        display = self.root.get_display()
        screen = self.root.get_screen()
        n = display.get_n_monitors()
        monitors = []
        for i in range(n):
            m = display.get_monitor(i)
            geom = m.get_geometry()
            try:
                scale_factor = m.get_scale_factor()
            except Exception as e:
                screenlog("no scale factor: %s", e)
                scale_factor = 1
            else:
                screenlog("scale factor for monitor %i: %i", i, scale_factor)
            plug_name = None
            try:
                plug_name = screen.get_monitor_plug_name(i)
            except Exception:
                pass
            if not plug_name:
                plug_name = m.get_model()
            monitors.append((plug_name, geom.x, geom.y, geom.width, geom.height, scale_factor))
        screenlog("get_shadow_monitors()=%s", monitors)
        return monitors

    def makeRootWindowModels(self):
        screenlog("makeRootWindowModels() root=%s, display_options=%s", self.root, self.display_options)
        self.capture = self.setup_capture()
        model_class = self.get_root_window_model_class()
        models = []
        display_name = prettify_plug_name(self.root.get_screen().get_display().get_name())
        monitors = self.get_shadow_monitors()
        match_str = None
        multi_window = MULTI_WINDOW
        geometries = None
        def parse_geometry(s):
            try:
                parts = s.split("@")
                if len(parts)==1:
                    x = y = 0
                else:
                    x, y = [int(v.strip(" ")) for v in parts[1].split("x")]
                w, h = [int(v.strip(" ")) for v in parts[0].split("x")]
                geometry = [x, y, w, h]
                screenlog("capture geometry: %s", geometry)
                return geometry
            except ValueError:
                screenlog("failed to parse geometry %r", s, exc_info=True)
                screenlog.error("Error: invalid display geometry specified: %r", s)
                screenlog.error(" use the format: WIDTHxHEIGHT@x,y")
                raise
        def parse_geometries(s):
            g = []
            for geometry_str in s.split("/"):
                if geometry_str:
                    g.append(parse_geometry(geometry_str))
            return g
        if "=" in self.display_options:
            #parse the display options as a dictionary:
            opt_dict = parse_simple_dict(self.display_options)
            match_str = opt_dict.get("plug")
            multi_window = parse_bool("multi-window", opt_dict.get("multi-window", multi_window))
            geometries_str = opt_dict.get("geometry")
            if geometries_str:
                geometries = parse_geometries(geometries_str)
        else:
            try:
                geometries = parse_geometries(self.display_options)
            except:
                match_str = self.display_options
        if not multi_window or geometries:
            for geometry in (geometries or (None,)):
                model = model_class(self.root, self.capture)
                model.title = display_name
                if geometry:
                    model.geometry = geometry
                models.append(model)
            return models
        found = []
        screenlog("capture inputs matching %r", match_str or "all")
        for i, monitor in enumerate(monitors):
            plug_name, x, y, width, height, scale_factor = monitor
            title = display_name
            if plug_name or i>1:
                title = plug_name or str(i)
            found.append(plug_name or title)
            if match_str and not(title in match_str or plug_name in match_str):
                screenlog.info(" skipped monitor %s", plug_name or title)
                continue
            model = model_class(self.root, self.capture)
            model.title = title
            model.geometry = (x, y, width, height)
            models.append(model)
            screenlog("monitor %i: %10s geometry=%s, scale factor=%s", i, title, model.geometry, scale_factor)
        screenlog("makeRootWindowModels()=%s", models)
        if not models and match_str:
            screenlog.warn("Warning: no monitors found matching %r", match_str)
            screenlog.warn(" only found: %s", csv(found))
        return models


    def _adjust_pointer(self, proto, wid, opointer):
        window = self._id_to_window.get(wid)
        if not window:
            self.suspend_cursor(proto)
            return None
        pointer = super()._adjust_pointer(proto, wid, opointer)
        #the window may be at an offset (multi-window for multi-monitor):
        wx, wy, ww, wh = window.get_geometry()
        #or maybe the pointer is off-screen:
        x, y = pointer[:2]
        if x<0 or x>=ww or y<0 or y>=wh:
            self.suspend_cursor(proto)
            return None
        self.restore_cursor(proto)
        #note: with x11 shadow servers,
        # X11ServerCore._get_pointer_abs_coordinates() will recalculate
        # the absolute coordinates from the relative ones,
        # and it should end up with the same values we calculated here
        ax = x+wx
        ay = y+wy
        return [ax, ay]+list(pointer[2:])

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
        if OSX:
            return
        try:
            #menu:
            label = "Xpra Shadow Server"
            display = os.environ.get("DISPLAY")
            if POSIX and display:
                label = "Xpra %s Shadow Server" % display
            self.tray_menu = Gtk.Menu()
            self.tray_menu.set_title(label)
            title_item = Gtk.MenuItem()
            title_item.set_label(label)
            title_item.set_sensitive(False)
            title_item.show()
            self.tray_menu.append(title_item)
            from xpra.gtk_common.about import about
            self.tray_menu.append(self.traymenuitem("About Xpra", "information.png", None, about))
            if server_features.windows:
                def readonly_toggled(menuitem):
                    log("readonly_toggled(%s)", menuitem)
                    ro = menuitem.get_active()
                    if ro!=self.readonly:
                        self.readonly = ro
                        self.setting_changed("readonly", ro)
                readonly_menuitem = self.checkitem("Read-only", cb=readonly_toggled, active=self.readonly)
                self.tray_menu.append(readonly_menuitem)
            self.tray_menu.append(self.traymenuitem("Exit", "quit.png", None, self.tray_exit_callback))
            self.tray_menu.append(self.traymenuitem("Close Menu", "close.png", None, self.close_tray_menu))
            #maybe add: session info, clipboard, sharing, etc
            #control: disconnect clients
            self.tray_menu.connect("deactivate", self.tray_menu_deactivated)
            self.tray_widget = self.make_tray_widget()
            self.set_tray_icon(self.tray_icon  or "server-notconnected")
        except ImportError as e:
            traylog.warn("Warning: failed to load systemtray:")
            traylog.warn(" %s", e)
        except Exception as e:
            traylog("error setting up %s", self.tray_widget, exc_info=True)
            traylog.error("Error setting up system tray:")
            traylog.error(" %s", e)


    def make_tray_widget(self):
        from xpra.platform.gui import get_native_system_tray_classes
        classes = get_native_system_tray_classes()
        try:
            from xpra.client.gtk_base.statusicon_tray import GTKStatusIconTray
            classes.append(GTKStatusIconTray)
        except ImportError:
            traylog("no GTKStatusIconTray", exc_info=True)
        traylog("tray classes: %s", classes)
        if not classes:
            traylog.error("Error: no system tray implementation available")
            return None
        errs = []
        for c in classes:
            try:
                w = c(self, XPRA_APP_ID, self.tray, "Xpra Shadow Server",
                      None, None, self.tray_click_callback, mouseover_cb=None, exit_cb=self.tray_exit_callback)
                return w
            except Exception as e:
                errs.append((c, e))
        traylog.error("Error: all system tray implementations have failed")
        for c, e in errs:
            traylog.error(" %s: %s", c, e)
        return None


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

    def checkitem(self, title, cb=None, active=False):
        check_item = Gtk.CheckMenuItem(label=title)
        check_item.set_active(active)
        if cb:
            check_item.connect("toggled", cb)
        check_item.show()
        return check_item

    def get_image(self, icon_name, size=None):
        from xpra.gtk_common.gtk_util import scaled_image
        try:
            pixbuf = get_icon_pixbuf(icon_name)
            traylog("get_image(%s, %s) pixbuf=%s", icon_name, size, pixbuf)
            if not pixbuf:
                return  None
            return scaled_image(pixbuf, size)
        except Exception:
            traylog.error("get_image(%s, %s)", icon_name, size, exc_info=True)
            return  None


    def tray_menu_deactivated(self, *_args):
        self.tray_menu_shown = False

    def tray_click_callback(self, button, pressed, time=0):
        traylog("tray_click_callback(%s, %s, %i) tray menu=%s, shown=%s",
                button, pressed, time, self.tray_menu, self.tray_menu_shown)
        if pressed:
            self.close_tray_menu()
        else:
            #status icon can give us a position function:
            #except this doesn't work and nothing happens!
            #position_menu = self.tray_widget.tray_widget.position_menu
            #pos = position_menu(self.tray_menu, x, y, self.tray_widget.tray_widget)
            if POSIX and not OSX:
                self.tray_menu.popup_at_pointer()
            else:
                self.tray_menu.popup(None, None, None, None, button, time)
            self.tray_menu_shown = True

    def tray_exit_callback(self, *_args):
        self.close_tray_menu()
        self.idle_add(self.clean_quit, False)

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
