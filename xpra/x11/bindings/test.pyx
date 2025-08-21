# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.x11.bindings.xlib cimport Display, XID, Bool, KeySym, KeyCode, Atom, Window, Status, Time
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check

from xpra.log import Logger

import_check("test")

log = Logger("x11", "bindings", "keyboard")


cdef extern from "X11/extensions/XTest.h":
    Bool XTestQueryExtension(Display *display, int *event_base_return, int *error_base_return,
                                int * major, int * minor)
    int XTestFakeKeyEvent(Display *, unsigned int keycode,
                          Bool is_press, unsigned long delay)
    int XTestFakeButtonEvent(Display *, unsigned int button,
                             Bool is_press, unsigned long delay)
    int XTestFakeMotionEvent(Display * display, int screen_number, int x, int y, unsigned long delay)
    int XTestFakeRelativeMotionEvent(Display * display, int x, int y, unsigned long delay)


DEF screen_number = 0


cdef class XTestBindingsInstance(X11CoreBindingsInstance):
    cdef int XTest_checked
    cdef int XTest_version_major
    cdef int XTest_version_minor

    def hasXTest(self) -> bool:
        self.context_check("hasXTest")
        if self.XTest_checked:
            return self.XTest_version_major>0 or self.XTest_version_minor>0
        self.XTest_checked = True
        if os.environ.get("XPRA_X11_XTEST", "1")!="1":
            log.warn("XTest disabled using XPRA_X11_XTEST")
            return False
        cdef int evbase, errbase
        cdef int major, minor
        cdef int r = XTestQueryExtension(self.display, &evbase, &errbase, &major, &minor)
        if not r:
            log.warn("Warning: XTest extension is missing")
            return False
        log("XTestQueryExtension found version %i.%i with event base=%i, error base=%i", major, minor, evbase, errbase)
        self.XTest_version_major = major
        self.XTest_version_minor = minor
        return True

    def unpress_keys(self, keycodes: Sequence[int]) -> None:
        if not self.hasXTest():
            return
        for keycode in keycodes:
            XTestFakeKeyEvent(self.display, keycode, False, 0)

    def xtest_fake_key(self, keycode: int, is_press: bool) -> bool:
        if not self.hasXTest():
            return False
        self.context_check("xtest_fake_key")
        return XTestFakeKeyEvent(self.display, keycode, is_press, 0)

    def xtest_fake_button(self, button: int, is_press: bool) -> bool:
        if not self.hasXTest():
            return False
        self.context_check("xtest_fake_button")
        return XTestFakeButtonEvent(self.display, button, is_press, 0)

    def xtest_fake_motion(self, int x, int y, int delay=0) -> bool:
        if not self.hasXTest():
            return False
        self.context_check("xtest_fake_motion")
        return XTestFakeMotionEvent(self.display, screen_number, x, y, delay)

    def xtest_fake_relative_motion(self, int x, int y, int delay=0) -> bool:
        if not self.hasXTest():
            return False
        self.context_check("xtest_fake_relative_motion")
        return XTestFakeRelativeMotionEvent(self.display, x, y, delay)


cdef XTestBindingsInstance singleton = None


def XTestBindings() -> XTestBindingsInstance:
    global singleton
    if singleton is None:
        singleton = XTestBindingsInstance()
    return singleton
