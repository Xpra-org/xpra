# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import OSX, POSIX, gi_import
from xpra.util.env import first_time, IgnoreWarningsContext
from xpra.util.system import is_X11
from xpra.log import Logger

Gdk = gi_import("Gdk")


def get_default_root_window() -> Gdk.Window | None:
    screen = Gdk.Screen.get_default()
    if screen is None:
        return None
    return screen.get_root_window()


def get_root_size(default: None | tuple[int, int] = (1920, 1024)) -> tuple[int, int] | None:
    if OSX:
        # the easy way:
        root = get_default_root_window()
        if not root:
            return default
        w, h = root.get_geometry()[2:4]
    else:
        # GTK3 on win32 triggers this warning:
        # "GetClientRect failed: Invalid window handle."
        # if we try to use the root window,
        # and on Linux with Wayland, we get bogus values...
        screen = Gdk.Screen.get_default()
        if screen is None:
            return default
        with IgnoreWarningsContext():
            w = screen.get_width()
            h = screen.get_height()
    if w <= 0 or h <= 0 or w > 32768 or h > 32768:
        if first_time("Gtk root window dimensions"):
            log = Logger("gtk", "screen")
            log.warn(f"Warning: Gdk returned invalid root window dimensions: {w}x{h}")
            log.warn(" no access to the display?")
            log.warn(f" using {default} instead")
        return default
    return w, h


GRAB_STATUS_STRING = {
    Gdk.GrabStatus.SUCCESS: "SUCCESS",
    Gdk.GrabStatus.ALREADY_GRABBED: "ALREADY_GRABBED",
    Gdk.GrabStatus.INVALID_TIME: "INVALID_TIME",
    Gdk.GrabStatus.NOT_VIEWABLE: "NOT_VIEWABLE",
    Gdk.GrabStatus.FROZEN: "FROZEN",
}

dsinit: bool = False


def init_display_source() -> None:
    """
    On X11, we want to be able to access the bindings,
    so we need to get the X11 display from GDK.
    """
    global dsinit
    dsinit = True
    x11 = is_X11()
    log = Logger("gtk", "screen")
    log(f"init_display_source() {x11=}")
    if x11:
        try:
            from xpra.x11.gtk.display_source import init_gdk_display_source
            init_gdk_display_source()
        except ImportError:  # pragma: no cover
            log("init_gdk_display_source()", exc_info=True)
            log.warn("Warning: the Gtk-3.0 X11 bindings are missing")
            log.warn(" some features may be degraded or unavailable")
            log.warn(" ie: keyboard mapping, focus, etc")


def ds_inited() -> bool:
    return dsinit


def main():
    from xpra.platform import program_context
    from xpra.util.str_fn import print_nested_dict
    from xpra.log import enable_color
    with program_context("GTK-Version-Info", "GTK Version Info"):
        enable_color()
        from xpra.gtk.versions import get_gtk_version_info
        print("%s" % get_gtk_version_info())
        if POSIX and not OSX:
            from xpra.x11.bindings.posix_display_source import init_posix_display_source
            init_posix_display_source()
        import warnings
        warnings.simplefilter("ignore")
        from xpra.gtk.info import get_display_info, get_screen_sizes
        print(get_screen_sizes()[0])
        print_nested_dict(get_display_info())


if __name__ == "__main__":
    main()
