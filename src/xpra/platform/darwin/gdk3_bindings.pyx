# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: language_level=3

from __future__ import absolute_import

from libc.stdint cimport uintptr_t  #pylint: disable=syntax-error

from xpra.log import Logger
log = Logger("bindings", "gtk")


from xpra.gtk_common.gtk3.gdk_bindings cimport get_gdkwindow

ctypedef float CGFloat
ctypedef int BOOL

cdef extern from "AppKit/AppKit.h":
    ctypedef struct NSColor:
        pass
    ctypedef struct NSWindow:
        pass
    ctypedef struct NSView:
        pass

cdef extern from "transparency_glue.h":
    #couldn't figure out how to get unions and cython+objc to play nice,
    #so we use a wrapper:
    void setAlphaValue(NSWindow *window, float alpha)
    void setOpaque(NSWindow *window, BOOL opaque)
    void setBackgroundColor(NSWindow *window, NSColor *color)
    void setClearBackgroundColor(NSWindow *window)
    void invalidateShadow(NSWindow *window)
    void setHasShadow(NSWindow *window, BOOL hasShadow)


cdef extern from "gtk-3.0/gdk/quartz/gdkquartz-cocoa-access.h":
    NSView *gdk_quartz_window_get_nsview(GdkWindow *window)
    NSWindow *gdk_quartz_window_get_nswindow(GdkWindow *window)


cdef extern from "gtk-3.0/gdk/gdk.h":
    ctypedef struct GdkWindow:
        pass

cdef NSWindow *get_nswindow(pywindow):
    cdef GdkWindow *gdkwindow = get_gdkwindow(pywindow)
    assert gdkwindow
    cdef NSWindow *nswindow = gdk_quartz_window_get_nswindow(gdkwindow)
    return nswindow

cdef NSView *get_nsview(pywindow):
    cdef GdkWindow *gdkwindow = get_gdkwindow(pywindow)
    assert gdkwindow
    cdef NSView *nsview = gdk_quartz_window_get_nsview(gdkwindow)
    return nsview

def get_nsview_ptr(pywindow):
    cdef NSView *nsview = get_nsview(pywindow)
    return <uintptr_t> nsview

def enable_transparency(pywindow):
    cdef NSWindow *window = get_nswindow(pywindow)
    setClearBackgroundColor(window)
    setOpaque(window, 0)
