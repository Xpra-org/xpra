# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

def main():
    from xpra.util import nonl, pver, flatten_dict, print_nested_dict
    def print_version_dict(d, vformat=pver):
        for k in sorted(d.keys()):
            v = d[k]
            print("* %-48s : %s" % (str(k).replace(".version", "").ljust(12), nonl(vformat(v))))
    from xpra.platform import program_context
    with program_context("GTK-Version-Info", "GTK Version Info"):
        from xpra.platform.gui import init as gui_init, ready
        gui_init()
        ready()
        from xpra.gtk_common import gtk_util
        if "-v" in sys.argv or "--verbose" in sys.argv:
            gtk_util.SHOW_ALL_VISUALS = True
        print("GTK Version:")
        print_version_dict(flatten_dict(gtk_util.get_gtk_version_info()))
        print("Display:")
        print_nested_dict(gtk_util.get_display_info(), vformat=str)


if __name__ == "__main__":
    main()
    sys.exit(0)
