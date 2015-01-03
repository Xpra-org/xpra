# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.window_bindings import constants, X11WindowBindings #@UnresolvedImport
X11Window = X11WindowBindings()

from xpra.log import Logger
log = Logger("x11", "focus")

CurrentTime = constants["CurrentTime"]


def send_wm_take_focus(target, timestamp):
    log("sending WM_TAKE_FOCUS: %#x, X11 timestamp=%r", target.xid, timestamp)
    if timestamp<0:
        timestamp = CurrentTime    #better than nothing...
    elif timestamp>0xFFFFFFFF:
        raise OverflowError("invalid time: %#x" % timestamp)
    X11Window.sendClientMessage(target.xid, target.xid, False, 0,
                      "WM_PROTOCOLS",
                      "WM_TAKE_FOCUS", timestamp)

def send_wm_delete_window(target):
    log("sending WM_DELETE_WINDOW to %#x", target.xid)
    X11Window.sendClientMessage(target.xid, target.xid, False, 0,
                      "WM_PROTOCOLS",
                      "WM_DELETE_WINDOW",
                      CurrentTime)
