# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uintptr_t   # pylint: disable=syntax-error
from xpra.gtk.bindings.gobject cimport unwrap

from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("bindings", "gtk")

Gdk = gi_import("Gdk")


cdef extern from "AppKit/AppKit.h":
    ctypedef struct NSView:
        pass


cdef extern from "gtk-3.0/gdk/quartz/gdkquartz-cocoa-access.h":
    NSView *gdk_quartz_window_get_nsview(GdkWindow *window)


cdef extern from "gtk-3.0/gdk/gdk.h":
    ctypedef struct GdkWindow:
        pass

cdef GdkWindow *get_gdkwindow(pywindow):
    return <GdkWindow*>unwrap(pywindow, Gdk.Window)

cdef NSView *get_nsview(pywindow):
    cdef GdkWindow *gdkwindow = get_gdkwindow(pywindow)
    assert gdkwindow
    cdef NSView *nsview = gdk_quartz_window_get_nsview(gdkwindow)
    return nsview

def get_nsview_ptr(pywindow) -> int:
    cdef NSView *nsview = get_nsview(pywindow)
    return <uintptr_t> nsview
