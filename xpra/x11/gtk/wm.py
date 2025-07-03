# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any, Final

from xpra.util.env import envbool
from xpra.os_util import gi_import
from xpra.common import MAX_WINDOW_SIZE
from xpra.gtk.error import xsync, xswallow, xlog
from xpra.gtk.gobject import no_arg_signal, one_arg_signal
from xpra.gtk.util import get_default_root_window
from xpra.x11.common import Unmanageable
from xpra.x11.gtk.native_window import GDKX11Window
from xpra.x11.gtk.selection import ManagerSelection
from xpra.x11.gtk.prop import prop_set, prop_get, prop_del, raw_prop_set, prop_encode
from xpra.x11.gtk.world_window import WorldWindow, destroy_world_window
from xpra.x11.gtk.bindings import add_event_receiver, add_fallback_receiver, remove_fallback_receiver
from xpra.x11.models.window import WindowModel, configure_bits
from xpra.x11.window_info import window_name, window_info
from xpra.x11.bindings.window import constants, X11WindowBindings
from xpra.x11.bindings.keyboard import X11KeyboardBindings
from xpra.log import Logger

GObject = gi_import("GObject")
Gdk = gi_import("Gdk")

log = Logger("x11", "window")

X11Window = X11WindowBindings()
X11Keyboard = X11KeyboardBindings()

focuslog = Logger("x11", "window", "focus")
screenlog = Logger("x11", "window", "screen")
framelog = Logger("x11", "window", "frame")

CWX: Final[int] = constants["CWX"]
CWY: Final[int] = constants["CWY"]
CWWidth: Final[int] = constants["CWWidth"]
CWHeight: Final[int] = constants["CWHeight"]

NotifyPointerRoot: Final[int] = constants["NotifyPointerRoot"]
NotifyDetailNone: Final[int] = constants["NotifyDetailNone"]

LOG_MANAGE_FAILURES = envbool("XPRA_LOG_MANAGE_FAILURES", False)

NO_NET_SUPPORTED = os.environ.get("XPRA_NO_NET_SUPPORTED", "").split(",")

