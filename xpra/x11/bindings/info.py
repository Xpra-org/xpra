# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from importlib.util import find_spec
from importlib import import_module
from typing import Any


from xpra.util.str_fn import print_nested_dict


def get_info() -> dict[str, Any]:
    """
    Return a dictionary with information about the X11 display.
    """
    info: dict[str, Any] = {}
    missing: list[str] = []
    for binding in (
        "classhint", "composite", "core", "damage", "display_source", "events", "fixes", "keyboard",
        "posix_display_source", "randr", "record", "res", "saveset", "shape", "shm", "test",
        "wait_for_server", "window", "xi2", "ximage", "xkb", "xwait", "xwayland",
    ):
        spec = find_spec("xpra.x11.bindings." + binding)
        if not spec:
            missing.append(binding)
            continue
        try:
            import_module("xpra.x11.bindings." + binding)
        except ImportError as e:
            print(f"Error importing xpra.x11.bindings.{binding}: {e}", file=sys.stderr)

    try:
        from xpra.x11.bindings.xwayland import isxwayland
        info["isXwayland"] = isxwayland()
    except ImportError:
        missing.append("xwayland")
    try:
        from xpra.x11.bindings.window import X11WindowBindings
        window = X11WindowBindings()
        root = window.get_root_xid()
        info["root"] = root
        window.addDefaultEvents(root)
        info["time"] = window.get_server_time(root)
    except ImportError:
        missing.append("window")

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
            "pointer": keyboard.query_pointer(),
            "mask": keyboard.query_mask(),
        }
    except ImportError:
        missing.append("keyboard")

    try:
        from xpra.x11.bindings.test import XTestBindings
        test = XTestBindings()
        info["xtest"] = bool(test.hasXTest())
    except ImportError:
        missing.append("xtest")

    try:
        from xpra.x11.bindings.fixes import XFixesBindings
        fixes = XFixesBindings()
        info["xfixes"] = bool(fixes.hasXFixes())
    except ImportError:
        missing.append("xfixes")

    try:
        from xpra.x11.bindings.composite import XCompositeBindings
        composite = XCompositeBindings()
        info["xcomposite"] = bool(composite.hasXComposite())
    except ImportError:
        missing.append("xcomposite")

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
        missing.append("randr")

    try:
        from xpra.x11.bindings.shm import XShmBindings
        xshm = XShmBindings()
        info["xshm"] = xshm.has_XShm()
    except ImportError:
        missing.append("xshm")

    try:
        from xpra.x11.bindings.xi2 import X11XI2Bindings
        xi2 = X11XI2Bindings()
        info["xi2"] = {
            "version": xi2.get_xi_version(),
            "devices": xi2.get_devices(),
        }
    except ImportError:
        missing.append("xi2")

    if missing:
        info["missing"] = missing
    return info


def main(args: list[str]) -> int:
    """
    Main function to run the script.
    """
    from xpra.x11.bindings.posix_display_source import X11DisplayContext
    with X11DisplayContext() as context:
        info = get_info()
        info["display"] = context.display_name

    print_nested_dict(info)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
