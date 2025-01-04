# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import

Gdk = gi_import("Gdk")

cursor_names = {}
cursor_types = {}


def _init_map() -> None:
    for x in dir(Gdk.CursorType):
        if not x.isupper():
            # probably a method
            continue
        try:
            v = int(getattr(Gdk.CursorType, x))
            cursor_names[v] = x
            cursor_types[x] = v
        except (TypeError, ValueError):
            pass


_init_map()


def get_default_cursor() -> Gdk.Cursor:
    display = Gdk.Display.get_default()
    return Gdk.Cursor.new_from_name(display, "default")


def main():
    # pylint: disable=import-outside-toplevel
    from xpra.util.str_fn import csv
    from xpra.platform import program_context
    with program_context("Cursors", "Cursors"):
        print(csv(cursor_types))


if __name__ == "__main__":
    main()
