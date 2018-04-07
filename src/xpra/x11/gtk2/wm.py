# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject
import os

from xpra.util import envbool
from xpra.gtk_common.error import xsync, xswallow
from xpra.x11.gtk_x11.prop import prop_set, prop_get
from xpra.x11.window_info import window_name, window_info
from xpra.gtk_common.gobject_util import no_arg_signal, one_arg_signal
from xpra.gtk_common.gtk_util import get_xwindow

from xpra.x11.common import Unmanageable
from xpra.x11.gtk2.selection import ManagerSelection
from xpra.x11.gtk2.world_window import WorldWindow
from xpra.x11.gtk2.window import WindowModel, configure_bits
from xpra.x11.gtk2.gdk_bindings import (
               add_event_receiver,                              #@UnresolvedImport
               add_fallback_receiver, remove_fallback_receiver, #@UnresolvedImport
               get_children,                                    #@UnresolvedImport
               )
from xpra.x11.bindings.window_bindings import constants, X11WindowBindings #@UnresolvedImport
X11Window = X11WindowBindings()
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings #@UnresolvedImport
X11Keyboard = X11KeyboardBindings()

from xpra.log import Logger
log = Logger("x11", "window")
focuslog = Logger("x11", "window", "focus")
screenlog = Logger("x11", "window", "screen")
framelog = Logger("x11", "window", "frame")


CWX             = constants["CWX"]
CWY             = constants["CWY"]
CWWidth         = constants["CWWidth"]
CWHeight        = constants["CWHeight"]

NotifyPointerRoot   = constants["NotifyPointerRoot"]
NotifyDetailNone    = constants["NotifyDetailNone"]

FORCE_REPLACE_WM = envbool("XPRA_FORCE_REPLACE_WM", False)
LOG_MANAGE_FAILURES = envbool("XPRA_LOG_MANAGE_FAILURES", False)

NO_NET_SUPPORTED = os.environ.get("XPRA_NO_NET_SUPPORTED", "").split(",")

DEFAULT_NET_SUPPORTED = [
        "_NET_SUPPORTED", # a bit redundant, perhaps...
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

        "WM_NAME", "_NET_WM_NAME",
        "WM_ICON_NAME", "_NET_WM_ICON_NAME",
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
        "_NET_FRAME_EXTENTS",

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
        # Not at all yet:
        #"_NET_RESTACK_WINDOW",
        ]
NET_SUPPORTED = [x for x in DEFAULT_NET_SUPPORTED if x not in NO_NET_SUPPORTED]


def wm_check(display, wm_name, upgrading=False):
    #there should only be one screen... but let's check all of them
    for i in range(display.get_n_screens()):
        screen = display.get_screen(i)
        root = screen.get_root_window()
        wm_prop = "WM_S%s" % i
        cwm_prop = "_NEW_WM_CM_S%s" % i
        wm_so = X11Window.XGetSelectionOwner(wm_prop)
        cwm_so = X11Window.XGetSelectionOwner(cwm_prop)
        log("ewmh selection owner for %s: %s", wm_prop, wm_so)
        log("compositing window manager %s: %s", cwm_prop, cwm_so)

        try:
            ewmh_wm = prop_get(root, "_NET_SUPPORTING_WM_CHECK", "window", ignore_errors=True, raise_xerrors=False)
        except:
            #errors here generally indicate that the window is gone
            #which is fine: it means the previous window manager is no longer active
            continue
        def xid(w):
            if w:
                return "%#x" % get_xwindow(w)
            return None
        log("_NET_SUPPORTING_WM_CHECK for screen %i: %s (root=%s)", i, xid(ewmh_wm), xid(root))
        if ewmh_wm:
            try:
                name = prop_get(ewmh_wm, "_NET_WM_NAME", "utf8", ignore_errors=False, raise_xerrors=False)
            except:
                name = None
            if upgrading and name and name==wm_name:
                log.info("found previous Xpra instance")
            else:
                log.warn("Warning: found an existing window manager on screen %s using window %#x: %s", i, ewmh_wm.xid, name or "unknown")
            if (wm_so is None or wm_so==0) and (cwm_so is None or cwm_so==0):
                if FORCE_REPLACE_WM:
                    log.warn("XPRA_FORCE_REPLACE_WM is set, replacing it forcibly")
                else:
                    log.error("it does not own the selection '%s' or '%s' so we cannot take over and make it exit", wm_prop, cwm_prop)
                    log.error("please stop %s so you can run xpra on this display", name or "the existing window manager")
                    log.warn("if you are certain that the window manager is already gone,")
                    log.warn(" you may set XPRA_FORCE_REPLACE_WM=1 to force xpra to continue, at your own risk")
                    return False
    return True


