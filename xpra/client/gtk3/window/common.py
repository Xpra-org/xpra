# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Sequence

from xpra.os_util import gi_import, WIN32, OSX, POSIX
from xpra.util.env import envbool, envint
from xpra.util.system import is_Wayland, is_X11
from xpra.log import Logger

log = Logger("window", "metadata")

Gdk = gi_import("Gdk")


def _use_x11_bindings() -> bool:
    if WIN32 or OSX or not POSIX:
        return False
    if not is_X11() or is_Wayland():
        return False
    if envbool("XPRA_USE_X11_BINDINGS", False):
        return True
    try:
        from xpra.x11.bindings.xwayland_info import isxwayland
    except ImportError:
        log("no xwayland bindings", exc_info=True)
        return False
    return not isxwayland()


_use_x11 = None


def use_x11_bindings() -> bool:
    global _use_x11
    if _use_x11 is None:
        _use_x11 = _use_x11_bindings()
    return bool(_use_x11)


def parse_padding_colors(colors_str: str) -> tuple[int, int, int]:
    padding_colors = 0, 0, 0
    if colors_str:
        try:
            padding_colors = tuple(float(x.strip()) for x in colors_str.split(","))
            assert len(padding_colors) == 3, "you must specify 3 components"
        except Exception as e:
            log.warn("Warning: invalid padding colors specified,")
            log.warn(" %s", e)
            log.warn(" using black")
            padding_colors = 0, 0, 0
    log("parse_padding_colors(%s)=%s", colors_str, padding_colors)
    return padding_colors


PADDING_COLORS = parse_padding_colors(os.environ.get("XPRA_PADDING_COLORS", ""))

UNDECORATED_TRANSIENT_IS_OR = envint("XPRA_UNDECORATED_TRANSIENT_IS_OR", 1)


def is_awt(metadata) -> bool:
    wm_class = metadata.strtupleget("class-instance")
    return wm_class and len(wm_class) == 2 and wm_class[0].startswith("sun-awt-X11")


# window types we map to POPUP rather than TOPLEVEL
POPUP_TYPE_HINTS: set[str] = {
    # "DIALOG",
    # "MENU",
    # "TOOLBAR",
    # "SPLASH",
    # "UTILITY",
    # "DOCK",
    # "DESKTOP",
    "DROPDOWN_MENU",
    "POPUP_MENU",
    # "TOOLTIP",
    # "NOTIFICATION",
    # "COMBO",
    # "DND",
}


def is_popup(metadata) -> bool:
    # decide if the window type is POPUP or NORMAL
    if UNDECORATED_TRANSIENT_IS_OR > 0:
        transient_for = metadata.intget("transient-for", -1)
        decorations = metadata.intget("decorations", 0)
        # noinspection PyChainedComparisons
        if transient_for > 0 and decorations <= 0:
            if UNDECORATED_TRANSIENT_IS_OR > 1:
                log("forcing POPUP type for window transient-for=%s", transient_for)
                return True
            if metadata.get("skip-taskbar") and is_awt(metadata):
                log("forcing POPUP type for Java AWT skip-taskbar window, transient-for=%s", transient_for)
                return True
    window_types = metadata.strtupleget("window-type")
    popup_types = tuple(POPUP_TYPE_HINTS.intersection(window_types))
    log("popup_types(%s)=%s", window_types, popup_types)
    if popup_types:
        log("forcing POPUP window type for %s", popup_types)
        return True
    return False


BUTTON_MASK: dict[int, int] = {
    Gdk.ModifierType.BUTTON1_MASK: 1,
    Gdk.ModifierType.BUTTON2_MASK: 2,
    Gdk.ModifierType.BUTTON3_MASK: 3,
    Gdk.ModifierType.BUTTON4_MASK: 4,
    Gdk.ModifierType.BUTTON5_MASK: 5,
}


def mask_buttons(state: int | Gdk.ModifierType) -> list[int]:
    return [button for mask, button in BUTTON_MASK.items() if state & mask]


wth = Gdk.WindowTypeHint
ALL_WINDOW_TYPES: Sequence[Gdk.WindowTypeHint] = (
    wth.NORMAL,
    wth.DIALOG,
    wth.MENU,
    wth.TOOLBAR,
    wth.SPLASHSCREEN,
    wth.UTILITY,
    wth.DOCK,
    wth.DESKTOP,
    wth.DROPDOWN_MENU,
    wth.POPUP_MENU,
    wth.TOOLTIP,
    wth.NOTIFICATION,
    wth.COMBO,
    wth.DND,
)
del wth
WINDOW_NAME_TO_HINT: dict[str, Gdk.WindowTypeHint] = {
    wth.value_name.replace("GDK_WINDOW_TYPE_HINT_", ""): wth for wth in ALL_WINDOW_TYPES
}
