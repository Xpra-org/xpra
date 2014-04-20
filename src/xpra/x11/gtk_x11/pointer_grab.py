# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.x11.gtk_x11.gdk_bindings import add_event_receiver,remove_event_receiver    #@UnresolvedImport
from xpra.x11.bindings.window_bindings import constants, X11WindowBindings #@UnresolvedImport
X11Window = X11WindowBindings()

from xpra.log import Logger
log = Logger("x11", "window", "grab")


StructureNotifyMask = constants["StructureNotifyMask"]
EnterWindowMask = constants["EnterWindowMask"]
LeaveWindowMask = constants["LeaveWindowMask"]

NotifyNormal        = constants["NotifyNormal"]
NotifyGrab          = constants["NotifyGrab"]
NotifyUngrab        = constants["NotifyUngrab"]
NotifyWhileGrabbed  = constants["NotifyWhileGrabbed"]

GRAB_CONSTANTS = {
                  NotifyNormal          : "NotifyNormal",
                  NotifyGrab            : "NotifyGrab",
                  NotifyUngrab          : "NotifyUngrab",
                  NotifyWhileGrabbed    : "NotifyWhileGrabbed",
                 }

DETAIL_CONSTANTS    = {}
for x in ("NotifyAncestor", "NotifyVirtual", "NotifyInferior",
          "NotifyNonlinear", "NotifyNonlinearVirtual", "NotifyPointer",
          "NotifyPointerRoot", "NotifyDetailNone"):
    DETAIL_CONSTANTS[constants[x]] = x

REVERT_CONSTANTS = {}
for x in ("RevertToParent", "RevertToPointerRoot", "RevertToNone"):
    REVERT_CONSTANTS[constants[x]] = x


log("pointer grab constants: %s", GRAB_CONSTANTS)
log("detail constants: %s", DETAIL_CONSTANTS)


class PointerGrabHelper(gobject.GObject):
    """ Listens for focus Grab/Ungrab events """

    __gsignals__ = {
        "xpra-focus-in-event"   : one_arg_signal,
        "xpra-focus-out-event"  : one_arg_signal,

        "grab"                  : one_arg_signal,
        "ungrab"                : one_arg_signal,
        }

    def __init__(self, window):
        super(PointerGrabHelper, self).__init__()
        log("PointerGrabHelper.__init__(%s)", window)
        self._window = window
        add_event_receiver(self._window, self)
        #do we also need enter/leave?
        X11Window.addXSelectInput(self._window.xid, StructureNotifyMask | EnterWindowMask | LeaveWindowMask)

    def __repr__(self):
        return "PointerGrabHelper(%s)" % self._window

    def cleanup(self):
        if self._window:
            remove_event_receiver(self._window, self)
            self._window = None
        else:
            log.warn("pointer grab helper %s already destroyed!", self)


    def do_xpra_focus_in_event(self, event):
        log("focus_in_event(%s) mode=%s, detail=%s",
            event, GRAB_CONSTANTS.get(event.mode), DETAIL_CONSTANTS.get(event.detail, event.detail))
        self.may_emit_grab(event)

    def do_xpra_focus_out_event(self, event):
        log("focus_out_event(%s) mode=%s, detail=%s",
            event, GRAB_CONSTANTS.get(event.mode), DETAIL_CONSTANTS.get(event.detail, event.detail))
        self.may_emit_grab(event)

    def may_emit_grab(self, event):
        if event.mode==NotifyGrab:
            log("emitting grab on %s", self)
            self.emit("grab", event)
        if event.mode==NotifyUngrab:
            log("emitting ungrab on %s", self)
            self.emit("ungrab", event)


gobject.type_register(PointerGrabHelper)
