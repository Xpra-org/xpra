# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any, Final

from xpra.util.env import envbool
from xpra.os_util import gi_import
from xpra.common import MAX_WINDOW_SIZE
from xpra.util.gobject import no_arg_signal, one_arg_signal
from xpra.x11.error import xsync, xswallow, xlog
from xpra.x11.common import Unmanageable, FRAME_EXTENTS, X11Event
from xpra.x11.prop import prop_set, prop_get, prop_del, raw_prop_set, prop_encode
from xpra.x11.selection.manager import ManagerSelection
from xpra.x11.dispatch import add_event_receiver, add_fallback_receiver, remove_fallback_receiver
from xpra.x11.window_info import window_name, window_info
from xpra.x11.xroot_props import (
    set_desktop_list, set_current_desktop, set_desktop_viewport, set_desktop_geometry, get_desktop_geometry,
    set_supported, set_workarea,
    root_set, root_get,
)
from xpra.x11.bindings.core import constants, get_root_xid, X11CoreBindings
from xpra.x11.bindings.window import X11WindowBindings
from xpra.log import Logger

GObject = gi_import("GObject")

log = Logger("x11", "window")

X11Window = X11WindowBindings()

focuslog = Logger("x11", "window", "focus")
screenlog = Logger("x11", "window", "screen")
framelog = Logger("x11", "window", "frame")

CWX: Final[int] = constants["CWX"]
CWY: Final[int] = constants["CWY"]
CWWidth: Final[int] = constants["CWWidth"]
CWHeight: Final[int] = constants["CWHeight"]
InputOnly: Final[int] = constants["InputOnly"]

NotifyPointerRoot: Final[int] = constants["NotifyPointerRoot"]
NotifyDetailNone: Final[int] = constants["NotifyDetailNone"]

LOG_MANAGE_FAILURES = envbool("XPRA_LOG_MANAGE_FAILURES", False)

DEFAULT_SIZE_CONSTRAINTS = (0, 0, MAX_WINDOW_SIZE, MAX_WINDOW_SIZE)

WINDOW_TYPE_ATOMS = tuple(f"_NET_WM_WINDOW_TYPE{wtype}" for wtype in (
    "",
    "_NORMAL",
    "_DESKTOP",
    "_DOCK",
    "_TOOLBAR",
    "_MENU",
    "_UTILITY",
    "_SPLASH",
    "_DIALOG",
    "_DROPDOWN_MENU",
    "_POPUP_MENU",
    "_TOOLTIP",
    "_NOTIFICATION",
    "_COMBO",
    "_DND",
    "_NORMAL"
))


rxid = get_root_xid()


