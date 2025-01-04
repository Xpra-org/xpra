# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Callable

from xpra.util.screen import prettify_plug_name
from xpra.util.str_fn import csv
from xpra.util.parsing import parse_simple_dict
from xpra.util.env import envbool, SilenceWarningsContext
from xpra.common import XPRA_APP_ID, noop
from xpra.os_util import POSIX, OSX, gi_import
from xpra.scripts.config import str_to_bool
from xpra.server import features
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.server.gtk_server import GTKServerBase
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.codecs.constants import TransientCodecException, CodecStateException
from xpra.gtk.util import get_default_root_window
from xpra.gtk.info import get_screen_sizes
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.net.compression import Compressed
from xpra.log import Logger

GLib = gi_import("GLib")
Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")

traylog = Logger("tray")
notifylog = Logger("notify")
screenlog = Logger("screen")
log = Logger("shadow")

MULTI_WINDOW = envbool("XPRA_SHADOW_MULTI_WINDOW", True)


def parse_geometry(s) -> list[int]:
    try:
        parts = s.split("@")
        if len(parts) == 1:
            x = y = 0
        else:
            x, y = (int(v.strip(" ")) for v in parts[1].split("x"))
        w, h = (int(v.strip(" ")) for v in parts[0].split("x"))
        geometry = [x, y, w, h]
        screenlog("capture geometry: %s", geometry)
        return geometry
    except ValueError:
        screenlog("failed to parse geometry %r", s, exc_info=True)
        screenlog.error("Error: invalid display geometry specified: %r", s)
        screenlog.error(" use the format: WIDTHxHEIGHT@x,y")
        raise


def parse_geometries(s) -> list:
    g = []
    for geometry_str in s.split("/"):
        if geometry_str:
            g.append(parse_geometry(geometry_str))
    return g


def checkitem(title: str, cb: Callable[[Any], None] = noop, active=False) -> Gtk.CheckMenuItem:
    check_item = Gtk.CheckMenuItem(label=title)
    check_item.set_active(active)
    if cb:
        check_item.connect("toggled", cb)
    check_item.show()
    return check_item


def get_icon_image(icon_name: str):
    from xpra.platform.gui import get_icon_size
    size = get_icon_size()
    from xpra.gtk.widget import scaled_image
    with log.trap_error(f"Error loading image from icon {icon_name!r} with size {size}"):
        pixbuf = get_icon_pixbuf(icon_name)
        traylog("get_image(%s, %s) pixbuf=%s", icon_name, size, pixbuf)
        if not pixbuf:
            return None
        return scaled_image(pixbuf, size)


