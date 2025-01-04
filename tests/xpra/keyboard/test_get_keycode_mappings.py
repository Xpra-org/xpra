#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>

from xpra.x11.gtk.display_source import init_gdk_display_source

init_gdk_display_source()
from xpra.x11.bindings.keyboard import X11KeyboardBindings

keyboard_bindings = X11KeyboardBindings()


def main():
    mappings = keyboard_bindings.get_keycode_mappings()
    print("mappings=%s" % mappings)
    print("")
    for k, v in mappings.items():
        print("%s\t\t:\t%s" % (k, v))


if __name__ == "__main__":
    main()
