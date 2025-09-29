# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Final

from xpra.util.parsing import TRUE_OPTIONS
from xpra.x11.common import get_pywindow
from xpra.x11.error import xsync
from xpra.util.str_fn import csv
from xpra.util.gobject import no_arg_signal, one_arg_signal
from xpra.x11.bindings.core import constants
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.x11.selection.common import AlreadyOwned, xfixes_selection_input
from xpra.x11.common import X11Event
from xpra.x11.prop import prop_set
from xpra.x11.info import get_wininfo
from xpra.util.env import envint
from xpra.os_util import gi_import
from xpra.log import Logger

GLib = gi_import("GLib")
GObject = gi_import("GObject")

log = Logger("x11", "util")

SELECTION_EXIT_TIMEOUT = envint("XPRA_SELECTION_EXIT_TIMEOUT", 20)

PropertyChangeMask: Final[int] = constants["PropertyChangeMask"]
StructureNotifyMask: Final[int] = constants["StructureNotifyMask"]
XNone: Final[int] = constants["XNone"]
InputOnly: Final[int] = constants["InputOnly"]


def get_owner(selection: str) -> int:
    return X11WindowBindings().XGetSelectionOwner(selection)


def create_manager_window() -> int:
    X11Window = X11WindowBindings()
    rxid = X11Window.get_root_xid()
    event_mask = PropertyChangeMask
    xid = X11Window.CreateWindow(rxid, -1, -1, event_mask=event_mask, inputoutput=InputOnly)
    prop_set(xid, "WM_TITLE", "latin1", "XPRA-SELECTION-MANAGER")
    log("create_manager_window()=%#x", xid)
    return xid


