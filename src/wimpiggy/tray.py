# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject

from wimpiggy.prop import prop_set, prop_get
from wimpiggy.util import one_arg_signal
from wimpiggy.error import trap

from wimpiggy.lowlevel import (
               const,                                       #@UnresolvedImport
               add_event_receiver,                          #@UnresolvedImport
               remove_event_receiver,                       #@UnresolvedImport
               sendClientMessage,                           #@UnresolvedImport
               get_xwindow,                                 #@UnresolvedImport
               mySetSelectionOwner,                         #@UnresolvedImport
               myGetSelectionOwner,                         #@UnresolvedImport
               send_xembed_message,                         #@UnresolvedImport
               map_raised,                                  #@UnresolvedImport
               withdraw,                                    #@UnresolvedImport
               reparent,                                    #@UnresolvedImport
               )

from wimpiggy.log import Logger
log = Logger()

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

XPRA_TRAY_WINDOW_PROPERTY = "_XPRA_TRAY_WINDOW"

#TRANSPARENCY = False
TRANSPARENCY = True


def get_tray_window(tray_window):
    return prop_get(tray_window, XPRA_TRAY_WINDOW_PROPERTY, "u32", True)

def set_tray_window(tray_window, window):
    prop_set(tray_window, XPRA_TRAY_WINDOW_PROPERTY, "u32", get_xwindow(window))

def set_tray_visual(tray_window, gdk_visual):
    prop_set(tray_window, TRAY_VISUAL, "visual", gdk_visual)

def set_tray_orientation(tray_window, orientation):
    prop_set(tray_window, TRAY_VISUAL, "u32", orientation)


