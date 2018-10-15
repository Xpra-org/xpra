#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>

import sys
import pygtk
pygtk.require('2.0')
import gtk
from gtk import gdk

from xpra.x11.gtk2 import gdk_display_source
assert gdk_display_source
from xpra.x11.gtk_x11.prop import prop_get
from xpra.x11.gtk_x11.send_wm import send_wm_workspace


class TestForm(object):


    def show_current_workspace(self, *args):
        try:
            workspace = prop_get(self.window.get_window(), "_NET_WM_DESKTOP", "u32")
            if workspace is None:
                workspace = ""
            self.entry.set_text(str(workspace))
            self.warn.set_text("")
        except Exception as e:
            self.warn.set_text(str(e))

    def move_to_workspace(self, *args):
        w = self.window.get_window()
        try:
            workspace = int(self.entry.get_text())
            send_wm_workspace(w.get_screen().get_root_window(), w, workspace)
        except Exception as e:
            self.warn.set_text("invalid workspace specified: %s" % e)

    def property_changed(self, widget, event):
        #print("%s.property_changed(%s, %s) : %s" % (self, widget, event, event.atom))
        if event.atom=="_NET_WM_DESKTOP":
            self.show_current_workspace()

    def    __init__(self):
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("destroy", gtk.main_quit)
        self.window.set_default_size(320, 200)
        self.window.set_border_width(20)
        self.window.add_events(gdk.PROPERTY_CHANGE_MASK)

        self.workspace = None
        self.window.connect("property-notify-event", self.property_changed)

        vbox = gtk.VBox()

        vbox.add(gtk.Label("Workspace:"))
        self.warn = gtk.Label()
        vbox.add(self.warn)

        self.entry = gtk.Entry()
        self.entry.set_text("")
        vbox.add(self.entry)

        move = gtk.Button("Move")
        move.connect('clicked', self.move_to_workspace)
        vbox.add(move)

        self.window.add(vbox)
        self.window.show_all()

        self.show_current_workspace()


def main():
    TestForm()
    gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
