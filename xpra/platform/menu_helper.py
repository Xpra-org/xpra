#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.platform import platform_import


def load_menu() -> dict:
    return {}


def load_desktop_sessions() -> dict:
    return {}


def clear_cache() -> None:
    """ the Posix override has a cache to clear """


platform_import(globals(), "menu_helper", False,
                "load_menu",
                "load_desktop_sessions",
                "clear_cache",
                )


def main():
    import os
    from xpra.util.str_fn import print_nested_dict
    from xpra.log import consume_verbose_argv
    from xpra.platform import program_context  # pylint: disable=import-outside-toplevel
    with program_context("Menu-Helper", "Menu Helper"):
        consume_verbose_argv(sys.argv, "menu")

        def icon_fmt(icondata):
            return "%i bytes" % len(icondata)

        if len(sys.argv) > 1:
            for x in sys.argv[1:]:
                if os.path.isabs(x):
                    from xpra.codecs.icon_util import load_icon_from_file
                    v = load_icon_from_file(x)
                    print(f"load_icon_from_file({x})={v}")
        else:
            menu = load_menu()
            if menu:
                print()
                print("application menu:")
                print_nested_dict(menu, vformat={"IconData": icon_fmt})
            else:
                print("no application menu data found")
            # try desktop sessions:
            sessions = load_desktop_sessions()
            if sessions:
                print()
                print("session menu:")
                print_nested_dict(sessions, vformat={"IconData": icon_fmt})
            else:
                print("no session menu data found")
    return 0


if __name__ == "__main__":
    r = main()
    sys.exit(r)
