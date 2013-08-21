# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.gtk_x11.gdk_bindings import get_xwindow       #@UnresolvedImport
from xpra.x11.bindings.window_bindings import constants, X11WindowBindings #@UnresolvedImport
X11Window = X11WindowBindings()

from xpra.log import Logger
log = Logger()

def send_wm_take_focus(target, time):
    log("sending WM_TAKE_FOCUS: %r, %r", target, time)
    if time<0:
        time = 0    #should mean CurrentTime which is better than nothing
    elif time>0xFFFFFFFF:
        raise OverflowError("invalid time: %s" % hex(time))
    X11Window.sendClientMessage(get_xwindow(target), get_xwindow(target), False, 0,                     #@UndefinedVariable"
                      "WM_PROTOCOLS",
                      "WM_TAKE_FOCUS", time, 0, 0, 0)

def send_wm_delete_window(target):
    log("sending WM_DELETE_WINDOW")
    X11Window.sendClientMessage(get_xwindow(target), get_xwindow(target), False, 0,                     #@UndefinedVariable"
                      "WM_PROTOCOLS",
                      "WM_DELETE_WINDOW",
                      constants["CurrentTime"], 0, 0, 0)        #@UndefinedVariable"
