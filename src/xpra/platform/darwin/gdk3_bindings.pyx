# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import absolute_import

from libc.stdint cimport uintptr_t

from xpra.log import Logger
log = Logger("bindings", "gtk")


from xpra.gtk_common.gtk3.gdk_bindings cimport get_gdkwindow

cdef extern from "AppKit/AppKit.h":
    ctypedef struct NSView:
        pass

cdef extern from "gtk-3.0/gdk/gdkquartz.h":
    NSView *gdk_quartz_window_get_nsview(GdkWindow *window)

cdef extern from "gtk-3.0/gdk/gdk.h":
    ctypedef struct GdkWindow:
        pass


cdef NSView *get_nsview(pywindow):
    cdef GdkWindow *gdkwindow = get_gdkwindow(pywindow)
    assert gdkwindow
    cdef NSView *nsview = gdk_quartz_window_get_nsview(gdkwindow)
    return nsview

def get_nsview_ptr(pywindow):
    cdef NSView *nsview = get_nsview(pywindow)
    return <uintptr_t> nsview