DEFAULT_NET_SUPPORTED = [
    "_NET_SUPPORTED",  # a bit redundant, perhaps...
    "_NET_SUPPORTING_WM_CHECK",
    "_NET_WM_FULL_PLACEMENT",
    "_NET_WM_HANDLED_ICONS",
    "_NET_CLIENT_LIST",
    "_NET_CLIENT_LIST_STACKING",
    "_NET_DESKTOP_VIEWPORT",
    "_NET_DESKTOP_GEOMETRY",
    "_NET_NUMBER_OF_DESKTOPS",
    "_NET_DESKTOP_NAMES",
    "_NET_WORKAREA",
    "_NET_ACTIVE_WINDOW",
    "_NET_CURRENT_DESKTOP",
    "_NET_SHOWING_DESKTOP",

    "WM_NAME", "_NET_WM_NAME",
    "WM_ICON_NAME", "_NET_WM_ICON_NAME",
    "WM_ICON_SIZE",
    "WM_CLASS",
    "WM_PROTOCOLS",
    "_NET_WM_PID",
    "WM_CLIENT_MACHINE",
    "WM_STATE",

    "_NET_WM_FULLSCREEN_MONITORS",

    "_NET_WM_ALLOWED_ACTIONS",
    "_NET_WM_ACTION_CLOSE",
    "_NET_WM_ACTION_FULLSCREEN",

    # We don't actually use _NET_WM_USER_TIME at all (yet), but it is
    # important to say we support the _NET_WM_USER_TIME_WINDOW property,
    # because this tells applications that they do not need to constantly
    # ping any pagers etc. that might be running -- see EWMH for details.
    # (Though it's not clear that any applications actually take advantage
    # of this yet.)
    "_NET_WM_USER_TIME",
    "_NET_WM_USER_TIME_WINDOW",
    # Not fully:
    "WM_HINTS",
    "WM_NORMAL_HINTS",
    "WM_TRANSIENT_FOR",
    "_NET_WM_STRUT",
    "_NET_WM_STRUT_PARTIAL"
    "_NET_WM_ICON",

    "_NET_CLOSE_WINDOW",

    # These aren't supported in any particularly meaningful way, but hey.
    "_NET_WM_WINDOW_TYPE",
    "_NET_WM_WINDOW_TYPE_NORMAL",
    "_NET_WM_WINDOW_TYPE_DESKTOP",
    "_NET_WM_WINDOW_TYPE_DOCK",
    "_NET_WM_WINDOW_TYPE_TOOLBAR",
    "_NET_WM_WINDOW_TYPE_MENU",
    "_NET_WM_WINDOW_TYPE_UTILITY",
    "_NET_WM_WINDOW_TYPE_SPLASH",
    "_NET_WM_WINDOW_TYPE_DIALOG",
    "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
    "_NET_WM_WINDOW_TYPE_POPUP_MENU",
    "_NET_WM_WINDOW_TYPE_TOOLTIP",
    "_NET_WM_WINDOW_TYPE_NOTIFICATION",
    "_NET_WM_WINDOW_TYPE_COMBO",
    # "_NET_WM_WINDOW_TYPE_DND",

    "_NET_WM_STATE",
    "_NET_WM_STATE_DEMANDS_ATTENTION",
    "_NET_WM_STATE_MODAL",
    # More states to support:
    "_NET_WM_STATE_STICKY",
    "_NET_WM_STATE_MAXIMIZED_VERT",
    "_NET_WM_STATE_MAXIMIZED_HORZ",
    "_NET_WM_STATE_SHADED",
    "_NET_WM_STATE_SKIP_TASKBAR",
    "_NET_WM_STATE_SKIP_PAGER",
    "_NET_WM_STATE_HIDDEN",
    "_NET_WM_STATE_FULLSCREEN",
    "_NET_WM_STATE_ABOVE",
    "_NET_WM_STATE_BELOW",
    "_NET_WM_STATE_FOCUSED",

    "_NET_WM_DESKTOP",

    "_NET_WM_MOVERESIZE",
    "_NET_MOVERESIZE_WINDOW",

    "_MOTIF_WM_HINTS",
    "_MOTIF_WM_INFO",

    "_NET_REQUEST_FRAME_EXTENTS",
    "_NET_RESTACK_WINDOW",

    "_NET_WM_OPAQUE_REGION",
]
FRAME_EXTENTS = envbool("XPRA_FRAME_EXTENTS", True)
if FRAME_EXTENTS:
    DEFAULT_NET_SUPPORTED.append("_NET_FRAME_EXTENTS")

NET_SUPPORTED = [x for x in DEFAULT_NET_SUPPORTED if x not in NO_NET_SUPPORTED]

DEFAULT_SIZE_CONSTRAINTS = (0, 0, MAX_WINDOW_SIZE, MAX_WINDOW_SIZE)


