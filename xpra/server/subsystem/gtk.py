# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import
from xpra.util.version import dict_version_trim
from xpra.util.screen import prettify_plug_name
from xpra.common import noop
from xpra.net.common import FULL_INFO
from xpra.gtk.versions import get_gtk_version_info
from xpra.gtk.info import get_screen_sizes
from xpra.server import features
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("server", "gtk")

get_default_window_icon_fallback = noop


def inject_gtk_window_icon_lookup() -> None:
    """
    Replace the default window-icon lookup with one that consults the
    current GTK icon theme. Safe to call on any GDK backend (X11, Wayland, ...).
    """
    global get_default_window_icon_fallback
    if get_default_window_icon_fallback != noop:
        return
    try:
        from xpra.server.window import windowicon
    except ImportError:
        return
    get_default_window_icon_fallback = windowicon.do_get_default_window_icon
    windowicon.get_default_window_icon = get_default_window_icon


def get_default_window_icon(size: int, wmclass_name: str):
    Gtk = gi_import("Gtk")
    it = Gtk.IconTheme.get_default()  # pylint: disable=no-member
    log("get_default_window_icon(%i) icon theme=%s, wmclass_name=%s", size, it, wmclass_name)
    for icon_name in (
            f"{wmclass_name}-color",
            wmclass_name,
            f"{wmclass_name}_{size}x{size}",
            f"application-x-{wmclass_name}",
            f"{wmclass_name}-symbolic",
            f"{wmclass_name}.symbolic",
    ):
        i = it.lookup_icon(icon_name, size, 0)
        log("lookup_icon(%s)=%s", icon_name, i)
        if not i:
            continue
        try:
            pixbuf = i.load_icon()
            log("load_icon()=%s", pixbuf)
            if pixbuf:
                w, h = pixbuf.props.width, pixbuf.props.height
                log("using '%s' pixbuf %ix%i", icon_name, w, h)
                return w, h, "RGBA", pixbuf.get_pixels()
        except Exception:
            log("%s.load_icon()", i, exc_info=True)
    return get_default_window_icon_fallback(size, wmclass_name)


class GTKServer(StubServerMixin):
    """
    Abstract base for GTK-based servers.

    Provides display-name resolution, keymap-change watching and screen-size
    reporting on top of a running GTK display.
    Backend-specific setup (X11, Wayland, ...) is performed by subclasses.
    """

    def init(self, opts) -> None:
        log("GTKServer.init(..)")
        from xpra.scripts.common import no_gtk
        no_gtk()

    def get_display_name(self) -> str:
        Gdk = gi_import("Gdk")
        manager = Gdk.DisplayManager.get()
        display = manager.get_default_display()
        return prettify_plug_name(display.get_name())

    def watch_keymap_changes(self) -> None:
        # Set up keymap change notification:
        from xpra.gtk.keymap import get_default_keymap
        keymap = get_default_keymap()
        keymap.connect("keys-changed", self.keymap_changed)

    def setup(self) -> None:
        inject_gtk_window_icon_lookup()
        if features.display:
            Gdk = gi_import("Gdk")
            screen = Gdk.Screen.get_default()
            if screen:
                screen.connect("size-changed", self._screen_size_changed)
                screen.connect("monitors-changed", self._monitors_changed)

    def _screen_size_changed(self, screen) -> None:
        log(f"_screen_size_changed({screen})")
        self.schedule_screen_changed(screen)

    def _monitors_changed(self, screen) -> None:
        log(f"_monitors_changed({screen})")
        self.schedule_screen_changed(screen)

    def late_cleanup(self, stop=True) -> None:
        from xpra.gtk.util import close_gtk_display
        close_gtk_display()

    def get_caps(self, source) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if "versions" in source.wants and FULL_INFO >= 2:
            caps["versions"] = get_gtk_version_info()
        return caps

    def get_server_features(self, _source) -> dict[str, Any]:
        return {
            "screen_sizes": get_screen_sizes(),
        }

    def get_ui_info(self, _proto, **kwargs) -> dict[str, Any]:
        return {
            "versions": dict_version_trim(get_gtk_version_info()),
            "screen_sizes": get_screen_sizes(),
        }
