# This file is part of Xpra.
# Copyright (C) 2012-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from enum import IntEnum
from typing import Dict, Optional
from gi.repository import GObject, Gdk, GdkX11  # @UnresolvedImport

from xpra.util import envint
from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.gtk_common.error import xsync, xlog
from xpra.x11.gtk_x11 import GDKX11Window
from xpra.x11.gtk_x11.prop import prop_set, prop_get, raw_prop_set
from xpra.gtk_common.gtk_util import get_default_root_window
from xpra.x11.bindings.window import constants, X11WindowBindings #@UnresolvedImport
from xpra.x11.gtk3.gdk_bindings import add_event_receiver, remove_event_receiver, get_xvisual
from xpra.log import Logger

X11Window = X11WindowBindings()

log = Logger("x11", "tray")


XNone = constants["XNone"]
StructureNotifyMask = constants["StructureNotifyMask"]


XEMBED_VERSION = 0

# XEmbed
class XEMBED(IntEnum):
    EMBEDDED_NOTIFY          = 0
    WINDOW_ACTIVATE          = 1
    WINDOW_DEACTIVATE        = 2
    REQUEST_FOCUS            = 3
    FOCUS_IN                 = 4
    FOCUS_OUT                = 5
    FOCUS_NEXT               = 6
    FOCUS_PREV               = 7
    # 8-9 were used for XEMBED_GRAB_KEY/XEMBED_UNGRAB_KEY */
    MODALITY_ON              = 10
    MODALITY_OFF             = 11
    REGISTER_ACCELERATOR     = 12
    UNREGISTER_ACCELERATOR   = 13
    ACTIVATE_ACCELERATOR     = 14
# A detail code is required for XEMBED_FOCUS_IN. The following values are valid:
# Details for  XEMBED_FOCUS_IN:
class XEMBED_FOCUS(IntEnum):
    CURRENT    = 0
    FIRST      = 1
    LAST       = 2

SELECTION = "_NET_SYSTEM_TRAY_S0"
SYSTRAY_VISUAL = "_NET_SYSTEM_TRAY_VISUAL"
SYSTRAY_ORIENTATION = "_NET_SYSTEM_TRAY_ORIENTATION"

class TRAY_ORIENTATION(IntEnum):
    HORZ   = 0
    VERT   = 1

XPRA_TRAY_WINDOW_PROPERTY = "_xpra_tray_window_"

SYSTEM_TRAY_REQUEST_DOCK = 0
SYSTEM_TRAY_BEGIN_MESSAGE = 1
SYSTEM_TRAY_CANCEL_MESSAGE = 2

#TRANSPARENCY = False
TRANSPARENCY = True

#Java can send this message to the tray (no idea why):
IGNORED_MESSAGE_TYPES = ("_GTK_LOAD_ICONTHEMES", )


MAX_TRAY_SIZE = envint("XPRA_MAX_TRAY_SIZE", 64)


def get_tray_window(tray_window) -> int:
    return getattr(tray_window, XPRA_TRAY_WINDOW_PROPERTY, 0)

def set_tray_window(tray_window, xid:int):
    setattr(tray_window, XPRA_TRAY_WINDOW_PROPERTY, xid)

def set_tray_visual(xid:int, gdk_visual):
    xvisual = get_xvisual(gdk_visual)
    value = struct.pack(b"@L", xvisual)
    raw_prop_set(xid, SYSTRAY_VISUAL, "VISUALID", 32, value)

def set_tray_orientation(xid:int, orientation:int):
    prop_set(xid, SYSTRAY_ORIENTATION, "u32", orientation)


