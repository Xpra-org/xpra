# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.util.str_fn import csv
from xpra.util.env import envbool
from xpra.util.gobject import to_gsignals
from xpra.common import noop
from xpra.os_util import gi_import
from xpra.util.parsing import str_to_bool
from xpra.server import features
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.codecs.constants import TransientCodecException, CodecStateException
from xpra.net.compression import Compressed
from xpra.log import Logger

GLib = gi_import("GLib")
GObject = gi_import("GObject")

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


def parse_geometries(s) -> list[list[int]]:
    g = []
    for geometry_str in s.split("/"):
        if geometry_str:
            g.append(parse_geometry(geometry_str))
    return g


class GTKShadowServerBase(GObject.GObject, ShadowServerBase):
    __gsignals__ = to_gsignals(ShadowServerBase.SIGNALS)

    def __init__(self, attrs: dict[str, str]):
        GObject.GObject.__init__(self)
        ShadowServerBase.__init__(self)
        self.multi_window = str_to_bool(attrs.get("multi-window", True))

    def add_tray_menu_items(self, tray_menu):
        if features.window:
            def readonly_toggled(menuitem) -> None:
                log("readonly_toggled(%s)", menuitem)
                ro = menuitem.get_active()
                if ro != self.readonly:
                    self.readonly = ro
                    self.setting_changed("readonly", ro)

            from xpra.gtk.widget import checkitem
            tray_menu.append(checkitem("Read-only", cb=readonly_toggled, active=self.readonly))

    def last_client_exited(self) -> None:
        log("last_client_exited() mapped=%s", self.mapped)
        for wid in tuple(self.mapped):
            self.stop_refresh(wid)
        super().last_client_exited()

    def make_hello(self, source) -> dict[str, Any]:
        caps = super().make_hello(source)
        if "features" in source.wants:
            from xpra.gtk.info import get_screen_sizes
            caps["screen_sizes"] = get_screen_sizes()
        return caps

    def accept_client_ssh_agent(self, uuid: str, ssh_auth_sock: str) -> None:
        log(f"accept_client_ssh_agent({uuid}, {ssh_auth_sock}) not setting up ssh agent forwarding for shadow servers")

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
        if features.window:
            self.recreate_window_models()

    def recreate_window_models(self) -> None:
        # remove all existing models and re-create them:
        for model in tuple(self._window_to_id.keys()):
            self._remove_window(model)
        self.cleanup_capture()
        for model in self.make_capture_window_models():
            self._add_new_window(model)

    def setup_capture(self):
        raise NotImplementedError()

    def get_root_window_model_class(self) -> type:
        from xpra.server.shadow.root_window_model import CaptureWindowModel
        return CaptureWindowModel

    def get_shadow_monitors(self) -> list[tuple[str, int, int, int, int, int]]:
        Gdk = gi_import("Gdk")
        manager = Gdk.DisplayManager.get()
        display = manager.get_default_display()
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

    def make_capture_window_models(self) -> list:
        screenlog("make_capture_window_models() display_options=%s", self.display_options)
        self.capture = self.setup_capture()
        if not self.capture:
            raise RuntimeError("failed to instantiate a capture backend")
        log.info(f"capture using {self.capture.get_type()}")
        model_class = self.get_root_window_model_class()
        models = []
        Gdk = gi_import("Gdk")
        manager = Gdk.DisplayManager.get()
        display = manager.get_default_display()
        from xpra.util.screen import prettify_plug_name
        display_name = prettify_plug_name(display.get_name())
        monitors = self.get_shadow_monitors()
        match_str = None
        geometries = None
        if "=" in self.display_options:
            # parse the display options as a dictionary:
            from xpra.util.parsing import parse_simple_dict
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
        log(f"make_capture_window_models() multi_window={self.multi_window}")
        if not self.multi_window or geometries:
            if not geometries:
                from xpra.gtk.util import get_root_size
                rw, rh = get_root_size()
                geometries = ((0, 0, rw, rh), )
            for geometry in geometries:
                model = model_class(self.capture, display_name, geometry)
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
            model = model_class(self.capture, title, geometry)
            models.append(model)
            screenlog("monitor %i: %10s geometry=%s, scale factor=%s", i, title, geometry, scale_factor)
        screenlog("make_capture_window_models()=%s", models)
        if not models and match_str:
            screenlog.warn("Warning: no monitors found matching %r", match_str)
            screenlog.warn(" only found: %s", csv(found))
        return models

    def makeDynamicWindowModels(self):
        assert self.window_matches
        raise NotImplementedError("dynamic window shadow is not implemented on this platform")

    def refresh_window_models(self) -> None:
        if not self.window_matches or not features.window:
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
                window.notify("size-constraints")
                for ss in sources:
                    ss.resize_window(wid, window, window.geometry[2], window.geometry[3])
        # any models left are new windows:
        for window in xid_to_window.values():
            self._add_new_window(window)
            self.refresh_window(window)

    def _adjust_pointer(self, proto, device_id, wid: int, opointer) -> list[int] | None:
        window = self._id_to_window.get(wid)
        # soft dependency on cursor subsystem:
        suspend_cursor = getattr(self, "suspend_cursor", noop)
        if wid > 0 and not window:
            suspend_cursor(proto)
            return None
        pointer = super()._adjust_pointer(proto, device_id, wid, opointer)
        ax = x = int(pointer[0])
        ay = y = int(pointer[1])
        if window:
            # the window may be at an offset (multi-window for multi-monitor):
            wx, wy, ww, wh = window.get_geometry()
            # or maybe the pointer is off-screen:
            if x < 0 or x >= ww or y < 0 or y >= wh:
                suspend_cursor(proto)
                return None
            # note: with x11 shadow servers,
            # _get_pointer_abs_coordinates() will recalculate
            # the absolute coordinates from the relative ones,
            # and it should end up with the same values we calculated here
            ax = x + wx
            ay = y + wy
        self.restore_cursor(proto)
        return [ax, ay] + list(pointer[2:])

    def get_pointer_position(self) -> tuple[int, int]:
        from xpra.gtk.util import get_default_root_window
        root = get_default_root_window()
        return root.get_pointer()[-3:-1]

    def get_notification_tray(self):
        return self.tray_widget

    def get_notifier_classes(self) -> list[Callable]:
        ncs: list[Callable] = list(super().get_notifier_classes())
        try:
            from xpra.gtk.notifier import GTKNotifier  # pylint: disable=import-outside-toplevel
            ncs.append(GTKNotifier)
        except Exception as e:
            notifylog = Logger("notify")
            notifylog("get_notifier_classes()", exc_info=True)
            notifylog.warn("Warning: cannot load GTK notifier:")
            notifylog.warn(" %s", e)
        return ncs

    def do_make_screenshot_packet(self) -> tuple[str, int, int, str, int, Compressed]:
        assert len(self._id_to_window) == 1, "multi root window screenshot not implemented yet"
        rwm = self._id_to_window.values()[0]
        w, h, encoding, rowstride, data = rwm.take_screenshot()
        assert encoding == "png"  # use fixed encoding for now
        return "screenshot", w, h, encoding, rowstride, Compressed(encoding, data)


GObject.type_register(GTKShadowServerBase)
