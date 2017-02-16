# This file is part of Xpra.
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
If we have python3 then use gobject introspection ("gi.repository"),
with python2, we try to import pygtk (gobject/gtk/gdk) before trying gobject introspection.
Once we have imported something, stick to that version from then on for all other imports.
"""

import sys, os

__all__ = ["is_gtk3", "get_xid", "import_gobject", "import_gtk", "import_gdk", "import_pango", "import_glib", "import_pixbufloader"]

_is_gtk3 = None
if sys.version>='3':
    #no other choice!
    _is_gtk3 = True

def is_gtk3():
    global _is_gtk3
    return  _is_gtk3

def want_gtk3(v):
    global _is_gtk3
    assert (_is_gtk3 is None or _is_gtk3==v), "cannot set gtk3=%s, already set to %s" % (v, _is_gtk3)
    _is_gtk3 = v


def _try_import(import_method_gtk3, import_method_gtk2):
    global _is_gtk3
    if "gi" in sys.modules:
        _is_gtk3 = True
    if _is_gtk3 is False:
        return  import_method_gtk2()
    if _is_gtk3 is True:
        return  import_method_gtk3()
    #python3 sets _is_gtk3 early
    assert sys.version_info[0]<3
    try:
        imported = import_method_gtk2()
        _is_gtk3 = False
    except:
        imported = import_method_gtk3()
        _is_gtk3 = True
    return imported

def try_import_GdkX11():
    from xpra.os_util import OSX
    if os.name=="posix" and not OSX:
        #try to ensure that we can call get_xid() on Gdk windows later,
        #this is a workaround for this GTK bug:
        #https://bugzilla.gnome.org/show_bug.cgi?id=656314
        try:
            import gi
            gi.require_version('GdkX11', '3.0')
            from gi.repository import GdkX11            #@UnresolvedImport @UnusedImport
        except:
            pass


def get_xid(window):
    if is_gtk3():
        return window.get_xid()
    else:
        return window.xid


def import_gobject2():
    import gobject
    return gobject
def import_gobject3():
    from gi.repository import GObject               #@UnresolvedImport
    #silence a GTK3 warning about threads_init not beeing needed:
    v = getattr(GObject, "pygobject_version", (0))
    if v>=(3,10):
        def noop(*args):
            pass
        GObject.threads_init = noop
    return GObject
def import_gobject():
    return  _try_import(import_gobject3, import_gobject2)

def import_glib3():
    from gi.repository import GLib                  #@UnresolvedImport
    return GLib
def import_glib2():
    import glib
    return glib
def import_glib():
    return _try_import(import_glib3, import_glib2)

def import_gtk2():
    import pygtk
    pygtk.require("2.0")
    import gtk
    return gtk
def import_gtk3():
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk                   #@UnresolvedImport
    try_import_GdkX11()
    return Gtk
def import_gtk():
    return  _try_import(import_gtk3, import_gtk2)

def import_gdk2():
    from gtk import gdk
    return gdk
def import_gdk3():
    import gi
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gdk                   #@UnresolvedImport
    try_import_GdkX11()
    return Gdk
def import_gdk():
    return  _try_import(import_gdk3, import_gdk2)

def import_pixbufloader2():
    from gtk.gdk import PixbufLoader
    return PixbufLoader
def import_pixbufloader3():
    from gi.repository import GdkPixbuf             #@UnresolvedImport
    return GdkPixbuf.PixbufLoader
def import_pixbufloader():
    return  _try_import(import_pixbufloader3, import_pixbufloader2)

def import_pango2():
    import pango
    return pango
def import_pango3():
    from gi.repository import Pango                 #@UnresolvedImport
    return Pango
def import_pango():
    return  _try_import(import_pango3, import_pango2)

def import_cairo():
    #we cannot use cairocffi with the do_paint callbacks..
    #import cairocffi                            #@UnresolvedImport
    #cairocffi.install_as_pycairo()
    #cairo = cairocffi
    import cairo
    return cairo
