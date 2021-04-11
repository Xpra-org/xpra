# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.util import envint, envbool, typedict
from xpra.gtk_common.gobject_util import one_arg_signal, non_none_list_accumulator, SIGNAL_RUN_LAST
from xpra.gtk_common.error import XError, XSwallowContext
from xpra.x11.gtk_x11.send_wm import send_wm_take_focus
from xpra.x11.gtk_x11.prop import prop_set, prop_get
from xpra.x11.prop_conv import MotifWMHints
from xpra.x11.bindings.window_bindings import X11WindowBindings #@UnresolvedImport
from xpra.x11.common import Unmanageable, MAX_WINDOW_SIZE
from xpra.x11.models.size_hints_util import sanitize_size_hints
from xpra.x11.models.base import BaseWindowModel, constants
from xpra.x11.models.core import sanestr, gobject, xswallow, xsync
from xpra.x11.gtk_x11.gdk_bindings import (
    add_event_receiver, remove_event_receiver,
    get_children,
    calc_constrained_size,
    x11_get_server_time,
    )
from xpra.gtk_common.gtk_util import (
    get_default_root_window, get_xwindow, icon_theme_get_default,
    GDKWindow, GDKWINDOW_CHILD, PROPERTY_CHANGE_MASK,
    PARAM_READABLE, PARAM_READWRITE,
    )
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_cairo
from xpra.log import Logger

gtk = import_gtk()
gdk = import_gdk()
cairo = import_cairo()

log = Logger("x11", "window")
workspacelog = Logger("x11", "window", "workspace")
shapelog = Logger("x11", "window", "shape")
grablog = Logger("x11", "window", "grab")
metalog = Logger("x11", "window", "metadata")
iconlog = Logger("x11", "window", "icon")
focuslog = Logger("x11", "window", "focus")
geomlog = Logger("x11", "window", "geometry")


X11Window = X11WindowBindings()

IconicState = constants["IconicState"]
NormalState = constants["NormalState"]

CWX             = constants["CWX"]
CWY             = constants["CWY"]
CWWidth         = constants["CWWidth"]
CWHeight        = constants["CWHeight"]
CWBorderWidth   = constants["CWBorderWidth"]
CWSibling       = constants["CWSibling"]
CWStackMode     = constants["CWStackMode"]
CONFIGURE_GEOMETRY_MASK = CWX | CWY | CWWidth | CWHeight
CW_MASK_TO_NAME = {
                   CWX              : "X",
                   CWY              : "Y",
                   CWWidth          : "Width",
                   CWHeight         : "Height",
                   CWBorderWidth    : "BorderWidth",
                   CWSibling        : "Sibling",
                   CWStackMode      : "StackMode",
                   CWBorderWidth    : "BorderWidth",
                   }
def configure_bits(value_mask):
    return "|".join(v for k,v in CW_MASK_TO_NAME.items() if k&value_mask)


FORCE_XSETINPUTFOCUS = envbool("XPRA_FORCE_XSETINPUTFOCUS", False)
VALIDATE_CONFIGURE_REQUEST = envbool("XPRA_VALIDATE_CONFIGURE_REQUEST", False)
CLAMP_OVERLAP = envint("XPRA_WINDOW_CLAMP_OVERLAP", 20)
assert CLAMP_OVERLAP>=0


