# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.lowlevel.bindings import sendClientMessage, const    #@UnresolvedImport
from xpra.log import Logger
log = Logger()

def int32(x):
    if x>0xFFFFFFFF:
        raise OverflowError
    if x>0x7FFFFFFF:
        x=int(0x100000000-x)
        if x<2147483648:
            return -x
        else:
            return -2147483648
    return x

def send_wm_take_focus(target, time):
    log("sending WM_TAKE_FOCUS: %r, %r", target, time)
    sendClientMessage(target, target, False, 0,                     #@UndefinedVariable"
                      "WM_PROTOCOLS",
                      "WM_TAKE_FOCUS", int32(time), 0, 0, 0)

def send_wm_delete_window(target):
    log("sending WM_DELETE_WINDOW")
    sendClientMessage(target, target, False, 0,                     #@UndefinedVariable"
                      "WM_PROTOCOLS",
                      "WM_DELETE_WINDOW",
                      const["CurrentTime"], 0, 0, 0)        #@UndefinedVariable"
