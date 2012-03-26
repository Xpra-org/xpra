# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import gtk
import parti.tray
from wimpiggy.window import WindowView

if sys.version < '3':
    import codecs
    def u(x):
        return codecs.unicode_escape_decode(x)[0]
else:
    def u(x):
        return x

class CompositeTestTray(parti.tray.Tray, gtk.HPaned):
    def __init__(self, trayset, tag):
        super(CompositeTestTray, self).__init__(trayset, tag)
        self.windows = []
        # Hack to start the spacer in the middle of the window
        self.set_position(gtk.gdk.screen_width() / 2)
        self.client_notebook = gtk.Notebook()
        self.add1(self.client_notebook)
        self.image_notebook = gtk.Notebook()
        self.add2(self.image_notebook)

        self.client_notebook.grab_focus()

        self.show_all()

    def windows(self):
        return set(self.windows)

    def add(self, window):
        self.windows.append(window)
        real_view = WindowView(window)
        self.client_notebook.append_page(real_view)
        real_view.show()

        ro_view = WindowView(window)
        self.image_notebook.append_page(ro_view)
        ro_view.show()

        window.connect("notify::title", self._handle_title_change)
        self._handle_title_change(window)

        real_view.grab_focus()

    def _handle_title_change(self, window, *args):
        title = window.get_property("title")
        for view in self.client_notebook.get_children():
            if view.model is window:
                self.client_notebook.set_tab_label_text(view, title)
        for view in self.image_notebook.get_children():
            if view.model is window:
                self.image_notebook.set_tab_label_text(view,
                                                       u("CLONE: ") + title)