class ManagerSelection(GObject.GObject):
    __gsignals__ = {
        # X11 signals we listen for:
        "x11-client-message-event": one_arg_signal,
        "x11-selection-request": one_arg_signal,
        "x11-selection-clear": one_arg_signal,
        # "x11-property-notify-event": one_arg_signal,
        "x11-destroy-event": one_arg_signal,
        # signals we emit:
        "selection-acquired": no_arg_signal,
        "selection-lost": no_arg_signal,
    }

    def __repr__(self):  # pylint: disable=arguments-differ
        return "ManagerSelection(%s)" % csv(self.selections)

    def __init__(self, *selections: str):
        super().__init__()
        self.selections = selections
        self.acquired: set[str] = set()
        self.owners: dict[int, str] = {}
        self.timestamp = 0
        self.exit_timer: int = 0
        with xsync:
            self.xid = create_manager_window()
            # so gtk doesn't get confused:
            self.window = get_pywindow(self.xid)
            rxid = X11WindowBindings().get_root_xid()
            for xid in (self.xid, rxid):
                for selection in self.selections:
                    xfixes_selection_input(xid, selection)
                add_event_receiver(xid, self)

    def acquire(self, force=False) -> None:
        """
        This method should cause either the `selection-acquired` or the `selection-lost` signals to fire
        """
        X11Window = X11WindowBindings()
        log("window bindings=%s", X11Window)
        with xsync:
            self.timestamp = X11Window.get_server_time(self.xid)
            log("acquire(%s) server timestamp=%s for selections=%s", force, self.timestamp, csv(self.selections))

        with xsync:
            for selection in self.selections:
                owner = get_owner(selection)
                if owner == XNone:
                    log("%r is not owned", selection)
                    self.acquire_selection(selection)
                    self.acquired_selection(selection)
                    continue

                if not force:
                    log.error("Error: %r is already owned by %s", selection, get_wininfo(owner))
                    raise AlreadyOwned()

                log(f"got existing owner window {owner:x} for %r: %s", selection, get_wininfo(owner))

                # we have to wait for the current owner to exit,
                # before we can emit `selection-acquired`:
                self.owners[owner] = selection
                X11Window.addXSelectInput(owner, StructureNotifyMask)
                add_event_receiver(owner, self)
                self.acquire_selection(selection)
                self.cancel_exit_timer()
                self.exit_timer = GLib.timeout_add(SELECTION_EXIT_TIMEOUT * 1000, self.exit_timeout)

    def cancel_exit_timer(self) -> None:
        et = self.exit_timer
        log("cancel_exit_timer() exit timer=%i", et)
        if et:
            self.exit_timer = 0
            GLib.source_remove(et)

    def exit_timeout(self) -> None:
        self.exit_timer = 0
        log.error("selection timeout")
        log.error(" the current owner did not exit")
        self.emit("selection-lost")

    def acquire_selection(self, selection: str) -> None:
        with xsync:
            X11Window = X11WindowBindings()
            X11Window.XSetSelectionOwner(self.xid, selection, self.timestamp)
            # Send announcement: (see ICCCM 2.8)
            root_xid = X11Window.get_root_xid()
            X11Window.sendClientMessage(root_xid, root_xid, False, StructureNotifyMask,
                                        "MANAGER",
                                        self.timestamp, selection, self.xid)

    def acquired_selection(self, selection: str) -> None:
        self.acquired.add(selection)
        if set(self.selections) == self.acquired:
            self.cancel_exit_timer()
            self.emit("selection-acquired")

    def do_x11_selection_request(self, event: X11Event) -> None:
        # only ever used for providing the version of the spec:
        log("do_selection_request_event(%s)", event)
        requestor = event.requestor
        prop = event.property
        target = str(event.target)
        if target not in self.selections:
            log.warn("Warning: unsupported selection target: %s", target)
            return
        if prop != "VERSION":
            wininfo = get_wininfo(requestor)
            log("requestor: %s", wininfo)
            log.warn("Warning: unknown property requested from the selection manager")
            return

        from struct import pack
        with xsync:
            version_data = pack("@ii", 2, 0)
            X11Window = X11WindowBindings()
            X11Window.XChangeProperty(requestor, prop, "INTEGER", 32, version_data)
            X11Window.sendSelectionNotify(requestor, "selection", target, prop, event.time)

    def do_x11_destroy_event(self, event: X11Event) -> None:
        xid = event.window
        if not xid:
            return
        remove_event_receiver(xid, self)
        # if this is the previous selection owner,
        # then we have successfully acquired it
        selection = self.owners.pop(xid, "")
        if xid == self.xid:
            self.cancel_exit_timer()
            self.emit("selection-lost")
        elif selection:
            self.acquired_selection(selection)

    def do_x11_selection_clear(self, event: X11Event) -> None:
        log("do_x11_selection_clear(%s) %s", event, event.selection)
        log.info("lost the %r selection", event.selection)
        self.emit("selection-lost")


GObject.type_register(ManagerSelection)


def main(argv: list[str]) -> int:
    if len(argv) >= 2:
        os.environ["DISPLAY"] = argv[1]

    force = len(argv) == 3 and argv[2] in TRUE_OPTIONS

    from xpra.platform import program_context
    with program_context("Window Manager Selection", "Window-Manager-Selection"):
        from xpra.x11.gtk.display_source import init_gdk_display_source
        init_gdk_display_source()
        from xpra.x11.gtk.bindings import init_x11_filter
        init_x11_filter()

        manager = ManagerSelection("_NET_WM_CM_S0", "WM_S0")

        def acquired(mgr):
            log.info("acquired(%r)", mgr)

        def lost(mgr):
            log.info("lost(%r)", mgr)
            loop.quit()

        manager.connect("selection-acquired", acquired)
        manager.connect("selection-lost", lost)

        def acquire() -> None:
            manager.acquire(force)

        GLib.timeout_add(1000, acquire)
        loop = GLib.MainLoop()

        from xpra.util.glib import register_os_signals

        def signal_quit(_signum) -> None:
            loop.quit()
        register_os_signals(signal_quit)

        loop.run()
        return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
