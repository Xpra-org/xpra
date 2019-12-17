#!/usr/bin/env python

import sys
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk   #pylint: disable=wrong-import-position

class TestWindow(Gtk.Window):

    def __init__(self, icons):
        Gtk.Window.__init__(self, Gtk.WindowType.TOPLEVEL)
        self.icons = icons
        self.index = 0
        self._set_window_icon()
        self.set_size_request(128, 128)
        self.connect("delete_event", self.quit_cb)
        self.show_all()
        self.connect("key_press_event", self._set_window_icon)

    def _set_window_icon(self, *_args):
        self.set_icon(self.icons[self.index % len(self.icons)])
        self.index += 1
        return True

    def quit_cb(self, *args):
        Gtk.main_quit()


def main():
    if len(sys.argv)<2:
        print("usage: %s ICONFILE1 [ICONFILE2] [..]" % sys.argv[0])
        sys.exit(1)
    icons = [GdkPixbuf_new_from_file(x) for x in sys.argv[1:]]
    TestWindow(icons)
    Gtk.main()


if __name__ == "__main__":
    main()
