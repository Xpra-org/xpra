# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from collections.abc import Sequence

from xpra.os_util import OSX, gi_import
from xpra.util.system import is_X11
from xpra.util.env import envbool, first_time, IgnoreWarningsContext
from xpra.log import Logger

Gdk = gi_import("Gdk")


def get_default_root_window() -> Gdk.Window | None:
    screen = Gdk.Screen.get_default()
    if screen is None:
        return None
    return screen.get_root_window()


def get_root_size(default: None | tuple[int, int] = (1920, 1024)) -> tuple[int, int] | None:
    w = h = 0
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

EVENT_MASK_STRS = {}
for mask in dir(Gdk.EventMask):
    if mask.endswith("_MASK"):
        value = getattr(Gdk.EventMask, mask)
        EVENT_MASK_STRS[value] = mask


def event_mask_strs(mask: int) -> Sequence[str]:
    masks = []
    for tmask, name in EVENT_MASK_STRS.items():
        if mask & tmask == tmask:
            masks.append(name)
    return masks


dsinit: bool = False


def init_display_source(warn=True) -> None:
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
            if warn:
                log.warn("Warning: the Gtk-3.0 X11 bindings are missing")
                log.warn(" some features may be degraded or unavailable")
                log.warn(" ie: keyboard mapping, focus, etc")


def ds_inited() -> bool:
    return dsinit


def verify_gdk_display(display_name: str):
    # pylint: disable=import-outside-toplevel
    # Now we can safely load gtk and connect:
    try:
        Gdk = gi_import("Gdk")
    except ImportError:
        return None
    display = Gdk.Display.open(display_name)
    if not display:
        return None
    manager = Gdk.DisplayManager.get()
    default_display = manager.get_default_display()
    if default_display is not None and default_display != display:
        default_display.close()
    manager.set_default_display(display)
    return display


def close_gtk_display() -> None:
    # Close our display(s) first, so the server dying won't kill us.
    # (if gtk has been loaded)
    gdk_mod = sys.modules.get("gi.repository.Gdk")
    # bug 2328: python3 shadow server segfault on Ubuntu 16.04
    # also crashes on Ubuntu 20.04
    close = envbool("XPRA_CLOSE_GTK_DISPLAY", False)
    if close and gdk_mod:
        log = Logger("gtk", "screen")
        displays = Gdk.DisplayManager.get().list_displays()
        log("close_gtk_display() close=%s, gdk_mod=%s, displays=%s", close, gdk_mod, displays)
        log("close_gtk_display() displays=%s", displays)
        for d in displays:
            log("close_gtk_display() closing %s", d)
            d.close()


def main() -> None:
    from xpra.platform import program_context
    from xpra.util.str_fn import print_nested_dict
    from xpra.log import enable_color

    with program_context("GTK-Version-Info", "GTK Version Info"):
        enable_color()
        from xpra.gtk.versions import get_gtk_version_info
        print("%s" % get_gtk_version_info())
        if is_X11():
            from xpra.x11.bindings.display_source import init_display_source
            init_display_source()
        import warnings
        warnings.simplefilter("ignore")
        from xpra.gtk.info import get_display_info, get_screen_sizes
        print(get_screen_sizes()[0])
        print_nested_dict(get_display_info())


if __name__ == "__main__":
    main()


def quit_on_signals(commandtype: str = "") -> None:
    from xpra.os_util import gi_import
    Gtk = gi_import("Gtk")

    def signal_handler(_signum: int) -> None:
        Gtk.main_quit()

    from xpra.util.glib import register_os_signals
    register_os_signals(signal_handler, commandtype)