class Wm(GObject.GObject):
    __gproperties__ = {
        "windows": (GObject.TYPE_PYOBJECT,
                    "Set of managed windows (as WindowModels)", "",
                    GObject.ParamFlags.READABLE),
        "toplevel": (GObject.TYPE_PYOBJECT,
                     "Toplevel container widget for the display", "",
                     GObject.ParamFlags.READABLE),
    }
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

    def __init__(self, replace_other_wm: bool, wm_name: str):
        super().__init__()

        self._wm_name = wm_name
        self._ewmh_window = None

        self._windows: dict[int, Any] = {}
        # EWMH says we have to know the order of our windows oldest to
        # youngest...
        self._windows_in_order = []

        # Become the Official Window Manager of this year's display:
        self._wm_selection = ManagerSelection("WM_S0")
        self._cm_wm_selection = ManagerSelection("_NET_WM_CM_S0")
        self._wm_selection.connect("selection-lost", self._lost_wm_selection)
        self._cm_wm_selection.connect("selection-lost", self._lost_wm_selection)
        # May throw AlreadyOwned:
        if replace_other_wm:
            mode = self._wm_selection.FORCE
        else:
            mode = self._wm_selection.IF_UNOWNED
        self._wm_selection.acquire(mode)
        self._cm_wm_selection.acquire(mode)

        # Set up the necessary EWMH properties on the root window.
        self._setup_ewmh_window()
        # Start with just one desktop:
        self.set_desktop_list(("Main",))
        self.set_current_desktop(0)
        # Start with the full display as workarea:
        root = get_default_root_window()
        root_w, root_h = root.get_geometry()[2:4]
        self.root_set("_NET_SUPPORTED", ["atom"], NET_SUPPORTED)
        self.set_workarea(0, 0, root_w, root_h)
        self.set_desktop_geometry(root_w, root_h)
        self.root_set("_NET_DESKTOP_VIEWPORT", ["u32"], [0, 0])

        self.size_constraints = DEFAULT_SIZE_CONSTRAINTS

        # Load up our full-screen widget
        self._world_window = WorldWindow()
        self.notify("toplevel")
        self._world_window.show_all()
        wxid = self._world_window.get_window().get_xid()

        # Okay, ready to select for SubstructureRedirect and then load in all
        # the existing clients.
        rxid = root.get_xid()
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
            # ignore windows we have created ourselves (ie: the world window),
            # unmapped or `OR` windows:
            if xid == wxid:
                continue
            if X11Window.is_override_redirect(xid):
                log("skipping %s", window_info(xid))
                continue
            if not X11Window.is_mapped(xid):
                log("skipping %s", window_info(xid))
                continue
            log(f"Wm managing pre-existing child window {xid:x}")
            self._manage_client(xid)

        # Also watch for focus change events on the root window
        X11Window.selectFocusChange(rxid)
        X11Keyboard.selectBellNotification(True)
        X11Window.setRootIconSizes(64, 64)

        # FIXME:
        # Need viewport abstraction for _NET_CURRENT_DESKTOP...
        # Tray's need to provide info for _NET_ACTIVE_WINDOW and _NET_WORKAREA
        # (and notifications for both)

    @staticmethod
    def root_set(*args) -> None:
        prop_set(X11Window.get_root_xid(), *args)

    @staticmethod
    def root_get(*args, **kwargs):
        return prop_get(X11Window.get_root_xid(), *args, **kwargs)

    def set_workarea(self, x: int, y: int, width: int, height: int) -> None:
        v = [x, y, width, height]
        screenlog("_NET_WORKAREA=%s", v)
        self.root_set("_NET_WORKAREA", ["u32"], v)

    def set_desktop_geometry(self, width: int, height: int) -> None:
        v = [width, height]
        screenlog("_NET_DESKTOP_GEOMETRY=%s", v)
        self.root_set("_NET_DESKTOP_GEOMETRY", ["u32"], v)
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

    def set_default_frame_extents(self, v):
        framelog("set_default_frame_extents(%s)", v)
        if not v or len(v) != 4:
            v = (0, 0, 0, 0)
        self.root_set("DEFAULT_NET_FRAME_EXTENTS", ["u32"], v)
        # update the models that are using the global default value:
        for win in self._windows.values():
            if win.is_OR() or win.is_tray():
                continue
            cur = win.get_property("frame")
            if cur is None:
                win._handle_frame_changed()

    def do_get_property(self, pspec):
        if pspec.name == "windows":
            return frozenset(self._windows.values())
        if pspec.name == "toplevel":
            return self._world_window
        assert False

    # This is in some sense the key entry point to the entire WM program.  We
    # have detected a new client window, and start managing it:
    def _manage_client(self, xid: int):
        if xid in self._windows:
            # already managed
            return
        try:
            with xsync:
                log("_manage_client(%x)", xid)
                desktop_geometry = self.root_get("_NET_DESKTOP_GEOMETRY", ["u32"], True, False)
                root = get_default_root_window()
                win = WindowModel(root.get_xid(), xid, desktop_geometry, self.size_constraints)
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
            self.notify("windows")
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
        self.notify("windows")

    def _update_window_list(self, *_args) -> None:
        # Ignore errors because not all the windows may still exist; if so,
        # then it's okay to leave the lists out of date for a moment, because
        # in a moment we'll get a signal telling us about the window that
        # doesn't exist anymore, will remove it from the list, and then call
        # _update_window_list again.
        dtype, dformat, window_xids = prop_encode(["u32"], tuple(self._windows_in_order))
        log("prop_encode(%s)=%s", self._windows_in_order, (dtype, dformat, window_xids))
        xid = X11Window.get_root_xid()
        with xlog:
            for prop in ("_NET_CLIENT_LIST", "_NET_CLIENT_LIST_STACKING"):
                raw_prop_set(xid, prop, "WINDOW", dformat, window_xids)

    def do_x11_client_message_event(self, event) -> None:
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
            frame = None
            with xswallow:
                xid = event.window
                if not X11Window.is_override_redirect(xid):
                    # use the global default:
                    frame = self.root_get("DEFAULT_NET_FRAME_EXTENTS", ["u32"], ignore_errors=True)
                if not frame:
                    # fallback:
                    frame = (0, 0, 0, 0)
                framelog("_NET_REQUEST_FRAME_EXTENTS: setting _NET_FRAME_EXTENTS=%s on %#x", frame, xid)
                prop_set(event.window, "_NET_FRAME_EXTENTS", ["u32"], frame)

    def _lost_wm_selection(self, selection) -> None:
        log.info("Lost WM selection %s, exiting", selection)
        self.emit("quit")

    def do_quit(self) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        remove_fallback_receiver("x11-client-message-event", self)
        remove_fallback_receiver("x11-child-map-request-event", self)
        for win in tuple(self._windows.values()):
            win.unmanage(True)
        xid = self._ewmh_window.get_xid()
        with xswallow:
            prop_del(xid, "_NET_SUPPORTING_WM_CHECK")
            prop_del(xid, "_NET_WM_NAME")
        destroy_world_window()

    def do_x11_child_map_request_event(self, event) -> None:
        log("Found a potential client")
        self._manage_client(event.window)

    def do_x11_child_configure_request_event(self, event) -> None:
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

    def do_x11_focus_in_event(self, event) -> None:
        # The purpose of this function is to detect when the focus mode has
        # gone to PointerRoot or None, so that it can be given back to
        # something real.  This is easy to detect -- a FocusIn event with
        # detail PointerRoot or None is generated on the root window.
        focuslog("wm.do_x11_focus_in_event(%s)", event)
        if event.detail in (NotifyPointerRoot, NotifyDetailNone) and self._world_window:
            self._world_window.reset_x_focus()

    # noinspection PyMethodMayBeStatic
    def do_x11_focus_out_event(self, event) -> None:
        focuslog("wm.do_x11_focus_out_event(%s) XGetInputFocus=%s", event, X11Window.XGetInputFocus())

    def set_desktop_list(self, desktops) -> None:
        log("set_desktop_list(%s)", desktops)
        self.root_set("_NET_NUMBER_OF_DESKTOPS", "u32", len(desktops))
        self.root_set("_NET_DESKTOP_NAMES", ["utf8"], desktops)

    def set_current_desktop(self, index) -> None:
        self.root_set("_NET_CURRENT_DESKTOP", "u32", index)

    def _setup_ewmh_window(self) -> None:
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
        root = get_default_root_window()
        self._ewmh_window = GDKX11Window(root, wclass=Gdk.WindowWindowClass.INPUT_ONLY, title=self._wm_name)
        xid = self._ewmh_window.get_xid()
        prop_set(xid, "_NET_SUPPORTING_WM_CHECK", "window", xid)
        self.root_set("_NET_SUPPORTING_WM_CHECK", "window", xid)
        self.root_set("_NET_WM_NAME", "utf8", self._wm_name)

    def get_net_wm_name(self) -> str:
        try:
            return prop_get(self._ewmh_window.get_xid(), "_NET_WM_NAME", "utf8",
                            ignore_errors=False, raise_xerrors=False)
        except Exception as e:
            log.error("Error querying _NET_WM_NAME")
            log.estr(e)
            return ""


GObject.type_register(Wm)
