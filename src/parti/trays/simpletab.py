# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk
import parti.tray

class SimpleTabTray(parti.tray.Tray, gtk.HPaned):
    def __init__(self, trayset, tag):
        super(SimpleTabTray, self).__init__(trayset, tag)
        self.windows = []
        # Hack to start the spacer in the middle of the window
        self.set_position(gtk.gdk.screen_width() / 2)
        self.left_notebook = gtk.Notebook()
        self.add1(self.left_notebook)
        self.right_notebook = gtk.Notebook()
        self.add2(self.right_notebook)

        self.left_notebook.grab_focus()

        for notebook in (self.left_notebook, self.right_notebook):
            notebook.set_group_id(5)

        self.show_all()

    def add(self, window):
        window.connect("unmanaged", self._handle_window_departure)
        self.windows.append(window)
        if self.left_notebook.get_n_pages() > self.right_notebook.get_n_pages():
            notebook = self.right_notebook
        else:
            notebook = self.left_notebook
        notebook.append_page(window)
        notebook.set_tab_reorderable(window, True)
        notebook.set_tab_detachable(window, True)
        window.connect("notify::title", self._handle_title_change)
        self._handle_title_change(window)
        window.show()
        window.grab_focus()

    def _handle_title_change(self, window, *args):
        left_children = self.left_notebook.get_children()
        right_children = self.right_notebook.get_children()
        if window in left_children:
            notebook = self.left_notebook
        elif window in right_children:
            notebook = self.right_notebook
        else:
            print("Mrr?")
            return
        notebook.set_tab_label_text(window,
                                    window.get_property("title"))

    def _handle_window_departure(self, window):
        self.windows.remove(window)
        left_children = self.left_notebook.get_children()
        right_children = self.right_notebook.get_children()
        if window in left_children:
            notebook = self.left_notebook
        elif window in right_children:
            notebook = self.right_notebook
        notebook.remove_page(notebook.page_num(window))

    def windows(self):
        return set(self.windows)
