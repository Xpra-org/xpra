#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import platform_import


def get_pointer_device():
    return None


platform_import(globals(), "pointer", True,
                "get_pointer_device")


def main() -> int:
    import sys
    from xpra.util.system import is_X11
    from xpra.platform import program_context
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("Pointer-Tool", "Pointer Tool"):
        # use the logger for the platform module we import from
        enable_color()
        consume_verbose_argv(sys.argv, "pointer")

        # naughty, but how else can I hook this up?
        if is_X11():
            try:
                from xpra.x11.bindings.display_source import init_display_source
                init_display_source()
            except Exception as e:
                print("failed to connect to the X11 server:")
                print(" %s" % e)
                # hope for the best..

        print("pointer device: %s" % get_pointer_device())

    return 0


if __name__ == "__main__":
    main()
