# This file is part of Xpra.
# Copyright (C) 2012-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
If we have python3 then use gobject introspection ("gi.repository"),
with python2, we try to import pygtk (gobject/gtk/gdk) before trying gobject introspection.
Once we have imported something, stick to that version from then on for all other imports.
"""

import sys

__all__ = [
    "is_gtk3",
    "import_gobject",
    "import_gtk",
    "import_gdk",
    "import_pango",
    "import_glib",
    "import_pixbufloader",
    ]

_is_gtk3 = None
if sys.version>='3':
    #no other choice!
    _is_gtk3 = True

def gi_gtk():
    try:
        from xpra.gtk_common import gi_init
        assert gi_init
    except ImportError:
        pass


def is_gtk3():
    global _is_gtk3
    return  _is_gtk3

def want_gtk3(v):
    global _is_gtk3
    assert (_is_gtk3 is None or _is_gtk3==v), "cannot set gtk3=%s, already set to %s" % (v, _is_gtk3)
    _is_gtk3 = v

def gtk_version():
    return 2+int(is_gtk3())

def _try_import(import_method_gtk3, import_method_gtk2):
    global _is_gtk3
    if "gi" in sys.modules:
        _is_gtk3 = True
    if _is_gtk3 is False:
        return import_method_gtk2()
    def trygtk3():
        #if the introspection data is missing,
        #we can get a ValueError
        #but this confuses a number of tools that try to load our code (ie: py2app)
        try:
            return import_method_gtk3()
        except ValueError as e:
            raise ImportError(e)
    if _is_gtk3 is True:
        return trygtk3()
    #python3 sets _is_gtk3 early
    assert sys.version_info[0]<3
    try:
        imported = import_method_gtk2()
        _is_gtk3 = False
    except ImportError:
        imported = trygtk3()
        _is_gtk3 = True
    return imported

def try_import_GdkX11():
    from xpra.os_util import OSX, POSIX
    if POSIX and not OSX:
        #try to ensure that we can call get_xid() on Gdk windows later,
        #this is a workaround for this GTK bug:
        #https://bugzilla.gnome.org/show_bug.cgi?id=656314
        try:
            import gi
            gi.require_version('GdkX11', '3.0')
            from gi.repository import GdkX11            #@UnresolvedImport @UnusedImport
            return GdkX11
        except ImportError:
            pass
    return None


def import_gobject2():
    import gobject                                  #@UnresolvedImport
    gobject.threads_init()
    return gobject
def import_gobject3():
    from gi.repository import GObject               #@UnresolvedImport
    #silence a GTK3 warning about threads_init not beeing needed:
    v = getattr(GObject, "pygobject_version", (0))
    if v>=(3,10):
        def noop(*_args):
            pass
        GObject.threads_init = noop
    return GObject
def import_gobject():
    return  _try_import(import_gobject3, import_gobject2)

def import_glib3():
    import gi
    from gi.repository import GLib                  #@UnresolvedImport
    if gi.version_info<(3, 11):
        GLib.threads_init()
    return GLib
def import_glib2():
    import glib                                     #@UnresolvedImport
    glib.threads_init()
    return glib
def import_glib():
    return _try_import(import_glib3, import_glib2)

def import_gtk2():
    import pygtk                                    #@UnresolvedImport
    pygtk.require("2.0")
    import gtk                                      #@UnresolvedImport
    return gtk
def import_gtk3():
    gi_gtk()
    from gi.repository import Gtk                   #@UnresolvedImport
    try_import_GdkX11()
    Gtk.init()
    return Gtk
def import_gtk():
    return  _try_import(import_gtk3, import_gtk2)

def import_gdk2():
    from gtk import gdk                             #@UnresolvedImport
    return gdk
def import_gdk3():
    gi_gtk()
    from gi.repository import Gdk                   #@UnresolvedImport
    try_import_GdkX11()
    return Gdk
def import_gdk():
    return  _try_import(import_gdk3, import_gdk2)

def import_pixbuf2():
    from gtk.gdk import Pixbuf                      #@UnresolvedImport
    return Pixbuf
def import_pixbuf3():
    gi_gtk()
    from gi.repository import GdkPixbuf             #@UnresolvedImport
    return GdkPixbuf
def import_pixbuf():
    return  _try_import(import_pixbuf3, import_pixbuf2)

def import_pixbufloader2():
    from gtk.gdk import PixbufLoader                #@UnresolvedImport
    return PixbufLoader
def import_pixbufloader3():
    from gi.repository import GdkPixbuf             #@UnresolvedImport
    return GdkPixbuf.PixbufLoader
def import_pixbufloader():
    return  _try_import(import_pixbufloader3, import_pixbufloader2)

def import_pango2():
    import pango                                    #@UnresolvedImport
    return pango
def import_pango3():
    from gi.repository import Pango                 #@UnresolvedImport
    return Pango
def import_pango():
    return  _try_import(import_pango3, import_pango2)

def import_pangocairo2():
    import pangocairo                               #@UnresolvedImport
    return pangocairo
def import_pangocairo3():
    from gi.repository import PangoCairo            #@UnresolvedImport
    return PangoCairo
def import_pangocairo():
    return  _try_import(import_pangocairo3, import_pangocairo2)

def import_cairo():
    #we cannot use cairocffi with the do_paint callbacks..
    #import cairocffi                            #@UnresolvedImport
    #cairocffi.install_as_pycairo()
    #cairo = cairocffi
    import cairo
    return cairo

def import_gtkosx_application2():
    import gtkosx_application                   #@UnresolvedImport
    return gtkosx_application
def import_gtkosx_application3():
    import gi
    gi.require_version('GtkosxApplication', '1.0')
    from gi.repository import GtkosxApplication #@UnresolvedImport
    return GtkosxApplication
def import_gtkosx_application():
    return _try_import(import_gtkosx_application3, import_gtkosx_application2)

_glib_unix_signals = {}
def register_os_signals(callback):
    from xpra.os_util import SIGNAMES, POSIX, PYTHON3, get_util_logger
    glib = import_glib()
    import signal
    def handle_signal(signum):
        try:
            sys.stderr.write("\n")
            sys.stderr.flush()
            get_util_logger().info("got signal %s", SIGNAMES.get(signum, signum))
        except (IOError, OSError):
            pass
        callback(signum)
    def os_signal(signum, _frame):
        glib.idle_add(handle_signal, signum)
    for signum in (signal.SIGINT, signal.SIGTERM):
        if POSIX and PYTHON3:
            #replace the previous definition if we had one:
            global _glib_unix_signals
            current = _glib_unix_signals.get(signum, None)
            if current:
                glib.source_remove(current)
            source_id = glib.unix_signal_add(glib.PRIORITY_HIGH, signum, handle_signal, signum)
            _glib_unix_signals[signum] = source_id
        else:
            signal.signal(signum, os_signal)
