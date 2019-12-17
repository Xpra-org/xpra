#!/usr/bin/env python

#code found here:
#http://stackoverflow.com/a/3859540/428751
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk  #pylint: disable=wrong-import-position
from xpra.gtk_common.gtk_util import get_root_size


def main():
    rw, rh = get_root_size()
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_default_size(100, rh)
    window.move(rw-100, 0)
    window.set_type_hint(Gdk.WindowTypeHint.DOCK)
    window.show()
    window.get_window().property_change("_NET_WM_STRUT", "CARDINAL", 32,
        Gtk.gdk.PROP_MODE_REPLACE, [0, 100, 0, 0])
    Gtk.main()


if __name__ == "__main__":
    main()
