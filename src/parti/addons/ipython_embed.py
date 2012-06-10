# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
from parti.addons.ipython_view import IPythonView

class PseudoclientWindow(gtk.Window):
    """A gtk.Window that acts like an ordinary client.

    All the wm-magic that would normally accrue to a window created within our
    process is removed.

    Keyword arguments (notably 'type') are forwarded to
    gtk.Window.__init__.

    The reason this is a separate class, as opposed to say a gtk.Window
    factory method on wm, is that this way allows for subclassing."""
    
    def __init__(self, wm, **kwargs):
        gtk.Window.__init__(self, **kwargs)
        wm._make_window_pseudoclient(self)

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
