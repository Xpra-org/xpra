# This file is part of Xpra.
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject

from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.x11.gtk_x11.prop import prop_set, prop_get
from xpra.gtk_common.error import xswallow, xsync

from xpra.x11.bindings.window_bindings import constants, X11WindowBindings #@UnresolvedImport
X11Window = X11WindowBindings()

from xpra.x11.gtk2.gdk_bindings import (
               add_event_receiver,                          #@UnresolvedImport
               remove_event_receiver,                       #@UnresolvedImport
               )

from xpra.log import Logger
log = Logger("x11", "tray")


CurrentTime = constants["CurrentTime"]
XNone = constants["XNone"]
StructureNotifyMask = constants["StructureNotifyMask"]


XEMBED_VERSION = 0

# XEmbed
XEMBED_EMBEDDED_NOTIFY          = 0
XEMBED_WINDOW_ACTIVATE          = 1
XEMBED_WINDOW_DEACTIVATE        = 2
XEMBED_REQUEST_FOCUS            = 3
XEMBED_FOCUS_IN                 = 4
XEMBED_FOCUS_OUT                = 5
XEMBED_FOCUS_NEXT               = 6
XEMBED_FOCUS_PREV               = 7
# 8-9 were used for XEMBED_GRAB_KEY/XEMBED_UNGRAB_KEY */
XEMBED_MODALITY_ON              = 10
XEMBED_MODALITY_OFF             = 11
XEMBED_REGISTER_ACCELERATOR     = 12
XEMBED_UNREGISTER_ACCELERATOR   = 13
XEMBED_ACTIVATE_ACCELERATOR     = 14
# A detail code is required for XEMBED_FOCUS_IN. The following values are valid:
# Details for  XEMBED_FOCUS_IN:
XEMBED_FOCUS_CURRENT    = 0
XEMBED_FOCUS_FIRST      = 1
XEMBED_FOCUS_LAST       = 2

SELECTION = "_NET_SYSTEM_TRAY_S0"
TRAY_VISUAL = "_NET_SYSTEM_TRAY_VISUAL"
TRAY_ORIENTATION = "_NET_SYSTEM_TRAY_ORIENTATION"

TRAY_ORIENTATION_HORZ   = 0
TRAY_ORIENTATION_VERT   = 1

XPRA_TRAY_WINDOW_PROPERTY = "_xpra_tray_window_"

#TRANSPARENCY = False
TRANSPARENCY = True

#Java can send this message to the tray (no idea why):
IGNORED_MESSAGE_TYPES = ("_GTK_LOAD_ICONTHEMES", )


def get_tray_window(tray_window):
    return tray_window.get_data(XPRA_TRAY_WINDOW_PROPERTY)

def set_tray_window(tray_window, window):
    tray_window.set_data(XPRA_TRAY_WINDOW_PROPERTY, window.xid)

def set_tray_visual(tray_window, gdk_visual):
    prop_set(tray_window, TRAY_VISUAL, "visual", gdk_visual)

def set_tray_orientation(tray_window, orientation):
    prop_set(tray_window, TRAY_ORIENTATION, "u32", orientation)