class Wm(GObject.GObject):
    __gsignals__ = {
        # Public use:
        # A new window has shown up:
        "new-window": one_arg_signal,
        "show-desktop": one_arg_signal,
        # You can emit this to cause the WM to quit, or the WM may
        # spontaneously raise it if another WM takes over the display.  By
        # default, unmanages all windows:
        "quit": no_arg_signal,

        # Mostly intended for internal use:
        "x11-child-map-request-event": one_arg_signal,
        "x11-child-configure-request-event": one_arg_signal,
        "x11-focus-in-event": one_arg_signal,
        "x11-focus-out-event": one_arg_signal,
        "x11-client-message-event": one_arg_signal,
        "x11-xkb-event": one_arg_signal,
    }

    def __init__(self, wm_name: str):
        super().__init__()

        self._wm_name = wm_name
        self._ewmh_window = 0
        self.size_constraints = DEFAULT_SIZE_CONSTRAINTS

        self._windows: dict[int, Any] = {}
        # EWMH says we have to know the order of our windows oldest to
        # youngest...
        self._windows_in_order = []
        self._wm_selection = None

    def init_atoms(self) -> None:
        with xsync:
            # some applications (like openoffice), do not work properly
            # if some x11 atoms aren't defined, so we define them in advance:
            X11CoreBindings().intern_atoms(WINDOW_TYPE_ATOMS)

    def setup(self, replace_other_wm: bool) -> None:
        # According to ICCCM 2.8/4.3, a window manager for screen N is a client which
        # acquires the selection WM_S<N>.  If another client already has this
        # selection, we can either abort or steal it.  Once we have it, if someone
        # else steals it, then we should exit.

        # Become the Official Window Manager of this year's display:
        self._wm_selection = ManagerSelection("WM_S0", "_NET_WM_CM_S0")
        self._wm_selection.connect("selection-lost", self._lost_wm_selection)
        self._wm_selection.connect("selection-acquired", self._got_wm_selection)
        # May throw AlreadyOwned:
        self._wm_selection.acquire(replace_other_wm)

    def _got_wm_selection(self, *_args):
        # Set up the necessary EWMH properties on the root window.
        self._ewmh_window = self._setup_ewmh_window()

        root_w, root_h = X11Window.getGeometry(rxid)[2:4]
        # Start with just one desktop:
        set_desktop_list(("Main",))
        set_current_desktop(0)
        set_supported()
        # Start with the full display as workarea:
        set_workarea(0, 0, root_w, root_h)
        set_desktop_geometry(root_w, root_h)
        set_desktop_viewport(0, 0)

        # Okay, ready to select for SubstructureRedirect and then load in all
        # the existing clients.
        add_event_receiver(rxid, self)
        add_fallback_receiver("x11-client-message-event", self)
        # when reparenting, the events may get sent
        # to a window that is already destroyed,
        # and we don't want to miss those events, so:
        add_fallback_receiver("x11-child-map-request-event", self)
        X11Window.substructureRedirect(rxid)

        children = X11Window.get_children(rxid)
        log(f"root window children: {children}")
        for xid in children:
            # ignore unmapped and `OR` windows:
            if X11Window.is_override_redirect(xid):
                log("skipping OR window %s", window_info(xid))
                continue
            if not X11Window.is_mapped(xid):
                log("skipping unmapped window %s", window_info(xid))
                continue
            log(f"Wm managing pre-existing child window {xid:x}")
            self._manage_client(xid)

        # Also watch for focus change events on the root window
        X11Window.selectFocusChange(rxid)
        X11Window.setRootIconSizes(64, 64)

        # FIXME:
        # Need viewport abstraction for _NET_CURRENT_DESKTOP...
        # Tray's need to provide info for _NET_ACTIVE_WINDOW and _NET_WORKAREA
        # (and notifications for both)

    def update_desktop_geometry(self, width: int, height: int) -> None:
        set_desktop_geometry(width, height)
        # update all the windows:
        for model in self._windows.values():
            model.update_desktop_geometry(width, height)

    def set_size_constraints(self, minw: int = 0, minh: int = 0, maxw: int = MAX_WINDOW_SIZE,
                             maxh: int = MAX_WINDOW_SIZE) -> None:
        log("set_size_constraints%s", (minw, minh, maxw, maxh))
        self.size_constraints = minw, minh, maxw, maxh
        # update all the windows:
        for model in self._windows.values():
            model.update_size_constraints(minw, minh, maxw, maxh)

    def set_default_frame_extents(self, v) -> None:
        framelog("set_default_frame_extents(%s)", v)
        if not v or len(v) != 4:
            v = (0, 0, 0, 0)
        root_set("DEFAULT_NET_FRAME_EXTENTS", ["u32"], v)
        # update the models that are using the global default value:
        for win in self._windows.values():
            if win.is_OR() or win.is_tray():
                continue
            cur = win.get_property("frame")
            if cur is None:
                win._handle_frame_changed()

    def get_windows(self):
        return tuple(self._windows.values())

    # This is in some sense the key entry point to the entire WM program.  We
    # have detected a new client window, and start managing it:
    def _manage_client(self, xid: int):
        if xid in self._windows:
            # already managed
            return
        from xpra.x11.models.window import WindowModel
        try:
            with xsync:
                log("_manage_client(%x)", xid)
                desktop_geometry = get_desktop_geometry()
                win = WindowModel(rxid, xid, desktop_geometry, self.size_constraints)
        except Exception as e:
            if LOG_MANAGE_FAILURES or not isinstance(e, Unmanageable):
                log_fn = log.warn
            else:
                log_fn = log.debug
            log_fn("Warning: failed to manage client window %#x:", xid)
            log_fn(" %s", e)
            log_fn("", exc_info=True)
            with xswallow:
                log_fn(" window name: %s", window_name(xid))
                log_fn(" window info: %s", window_info(xid))
        else:
            win.managed_connect("unmanaged", self._handle_client_unmanaged, xid)
            self._windows[xid] = win
            self._windows_in_order.append(xid)
            self._update_window_list()
            self.emit("new-window", win)

    def _handle_client_unmanaged(self, model, wm_exiting, xid: int) -> None:
        log(f"_handle_client_unmanaged({model}, {wm_exiting}, {xid:x})")
        if xid not in self._windows:
            log.error(f"Error: gdk window {xid} not found in {self._windows}")
            return
        del self._windows[xid]
        self._windows_in_order.remove(xid)
        self._update_window_list()

    def _update_window_list(self, *_args) -> None:
        # Ignore errors because not all the windows may still exist; if so,
        # then it's okay to leave the lists out of date for a moment, because
        # in a moment we'll get a signal telling us about the window that
        # doesn't exist anymore, will remove it from the list, and then call
        # _update_window_list again.
        dtype, dformat, window_xids = prop_encode(["u32"], tuple(self._windows_in_order))
        log("prop_encode(%s)=%s", self._windows_in_order, (dtype, dformat, window_xids))
        with xlog:
            for prop in ("_NET_CLIENT_LIST", "_NET_CLIENT_LIST_STACKING"):
                raw_prop_set(rxid, prop, "WINDOW", dformat, window_xids)

    def do_x11_client_message_event(self, event: X11Event) -> None:
        # FIXME
        # Need to listen for:
        #   _NET_ACTIVE_WINDOW
        #   _NET_CURRENT_DESKTOP
        #   _NET_WM_PING responses
        # and maybe:
        #   _NET_WM_STATE
        log("do_x11_client_message_event(%s)", event)
        if event.message_type == "_NET_SHOWING_DESKTOP":
            show = bool(event.data[0])
            self.emit("show-desktop", show)
        elif event.message_type == "_NET_REQUEST_FRAME_EXTENTS" and FRAME_EXTENTS:
            # if we're here, that means the window model does not exist
            # (or it would have processed the event)
            # so this must be an unmapped window
            NO_FRAME = (0, 0, 0, 0)
            frame = NO_FRAME
            with xswallow:
                xid = event.window
                if not X11Window.is_override_redirect(xid):
                    # use the global default:
                    frame = root_get("DEFAULT_NET_FRAME_EXTENTS", ["u32"])
                if not frame or len(frame) != 4:
                    frame = NO_FRAME
                framelog("_NET_REQUEST_FRAME_EXTENTS: setting _NET_FRAME_EXTENTS=%s on %#x", frame, xid)
                prop_set(event.window, "_NET_FRAME_EXTENTS", ["u32"], frame)

    def _lost_wm_selection(self, *_args) -> None:
        self.emit("quit")

    def do_quit(self) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        remove_fallback_receiver("x11-client-message-event", self)
        remove_fallback_receiver("x11-child-map-request-event", self)
        for win in tuple(self._windows.values()):
            win.unmanage(True)
        xid = self._ewmh_window
        if xid:
            self._ewmh_window = 0
            with xswallow:
                prop_del(xid, "_NET_SUPPORTING_WM_CHECK")
                prop_del(xid, "_NET_WM_NAME")

    def do_x11_child_map_request_event(self, event: X11Event) -> None:
        log("Found a potential client")
        self._manage_client(event.window)

    def do_x11_child_configure_request_event(self, event: X11Event) -> None:
        # The point of this method is to handle configure requests on
        # withdrawn windows.  We simply allow them to move/resize any way they
        # want.  This is harmless because the window isn't visible anyway (and
        # apps can create unmapped windows with whatever coordinates they want
        # anyway, no harm in letting them move existing ones around), and it
        # means that when the window actually gets mapped, we have more
        # accurate info on what the app is actually requesting.
        xid = event.window
        if not xid:
            return
        from xpra.x11.models.window import configure_bits
        model = self._windows.get(xid)
        if model:
            # the window has been reparented already,
            # but we're getting the configure request event on the root window
            # forward it to the model
            log("do_x11_child_configure_request_event(%s) value_mask=%s, forwarding to %s",
                event, configure_bits(event.value_mask), model)
            model.do_x11_child_configure_request_event(event)
            return
        log("do_x11_child_configure_request_event(%s) value_mask=%s, reconfigure on withdrawn window",
            event, configure_bits(event.value_mask))
        with xswallow:
            geom = X11Window.getGeometry(xid)
            if not geom:
                log(f"failed to get geometry for window {xid:x} - skipping configure request")
                return
            x, y, w, h = geom[:4]
            if event.value_mask & CWX:
                x = event.x
            if event.value_mask & CWY:
                y = event.y
            if event.value_mask & CWWidth:
                w = event.width
            if event.value_mask & CWHeight:
                h = event.height
            if event.value_mask & (CWX | CWY | CWWidth | CWHeight):
                log("updated window geometry for window %#x from %s to %s",
                    xid, geom[:4], (x, y, w, h))
            X11Window.configure(xid, x, y, w, h, event.value_mask)
            X11Window.sendConfigureNotify(xid)

    def do_x11_focus_in_event(self, event: X11Event) -> None:
        # The purpose of this function is to detect when the focus mode has
        # gone to PointerRoot or None, so that it can be given back to
        # something real.  This is easy to detect -- a FocusIn event with
        # detail PointerRoot or None is generated on the root window.
        focuslog("wm.do_x11_focus_in_event(%s)", event)
        # if event.detail in (NotifyPointerRoot, NotifyDetailNone):
        #     self._world_window.reset_x_focus()

    # noinspection PyMethodMayBeStatic
    def do_x11_focus_out_event(self, event: X11Event) -> None:
        focuslog("wm.do_x11_focus_out_event(%s) XGetInputFocus=%s", event, X11Window.XGetInputFocus())

    def _setup_ewmh_window(self) -> int:
        # Set up a 1x1 invisible unmapped window, with which to participate in
        # EWMH's _NET_SUPPORTING_WM_CHECK protocol.  The only important things
        # about this window are the _NET_SUPPORTING_WM_CHECK property, and
        # its title (which is supposed to be the name of the window manager).

        # NB, GDK will do strange things to this window.  We don't want to use
        # it for anything.  (In particular, it will call XSelectInput on it,
        # which is fine normally when GDK is running in a client, but since it
        # happens to be using the same connection as we, the WM, it will
        # clobber any `XSelectInput` calls that *we* might have wanted to make
        # on this window.)  Also, GDK might silently swallow all events that
        # are detected on it, anyway.
        xid = X11Window.CreateWindow(rxid, -1, -1, inputoutput=InputOnly)
        prop_set(xid, "WM_TITLE", "latin1", self._wm_name)
        prop_set(xid,"WM_NAME", "utf8", self._wm_name)
        prop_set(xid,"_NET_WM_NAME", "utf8", self._wm_name)
        prop_set(xid, "_NET_SUPPORTING_WM_CHECK", "window", xid)
        root_set("_NET_SUPPORTING_WM_CHECK", "window", xid)
        root_set("_NET_WM_NAME", "utf8", self._wm_name)
        return xid

    def get_net_wm_name(self) -> str:
        if self._ewmh_window:
            try:
                return prop_get(self._ewmh_window, "_NET_WM_NAME", "utf8",
                                ignore_errors=False, raise_xerrors=False)
            except Exception as e:
                log.error("Error querying _NET_WM_NAME")
                log.estr(e)
        return ""


GObject.type_register(Wm)