class Wm(gobject.GObject):

    __gproperties__ = {
        "windows": (gobject.TYPE_PYOBJECT,
                    "Set of managed windows (as WindowModels)", "",
                    gobject.PARAM_READABLE),
        "toplevel": (gobject.TYPE_PYOBJECT,
                     "Toplevel container widget for the display", "",
                     gobject.PARAM_READABLE),
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
        "child-map-request-event": one_arg_signal,
        "child-configure-request-event": one_arg_signal,
        "xpra-focus-in-event": one_arg_signal,
        "xpra-focus-out-event": one_arg_signal,
        "xpra-client-message-event": one_arg_signal,
        "xpra-xkb-event": one_arg_signal,
        }

    def __init__(self, replace_other_wm, wm_name, display=None):
        gobject.GObject.__init__(self)

        if display is None:
            display = gtk.gdk.display_manager_get().get_default_display()
        self._display = display
        self._root = self._display.get_default_screen().get_root_window()
        self._wm_name = wm_name
        self._ewmh_window = None

        self._windows = {}
        # EWMH says we have to know the order of our windows oldest to
        # youngest...
        self._windows_in_order = []

        # Become the Official Window Manager of this year's display:
        self._wm_selection = ManagerSelection(self._display, "WM_S0")
        self._cm_wm_selection = ManagerSelection(self._display, "_NET_WM_CM_S0")
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
        self.set_desktop_list((u"Main", ))
        self.set_current_desktop(0)
        # Start with the full display as workarea:
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        self.root_set("_NET_SUPPORTED", ["atom"], NET_SUPPORTED)
        self.set_workarea(0, 0, root_w, root_h)
        self.set_desktop_geometry(root_w, root_h)
        self.root_set("_NET_DESKTOP_VIEWPORT", ["u32"], [0, 0])

        # Load up our full-screen widget
        self._world_window = WorldWindow(self._display.get_default_screen())
        self.notify("toplevel")
        self._world_window.show_all()

        # Okay, ready to select for SubstructureRedirect and then load in all
        # the existing clients.
        add_event_receiver(self._root, self)
        add_fallback_receiver("xpra-client-message-event", self)
        X11Window.substructureRedirect(self._root.xid)

        for w in get_children(self._root):
            # Checking for FOREIGN here filters out anything that we've
            # created ourselves (like, say, the world window), and checking
            # for mapped filters out any withdrawn windows.
            if (w.get_window_type() == gtk.gdk.WINDOW_FOREIGN
                and not X11Window.is_override_redirect(w.xid)
                and X11Window.is_mapped(w.xid)):
                log("Wm managing pre-existing child window %#x", w.xid)
                self._manage_client(w)

        # Also watch for focus change events on the root window
        X11Window.selectFocusChange(self._root.xid)
        X11Keyboard.selectBellNotification(True)

        # FIXME:
        # Need viewport abstraction for _NET_CURRENT_DESKTOP...
        # Tray's need to provide info for _NET_ACTIVE_WINDOW and _NET_WORKAREA
        # (and notifications for both)

    def root_set(self, *args):
        prop_set(self._root, *args)

    def root_get(self, *args):
        return prop_get(self._root, *args)

    def set_dpi(self, xdpi, ydpi):
        #this is used by some newer versions of the dummy driver (xf86-driver-dummy)
        #(and will not be honoured by anything else..)
        self.root_set("dummy-constant-xdpi", "u32", xdpi)
        self.root_set("dummy-constant-ydpi", "u32", ydpi)
        screenlog("set_dpi(%i, %i)", xdpi, ydpi)

    def set_workarea(self, x, y, width, height):
        v = [x, y, width, height]
        screenlog("_NET_WORKAREA=%s", v)
        self.root_set("_NET_WORKAREA", ["u32"], v)

    def set_desktop_geometry(self, width, height):
        v = [width, height]
        screenlog("_NET_DESKTOP_GEOMETRY=%s", v)
        self.root_set("_NET_DESKTOP_GEOMETRY", ["u32"], v)
        #update all the windows:
        for model in self._windows.values():
            model.update_desktop_geometry(width, height)

    def set_default_frame_extents(self, v):
        framelog("set_default_frame_extents(%s)", v)
        if not v or len(v)!=4:
            v = (0, 0, 0, 0)
        self.root_set("DEFAULT_NET_FRAME_EXTENTS", ["u32"], v)
        #update the models that are using the global default value:
        for win in list(self._windows.itervalues()):
            if win.is_OR() or win.is_tray():
                continue
            cur = win.get_property("frame")
            if cur is None:
                win._handle_frame_changed()


    def do_get_property(self, pspec):
        if pspec.name == "windows":
            return frozenset(self._windows.itervalues())
        elif pspec.name == "toplevel":
            return self._world_window
        else:
            assert False

    # This is in some sense the key entry point to the entire WM program.  We
    # have detected a new client window, and start managing it:
    def _manage_client(self, gdkwindow):
        if gdkwindow in self._windows:
            #already managed
            return
        try:
            with xsync:
                log("_manage_client(%s)", gdkwindow)
                desktop_geometry = self.root_get("_NET_DESKTOP_GEOMETRY", ["u32"], True, False)
                win = WindowModel(self._root, gdkwindow, desktop_geometry)
        except Exception as e:
            if LOG_MANAGE_FAILURES or type(e) not in (Unmanageable, ):
                l = log.warn
            else:
                l = log
            l("Warning: failed to manage client window %#x:", gdkwindow.xid)
            l(" %s", e)
            l("", exc_info=True)
            with xswallow:
                l(" window name: %s", window_name(gdkwindow))
                l(" window info: %s", window_info(gdkwindow))
        else:
            win.managed_connect("unmanaged", self._handle_client_unmanaged)
            self._windows[gdkwindow] = win
            self._windows_in_order.append(gdkwindow)
            self.notify("windows")
            self._update_window_list()
            self.emit("new-window", win)

    def _handle_client_unmanaged(self, window, _wm_exiting):
        gdkwindow = window.get_property("client-window")
        assert gdkwindow in self._windows
        del self._windows[gdkwindow]
        self._windows_in_order.remove(gdkwindow)
        self._update_window_list()
        self.notify("windows")

    def _update_window_list(self, *_args):
        # Ignore errors because not all the windows may still exist; if so,
        # then it's okay to leave the lists out of date for a moment, because
        # in a moment we'll get a signal telling us about the window that
        # doesn't exist anymore, will remove it from the list, and then call
        # _update_window_list again.
        with xswallow:
            self.root_set("_NET_CLIENT_LIST", ["window"], self._windows_in_order)
            # This is a lie, but we don't maintain a stacking order, so...
            self.root_set("_NET_CLIENT_LIST_STACKING", ["window"], self._windows_in_order)

    def do_xpra_client_message_event(self, event):
        # FIXME
        # Need to listen for:
        #   _NET_ACTIVE_WINDOW
        #   _NET_CURRENT_DESKTOP
        #   _NET_WM_PING responses
        # and maybe:
        #   _NET_RESTACK_WINDOW
        #   _NET_WM_STATE
        log("do_xpra_client_message_event(%s)", event)
        if event.message_type=="_NET_SHOWING_DESKTOP":
            show = bool(event.data[0])
            self.emit("show-desktop", show)
        elif event.message_type=="_NET_REQUEST_FRAME_EXTENTS":
            #if we're here, that means the window model does not exist
            #(or it would have processed the event)
            #so this must be a an unmapped window
            frame = (0, 0, 0, 0)
            with xswallow:
                if not X11Window.is_override_redirect(event.window.xid):
                    #use the global default:
                    frame = prop_get(self._root, "DEFAULT_NET_FRAME_EXTENTS", ["u32"], ignore_errors=True)
                if not frame:
                    #fallback:
                    frame = (0, 0, 0, 0)
                log("_NET_REQUEST_FRAME_EXTENTS: setting _NET_FRAME_EXTENTS=%s on %#x", frame, event.window.xid)
                prop_set(event.window, "_NET_FRAME_EXTENTS", ["u32"], frame)

    def _lost_wm_selection(self, selection):
        log.info("Lost WM selection %s, exiting", selection)
        self.emit("quit")

    def do_quit(self):
        self.cleanup()

    def cleanup(self):
        remove_fallback_receiver("xpra-client-message-event", self)
        for win in tuple(self._windows.itervalues()):
            win.unmanage(True)

    def do_child_map_request_event(self, event):
        log("Found a potential client")
        self._manage_client(event.window)

    def do_child_configure_request_event(self, event):
        # The point of this method is to handle configure requests on
        # withdrawn windows.  We simply allow them to move/resize any way they
        # want.  This is harmless because the window isn't visible anyway (and
        # apps can create unmapped windows with whatever coordinates they want
        # anyway, no harm in letting them move existing ones around), and it
        # means that when the window actually gets mapped, we have more
        # accurate info on what the app is actually requesting.
        model = self._windows.get(event.window)
        if model:
            #the window has been reparented already,
            #but we're getting the configure request event on the root window
            #forward it to the model
            log("do_child_configure_request_event(%s) value_mask=%s, forwarding to %s", event, configure_bits(event.value_mask), model)
            model.do_child_configure_request_event(event)
            return
        log("do_child_configure_request_event(%s) value_mask=%s, reconfigure on withdrawn window", event, configure_bits(event.value_mask))
        with xswallow:
            xid = event.window.xid
            x, y, w, h = X11Window.getGeometry(xid)[:4]
            if event.value_mask & CWX:
                x = event.x
            if event.value_mask & CWY:
                y = event.y
            if event.value_mask & CWWidth:
                w = event.width
            if event.value_mask & CWHeight:
                h = event.height
            if event.value_mask & (CWX | CWY | CWWidth | CWHeight):
                log("updated window geometry for window %#x from %s to %s", xid, X11Window.getGeometry(xid)[:4], (x, y, w, h))
            X11Window.configureAndNotify(xid, x, y, w, h, event.value_mask)

    def do_xpra_focus_in_event(self, event):
        # The purpose of this function is to detect when the focus mode has
        # gone to PointerRoot or None, so that it can be given back to
        # something real.  This is easy to detect -- a FocusIn event with
        # detail PointerRoot or None is generated on the root window.
        focuslog("wm.do_xpra_focus_in_event(%s)", event)
        if event.detail in (NotifyPointerRoot, NotifyDetailNone):
            self._world_window.reset_x_focus()

    def do_xpra_focus_out_event(self, event):
        focuslog("wm.do_xpra_focus_out_event(%s) XGetInputFocus=%s", event, X11Window.XGetInputFocus())

    def set_desktop_list(self, desktops):
        log("set_desktop_list(%s)", desktops)
        self.root_set("_NET_NUMBER_OF_DESKTOPS", "u32", len(desktops))
        self.root_set("_NET_DESKTOP_NAMES", ["utf8"], [d.decode("utf8") for d in desktops])

    def set_current_desktop(self, index):
        self.root_set("_NET_CURRENT_DESKTOP", "u32", index)

    def _setup_ewmh_window(self):
        # Set up a 1x1 invisible unmapped window, with which to participate in
        # EWMH's _NET_SUPPORTING_WM_CHECK protocol.  The only important things
        # about this window are the _NET_SUPPORTING_WM_CHECK property, and
        # its title (which is supposed to be the name of the window manager).

        # NB, GDK will do strange things to this window.  We don't want to use
        # it for anything.  (In particular, it will call XSelectInput on it,
        # which is fine normally when GDK is running in a client, but since it
        # happens to be using the same connection as we the WM, it will
        # clobber any XSelectInput calls that *we* might have wanted to make
        # on this window.)  Also, GDK might silently swallow all events that
        # are detected on it, anyway.
        self._ewmh_window = gtk.gdk.Window(self._root,
                                           width=1,
                                           height=1,
                                           window_type=gtk.gdk.WINDOW_TOPLEVEL,
                                           event_mask=0, # event mask
                                           wclass=gtk.gdk.INPUT_ONLY,
                                           title=self._wm_name)
        prop_set(self._ewmh_window, "_NET_SUPPORTING_WM_CHECK",
                 "window", self._ewmh_window)
        self.root_set("_NET_SUPPORTING_WM_CHECK", "window", self._ewmh_window)
        self.root_set("_NET_WM_NAME", "utf8", self._wm_name.decode("utf8"))

    def get_net_wm_name(self):
        try:
            return prop_get(self._ewmh_window, "_NET_WM_NAME", "utf8", ignore_errors=False, raise_xerrors=False)
        except Exception as e:
            log.error("error querying _NET_WM_NAME: %s", e)

gobject.type_register(Wm)
