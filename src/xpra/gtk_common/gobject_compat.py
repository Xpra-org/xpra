# This file is part of Xpra.
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#legacy compatibility file

import sys

__all__ = [
    "import_gobject",
    "import_gtk",
    "import_gdk",
    ]


def gi_gtk():
    try:
        from xpra.gtk_common import gi_init
        assert gi_init
    except ImportError:
        pass



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


def import_gobject():
    from gi.repository import GObject               #@UnresolvedImport
    #silence a GTK3 warning about threads_init not beeing needed:
    v = getattr(GObject, "pygobject_version", (0))
    if v>=(3,10):
        def noop(*_args):
            pass
        GObject.threads_init = noop
    return GObject

def import_gtk():
    gi_gtk()
    from gi.repository import Gtk                   #@UnresolvedImport
    try_import_GdkX11()
    Gtk.init()
    return Gtk

def import_gdk():
    gi_gtk()
    from gi.repository import Gdk                   #@UnresolvedImport
    try_import_GdkX11()
    return Gdk


_glib_unix_signals = {}
def register_os_signals(callback):
    from xpra.os_util import SIGNAMES, POSIX, get_util_logger
    from gi.repository import GLib
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
        GLib.idle_add(handle_signal, signum)
    for signum in (signal.SIGINT, signal.SIGTERM):
        if POSIX:
            #replace the previous definition if we had one:
            global _glib_unix_signals
            current = _glib_unix_signals.get(signum, None)
            if current:
                GLib.source_remove(current)
            source_id = GLib.unix_signal_add(GLib.PRIORITY_HIGH, signum, handle_signal, signum)
            _glib_unix_signals[signum] = source_id
        else:
            signal.signal(signum, os_signal)
