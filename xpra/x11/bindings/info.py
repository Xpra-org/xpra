# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.posix_display_source import X11DisplayContext

from xpra.util.str_fn import repr_ellipsized

with X11DisplayContext() as context:
    from xpra.x11.bindings.window import X11WindowBindings
    window = X11WindowBindings()

    print("display=%s" % context.display_name)
    from xpra.x11.bindings.xwayland import isxwayland
    print("isXwayland=%s" % isxwayland())

    root = window.get_root_xid()
    print("root=%#x" % root)
    window.addDefaultEvents(root)

    print("time(%#x)=%s" % (root, window.get_server_time(root)))

    from xpra.x11.bindings.keyboard import X11KeyboardBindings
    keyboard = X11KeyboardBindings()
    print("XFixes=%d" % bool(keyboard.hasXFixes()))
    print("Xkb=%d" % bool(keyboard.hasXkb()))
    print("XTest=%d" % bool(keyboard.hasXTest()))
    print(" layout group=%i", keyboard.get_layout_group())
    print(" default properties=%s" % keyboard.get_default_properties())
    print(" Xkb properties=%s" % keyboard.getXkbProperties())
    print(" modifier map=%s" % (keyboard.get_modifier_map(), ))
    print(" min-max keycodes=%s" % (keyboard.get_minmax_keycodes(), ))
    print(" modifier mappings=%s" % (keyboard.get_modifier_mappings(), ))
    print(" keycodes down=%s" % (keyboard.get_keycodes_down(), ))
    print(" pointer=%s" % (keyboard.query_pointer(), ))
    print(" mask=%s" % (keyboard.query_mask(), ))

    from xpra.x11.bindings.randr import RandRBindings
    randr = RandRBindings()
    print("RandR=%s" % bool(randr.has_randr()))
    print(" dummy16=%s" % bool(randr.is_dummy16()))
    print(" vrefresh=%d" % randr.get_vrefresh())
    print(" screen size=%s" % (randr.get_screen_size(), ))
    print(" version=%s" % (randr.get_version(), ))
    print(" monitors=%s" % (randr.get_monitor_properties(), ))

    from xpra.x11.bindings.ximage import XImageBindings
    image = XImageBindings()
    print("XShm=%s" % bool(image.has_XShm()))

    from xpra.x11.bindings.xi2 import X11XI2Bindings
    xi2 = X11XI2Bindings()
    print("XI2 version=%s" % (xi2.get_xi_version(), ))
    print(" devices=%s" % (repr_ellipsized(xi2.get_devices()), ))