class SystemTray(gobject.GObject):
    """ This is an X11 system tray area,
        owning the "_NET_SYSTEM_TRAY_S0" selection,
        X11 client applications can request to embed their tray icon in it,
        the xpra server can request to "move_resize" to where the xpra client has it mapped.
    """

    __gsignals__ = {
        "xpra-unmap-event": one_arg_signal,
        "xpra-client-message-event": one_arg_signal,
        }

    def __init__(self):
        gobject.GObject.__init__(self)
        self.tray_window = None
        self.window_trays = {}
        self.tray_windows = {}
        self.setup_tray_window()

    def cleanup(self):
        log("SystemTray.cleanup()")
        root = gdk.get_default_root_window()
        def undock(window):
            log("undocking %s", window)
            X11Window.Unmap(window.xid)
            X11Window.Reparent(window.xid, root.xid, 0, 0)
        with xswallow:
            owner = X11Window.XGetSelectionOwner(SELECTION)
            if owner==self.tray_window.xid:
                X11Window.XSetSelectionOwner(0, SELECTION)
                log("SystemTray.cleanup() reset %s selection owner to %#x", SELECTION, X11Window.XGetSelectionOwner(SELECTION))
            else:
                log.warn("Warning: we were no longer the tray selection owner")
        remove_event_receiver(self.tray_window, self)
        tray_windows = self.tray_windows
        self.tray_windows = {}
        for window, tray_window in tray_windows.items():
            with xswallow:
                undock(window)
            tray_window.destroy()
        self.tray_window.destroy()
        self.tray_window = None
        log("SystemTray.cleanup() done")

    def setup_tray_window(self):
        display = gtk.gdk.display_get_default()
        root = gtk.gdk.get_default_root_window()
        screen = root.get_screen()
        if TRANSPARENCY:
            colormap, visual = screen.get_rgba_colormap(), screen.get_rgba_visual()
        if colormap is None or visual is None:
            log.warn("setup tray: using rgb visual fallback")
            colormap, visual = screen.get_rgb_colormap(), screen.get_rgb_visual()
        assert colormap is not None and visual is not None, "failed to obtain visual or colormap"
        owner = X11Window.XGetSelectionOwner(SELECTION)
        log("setup tray: current selection owner=%#x", owner)
        if owner!=XNone:
            raise Exception("%s already owned by %s" % (SELECTION, owner))
        self.tray_window = gtk.gdk.Window(root, width=1, height=1,
                                           window_type=gtk.gdk.WINDOW_TOPLEVEL,
                                           event_mask = 0,
                                           wclass=gtk.gdk.INPUT_OUTPUT,
                                           title="Xpra-SystemTray",
                                           visual=visual,
                                           colormap=colormap)
        xtray = self.tray_window.xid
        set_tray_visual(self.tray_window, visual)
        set_tray_orientation(self.tray_window, TRAY_ORIENTATION_HORZ)
        log("setup tray: tray window %#x", xtray)
        display.request_selection_notification(SELECTION)
        try:
            with xsync:
                setsel = X11Window.XSetSelectionOwner(xtray, SELECTION)
                log("setup tray: set selection owner returned %s, owner=%#x", setsel, X11Window.XGetSelectionOwner(SELECTION))
                event_mask = StructureNotifyMask
                log("setup tray: sending client message")
                X11Window.sendClientMessage(root.xid, root.xid, False, event_mask, "MANAGER",
                                  CurrentTime, SELECTION, xtray)
                owner = X11Window.XGetSelectionOwner(SELECTION)
                assert owner==xtray, "we failed to get ownership of the tray selection"
                add_event_receiver(self.tray_window, self)
                log("setup tray: done")
        except Exception:
            log("setup_tray failure", exc_info=True)
            self.cleanup()
            raise

    def do_xpra_client_message_event(self, event):
        if event.message_type=="_NET_SYSTEM_TRAY_OPCODE" and event.window==self.tray_window and event.format==32:
            opcode = event.data[1]
            SYSTEM_TRAY_REQUEST_DOCK = 0
            SYSTEM_TRAY_BEGIN_MESSAGE = 1
            SYSTEM_TRAY_CANCEL_MESSAGE = 2
            if opcode==SYSTEM_TRAY_REQUEST_DOCK:
                xid = event.data[2]
                log("tray docking request from %#x", xid)
                with xsync:
                    self.dock_tray(xid)
            elif opcode==SYSTEM_TRAY_BEGIN_MESSAGE:
                timeout = event.data[2]
                mlen = event.data[3]
                mid = event.data[4]
                log.info("tray begin message timeout=%s, mlen=%s, mid=%s - not handled yet!", timeout, mlen, mid)
            elif opcode==SYSTEM_TRAY_CANCEL_MESSAGE:
                mid = event.data[2]
                log.info("tray cancel message for mid=%s - not handled yet!", mid)
        elif event.message_type=="_NET_SYSTEM_TRAY_MESSAGE_DATA":
            assert event.format==8
            log.info("tray message data - not handled yet!")
        elif event.message_type in IGNORED_MESSAGE_TYPES:
            log("do_xpra_client_message_event(%s) in ignored message type list", event)
        else:
            log.info("do_xpra_client_message_event(%s)", event)

    def dock_tray(self, xid):
        root = gtk.gdk.get_default_root_window()
        window = gtk.gdk.window_foreign_new(xid)
        if window is None:
            log.warn("could not find gdk window for tray window %#x", xid)
            return
        w, h = window.get_geometry()[2:4]
        if w==0 and h==0:
            log("dock_tray: invalid tray geometry, ignoring this request")
            return
        event_mask = gtk.gdk.STRUCTURE_MASK | gtk.gdk.EXPOSURE_MASK | gtk.gdk.PROPERTY_CHANGE_MASK
        window.set_events(event_mask=event_mask)
        add_event_receiver(window, self)
        w = max(1, min(64, w))
        h = max(1, min(64, h))
        title = prop_get(window, "_NET_WM_NAME", "utf8", ignore_errors=True)
        if title is None:
            title = prop_get(window, "WM_NAME", "latin1", ignore_errors=True)
        if title is None:
            title = ""
        log("dock_tray(%#x) gdk window=%#x, geometry=%s, title=%s, visual.depth=%s", xid, window.xid, window.get_geometry(), title, window.get_visual().depth)
        event_mask = gtk.gdk.STRUCTURE_MASK | gtk.gdk.EXPOSURE_MASK | gtk.gdk.PROPERTY_CHANGE_MASK
        tray_window = gtk.gdk.Window(root, width=w, height=h,
                                           window_type=gtk.gdk.WINDOW_TOPLEVEL,
                                           event_mask = event_mask,
                                           wclass=gtk.gdk.INPUT_OUTPUT,
                                           title=title,
                                           x=-200, y=-200,
                                           override_redirect=True,
                                           visual=window.get_visual(),
                                           colormap=window.get_colormap())
        log("dock_tray(%#x) setting tray properties", xid)
        set_tray_window(tray_window, window)
        tray_window.show()
        self.tray_windows[window] = tray_window
        self.window_trays[tray_window] = window
        log("dock_tray(%#x) resizing and reparenting", xid)
        window.resize(w, h)
        xwin = window.xid
        xtray = tray_window.xid
        X11Window.Withdraw(xwin)
        X11Window.Reparent(xwin, xtray, 0, 0)
        X11Window.MapRaised(xwin)
        log("dock_tray(%#x) new tray container window %#x", xid, xtray)
        tray_window.invalidate_rect(gtk.gdk.Rectangle(width=w, height=h), True)
        X11Window.send_xembed_message(xwin, XEMBED_EMBEDDED_NOTIFY, 0, xtray, XEMBED_VERSION)

    def move_resize(self, window, x, y, w, h):
        #see SystemTrayWindowModel.move_resize:
        window.move_resize(x, y, w, h)
        embedded_window = self.window_trays[window.client_window]
        embedded_window.resize(w, h)
        log("system tray moved to %sx%s and resized to %sx%s", x, y, w, h)

    def do_xpra_unmap_event(self, event):
        tray_window = self.tray_windows.get(event.window)
        log("SystemTray.do_xpra_unmap_event(%s) container window=%s", event, tray_window)
        if tray_window:
            tray_window.destroy()
            del self.tray_windows[event.window]
            del self.window_trays[tray_window]

gobject.type_register(SystemTray)
