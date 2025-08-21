# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from typing import Final
from enum import IntEnum

from xpra.util.env import envint
from xpra.os_util import gi_import
from xpra.util.gobject import one_arg_signal
from xpra.x11.error import xsync, xlog
from xpra.x11.common import X11Event
from xpra.x11.prop import prop_set, prop_get, raw_prop_set
from xpra.x11.bindings.core import constants, get_root_xid
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.x11.selection.common import xfixes_selection_input
from xpra.log import Logger

GObject = gi_import("GObject")
glib = gi_import("GLib")

X11Window = X11WindowBindings()

log = Logger("x11", "tray")

XNone: Final[int] = constants["XNone"]
StructureNotifyMask: Final[int] = constants["StructureNotifyMask"]
ExposureMask: Final[int] = constants["ExposureMask"]
PropertyChangeMask: Final[int] = constants["PropertyChangeMask"]

XEMBED_VERSION: Final[int] = 0

rxid: Final[int] = get_root_xid()


# XEmbed
class XEMBED(IntEnum):
    EMBEDDED_NOTIFY = 0
    WINDOW_ACTIVATE = 1
    WINDOW_DEACTIVATE = 2
    REQUEST_FOCUS = 3
    FOCUS_IN = 4
    FOCUS_OUT = 5
    FOCUS_NEXT = 6
    FOCUS_PREV = 7
    # 8-9 were used for XEMBED_GRAB_KEY/XEMBED_UNGRAB_KEY */
    MODALITY_ON = 10
    MODALITY_OFF = 11
    REGISTER_ACCELERATOR = 12
    UNREGISTER_ACCELERATOR = 13
    ACTIVATE_ACCELERATOR = 14


# A detail code is required for XEMBED_FOCUS_IN. The following values are valid:
# Details for  XEMBED_FOCUS_IN:


class XEMBED_FOCUS(IntEnum):
    CURRENT = 0
    FIRST = 1
    LAST = 2


SELECTION: Final[str] = "_NET_SYSTEM_TRAY_S0"
SYSTRAY_VISUAL: Final[str] = "_NET_SYSTEM_TRAY_VISUAL"
SYSTRAY_ORIENTATION: Final[str] = "_NET_SYSTEM_TRAY_ORIENTATION"


class TRAY_ORIENTATION(IntEnum):
    HORZ = 0
    VERT = 1


XPRA_TRAY_WINDOW_PROPERTY = "_xpra_tray_window_"

SYSTEM_TRAY_REQUEST_DOCK = 0
SYSTEM_TRAY_BEGIN_MESSAGE = 1
SYSTEM_TRAY_CANCEL_MESSAGE = 2

TRANSPARENCY = True

# Java can send this message to the tray (no idea why):
IGNORED_MESSAGE_TYPES = ("_GTK_LOAD_ICONTHEMES",)

MAX_TRAY_SIZE = envint("XPRA_MAX_TRAY_SIZE", 64)


def get_tray_window(xid: int) -> int:
    return prop_get(xid, XPRA_TRAY_WINDOW_PROPERTY, "u32")


def set_tray_visual(xid: int, visualid: int) -> None:
    value = struct.pack(b"@L", visualid)
    raw_prop_set(xid, SYSTRAY_VISUAL, "VISUALID", 32, value)


def set_tray_orientation(xid: int, orientation: TRAY_ORIENTATION) -> None:
    prop_set(xid, SYSTRAY_ORIENTATION, "u32", int(orientation))


