#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2015-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict
import sys

def main() -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.util import pver, flatten_dict, print_nested_dict
    def print_version_dict(d:Dict, vformat=pver):
        for k in sorted(d.keys()):
            v = d[k]
            print("* %-48s : %r" % (str(k).replace(".version", "").ljust(12), vformat(v)))
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
