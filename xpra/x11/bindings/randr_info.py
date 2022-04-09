# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.util import print_nested_dict
from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
from xpra.x11.bindings.randr_bindings import RandRBindings  #pylint: disable=no-name-in-module

def main():
    init_gdk_display_source()
    randr = RandRBindings()
    print_nested_dict(randr.get_all_screen_properties())


if __name__ == "__main__":
    sys.exit(main())