class SystemTray(GObject.GObject):
    """ This is an X11 system tray area,
        owning the "_NET_SYSTEM_TRAY_S0" selection,
        X11 client applications can request to embed their tray icon in it,
        the xpra server can request to "move_resize" to where the xpra client has it mapped.
    """
    __slots__ = ("xid", "tray_window", "window_trays", "tray_windows")
    __gsignals__ = {
        "x11-unmap-event": one_arg_signal,
        "x11-client-message-event": one_arg_signal,
    }

    def __init__(self):
        super().__init__()
        # the container window where we embed all the tray icons:
        self.xid: int = 0
        # map client tray windows to their corral window:
        self.tray_windows: dict[int, int] = {}
        self.setup_tray_window()

    def cleanup(self) -> None:
        log("SystemTray.cleanup()")
        with xlog:
            owner = X11Window.XGetSelectionOwner(SELECTION)
            if owner == self.xid:
                X11Window.XSetSelectionOwner(0, SELECTION)
                owner = X11Window.XGetSelectionOwner(SELECTION)
                log(f"SystemTray.cleanup() reset {SELECTION} selection owner to {owner:x}")
            else:
                log.warn("Warning: we were no longer the tray selection owner")
        remove_event_receiver(self.xid, self)
        tray_windows = self.tray_windows
        self.tray_windows = {}
        with xlog:
            for xid, xtray in tray_windows.items():
                self.undock(xid)
                X11Window.Unmap(xtray)
            xid = self.xid
            if xid:
                self.xid = 0
                X11Window.Unmap(xid)
        log("SystemTray.cleanup() done")

    def setup_tray_window(self) -> None:
        try:
            with xsync:
                owner = X11Window.XGetSelectionOwner(SELECTION)
                log(f"setup tray: current selection owner={owner:x}")
                if owner != XNone:
                    from xpra.x11.window_info import window_info
                    log.warn(f"Warning: the system tray selection {SELECTION!r} is already owned by:")
                    log.warn(" %s", window_info(owner))
                    raise RuntimeError(f"{SELECTION} already owned by {owner:x}")
                root_depth = X11Window.get_depth(rxid)
                visualid = 0
                if TRANSPARENCY:
                    depth = root_depth if root_depth != 24 else 32
                    visualid = X11Window.get_rgba_visualid(depth)
                event_mask = PropertyChangeMask
                win_vid = X11Window.get_default_visualid()
                self.xid = X11Window.CreateWindow(rxid, depth=root_depth, event_mask=event_mask, visualid=win_vid)
                log(f"tray dock window: visualid=0x{visualid:x} geometry=%s", X11Window.getGeometry(self.xid))
                prop_set(self.xid, "WM_TITLE", "latin1", "Xpra-SystemTray")
                set_tray_visual(self.xid, visualid)
                set_tray_orientation(self.xid, TRAY_ORIENTATION.HORZ)
                xfixes_selection_input(rxid, SELECTION)
                setsel = X11Window.XSetSelectionOwner(self.xid, SELECTION)
                owner = X11Window.XGetSelectionOwner(SELECTION)
                log(f"setup tray: set selection owner returned {setsel}, owner={owner:x}")
                time = X11Window.get_server_time(self.xid)
                log(f"setup tray: sending client message with {time=}")
                event_mask = StructureNotifyMask
                X11Window.sendClientMessage(rxid, rxid, False, event_mask, "MANAGER", time, SELECTION, self.xid)
                owner = X11Window.XGetSelectionOwner(SELECTION)
                if owner != self.xid:
                    raise RuntimeError("we failed to get ownership of the tray selection")
                add_event_receiver(self.xid, self)
                log("setup tray: done")
        except Exception:
            log("setup_tray failure", exc_info=True)
            self.cleanup()
            raise

    def do_x11_client_message_event(self, event: X11Event) -> None:
        if event.message_type == "_NET_SYSTEM_TRAY_OPCODE" and event.window == self.xid and event.format == 32:
            opcode = event.data[1]
            if opcode == SYSTEM_TRAY_REQUEST_DOCK:
                xid = event.data[2]
                log("tray docking request from %#x", xid)
                glib.idle_add(self.dock_tray, xid)
            elif opcode == SYSTEM_TRAY_BEGIN_MESSAGE:
                timeout = event.data[2]
                mlen = event.data[3]
                mid = event.data[4]
                log.info("tray begin message timeout=%s, mlen=%s, mid=%s - not handled yet!", timeout, mlen, mid)
            elif opcode == SYSTEM_TRAY_CANCEL_MESSAGE:
                mid = event.data[2]
                log.info("tray cancel message for mid=%s - not handled yet!", mid)
        elif event.message_type == "_NET_SYSTEM_TRAY_MESSAGE_DATA":
            assert event.format == 8
            log.info("tray message data - not handled yet!")
        elif event.message_type in IGNORED_MESSAGE_TYPES:
            log("do_x11_client_message_event(%s) in ignored message type list", event)
        else:
            log.info("do_x11_client_message_event(%s)", event)

    def undock(self, xid) -> None:
        log("undock(%#x)", xid)
        X11Window.Unmap(xid)
        X11Window.Reparent(xid, rxid, 0, 0)

    def dock_tray(self, xid: int) -> None:
        log(f"dock_tray({xid:x})")
        try:
            with xsync:
                if X11Window.getGeometry(xid):
                    self.do_dock_tray(xid)
                else:
                    log.warn(f"Warning: unable to dock tray {xid:x}: window does not exist")
        except Exception as e:
            log(f"dock_tray({xid:x})", exc_info=True)
            log.warn(f"Warning: failed to dock tray {xid:x}:")
            log.warn(f" {e}")
            log.warn(" the application may retry later")

    def do_dock_tray(self, xid: int) -> None:
        geom = X11Window.getGeometry(xid)
        if not geom:
            log(f"tray {xid:x} vanished")
            return
        w, h = geom[2:4]
        log(f"tray geometry={w}x{h}")
        if w == 0 and h == 0:
            log(f"invalid tray geometry {w}x{h}, ignoring this request")
            return
        event_mask = StructureNotifyMask | ExposureMask | PropertyChangeMask
        X11Window.setEventMask(xid, event_mask)
        add_event_receiver(xid, self)
        w = max(1, min(MAX_TRAY_SIZE, w))
        h = max(1, min(MAX_TRAY_SIZE, h))
        title = prop_get(xid, "_NET_WM_NAME", "utf8", ignore_errors=True)
        if not title:
            title = prop_get(xid, "WM_NAME", "latin1", ignore_errors=True)
        if not title:
            title = ""
        log(f"geometry={geom}, title={title!r}")
        xtray = X11Window.CreateWindow(rxid, -200, -200, w, h, OR=True, event_mask=event_mask)
        prop_set(xtray, "WM_TITLE", "latin1", title)
        log(f"tray: recording corral window {xtray:x}, setting tray properties")
        prop_set(xtray, XPRA_TRAY_WINDOW_PROPERTY, "u32", xid)
        self.tray_windows[xid] = xtray
        log("showing tray window, resizing and reparenting")
        X11Window.MapWindow(xtray)
        X11Window.ResizeWindow(xtray, w, h)
        X11Window.Withdraw(xid)
        X11Window.Reparent(xid, xtray, 0, 0)
        X11Window.MapRaised(xid)
        log(f"redrawing new tray container window {xtray:x}")
        X11Window.send_expose(xtray, 0, 0, w, h)
        log(f"dock_tray({xid:x}) done, sending xembed notification")
        X11Window.send_xembed_message(xid, XEMBED.EMBEDDED_NOTIFY, 0, xtray, XEMBED_VERSION)

    def do_x11_unmap_event(self, event: X11Event) -> None:
        xid = event.window
        xtray = self.tray_windows.pop(xid, None)
        log(f"SystemTray.do_x11_unmap_event({event}) window={xid}, container window={xtray}")
        if xtray:
            with xlog:
                X11Window.Unmap(xtray)


GObject.type_register(SystemTray)