class SystemTray(GObject.GObject):
    """ This is an X11 system tray area,
        owning the "_NET_SYSTEM_TRAY_S0" selection,
        X11 client applications can request to embed their tray icon in it,
        the xpra server can request to "move_resize" to where the xpra client has it mapped.
    """
    __slots__ = ("xid", "tray_window", "window_trays", "tray_windows")
    __gsignals__ = {
        "xpra-unmap-event": one_arg_signal,
        "xpra-client-message-event": one_arg_signal,
        }

    def __init__(self):
        super().__init__()
        #the window where we embed all the tray icons:
        self.tray_window : Optional[GdkX11.X11Window] = None
        self.xid : int = 0
        #map xid to the gdk window:
        self.window_trays : Dict[int,Gdk.Window] = {}
        #map gdk windows to their corral window:
        self.tray_windows : Dict[GdkX11.X11Window,GdkX11.X11Window] = {}
        self.setup_tray_window()

    def cleanup(self) -> None:
        log("SystemTray.cleanup()")
        with xlog:
            owner = X11Window.XGetSelectionOwner(SELECTION)
            if owner==self.xid:
                X11Window.XSetSelectionOwner(0, SELECTION)
                owner = X11Window.XGetSelectionOwner(SELECTION)
                log(f"SystemTray.cleanup() reset {SELECTION} selection owner to {owner:x}")
            else:
                log.warn("Warning: we were no longer the tray selection owner")
        remove_event_receiver(self.xid, self)
        tray_windows = self.tray_windows
        self.tray_windows = {}
        for window, tray_window in tray_windows.items():
            with xlog:
                self.undock(window)
            tray_window.destroy()
        tw = self.tray_window
        if tw:
            self.tray_window = None
            tw.destroy()
        log("SystemTray.cleanup() done")

    def setup_tray_window(self) -> None:
        display = Gdk.Display.get_default()
        root = get_default_root_window()
        if root is None:
            raise RuntimeError("no root window!")
        screen = root.get_screen()
        owner = X11Window.XGetSelectionOwner(SELECTION)
        log(f"setup tray: current selection owner={owner:x}")
        if owner!=XNone:
            raise RuntimeError(f"{SELECTION} already owned by {owner}")
        visual = screen.get_system_visual()
        if TRANSPARENCY:
            visual = screen.get_rgba_visual()
            if visual is None:
                log.warn("setup tray: using rgb visual fallback")
                visual = screen.get_rgb_visual()
        assert visual is not None, "failed to obtain visual"
        self.tray_window = GDKX11Window(root, width=1, height=1,
                                        title="Xpra-SystemTray",
                                        visual=visual)
        self.xid = self.tray_window.get_xid()
        set_tray_visual(self.xid, visual)
        set_tray_orientation(self.xid, TRAY_ORIENTATION.HORZ)
        log("setup tray: tray window %#x", self.xid)
        display.request_selection_notification(Gdk.Atom.intern(SELECTION, False))
        try:
            with xsync:
                setsel = X11Window.XSetSelectionOwner(self.xid, SELECTION)
                owner = X11Window.XGetSelectionOwner(SELECTION)
                log(f"setup tray: set selection owner returned {setsel}, owner={owner:x}")
                event_mask = StructureNotifyMask
                log("setup tray: sending client message")
                time = X11Window.get_server_time(self.xid)
                xid = X11Window.get_root_xid()
                X11Window.sendClientMessage(xid, xid, False, event_mask, "MANAGER", time, SELECTION, self.xid)
                owner = X11Window.XGetSelectionOwner(SELECTION)
                if owner!=self.xid:
                    raise RuntimeError("we failed to get ownership of the tray selection")
                add_event_receiver(self.xid, self)
                log("setup tray: done")
        except Exception:
            log("setup_tray failure", exc_info=True)
            self.cleanup()
            raise

    def get_pywindow(self, xid:int) -> GdkX11.X11Window:
        assert self.tray_window
        display = self.tray_window.get_display()
        return GdkX11.X11Window.foreign_new_for_display(display, xid)

    def do_xpra_client_message_event(self, event) -> None:
        if event.message_type=="_NET_SYSTEM_TRAY_OPCODE" and event.window==self.xid and event.format==32:
            opcode = event.data[1]
            if opcode==SYSTEM_TRAY_REQUEST_DOCK:
                xid = event.data[2]
                log("tray docking request from %#x", xid)
                window = self.get_pywindow(xid)
                log("tray docking window %s", window)
                if window:
                    from gi.repository import GLib  # pylint: disable=import-outside-toplevel @UnresolvedImport
                    GLib.idle_add(self.dock_tray, xid)
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

    def undock(self, window) -> None:
        log("undock(%s)", window)
        rxid = X11Window.get_root_xid()
        xid = window.get_xid()
        X11Window.Unmap(xid)
        X11Window.Reparent(xid, rxid, 0, 0)

    def dock_tray(self, xid:int) -> None:
        log(f"dock_tray({xid:x})")
        try:
            with xsync:
                X11Window.getGeometry(xid)
                self.do_dock_tray(xid)
        except Exception as e:
            log(f"dock_tray({xid:x})", exc_info=True)
            log.warn(f"Warning: failed to dock tray {xid:x}:")
            log.warn(f" {e}")
            log.warn(" the application may retry later")

    def do_dock_tray(self, xid:int) -> None:
        root = get_default_root_window()
        window = self.get_pywindow(xid)
        if window is None:
            log.warn(f"Warning: could not find gdk window for tray window {xid:x}")
            return
        w, h = window.get_geometry()[2:4]
        log(f"tray geometry={w}x{h}")
        if w==0 and h==0:
            log(f"invalid tray geometry {w}x{h}, ignoring this request")
            return
        em = Gdk.EventMask
        event_mask = em.STRUCTURE_MASK | em.EXPOSURE_MASK | em.PROPERTY_CHANGE_MASK
        window.set_events(event_mask=event_mask)
        add_event_receiver(xid, self)
        w = max(1, min(MAX_TRAY_SIZE, w))
        h = max(1, min(MAX_TRAY_SIZE, h))
        title = prop_get(xid, "_NET_WM_NAME", "utf8", ignore_errors=True)
        if title is None:
            title = prop_get(xid, "WM_NAME", "latin1", ignore_errors=True)
        if title is None:
            title = ""
        log(f"adjusted geometry={window.get_geometry()}, title={title!r}")
        visual = window.get_visual()
        tray_window = GDKX11Window(root, width=w, height=h,
                                   event_mask = event_mask,
                                   title=title,
                                   x=-200, y=-200,
                                   override_redirect=True,
                                   visual=visual)
        xtray = tray_window.get_xid()
        log(f"tray: recording corral window {xtray:x}, setting tray properties")
        set_tray_window(tray_window, xid)
        self.tray_windows[window] = tray_window
        self.window_trays[xid] = window
        log("showing tray window, resizing and reparenting")
        tray_window.show()
        window.resize(w, h)
        X11Window.Withdraw(xid)
        X11Window.Reparent(xid, xtray, 0, 0)
        X11Window.MapRaised(xid)
        log(f"redrawing new tray container window {xtray:x}")
        rect = Gdk.Rectangle()
        rect.width = w
        rect.height = h
        tray_window.invalidate_rect(rect, True)
        log(f"dock_tray({xid:x}) done, sending xembed notification")
        X11Window.send_xembed_message(xid, XEMBED.EMBEDDED_NOTIFY, 0, xtray, XEMBED_VERSION)

    def do_xpra_unmap_event(self, event) -> None:
        gdk_window = self.window_trays.pop(event.window, None)
        tray_window = self.tray_windows.pop(gdk_window, None)
        log(f"SystemTray.do_xpra_unmap_event({event}) gdk window={gdk_window}, container window={tray_window}")
        if tray_window:
            tray_window.destroy()

GObject.type_register(SystemTray)
