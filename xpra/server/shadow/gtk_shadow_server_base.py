# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.server import features
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.log import Logger

screenlog = Logger("screen")
log = Logger("shadow")


class GTKShadowServerBase(ShadowServerBase):

    def __init__(self, attrs: dict[str, str]):
        ShadowServerBase.__init__(self, attrs)

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

    def get_server_features(self, source=None) -> dict[str, Any]:
        caps = super().get_server_features(source)
        from xpra.gtk.info import get_screen_sizes
        caps["screen_sizes"] = get_screen_sizes()
        return caps

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

    def get_notification_tray(self):
        tray = self.get_subsystem("tray")
        return getattr(tray, "widget", None)

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
