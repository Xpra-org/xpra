# This file is part of Parti.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
If we have python3 then try gobject introspection first,
otherwise import gobject/gtk/gdk version 2 (also as fallback)
Once we have imported something, stick to that version from then on.
"""

import sys

_is_gtk3 = None
def is_gtk3():
    global _is_gtk3
    return  _is_gtk3

def _try_import(import_method_gtk3, import_method_gtk2):
    global _is_gtk3
    if sys.version<'3':
        _is_gtk3 = False
    if _is_gtk3 is False:
        return  import_method_gtk2()
    if _is_gtk3 is True:
        return  import_method_gtk3()
    try:
        imported = import_method_gtk3()
        _is_gtk3 = True
        return imported
    except:
        _is_gtk3 = False
        return import_method_gtk2()



def import_gobject2():
    import gobject                                  #@UnusedImport
    return gobject
def import_gobject3():
    from gi.repository import GObject as gobject    #@UnresolvedImport @UnusedImport (python3)
    return gobject
def import_gobject():
    return  _try_import(import_gobject3, import_gobject2)

def import_glib3():
    from gi.repository import GLib                  #@UnresolvedImport @UnusedImport
    return GLib
def import_glib2():
    import glib
    return glib
def import_glib():
    return _try_import(import_glib3, import_glib2)

def import_gtk2():
    import pygtk
    pygtk.require("2.0")
    import gtk                                      #@UnusedImport
    return gtk
def import_gtk3():
    from gi.repository import Gtk as gtk            #@UnresolvedImport @UnusedImport (python3)
    return gtk
def import_gtk():
    return  _try_import(import_gtk3, import_gtk2)

def import_gdk2():
    from gtk import gdk                             #@UnusedImport
    return gdk
def import_gdk3():
    from gi.repository import Gdk as gdk            #@UnresolvedImport @UnusedImport (python3)
    return gdk
def import_gdk():
    return  _try_import(import_gdk3, import_gdk2)
