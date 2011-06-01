# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
from wimpiggy.pseudoclient import PseudoclientWindow
from parti.addons.ipython_view import IPythonView

def spawn_repl_window(wm, namespace):
    window = PseudoclientWindow(wm)
    window.set_resizable(True)
    window.set_title("Parti REPL")
    scroll = gtk.ScrolledWindow()
    scroll.set_policy(gtk.POLICY_AUTOMATIC,gtk.POLICY_AUTOMATIC)
    view = IPythonView()
    view.set_wrap_mode(gtk.WRAP_CHAR)
    view.updateNamespace(namespace)
    scroll.add(view)
    window.add(scroll)
    window.show_all()
    window.connect('delete-event', lambda x, y: window.destroy())