class SystemTray(gobject.GObject):
    __gsignals__ = {
        "wimpiggy-unmap-event": one_arg_signal,
        "wimpiggy-client-message-event": one_arg_signal,
        }

    def __init__(self):
        gobject.GObject.__init__(self)
        self.tray_window = None
        self.window_trays = {}
        self.tray_windows = {}
        self.setup_tray_window()

    def cleanup(self):
        log("Tray.cleanup()")
        root = gtk.gdk.get_default_root_window()
        owner = myGetSelectionOwner(root, SELECTION)
        if owner==get_xwindow(self.tray_window):
            mySetSelectionOwner(root, const["XNone"], SELECTION)
        else:
            log.warn("Tray.cleanup() we were no longer the selection owner")
        remove_event_receiver(self.tray_window, self)
        def undock(window):
            log("undocking %s", window)
            withdraw(window)
            reparent(window, root, 0, 0)
            map_raised(window)
        for window, tray_window in self.tray_windows.items():
            trap.swallow_synced(undock, window)
            tray_window.destroy()
        self.tray_window.destroy()
        self.tray_window = None
        log("Tray.cleanup() done")

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
        owner = myGetSelectionOwner(root, SELECTION)
        log("setup tray: current selection owner=%s", owner)
        if owner!=const["XNone"]:
            raise Exception("%s already owned by %s" % (SELECTION, owner))
        self.tray_window = gtk.gdk.Window(root, width=1, height=1,
                                           window_type=gtk.gdk.WINDOW_TOPLEVEL,
                                           event_mask = 0,
                                           wclass=gtk.gdk.INPUT_OUTPUT,
                                           title="Xpra-SystemTray",
                                           visual=visual,
                                           colormap=colormap)
        set_tray_visual(self.tray_window, visual)
        set_tray_orientation(self.tray_window, TRAY_ORIENTATION_HORZ)
        log("setup tray: tray window %s", get_xwindow(self.tray_window))
        display.request_selection_notification(SELECTION)
        setsel = mySetSelectionOwner(root, self.tray_window, SELECTION)
        log("setup tray: set selection owner returned %s", setsel)
        event_mask = const["StructureNotifyMask"]
        sendClientMessage(root, root, False, event_mask, "MANAGER",
                          const["CurrentTime"], SELECTION,
                          get_xwindow(self.tray_window), 0, 0)
        owner = myGetSelectionOwner(root, SELECTION)
        #FIXME: cleanup if we fail!
        assert owner==get_xwindow(self.tray_window), "we failed to get ownership of the tray selection"
        add_event_receiver(self.tray_window, self)
        log("setup tray: done")

    def do_wimpiggy_client_message_event(self, event):
        if event.message_type=="_NET_SYSTEM_TRAY_OPCODE" and event.window==self.tray_window and event.format==32:
            opcode = event.data[1]
            SYSTEM_TRAY_REQUEST_DOCK = 0
            SYSTEM_TRAY_BEGIN_MESSAGE = 1
            SYSTEM_TRAY_CANCEL_MESSAGE = 2
            if opcode==SYSTEM_TRAY_REQUEST_DOCK:
                xid = event.data[2]
                trap.call_synced(self.dock_tray, xid)
            elif opcode==SYSTEM_TRAY_BEGIN_MESSAGE:
                timeout = event.data[2]
                mlen = event.data[3]
                mid = event.data[4]
                log.info("tray begin message timeout=%s, mlen=%s, mid=%s - not handled yet!", timeout, mlen, mid)
            elif opcode==SYSTEM_TRAY_CANCEL_MESSAGE:
                mid = event.data[2]
                log.info("tray cancel message for mid=%s - not handled yet!", mid)
        elif opcode=="_NET_SYSTEM_TRAY_MESSAGE_DATA":
            assert event.format==8
            log.info("tray message data - not handled yet!")
        else:
            log.info("do_wimpiggy_client_message_event(%s)", event)

    def dock_tray(self, xid):
        root = gtk.gdk.get_default_root_window()
        window = gtk.gdk.window_foreign_new(xid)
        w, h = window.get_geometry()[2:4]
        event_mask = gtk.gdk.STRUCTURE_MASK | gtk.gdk.EXPOSURE_MASK | gtk.gdk.PROPERTY_CHANGE_MASK
        window.set_events(event_mask=event_mask)
        add_event_receiver(window, self)
        w = max(1, min(200, w))
        h = max(1, min(200, h))
        log("dock_tray(%s) window=%s, geometry=%s, visual.depth=%s", xid, window, window.get_geometry(), window.get_visual().depth)
        event_mask = gtk.gdk.STRUCTURE_MASK | gtk.gdk.EXPOSURE_MASK | gtk.gdk.PROPERTY_CHANGE_MASK
        tray_window = gtk.gdk.Window(root, width=w, height=h,
                                           window_type=gtk.gdk.WINDOW_TOPLEVEL,
                                           event_mask = event_mask,
                                           wclass=gtk.gdk.INPUT_OUTPUT,
                                           title="TrayWindow",
                                           override_redirect=True,
                                           visual=window.get_visual(),
                                           colormap=window.get_colormap())
        log("dock_tray(%s) setting tray properties", xid)
        set_tray_window(tray_window, window)
        tray_window.show()
        self.tray_windows[window] = tray_window
        self.window_trays[tray_window] = window
        log("dock_tray(%s) resizing and reparenting", xid)
        window.resize(w, h)
        withdraw(window)
        reparent(window, tray_window, 0, 0)
        map_raised(window)
        log("dock_tray(%s) new tray container window %s", xid, get_xwindow(tray_window))
        tray_window.invalidate_rect(gtk.gdk.Rectangle(width=w, height=h), True)
        embedder = get_xwindow(tray_window)
        send_xembed_message(window, XEMBED_EMBEDDED_NOTIFY, 0, embedder, XEMBED_VERSION)

    def move_resize(self, window, x, y, w, h):
        #see SystemTrayWindowModel.move_resize:
        window.move_resize(x, y, w, h)
        embedded_window = self.window_trays[window.client_window]
        embedded_window.resize(w, h)
        log("system tray moved to %sx%s and resized to %sx%s", x, y, w, h)

    def do_wimpiggy_unmap_event(self, event):
        tray_window = self.tray_windows.get(event.window)
        log("SystemTray.do_wimpiggy_unmap_event(%s) container window=%s", event, tray_window)
        if tray_window:
            tray_window.destroy()
            del self.tray_windows[event.window]
            del self.window_trays[tray_window]

gobject.type_register(SystemTray)
