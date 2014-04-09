# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.x11.gtk_x11.gdk_bindings import (
            add_event_receiver,             #@UnresolvedImport
            remove_event_receiver,          #@UnresolvedImport
            get_parent)  #@UnresolvedImport
from xpra.x11.gtk_x11.error import trap
from xpra.x11.bindings.window_bindings import constants, X11WindowBindings #@UnresolvedImport
from xpra.x11.gtk_x11.world_window import get_world_window
X11Window = X11WindowBindings()

from xpra.log import Logger
log = Logger("x11", "window", "grab")


StructureNotifyMask = constants["StructureNotifyMask"]

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
log("pointer grab constants: %s", GRAB_CONSTANTS)


class PointerGrabHelper(gobject.GObject):
    """ Listens for StructureNotifyMask events
        on the window and its parents.
    """

    __gsignals__ = {
        "xpra-unmap-event"      : one_arg_signal,
        "xpra-reparent-event"   : one_arg_signal,

        "xpra-focus-in-event"   : one_arg_signal,
        "xpra-focus-out-event"  : one_arg_signal,

        "grab"                  : one_arg_signal,
        "ungrab"                : one_arg_signal,
        }

    # This may raise XError.
    def __init__(self, window):
        super(PointerGrabHelper, self).__init__()
        log("PointerGrabHelper.__init__(%#x)", window.xid)
        self._has_grab = False
        self._window = window
        self._listening = None

    def __repr__(self):
        xid = 0
        if self._window:
            xid = self._window.xid
        return "PointerGrabHelper(%#x - %s)" % (xid, [hex(x.xid) for x in (self._listening or [])])

    def setup(self):
        self._setup_listening()

    def destroy(self):
        if self._window is None:
            log.warn("pointer grab helper %s already destroyed!", self)
        self._window = None
        self.force_ungrab("destroying window")
        self._cleanup_listening()


    def _cleanup_listening(self):
        if self._listening:
            for w in self._listening:
                remove_event_receiver(w, self)
            self._listening = None

    def _setup_listening(self):
        try:
            trap.call_synced(self.do_setup_listening)
        except Exception, e:
            log("PointerGrabHelper._setup_listening() failed: %s", e)

    def do_setup_listening(self):
        assert self._listening is None
        add_event_receiver(self._window, self, max_receivers=-1)
        self._listening = [self._window]
        #recurse parents:
        root = self._window.get_screen().get_root_window()
        world = get_world_window().window
        win = get_parent(self._window)
        while win not in (None, root, world) and win.get_parent() is not None:
            # We have to use a lowlevel function to manipulate the
            # event selection here, because SubstructureRedirectMask
            # does not roundtrip through the GDK event mask
            # functions.  So if we used them, here, we would clobber
            # corral window selection masks, and those don't deserve
            # clobbering.  They are our friends!  X is driving me
            # slowly mad.
            X11Window.addXSelectInput(win.xid, StructureNotifyMask)
            add_event_receiver(win, self, max_receivers=-1)
            self._listening.append(win)
            win = get_parent(win)
        log("grab: listening for: %s", [hex(x.xid) for x in self._listening])

    def do_xpra_unmap_event(self, event):
        log("grab: unmap %s", event)
        #can windows be unmapped with a grab held?
        self.force_ungrab(event)

    def do_xpra_reparent_event(self, event):
        log("grab: reparent %s", event)
        #maybe this isn't needed?
        self.force_ungrab(event)
        #setup new tree:
        self._cleanup_listening()
        self._setup_listening()

    def force_ungrab(self, event):
        log("force ungrab (has_grab=%s) %s", self._has_grab, event)
        if self._has_grab:
            self._has_grab = False
            self.emit("ungrab", event)


    def do_xpra_focus_in_event(self, event):
        log("focus_in_event(%s) mode=%s", event, GRAB_CONSTANTS.get(event.mode))
        self._focus_event(event)

    def do_xpra_focus_out_event(self, event):
        log("focus_out_event(%s) mode=%s", event, GRAB_CONSTANTS.get(event.mode))
        self._focus_event(event)

    def _focus_event(self, event):
        if event.mode==NotifyGrab and not self._has_grab:
            log("emitting grab on %s", self)
            self._has_grab = True
            self.emit("grab", event)
        if event.mode==NotifyUngrab:
            log("emitting ungrab on %s", self)
            self._has_grab = False
            self.emit("ungrab", event)


gobject.type_register(PointerGrabHelper)
