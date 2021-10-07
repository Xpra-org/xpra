# This file is part of Xpra.
# Copyright (C) 2012-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gi
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk  #pylint: disable=wrong-import-position

cursor_names = {}
cursor_types = {}

for x in dir(Gdk.CursorType):
    if not x.isupper():
        #probably a method
        continue
    try:
        v = int(getattr(Gdk.CursorType, x))
        cursor_names[v] = x
        cursor_types[x] = v
    except (TypeError, ValueError):
        pass


def main():
    from xpra.util import csv
    from xpra.platform import program_context
    with program_context("Cursors", "Cursors"):
        print(csv(cursor_types))


if __name__ == "__main__":
    main()
