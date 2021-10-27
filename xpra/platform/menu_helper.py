#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

def load_menu():
    return {}

def load_desktop_sessions():
    return {}

def clear_cache():
    pass


from xpra.platform import platform_import
platform_import(globals(), "menu_helper", False,
                "load_menu",
                "load_desktop_sessions",
                "clear_cache",
                )

def main():
    import os
    from xpra.util import print_nested_dict
    from xpra.log import Logger, add_debug_category
    log = Logger("exec", "menu")
    from xpra.platform import program_context  #pylint: disable=import-outside-toplevel
    with program_context("XDG-Menu-Helper", "XDG Menu Helper"):
        for x in list(sys.argv):
            if x in ("-v", "--verbose"):
                sys.argv.remove(x)
                add_debug_category("menu")
                log.enable_debug()
        def icon_fmt(icondata):
            return "%i bytes" % len(icondata)
        if len(sys.argv)>1:
            for x in sys.argv[1:]:
                if os.path.isabs(x):
                    from xpra.codecs.icon_util import load_icon_from_file
                    v = load_icon_from_file(x)
                    print("load_icon_from_file(%s)=%s" % (x, v))
        else:
            menu = load_menu()
            if menu:
                print()
                print("application menu:")
                print_nested_dict(menu, vformat={"IconData" : icon_fmt})
            else:
                print("no application menu data found")
            #try desktop sessions:
            sessions = load_desktop_sessions()
            if sessions:
                print()
                print("session menu:")
                print_nested_dict(sessions, vformat={"IconData" : icon_fmt})
            else:
                print("no session menu data found")
    return 0

if __name__ == "__main__":
    r = main()
    sys.exit(r)
