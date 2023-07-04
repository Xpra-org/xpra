# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# According to ICCCM 2.8/4.3, a window manager for screen N is a client which
# acquires the selection WM_S<N>.  If another client already has this
# selection, we can either abort or steal it.  Once we have it, if someone
# else steals it, then we should exit.

import sys
from struct import unpack, calcsize
import gi
gi.require_version('Gtk', '3.0')  # @UndefinedVariable
gi.require_version('Gdk', '3.0')  # @UndefinedVariable
from gi.repository import GObject, Gtk, Gdk, GLib  # @UnresolvedImport

from xpra.gtk_common.gobject_util import no_arg_signal, one_arg_signal
from xpra.x11.bindings.window import constants, X11WindowBindings #@UnresolvedImport
from xpra.x11.gtk3.gdk_bindings import (
    add_event_receiver,         #@UnresolvedImport
    remove_event_receiver,      #@UnresolvedImport
    get_xatom,                  #@UnresolvedImport
    get_pywindow,               #@UnresolvedImport
    )
from xpra.exit_codes import ExitCode
from xpra.util import envint
from xpra.log import Logger

log = Logger("x11", "util")

SELECTION_EXIT_TIMEOUT = envint("XPRA_SELECTION_EXIT_TIMEOUT", 20)

StructureNotifyMask = constants["StructureNotifyMask"]
XNone = constants["XNone"]


class AlreadyOwned(Exception):
    pass

class ManagerSelection(GObject.GObject):
    __gsignals__ = {
        "selection-lost": no_arg_signal,
        "xpra-destroy-event": one_arg_signal,
        }

    def __str__(self):  #pylint: disable=arguments-differ
        return "ManagerSelection(%s)" % self.atom

    def __init__(self, selection):
        super().__init__()
        self.atom = selection
        atom = Gdk.Atom.intern(selection, False)
        self.clipboard = Gtk.Clipboard.get(atom)
        self.xid : int = 0
        self.exit_timer : int = 0

    def _owner(self) -> int:
        return X11WindowBindings().XGetSelectionOwner(self.atom)

    def owned(self) -> bool:
        """Returns True if someone owns the given selection."""
        return self._owner() != XNone

    # If the selection is already owned, then raise AlreadyOwned rather
    # than stealing it.
    IF_UNOWNED = "if_unowned"
    # If the selection is already owned, then steal it, and then block until
    # the previous owner has signaled that they are done cleaning up.
    FORCE = "force"
    # If the selection is already owned, then steal it and return immediately.
    # Created for the use of tests.
    FORCE_AND_RETURN = "force_and_return"
    def acquire(self, when):
        old_owner = self._owner()
        if when is self.IF_UNOWNED and old_owner != XNone:
            raise AlreadyOwned

        #we can only set strings with GTK3,
        # we should try to be compliant with ICCCM version 2.0 (see section 4.3)
        # and use this format instead:
        # outdata.set("INTEGER", 32, pack("@ii", 2, 0))
        thestring = "VERSION"
        self.clipboard.set_text(thestring, len(thestring))

        # Having acquired the selection, we have to announce our existence
        # (ICCCM 2.8, still).  The details here probably don't matter too
        # much; I've never heard of an app that cares about these messages,
        # and metacity actually gets the format wrong in several ways (no
        # MANAGER or owner_window atoms).  But might as well get it as right
        # as possible.

        # To announce our existence, we need:
        #   -- the timestamp we arrived at
        #   -- the manager selection atom
        #   -- the window that registered the selection
        # Of course, because Gtk is doing so much magic for us, we have to do
        # some weird tricks to get at these.

        # Ask ourselves when we acquired the selection:
        timestamp_atom = Gdk.Atom.intern("TIMESTAMP", False)
        contents = self.clipboard.wait_for_contents(timestamp_atom)
        ts_data = contents.get_data()
        log("ManagerSelection.acquire(%s) %s.wait_for_contents(%s)=%s",
            when, self.clipboard, timestamp_atom, ts_data)

        #data is a timestamp, X11 datatype is Time which is CARD32,
        #(which is 64 bits on 64-bit systems!)
        Lsize = calcsize("@L")
        if len(ts_data)==Lsize:
            ts_num = unpack("@L", ts_data[:Lsize])[0]
        else:
            ts_num = 0      #CurrentTime
            log.warn("invalid data for 'TIMESTAMP': %s", tuple(hex(ord(x)) for x in ts_data))
        log("selection timestamp(%s)=%s", ts_data, ts_num)
        # Calculate the X atom for this selection:
        selection_xatom = get_xatom(self.atom)
        # Ask X what window we used:
        self.xid = int(X11WindowBindings().XGetSelectionOwner(self.atom))

        root = self.clipboard.get_display().get_default_screen().get_root_window()
        xid = root.get_xid()
        X11WindowBindings().sendClientMessage(xid, xid, False, StructureNotifyMask,
                          "MANAGER",
                          ts_num, selection_xatom, self.xid)

        if old_owner != XNone and when is self.FORCE:
            # Block in a recursive mainloop until the previous owner has
            # cleared out.
            window = get_pywindow(old_owner)
            if not window:
                log(f"Previous owner {old_owner:x} is already gone? not blocking")
            else:
                log(f"got owner window {window}")
                window.set_events(window.get_events() | Gdk.EventMask.STRUCTURE_MASK)
                log("Waiting for previous owner to exit...")
                add_event_receiver(window.get_xid(), self)
                self.exit_timer = GLib.timeout_add(SELECTION_EXIT_TIMEOUT*1000, self.exit_timeout)
                Gtk.main()
                if self.exit_timer:
                    GLib.source_remove(self.exit_timer)
                    self.exit_timer = 0
                log("...they did.")
        window = get_pywindow(self.xid)
        window.set_title("Xpra_ManagerSelection%s" % self.atom)
        self.clipboard.connect("owner-change", self._owner_change)

    def exit_timeout(self) -> None:
        self.exit_timer = 0
        log.error("selection timeout")
        log.error(" the current owner did not exit")
        sys.exit(ExitCode.TIMEOUT)

    def _owner_change(self, clipboard, event) -> None:
        log(f"owner_change({clipboard}, {event}) selection={event.selection}")
        if str(event.selection)!=self.atom or not event.owner:
            #log("_owner_change(..) not our selection: %s vs %s", event.selection, self.atom)
            return
        owner = event.owner.get_xid()
        log(f"owner_change({clipboard}, {event}) selection={event.selection}, owner={owner:x}, xid={self.xid:x}")
        if owner==self.xid:
            log("_owner_change(..) we still own %s", event.selection)
            return
        if self.xid:
            self.xid = 0
            self.emit("selection-lost")

    def do_xpra_destroy_event(self, event) -> None:
        xid = event.window
        if xid:
            remove_event_receiver(xid, self)
        Gtk.main_quit()

    def window(self):
        if self.xid is None:
            return None
        return get_pywindow(self.xid)

GObject.type_register(ManagerSelection)
