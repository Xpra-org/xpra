# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any
from importlib.util import find_spec
from importlib import import_module

from xpra.log import Logger
from xpra.util.str_fn import print_nested_dict

log = Logger("x11")

ALL_X11_BINDINGS = (
    "classhint", "composite", "core", "damage", "display_source", "events", "fixes", "keyboard",
    "present", "randr", "record", "res", "saveset", "shape", "shm", "test",
    "wait_for_x_server", "window", "xi2", "ximage", "xkb", "xwait", "xwayland",
)


def get_extensions_info(load=True) -> dict[str, Any]:
    missing: list[str] = []
    available: list[str] = []
    for binding in ALL_X11_BINDINGS:
        spec = find_spec("xpra.x11.bindings." + binding)
        if not spec:
            missing.append(binding)
            continue
        if load:
            try:
                import_module("xpra.x11.bindings." + binding)
            except ImportError as e:
                log.error(f"Error importing xpra.x11.bindings.{binding}: {e}", file=sys.stderr)
                continue
        available.append(binding)
    return {
        "missing": missing,
        "available": available,
    }


def get_info() -> dict[str, Any]:
    """
    Return a dictionary with information about the X11 display.
    """
    info = get_extensions_info(True)

    from xpra.x11.bindings.core import X11CoreBindings
    info.update(X11CoreBindings().get_info())

    try:
        from xpra.x11.bindings.xwayland import isxwayland
        info["isXwayland"] = isxwayland()
    except ImportError:
        pass
    try:
        from xpra.x11.bindings.window import X11WindowBindings
        window = X11WindowBindings()
        root = window.get_root_xid()
        info["root"] = root
        window.addDefaultEvents(root)
        info["time"] = window.get_server_time(root)
    except ImportError:
        pass

    try:
        from xpra.x11.bindings.keyboard import X11KeyboardBindings
        keyboard = X11KeyboardBindings()
        minc, maxc = keyboard.get_minmax_keycodes()
        info["keyboard"] = {
            "xkb": bool(keyboard.hasXkb()),
            "layout-group": keyboard.get_layout_group(),
            "default-properties": keyboard.get_default_properties(),
            "xkb-properties": keyboard.getXkbProperties(),
            "modifier-map": keyboard.get_modifier_map(),
            "min-keycode": minc,
            "max-keycode": maxc,
            "modifier-mappings": keyboard.get_modifier_mappings(),
            "keycodes-down": keyboard.get_keycodes_down(),
        }
    except ImportError:
        pass

    try:
        from xpra.x11.bindings.test import XTestBindings
        test = XTestBindings()
        info["xtest"] = bool(test.hasXTest())
    except ImportError:
        pass

    try:
        from xpra.x11.bindings.fixes import XFixesBindings
        fixes = XFixesBindings()
        info["xfixes"] = bool(fixes.hasXFixes())
    except ImportError:
        pass

    try:
        from xpra.x11.bindings.composite import XCompositeBindings
        composite = XCompositeBindings()
        info["xcomposite"] = bool(composite.hasXComposite())
    except ImportError:
        pass

    try:
        from xpra.x11.bindings.randr import RandRBindings
        randr = RandRBindings()
        if randr.has_randr():
            info["randr"] = {
                "dummy16": bool(randr.is_dummy16()),
                "vrefresh": randr.get_vrefresh(),
                "screen_size": randr.get_screen_size(),
                "version": randr.get_version(),
                "monitors": randr.get_monitor_properties(),
            }
    except ImportError:
        pass

    try:
        from xpra.x11.bindings.shm import XShmBindings
        xshm = XShmBindings()
        info["xshm"] = xshm.has_XShm()
    except ImportError:
        pass

    try:
        from xpra.x11.bindings.xi2 import X11XI2Bindings
        xi2 = X11XI2Bindings()
        info["xi2"] = {
            "version": xi2.get_xi_version(),
            "devices": xi2.get_devices(),
        }
    except ImportError:
        pass
    return info


def get_windows_info() -> dict[str, Any]:
    try:
        from xpra.x11.bindings.window import X11WindowBindings
        window = X11WindowBindings()

        def get_window_info(w: int) -> dict[str, Any]:
            info = {
                "xid": w,
                "attributes": window.getWindowAttributes(w),
                "event-mask": window.get_event_mask_strs(w),
                "override-redirect": window.is_override_redirect(w),
                "input-only": window.is_inputonly(w),
                "depth": window.get_depth(w),
                "geometry": window.getGeometry(w),
                "size-hints": window.getSizeHints(w),
                "wm-hints": window.getWMHints(w)
            }
            children = window.get_children(w)
            if children:
                info["children"] = dict((c, get_window_info(c)) for c in children)
            return info
    except ImportError:
        return {}
    root = window.get_root_xid()
    return {"root": get_window_info(root)}


def main(args: list[str]) -> int:
    display_name = args[0] if args else os.environ.get("DISPLAY", "")
    from xpra.x11.bindings.display_source import X11DisplayContext
    with X11DisplayContext(display_name) as context:
        info = get_info()
        info["display"] = context.display_name
        print_nested_dict(info)
        print()
        info = get_windows_info()
        print_nested_dict(info)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