class GTKShadowServerBase(ShadowServerBase, GTKServerBase):

    def __init__(self, attrs: dict[str, str]):
        ShadowServerBase.__init__(self, get_default_root_window())
        GTKServerBase.__init__(self)
        self.session_type = "shadow"
        self.multi_window = str_to_bool(attrs.get("multi-window", True))
        # for managing the systray
        self.tray_menu = None
        self.tray_menu_shown = False
        self.tray_widget = None
        self.tray = False
        self.tray_icon = None

    def init(self, opts) -> None:
        GTKServerBase.init(self, opts)
        ShadowServerBase.init(self, opts)
        self.tray = opts.tray
        self.tray_icon = opts.tray_icon
        if self.tray:
            self.setup_tray()

    def cleanup(self) -> None:
        self.cleanup_tray()
        ShadowServerBase.cleanup(self)
        GTKServerBase.cleanup(self)  # @UndefinedVariable

    def client_startup_complete(self, ss) -> None:
        GTKServerBase.client_startup_complete(self, ss)
        if not self.tray_icon:
            self.set_tray_icon("server-connected")

    def last_client_exited(self) -> None:
        log("last_client_exited() mapped=%s", self.mapped)
        for wid in tuple(self.mapped):
            self.stop_refresh(wid)
        # revert to default icon:
        if not self.tray_icon:
            self.set_tray_icon("server-notconnected")
        GTKServerBase.last_client_exited(self)

    def make_hello(self, source) -> dict[str, Any]:
        caps = ShadowServerBase.make_hello(self, source)
        caps.update(GTKServerBase.make_hello(self, source))
        if "features" in source.wants:
            caps["screen_sizes"] = get_screen_sizes()
        return caps

    def get_info(self, proto=None, *args) -> dict[str, Any]:
        info = ShadowServerBase.get_info(self, proto, *args)
        info.update(GTKServerBase.get_info(self, proto, *args))
        return info

    def accept_client_ssh_agent(self, uuid: str, ssh_auth_sock: str) -> None:
        log("accept_client_ssh_agent: not setting up ssh agent forwarding for shadow servers")

    def refresh(self) -> bool:
        log("refresh() mapped=%s, capture=%s", self.mapped, self.capture)
        if not self.mapped:
            self.refresh_timer = 0
            return False
        self.refresh_window_models()
        if self.capture:
            try:
                if not self.capture.refresh():
                    # capture doesn't have any screen updates,
                    # so we can skip calling damage
                    # (this shortcut is only used with nvfbc)
                    return True
            except TransientCodecException as tce:
                log("refresh()", exc_info=True)
                log.warn("Warning: transient codec exception:")
                log.warn(" %s", tce)
                self.recreate_window_models()
                return False
            except CodecStateException as cse:
                log("refresh()", exc_info=True)
                log.warn("Warning: codec state exception:")
                log.warn(" %s", cse)
                self.recreate_window_models()
                return False
        self.refresh_windows()
        return True

    def refresh_windows(self) -> None:
        for window in self._id_to_window.values():
            self.refresh_window(window)

    ############################################################################
    # handle monitor changes

    def send_updated_screen_size(self) -> None:
        log("send_updated_screen_size")
        super().send_updated_screen_size()
        if features.windows:
            self.recreate_window_models()

    def recreate_window_models(self) -> None:
        # remove all existing models and re-create them:
        for model in tuple(self._window_to_id.keys()):
            self._remove_window(model)
        self.cleanup_capture()
        for model in self.makeRootWindowModels():
            self._add_new_window(model)

    def setup_capture(self):
        raise NotImplementedError()

    def get_root_window_model_class(self) -> type:
        return RootWindowModel

    def get_shadow_monitors(self) -> list[tuple[str, int, int, int, int, int]]:
        display = self.root.get_display()
        if not display:
            return []
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
            plug_name = m.get_model()
            monitors.append((plug_name, geom.x, geom.y, geom.width, geom.height, scale_factor))
        screenlog("get_shadow_monitors()=%s", monitors)
        return monitors

    def makeRootWindowModels(self) -> list:
        screenlog("makeRootWindowModels() root=%s, display_options=%s", self.root, self.display_options)
        self.capture = self.setup_capture()
        if not self.capture:
            raise RuntimeError("failed to instantiate a capture backend")
        log.info(f"capture using {self.capture.get_type()}")
        model_class = self.get_root_window_model_class()
        models = []
        display_name = prettify_plug_name(self.root.get_screen().get_display().get_name())
        monitors = self.get_shadow_monitors()
        match_str = None
        geometries = None
        if "=" in self.display_options:
            # parse the display options as a dictionary:
            opt_dict = parse_simple_dict(self.display_options)
            windows = opt_dict.get("windows")
            if windows:
                self.window_matches = windows.split("/")
                return self.makeDynamicWindowModels()
            match_str = opt_dict.get("plug")
            self.multi_window = str_to_bool(opt_dict.get("multi-window", self.multi_window))
            geometries_str = opt_dict.get("geometry")
            if geometries_str:
                geometries = parse_geometries(geometries_str)
        else:
            try:
                geometries = parse_geometries(self.display_options)
            except ValueError:
                match_str = self.display_options
        log(f"makeRootWindowModels() multi_window={self.multi_window}")
        if not self.multi_window or geometries:
            for geometry in (geometries or (self.root.get_geometry()[:4],)):
                model = model_class(self.root, self.capture, display_name, geometry)
                models.append(model)
            return models
        found = []
        screenlog("capture inputs matching %r", match_str or "all")
        for i, monitor in enumerate(monitors):
            plug_name, x, y, width, height, scale_factor = monitor
            title = display_name
            if plug_name or i > 1:
                title = plug_name or str(i)
            found.append(plug_name or title)
            if match_str and not (title in match_str or plug_name in match_str):
                screenlog.info(" skipped monitor %s", plug_name or title)
                continue
            geometry = (x, y, width, height)
            model = model_class(self.root, self.capture, title, geometry)
            models.append(model)
            screenlog("monitor %i: %10s geometry=%s, scale factor=%s", i, title, geometry, scale_factor)
        screenlog("makeRootWindowModels()=%s", models)
        if not models and match_str:
            screenlog.warn("Warning: no monitors found matching %r", match_str)
            screenlog.warn(" only found: %s", csv(found))
        return models

    def makeDynamicWindowModels(self):
        assert self.window_matches
        raise NotImplementedError("dynamic window shadow is not implemented on this platform")

    def refresh_window_models(self) -> None:
        if not self.window_matches or not features.windows:
            return
        # update the window models which may have changed,
        # some may have disappeared, new ones created,
        # or they may just have changed their geometry:
        try:
            windows = self.makeDynamicWindowModels()
        except Exception as e:
            log("refresh_window_models()", exc_info=True)
            log.error("Error refreshing window models")
            log.estr(e)
            return
        # build a map of window identifier -> window model:
        xid_to_window = {window.get_id(): window for window in windows}
        log("xid_to_window(%s)=%s", windows, xid_to_window)
        sources = self.window_sources()
        for wid, window in tuple(self._id_to_window.items()):
            xid = window.get_id()
            new_model = xid_to_window.pop(xid, None)
            if new_model is None:
                # window no longer exists:
                self._remove_window(window)
                continue
            resized = window.geometry[2:] != new_model.geometry[2:]
            window.geometry = new_model.geometry
            if resized:
                # it has been resized:
                window.geometry = new_model.geometry
                window.notify("size-hints")
                for ss in sources:
                    ss.resize_window(wid, window, window.geometry[2], window.geometry[3])
        # any models left are new windows:
        for window in xid_to_window.values():
            self._add_new_window(window)
            self.refresh_window(window)

    def _adjust_pointer(self, proto, device_id, wid: int, opointer) -> list[int] | None:
        window = self._id_to_window.get(wid)
        if wid > 0 and not window:
            self.suspend_cursor(proto)
            return None
        pointer = super()._adjust_pointer(proto, device_id, wid, opointer)
        ax = x = int(pointer[0])
        ay = y = int(pointer[1])
        if window:
            # the window may be at an offset (multi-window for multi-monitor):
            wx, wy, ww, wh = window.get_geometry()
            # or maybe the pointer is off-screen:
            if x < 0 or x >= ww or y < 0 or y >= wh:
                self.suspend_cursor(proto)
                return None
            # note: with x11 shadow servers,
            # X11ServerCore._get_pointer_abs_coordinates() will recalculate
            # the absolute coordinates from the relative ones,
            # and it should end up with the same values we calculated here
            ax = x + wx
            ay = y + wy
        self.restore_cursor(proto)
        return [ax, ay] + list(pointer[2:])

    def get_pointer_position(self):
        return self.root.get_pointer()[-3:-1]

    def get_notification_tray(self):
        return self.tray_widget

    def get_notifier_classes(self) -> list[type]:
        ncs = list(ShadowServerBase.get_notifier_classes(self))
        try:
            from xpra.gtk.notifier import GTKNotifier  # pylint: disable=import-outside-toplevel
            ncs.append(GTKNotifier)
        except Exception as e:
            notifylog("get_notifier_classes()", exc_info=True)
            notifylog.warn("Warning: cannot load GTK notifier:")
            notifylog.warn(" %s", e)
        return ncs

    ############################################################################
    # system tray methods, mostly copied from the gtk client...
    # (most of these should probably be moved to a common location instead)

    def cleanup_tray(self) -> None:
        tw = self.tray_widget
        traylog("cleanup_tray() tray_widget=%s", tw)
        if tw:
            self.tray_widget = None
            tw.cleanup()

    def setup_tray(self) -> None:
        if OSX:
            return
        display = Gdk.Display.get_default()
        if not display:
            # usually this is wayland shadow server:
            traylog("no access to the display, cannot setup tray")
            return
        try:
            # menu:
            label = "Xpra Shadow Server"
            display = os.environ.get("DISPLAY")
            if POSIX and display:
                label = f"Xpra {display} Shadow Server"
            self.tray_menu = Gtk.Menu()
            with SilenceWarningsContext(DeprecationWarning):
                self.tray_menu.set_title(label)
            title_item = Gtk.MenuItem()
            title_item.set_label(label)
            title_item.set_sensitive(False)
            title_item.show()
            self.tray_menu.append(title_item)

            def show_about(*_args):
                from xpra.gtk.dialogs.about import about  # pylint: disable=import-outside-toplevel
                about()

            self.tray_menu.append(self.traymenuitem("About Xpra", "information.png", cb=show_about))
            if features.windows:
                def readonly_toggled(menuitem) -> None:
                    log("readonly_toggled(%s)", menuitem)
                    ro = menuitem.get_active()
                    if ro != self.readonly:
                        self.readonly = ro
                        self.setting_changed("readonly", ro)

                self.tray_menu.append(checkitem("Read-only", cb=readonly_toggled, active=self.readonly))
            self.tray_menu.append(self.traymenuitem("Exit", "quit.png", cb=self.tray_exit_callback))
            self.tray_menu.append(self.traymenuitem("Close Menu", "close.png", cb=self.close_tray_menu))
            # maybe add: session info, clipboard, sharing, etc
            # control: disconnect clients
            self.tray_menu.connect("deactivate", self.tray_menu_deactivated)
            self.tray_widget = self.make_tray_widget()
            self.set_tray_icon(self.tray_icon or "server-notconnected")
        except ImportError as e:
            traylog("setup_tray()", exc_info=True)
            traylog.warn("Warning: failed to load systemtray:")
            traylog.warn(" %s", e)
        except Exception as e:
            traylog("error setting up %s", self.tray_widget, exc_info=True)
            traylog.error("Error setting up system tray:")
            traylog.estr(e)

    def make_tray_widget(self):
        # pylint: disable=import-outside-toplevel
        from xpra.platform.gui import get_native_system_tray_classes
        classes = get_native_system_tray_classes()
        try:
            from xpra.client.gtk3.statusicon_tray import GTKStatusIconTray
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
                w = c(self, XPRA_APP_ID, self.tray_menu, "Xpra Shadow Server",
                      icon_filename="server-notconnected.png",
                      click_cb=self.tray_click_callback, exit_cb=self.tray_exit_callback)
                if w:
                    traylog(f"server system tray widget using {c}(..)={w}")
                    return w
                traylog(f"{c}(..) returned None")
                errs.append((c, "returned None"))
            except Exception as e:
                traylog(f"{c}(..)", exc_info=True)
                errs.append((c, e))
        traylog.error("Error: all system tray implementations have failed")
        for c, err in errs:
            traylog.error(" %s: %s", c, err)
        return None

    def set_tray_icon(self, filename: str) -> None:
        if not self.tray_widget:
            return
        try:
            self.tray_widget.set_icon(filename)
        except Exception as e:
            traylog.warn("Warning: failed to set tray icon to %s", filename)
            traylog.warn(" %s", e)

    def traymenuitem(self, title: str, icon_name="", tooltip="", cb: Callable = noop) -> Gtk.ImageMenuItem:
        """ Utility method for easily creating an ImageMenuItem """
        # pylint: disable=import-outside-toplevel
        from xpra.gtk.widget import menuitem
        image = None
        if icon_name:
            image = get_icon_image(icon_name)
        return menuitem(title, image, tooltip, cb)

    def tray_menu_deactivated(self, *_args) -> None:
        self.tray_menu_shown = False

    def tray_click_callback(self, button: int, pressed: int, time=0) -> None:
        traylog("tray_click_callback(%s, %s, %i) tray menu=%s, shown=%s",
                button, pressed, time, self.tray_menu, self.tray_menu_shown)
        if pressed:
            self.close_tray_menu()
        else:
            # status icon can give us a position function:
            # except this doesn't work and nothing happens!
            # position_menu = self.tray_widget.tray_widget.position_menu
            # pos = position_menu(self.tray_menu, x, y, self.tray_widget.tray_widget)
            if POSIX and not OSX:
                self.tray_menu.popup_at_pointer()
            else:
                with SilenceWarningsContext(DeprecationWarning):
                    self.tray_menu.popup(None, None, None, None, button, time)
            self.tray_menu_shown = True

    def tray_exit_callback(self, *_args) -> None:
        self.close_tray_menu()
        GLib.idle_add(self.clean_quit, False)

    def close_tray_menu(self, *_args) -> None:
        if self.tray_menu_shown:
            self.tray_menu.popdown()
            self.tray_menu_shown = False

    ############################################################################
    # screenshot
    def do_make_screenshot_packet(self):
        assert len(self._id_to_window) == 1, "multi root window screenshot not implemented yet"
        rwm = self._id_to_window.values()[0]
        w, h, encoding, rowstride, data = rwm.take_screenshot()
        assert encoding == "png"  # use fixed encoding for now
        return ["screenshot", w, h, encoding, rowstride, Compressed(encoding, data)]