class WindowModel(BaseWindowModel):
    """This represents a managed client window.  It allows one to produce
    widgets that view that client window in various ways."""

    _NET_WM_ALLOWED_ACTIONS = ["_NET_WM_ACTION_%s" % x for x in (
        "CLOSE", "MOVE", "RESIZE", "FULLSCREEN",
        "MINIMIZE", "SHADE", "STICK",
        "MAXIMIZE_HORZ", "MAXIMIZE_VERT",
        "CHANGE_DESKTOP", "ABOVE", "BELOW")]

    __gproperties__ = dict(BaseWindowModel.__common_properties__)
    __gproperties__.update({
        "owner": (gobject.TYPE_PYOBJECT,
                  "Owner", "",
                  PARAM_READABLE),
        # Interesting properties of the client window, that will be
        # automatically kept up to date:
        "requested-position": (gobject.TYPE_PYOBJECT,
                               "Client-requested position on screen", "",
                               PARAM_READABLE),
        "requested-size": (gobject.TYPE_PYOBJECT,
                           "Client-requested size on screen", "",
                           PARAM_READABLE),
        "set-initial-position": (gobject.TYPE_BOOLEAN,
                                 "Should the requested position be honoured?", "",
                                 False,
                                 PARAM_READWRITE),
        # Toggling this property does not actually make the window iconified,
        # i.e. make it appear or disappear from the screen -- it merely
        # updates the various window manager properties that inform the world
        # whether or not the window is iconified.
        "iconic": (gobject.TYPE_BOOLEAN,
                   "ICCCM 'iconic' state -- any sort of 'not on desktop'.", "",
                   False,
                   PARAM_READWRITE),
        #from WM_NORMAL_HINTS
        "size-hints": (gobject.TYPE_PYOBJECT,
                       "Client hints on constraining its size", "",
                       PARAM_READABLE),
        #from _NET_WM_ICON_NAME or WM_ICON_NAME
        "icon-title": (gobject.TYPE_PYOBJECT,
                       "Icon title (unicode or None)", "",
                       PARAM_READABLE),
        #from _NET_WM_ICON
        "icons": (gobject.TYPE_PYOBJECT,
                 "Icons in raw RGBA format, by size", "",
                 PARAM_READABLE),
        #from _MOTIF_WM_HINTS.decorations
        "decorations": (gobject.TYPE_INT,
                       "Should the window decorations be shown", "",
                       -1, 65535, -1,
                       PARAM_READABLE),
        "children" : (gobject.TYPE_PYOBJECT,
                        "Sub-windows", None,
                        PARAM_READABLE),
        })
    __gsignals__ = dict(BaseWindowModel.__common_signals__)
    __gsignals__.update({
        "ownership-election"            : (SIGNAL_RUN_LAST, gobject.TYPE_PYOBJECT, (), non_none_list_accumulator),
        "child-map-request-event"       : one_arg_signal,
        "child-configure-request-event" : one_arg_signal,
        "xpra-destroy-event"            : one_arg_signal,
        })

    _property_names         = BaseWindowModel._property_names + [
                              "size-hints", "icon-title", "icons", "decorations",
                              "modal", "set-initial-position", "iconic",
                              ]
    _dynamic_property_names = BaseWindowModel._dynamic_property_names + [
                              "size-hints", "icon-title", "icons", "decorations", "modal", "iconic"]
    _initial_x11_properties = BaseWindowModel._initial_x11_properties + [
                              "WM_HINTS", "WM_NORMAL_HINTS", "_MOTIF_WM_HINTS",
                              "WM_ICON_NAME", "_NET_WM_ICON_NAME", "_NET_WM_ICON",
                              "_NET_WM_STRUT", "_NET_WM_STRUT_PARTIAL"]
    _internal_property_names = BaseWindowModel._internal_property_names+["children"]
    _MODELTYPE = "Window"

    def __init__(self, parking_window, client_window, desktop_geometry, size_constraints=None):
        """Register a new client window with the WM.

        Raises an Unmanageable exception if this window should not be
        managed, for whatever reason.  ATM, this mostly means that the window
        died somehow before we could do anything with it."""

        super(WindowModel, self).__init__(client_window)
        self.parking_window = parking_window
        self.corral_window = None
        self.desktop_geometry = desktop_geometry
        self.size_constraints = size_constraints or (0, 0, MAX_WINDOW_SIZE, MAX_WINDOW_SIZE)
        #extra state attributes so we can unmanage() the window cleanly:
        self.in_save_set = False
        self.client_reparented = False
        self.kill_count = 0

        self.call_setup()

    #########################################
    # Setup and teardown
    #########################################

    def setup(self):
        super(WindowModel, self).setup()

        ox, oy, ow, oh = self.client_window.get_geometry()[:4]
        # We enable PROPERTY_CHANGE_MASK so that we can call
        # x11_get_server_time on this window.
        # clamp this window to the desktop size:
        x, y = self._clamp_to_desktop(ox, oy, ow, oh)
        self.corral_window = GDKWindow(self.parking_window,
                                        x=x, y=y, width=ow, height=oh,
                                        window_type=GDKWINDOW_CHILD,
                                        event_mask=PROPERTY_CHANGE_MASK,
                                        title = "CorralWindow-%#x" % self.xid)
        cxid = get_xwindow(self.corral_window)
        log("setup() corral_window=%#x", cxid)
        prop_set(self.corral_window, "_NET_WM_NAME", "utf8", u"Xpra-CorralWindow-%#x" % self.xid)
        X11Window.substructureRedirect(cxid)
        add_event_receiver(self.corral_window, self)

        # The child might already be mapped, in case we inherited it from
        # a previous window manager.  If so, we unmap it now, and save the
        # serial number of the request -- this way, when we get an
        # UnmapNotify later, we'll know that it's just from us unmapping
        # the window, not from the client withdrawing the window.
        if X11Window.is_mapped(self.xid):
            log("hiding inherited window")
            self.last_unmap_serial = X11Window.Unmap(self.xid)

        log("setup() adding to save set")
        X11Window.XAddToSaveSet(self.xid)
        self.in_save_set = True

        log("setup() reparenting")
        X11Window.Reparent(self.xid, cxid, 0, 0)
        self.client_reparented = True

        geomlog("setup() geometry")
        geom = X11Window.geometry_with_border(self.xid)
        if geom is None:
            raise Unmanageable("window %#x disappeared already" % self.xid)
        w, h = geom[2:4]
        hints = self.get_property("size-hints")
        geomlog("setup() hints=%s size=%ix%i", hints, w, h)
        nw, nh = self.calc_constrained_size(w, h, hints)
        self._updateprop("geometry", (x, y, nw, nh))
        geomlog("setup() resizing windows to %sx%s", nw, nh)
        #don't trigger a resize unless we have to:
        if ow!=nw or oh!=nh:
            self.corral_window.resize(nw, nh)
        if w!=nw or h!=nh:
            self.client_window.resize(nw, nh)
        self.client_window.show_unraised()
        #this is here to trigger X11 errors if any are pending
        #or if the window is deleted already:
        self.client_window.get_geometry()


    def _clamp_to_desktop(self, x, y, w, h):
        if self.desktop_geometry:
            dw, dh = self.desktop_geometry
            if x+w<0:
                x = min(0, CLAMP_OVERLAP-w)
            elif x>=dw:
                x = max(0, dw-CLAMP_OVERLAP)
            if y+h<0:
                y = min(0, CLAMP_OVERLAP-h)
            elif y>dh:
                y = max(0, dh-CLAMP_OVERLAP)
        return x, y

    def update_desktop_geometry(self, width, height):
        if self.desktop_geometry==(width, height):
            return  #no need to do anything
        self.desktop_geometry = (width, height)
        x, y, w, h = self.corral_window.get_geometry()[:4]
        nx, ny = self._clamp_to_desktop(x, y, w, h)
        if nx!=x or ny!=y:
            log("update_desktop_geometry(%i, %i) adjusting corral window to new location: %i,%i", width, height, nx, ny)
            self.corral_window.move(nx, ny)


    def _read_initial_X11_properties(self):
        metalog("read_initial_X11_properties() window")
        # WARNING: have to handle _NET_WM_STATE before we look at WM_HINTS;
        # WM_HINTS assumes that our "state" property is already set.  This is
        # because there are four ways a window can get its urgency
        # ("attention-requested") bit set:
        #   1) _NET_WM_STATE_DEMANDS_ATTENTION in the _initial_ state hints
        #   2) setting the bit WM_HINTS, at _any_ time
        #   3) sending a request to the root window to add
        #      _NET_WM_STATE_DEMANDS_ATTENTION to their state hints
        #   4) if we (the wm) decide they should be and set it
        # To implement this, we generally track the urgency bit via
        # _NET_WM_STATE (since that is under our sole control during normal
        # operation).  Then (1) is accomplished through the normal rule that
        # initial states are read off from the client, and (2) is accomplished
        # by having WM_HINTS affect _NET_WM_STATE.  But this means that
        # WM_HINTS and _NET_WM_STATE handling become intertangled.
        def set_if_unset(propname, value):
            #the property may not be initialized yet,
            #if that's the case then calling get_property throws an exception:
            try:
                if self.get_property(propname) not in (None, ""):
                    return
            except TypeError:
                pass
            self._internal_set_property(propname, value)
        #"decorations" needs to be set before reading the X11 properties
        #because handle_wm_normal_hints_change reads it:
        set_if_unset("decorations", -1)
        super(WindowModel, self)._read_initial_X11_properties()
        net_wm_state = self.get_property("state")
        assert net_wm_state is not None, "_NET_WM_STATE should have been read already"
        geom = X11Window.getGeometry(self.xid)
        if not geom:
            raise Unmanageable("failed to get geometry for %#x" % self.xid)
        #initial position and size, from the Window object,
        #but allow size hints to override it if specified
        x, y, w, h = geom[:4]
        size_hints = self.get_property("size-hints")
        ax, ay = size_hints.get("position", (x, y))
        aw, ah = size_hints.get("size", (w, h))
        geomlog("initial X11 position and size: requested(%s, %s)=%s", (x, y, w, h), size_hints, (ax, ay, aw, ah))
        set_if_unset("modal", "_NET_WM_STATE_MODAL" in net_wm_state)
        set_if_unset("requested-position", (ax, ay))
        set_if_unset("requested-size", (aw, ah))
        #it may have been set already:
        v = self.get_property("set-initial-position")
        self._internal_set_property("set-initial-position", v or ("position" in size_hints))
        self.update_children()

    def do_unmanaged(self, wm_exiting):
        log("unmanaging window: %s (%s - %s)", self, self.corral_window, self.client_window)
        self._internal_set_property("owner", None)
        cwin = self.corral_window
        if cwin:
            self.corral_window = None
            remove_event_receiver(cwin, self)
            geom = None
            #use a new context so we will XSync right here
            #and detect if the window is already gone:
            with XSwallowContext():
                geom = X11Window.getGeometry(self.xid)
            if geom is not None:
                if self.client_reparented:
                    self.client_window.reparent(get_default_root_window(), 0, 0)
                self.client_window.set_events(self.client_window_saved_events)
            self.client_reparented = False
            # It is important to remove from our save set, even after
            # reparenting, because according to the X spec, windows that are
            # in our save set are always Mapped when we exit, *even if those
            # windows are no longer inferior to any of our windows!* (see
            # section 10. Connection Close).  This causes "ghost windows", see
            # bug #27:
            if self.in_save_set:
                with xswallow:
                    X11Window.XRemoveFromSaveSet(self.xid)
                self.in_save_set = False
            with xswallow:
                X11Window.sendConfigureNotify(self.xid)
            if wm_exiting:
                self.client_window.show_unraised()
            #it is now safe to destroy the corral window:
            cwin.destroy()
        BaseWindowModel.do_unmanaged(self, wm_exiting)


    #########################################
    # Actions specific to WindowModel
    #########################################

    def raise_window(self):
        X11Window.XRaiseWindow(get_xwindow(self.corral_window))
        X11Window.XRaiseWindow(get_xwindow(self.client_window))

    def unmap(self):
        with xsync:
            if X11Window.is_mapped(self.xid):
                self.last_unmap_serial = X11Window.Unmap(self.xid)
                log("client window %#x unmapped, serial=%#x", self.xid, self.last_unmap_serial)

    def map(self):
        with xsync:
            if not X11Window.is_mapped(self.xid):
                X11Window.MapWindow(self.xid)
                log("client window %#x mapped", self.xid)


    #########################################
    # X11 Events
    #########################################

    def do_xpra_property_notify_event(self, event):
        if event.delivered_to is self.corral_window:
            return
        BaseWindowModel.do_xpra_property_notify_event(self, event)

    def do_child_map_request_event(self, event):
        # If we get a MapRequest then it might mean that someone tried to map
        # this window multiple times in quick succession, before we actually
        # mapped it (so that several MapRequests ended up queued up; FSF Emacs
        # 22.1.50.1 does this, at least).  It alternatively might mean that
        # the client is naughty and tried to map their window which is
        # currently not displayed.  In either case, we should just ignore the
        # request.
        log("do_child_map_request_event(%s)", event)

    def do_xpra_unmap_event(self, event):
        if event.delivered_to is self.corral_window or self.corral_window is None:
            return
        assert event.window is self.client_window
        # The client window got unmapped.  The question is, though, was that
        # because it was withdrawn/destroyed, or was it because we unmapped it
        # going into IconicState?
        #
        # Also, if we receive a *synthetic* UnmapNotify event, that always
        # means that the client has withdrawn the window (even if it was not
        # mapped in the first place) -- ICCCM section 4.1.4.
        log("do_xpra_unmap_event(%s) client window unmapped, last_unmap_serial=%#x", event, self.last_unmap_serial)
        if event.send_event or self.serial_after_last_unmap(event.serial):
            self.unmanage()

    def do_xpra_destroy_event(self, event):
        if event.delivered_to is self.corral_window or self.corral_window is None:
            return
        assert event.window is self.client_window
        super(WindowModel, self).do_xpra_destroy_event(event)


    #########################################
    # Hooks for WM
    #########################################

    def ownership_election(self):
        #returns True if we have updated the geometry
        candidates = self.emit("ownership-election")
        if candidates:
            rating, winner = sorted(candidates)[-1]
            if rating < 0:
                winner = None
        else:
            winner = None
        old_owner = self.get_property("owner")
        log("ownership_election() winner=%s, old owner=%s, candidates=%s", winner, old_owner, candidates)
        if old_owner is winner:
            return False
        if old_owner is not None:
            self.corral_window.hide()
            self.corral_window.reparent(self.parking_window, 0, 0)
        self._internal_set_property("owner", winner)
        if winner is not None:
            winner.take_window(self, self.corral_window)
            self._update_client_geometry()
            self.corral_window.show_unraised()
            return True
        with xswallow:
            X11Window.sendConfigureNotify(self.xid)
        return False

    def maybe_recalculate_geometry_for(self, maybe_owner):
        if maybe_owner and self.get_property("owner") is maybe_owner:
            self._update_client_geometry()

    def _update_client_geometry(self):
        """ figure out where we're supposed to get the window geometry from,
            and call do_update_client_geometry which will send a Configure and Notify
        """
        owner = self.get_property("owner")
        if owner is not None:
            geomlog("_update_client_geometry: using owner=%s (setup_done=%s)", owner, self._setup_done)
            def window_size():
                return  owner.window_size(self)
            def window_position(w, h):
                return  owner.window_position(self, w, h)
        elif not self._setup_done:
            #try to honour initial size and position requests during setup:
            def window_size():
                return self.get_property("requested-size")
            def window_position(_w, _h):
                return self.get_property("requested-position")
            geomlog("_update_client_geometry: using initial size=%s and position=%s", window_size, window_position)
        else:
            geomlog("_update_client_geometry: ignored, owner=%s, setup_done=%s", owner, self._setup_done)
            def window_size():
                return self.get_property("geometry")[2:4]
            def window_position(_w, _h):
                return self.get_property("geometry")[:2]
        self._do_update_client_geometry(window_size, window_position)


    def _do_update_client_geometry(self, window_size_cb, window_position_cb):
        allocated_w, allocated_h = window_size_cb()
        geomlog("_do_update_client_geometry: allocated %ix%i (from %s)", allocated_w, allocated_h, window_size_cb)
        hints = self.get_property("size-hints")
        w, h = self.calc_constrained_size(allocated_w, allocated_h, hints)
        geomlog("_do_update_client_geometry: size(%s)=%ix%i", hints, w, h)
        x, y = window_position_cb(w, h)
        geomlog("_do_update_client_geometry: position=%ix%i (from %s)", x, y, window_position_cb)
        self.corral_window.move_resize(x, y, w, h)
        self._updateprop("geometry", (x, y, w, h))
        with xswallow:
            X11Window.configureAndNotify(self.xid, 0, 0, w, h)

    def do_xpra_configure_event(self, event):
        cxid = get_xwindow(self.corral_window)
        geomlog("WindowModel.do_xpra_configure_event(%s) corral=%#x, client=%#x, managed=%s",
                event, cxid, self.xid, self._managed)
        if not self._managed:
            return
        if event.window==self.corral_window:
            #we only care about events on the client window
            geomlog("WindowModel.do_xpra_configure_event: event is on the corral window %#x, ignored", cxid)
            return
        if event.window!=self.client_window:
            #we only care about events on the client window
            geomlog("WindowModel.do_xpra_configure_event: event is not on the client window but on %#x, ignored",
                    get_xwindow(event.window))
            return
        if self.corral_window is None or not self.corral_window.is_visible():
            geomlog("WindowModel.do_xpra_configure_event: corral window is not visible")
            return
        if self.client_window is None or not self.client_window.is_visible():
            geomlog("WindowModel.do_xpra_configure_event: client window is not visible")
            return
        try:
            #workaround applications whose windows disappear from underneath us:
            with xsync:
                #event.border_width unused
                self.resize_corral_window(event.x, event.y, event.width, event.height)
                self.update_children()
        except XError as e:
            geomlog("do_xpra_configure_event(%s)", event, exc_info=True)
            geomlog.warn("Warning: failed to resize corral window %#x", cxid)
            geomlog.warn(" %s", e)

    def update_children(self):
        ww, wh = self.client_window.get_geometry()[2:4]
        children = []
        for w in get_children(self.client_window):
            xid = get_xwindow(w)
            if X11Window.is_inputonly(xid):
                continue
            geom = X11Window.getGeometry(xid)
            if not geom:
                continue
            if geom[2]==geom[3]==1:
                #skip 1x1 windows, as those are usually just event windows
                continue
            if geom[0]==geom[1]==0 and geom[2]==ww and geom[3]==wh:
                #exact same geometry as the window itself
                continue
            #record xid and geometry:
            children.append([xid]+list(geom))
        self._internal_set_property("children", children)

    def resize_corral_window(self, x, y, w, h):
        #the client window may have been resized or moved (generally programmatically)
        #so we may need to update the corral_window to match
        cox, coy, cow, coh = self.corral_window.get_geometry()[:4]
        #size changes (and position if any):
        hints = self.get_property("size-hints")
        w, h = self.calc_constrained_size(w, h, hints)
        cx, cy, cw, ch = self.get_property("geometry")
        resized = cow!=w or coh!=h
        moved = x!=0 or y!=0
        if resized:
            if moved:
                self._internal_set_property("set-initial-position", True)
                geomlog("resize_corral_window() move and resize from %s to %s", (cox, coy, cow, coh), (x, y, w, h))
                self.corral_window.move_resize(x, y, w, h)
                self.client_window.move(0, 0)
                self._updateprop("geometry", (x, y, w, h))
            else:
                geomlog("resize_corral_window() resize from %s to %s", (cow, coh), (w, h))
                self.corral_window.resize(w, h)
                self._updateprop("geometry", (cx, cy, w, h))
        elif moved:
            self._internal_set_property("set-initial-position", True)
            geomlog("resize_corral_window() moving corral window from %s to %s", (cox, coy), (x, y))
            self.corral_window.move(x, y)
            self.client_window.move(0, 0)
            self._updateprop("geometry", (x, y, cw, ch))

    def do_child_configure_request_event(self, event):
        cxid = get_xwindow(self.corral_window)
        hints = self.get_property("size-hints")
        geomlog("do_child_configure_request_event(%s) client=%#x, corral=%#x, value_mask=%s, size-hints=%s",
                event, self.xid, cxid, configure_bits(event.value_mask), hints)
        if event.value_mask & CWStackMode:
            geomlog(" restack above=%s, detail=%s", event.above, event.detail)
        # Also potentially update our record of what the app has requested:
        ogeom = self.get_property("geometry")
        x, y, w, h = ogeom[:4]
        rx, ry = self.get_property("requested-position")
        if event.value_mask & CWX:
            x = event.x
            rx = x
        if event.value_mask & CWY:
            y = event.y
            ry = y
        if event.value_mask & CWX or event.value_mask & CWY:
            self._internal_set_property("set-initial-position", True)
            self._updateprop("requested-position", (rx, ry))

        rw, rh = self.get_property("requested-size")
        if event.value_mask & CWWidth:
            w = event.width
            rw = w
        if event.value_mask & CWHeight:
            h = event.height
            rh = h
        if event.value_mask & CWWidth or event.value_mask & CWHeight:
            self._updateprop("requested-size", (rw, rh))

        if VALIDATE_CONFIGURE_REQUEST:
            w, h = self.calc_constrained_size(w, h, hints)
        #update the geometry now, as another request may come in
        #before we've had a chance to process the ConfigureNotify that the code below will generate
        self._updateprop("geometry", (x, y, w, h))
        geomlog("do_child_configure_request_event updated requested geometry from %s to  %s", ogeom, (x, y, w, h))
        # As per ICCCM 4.1.5, even if we ignore the request
        # send back a synthetic ConfigureNotify telling the client that nothing has happened.
        with xswallow:
            X11Window.configureAndNotify(self.xid, x, y, w, h)
        # FIXME: consider handling attempts to change stacking order here.
        # (In particular, I believe that a request to jump to the top is
        # meaningful and should perhaps even be respected.)

    def process_client_message_event(self, event):
        if event.message_type=="_NET_MOVERESIZE_WINDOW":
            #TODO: honour gravity, show source indication
            geom = self.corral_window.get_geometry()
            x, y, w, h, _ = geom
            if event.data[0] & 0x100:
                x = event.data[1]
            if event.data[0] & 0x200:
                y = event.data[2]
            if event.data[0] & 0x400:
                w = event.data[3]
            if event.data[0] & 0x800:
                h = event.data[4]
            self._internal_set_property("set-initial-position", (event.data[0] & 0x100) or (event.data[0] & 0x200))
            #honour hints:
            hints = self.get_property("size-hints")
            w, h = self.calc_constrained_size(w, h, hints)
            geomlog("_NET_MOVERESIZE_WINDOW on %s (data=%s, current geometry=%s, new geometry=%s)",
                    self, event.data, geom, (x,y,w,h))
            with xswallow:
                X11Window.configureAndNotify(self.xid, x, y, w, h)
            return True
        return BaseWindowModel.process_client_message_event(self, event)

    def calc_constrained_size(self, w, h, hints):
        mhints = typedict(hints)
        cw, ch = calc_constrained_size(w, h, mhints)
        geomlog("calc_constrained_size%s=%s (size_constraints=%s)", (w, h, mhints), (cw, ch), self.size_constraints)
        return cw, ch

    def update_size_constraints(self, minw=0, minh=0, maxw=MAX_WINDOW_SIZE, maxh=MAX_WINDOW_SIZE):
        if self.size_constraints==(minw, minh, maxw, maxh):
            geomlog("update_size_constraints%s unchanged", (minw, minh, maxw, maxh))
            return  #no need to do anything
        ominw, ominh, omaxw, omaxh = self.size_constraints
        self.size_constraints = minw, minh, maxw, maxh
        if minw<=ominw and minh<=ominh and maxw>=omaxw and maxh>=omaxh:
            geomlog("update_size_constraints%s less restrictive, no need to recalculate", (minw, minh, maxw, maxh))
            return
        geomlog("update_size_constraints%s recalculating client geometry", (minw, minh, maxw, maxh))
        self._update_client_geometry()

    #########################################
    # X11 properties synced to Python objects
    #########################################

    def _handle_icon_title_change(self):
        icon_name = self.prop_get("_NET_WM_ICON_NAME", "utf8", True)
        iconlog("_NET_WM_ICON_NAME=%s", icon_name)
        if icon_name is None:
            icon_name = self.prop_get("WM_ICON_NAME", "latin1", True)
            iconlog("WM_ICON_NAME=%s", icon_name)
        self._updateprop("icon-title", sanestr(icon_name))

    def _handle_motif_wm_hints_change(self):
        #motif_hints = self.prop_get("_MOTIF_WM_HINTS", "motif-hints")
        motif_hints = prop_get(self.client_window, "_MOTIF_WM_HINTS", "motif-hints",
                               ignore_errors=False, raise_xerrors=True)
        metalog("_MOTIF_WM_HINTS=%s", motif_hints)
        if motif_hints:
            if motif_hints.flags & (2**MotifWMHints.DECORATIONS_BIT):
                if self._updateprop("decorations", motif_hints.decorations):
                    #we may need to clamp the window size:
                    self._handle_wm_normal_hints_change()
            if motif_hints.flags & (2**MotifWMHints.INPUT_MODE_BIT):
                self._updateprop("modal", int(motif_hints.input_mode))


    def _handle_wm_normal_hints_change(self):
        with xswallow:
            size_hints = X11Window.getSizeHints(self.xid)
        metalog("WM_NORMAL_HINTS=%s", size_hints)
        #getSizeHints exports fields using their X11 names as defined in the "XSizeHints" structure,
        #but we use a different naming (for historical reason and backwards compatibility)
        #so rename the fields:
        hints = {}
        if size_hints:
            TRANSLATED_NAMES = {
                "position"          : "position",
                "size"              : "size",
                "base_size"         : "base-size",
                "resize_inc"        : "increment",
                "win_gravity"       : "gravity",
                "min_aspect_ratio"  : "minimum-aspect-ratio",
                "max_aspect_ratio"  : "maximum-aspect-ratio",
                }
            for k,v in size_hints.items():
                trans_name = TRANSLATED_NAMES.get(k)
                if trans_name:
                    hints[trans_name] = v
        #handle min-size and max-size,
        #applying our size constraints if we have any:
        mhints = typedict(size_hints or {})
        hminw, hminh = mhints.intlistget("min_size", (0, 0), 2, 2)
        hmaxw, hmaxh = mhints.intlistget("max_size", (MAX_WINDOW_SIZE, MAX_WINDOW_SIZE), 2, 2)
        d = self.get("decorations", -1)
        decorated = d==-1 or any((d & 2**b) for b in (
            MotifWMHints.ALL_BIT,
            MotifWMHints.TITLE_BIT,
            MotifWMHints.MINIMIZE_BIT,
            MotifWMHints.MAXIMIZE_BIT,
            ))
        cminw, cminh, cmaxw, cmaxh = self.size_constraints
        if decorated:
            #min-size only applies to decorated windows
            if cminw>0 and cminw>hminw:
                hminw = cminw
            if cminh>0 and cminh>hminh:
                hminh = cminh
        #max-size applies to all windows:
        if 0<cmaxw<hmaxw:
            hmaxw = cmaxw
        if 0<cmaxh<hmaxh:
            hmaxh = cmaxh
        #if the values mean something, expose them:
        if hminw>0 or hminw>0:
            hints["minimum-size"] = hminw, hminh
        if hmaxw<MAX_WINDOW_SIZE or hmaxh<MAX_WINDOW_SIZE:
            hints["maximum-size"] = hmaxw, hmaxh
        sanitize_size_hints(hints)
        #we don't use the "size" attribute for anything yet,
        #and changes to this property could send us into a loop
        try:
            del hints["size"]
        except KeyError:
            pass
        # Don't send out notify and ConfigureNotify events when this property
        # gets no-op updated -- some apps like FSF Emacs 21 like to update
        # their properties every time they see a ConfigureNotify, and this
        # reduces the chance for us to get caught in loops:
        if self._updateprop("size-hints", hints):
            metalog("updated: size-hints=%s", hints)
            if self._setup_done:
                self._update_client_geometry()


    def _handle_net_wm_icon_change(self):
        iconlog("_NET_WM_ICON changed on %#x, re-reading", self.xid)
        icons = self.prop_get("_NET_WM_ICON", "icons")
        self._internal_set_property("icons", icons)

    _x11_property_handlers = dict(BaseWindowModel._x11_property_handlers)
    _x11_property_handlers.update({
        "WM_ICON_NAME"                  : _handle_icon_title_change,
        "_NET_WM_ICON_NAME"             : _handle_icon_title_change,
        "_MOTIF_WM_HINTS"               : _handle_motif_wm_hints_change,
        "WM_NORMAL_HINTS"               : _handle_wm_normal_hints_change,
        "_NET_WM_ICON"                  : _handle_net_wm_icon_change,
       })


    def get_default_window_icon(self, size=48):
        #return the icon which would be used from the wmclass
        c_i = self.get_property("class-instance")
        iconlog("get_default_window_icon(%i) class-instance=%s", size, c_i)
        if not c_i or len(c_i)!=2:
            return None
        wmclass_name = c_i[0]
        if not wmclass_name:
            return None
        it = icon_theme_get_default()
        pixbuf = None
        iconlog("get_default_window_icon(%i) icon theme=%s, wmclass_name=%s", size, it, wmclass_name)
        for icon_name in (
            "%s-color" % wmclass_name,
            wmclass_name,
            "%s_%ix%i" % (wmclass_name, size, size),
            "application-x-%s" % wmclass_name,
            "%s-symbolic" % wmclass_name,
            "%s.symbolic" % wmclass_name,
            ):
            i = it.lookup_icon(icon_name, size, 0)
            iconlog("lookup_icon(%s)=%s", icon_name, i)
            if not i:
                continue
            try:
                pixbuf = i.load_icon()
                iconlog("load_icon()=%s", pixbuf)
                if pixbuf:
                    w, h = pixbuf.props.width, pixbuf.props.height
                    iconlog("using '%s' pixbuf %ix%i", icon_name, w, h)
                    return w, h, "RGBA", pixbuf.get_pixels()
            except Exception:
                iconlog("%s.load_icon()", i, exc_info=True)
        return None

    def get_wm_state(self, prop):
        state_names = self._state_properties.get(prop)
        assert state_names, "invalid window state %s" % prop
        log("get_wm_state(%s) state_names=%s", prop, state_names)
        #this is a virtual property for _NET_WM_STATE:
        #return True if any is set (only relevant for maximized)
        for x in state_names:
            if self._state_isset(x):
                return True
        return False


    ################################
    # Focus handling:
    ################################

    def give_client_focus(self):
        """The focus manager has decided that our client should receive X
        focus.  See world_window.py for details."""
        if self.corral_window:
            with xswallow:
                self.do_give_client_focus()

    def do_give_client_focus(self):
        focuslog("Giving focus to %#x", self.xid)
        # Have to fetch the time, not just use CurrentTime, both because ICCCM
        # says that WM_TAKE_FOCUS must use a real time and because there are
        # genuine race conditions here (e.g. suppose the client does not
        # actually get around to requesting the focus until after we have
        # already changed our mind and decided to give it to someone else).
        now = x11_get_server_time(self.corral_window)
        # ICCCM 4.1.7 *claims* to describe how we are supposed to give focus
        # to a window, but it is completely opaque.  From reading the
        # metacity, kwin, gtk+, and qt code, it appears that the actual rules
        # for giving focus are:
        #   -- the WM_HINTS input field determines whether the WM should call
        #      XSetInputFocus
        #   -- independently, the WM_TAKE_FOCUS protocol determines whether
        #      the WM should send a WM_TAKE_FOCUS ClientMessage.
        # If both are set, both methods MUST be used together. For example,
        # GTK+ apps respect WM_TAKE_FOCUS alone but I'm not sure they handle
        # XSetInputFocus well, while Qt apps ignore (!!!) WM_TAKE_FOCUS
        # (unless they have a modal window), and just expect to get focus from
        # the WM's XSetInputFocus.
        if bool(self._input_field) or FORCE_XSETINPUTFOCUS:
            focuslog("... using XSetInputFocus")
            X11Window.XSetInputFocus(self.xid, now)
        if "WM_TAKE_FOCUS" in self.get_property("protocols"):
            focuslog("... using WM_TAKE_FOCUS")
            send_wm_take_focus(self.client_window, now)
        self.set_active()


gobject.type_register(WindowModel)
