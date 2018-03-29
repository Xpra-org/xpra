# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import glib
import gobject
from gtk import gdk
import signal

from xpra.util import envbool
from xpra.x11.common import Unmanageable
from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.gtk_common.gtk_util import get_xwindow
from xpra.gtk_common.error import XError, xsync, xswallow
from xpra.x11.bindings.window_bindings import X11WindowBindings, constants, SHAPE_KIND #@UnresolvedImport
from xpra.x11.gtk_x11.prop import prop_get, prop_set
from xpra.x11.gtk_x11.send_wm import send_wm_delete_window
from xpra.x11.gtk2.composite import CompositeHelper
from xpra.x11.gtk2.models.model_stub import WindowModelStub
from xpra.x11.gtk2.gdk_bindings import (
                add_event_receiver,                         #@UnresolvedImport
                remove_event_receiver,                      #@UnresolvedImport
               )

from xpra.log import Logger
log = Logger("x11", "window")
metalog = Logger("x11", "window", "metadata")
shapelog = Logger("x11", "window", "shape")
grablog = Logger("x11", "window", "grab")
framelog = Logger("x11", "window", "frame")
geomlog = Logger("x11", "window", "geometry")


X11Window = X11WindowBindings()
ADDMASK = gdk.STRUCTURE_MASK | gdk.PROPERTY_CHANGE_MASK | gdk.FOCUS_CHANGE_MASK | gdk.POINTER_MOTION_MASK

FORCE_QUIT = envbool("XPRA_FORCE_QUIT", True)
XSHAPE = envbool("XPRA_XSHAPE", True)


# grab stuff:
NotifyNormal        = constants["NotifyNormal"]
NotifyGrab          = constants["NotifyGrab"]
NotifyUngrab        = constants["NotifyUngrab"]
NotifyWhileGrabbed  = constants["NotifyWhileGrabbed"]
NotifyNonlinearVirtual = constants["NotifyNonlinearVirtual"]
GRAB_CONSTANTS = {
                  NotifyNormal          : "NotifyNormal",
                  NotifyGrab            : "NotifyGrab",
                  NotifyUngrab          : "NotifyUngrab",
                  NotifyWhileGrabbed    : "NotifyWhileGrabbed",
                 }
DETAIL_CONSTANTS    = {}
for x in ("NotifyAncestor", "NotifyVirtual", "NotifyInferior",
          "NotifyNonlinear", "NotifyNonlinearVirtual", "NotifyPointer",
          "NotifyPointerRoot", "NotifyDetailNone"):
    DETAIL_CONSTANTS[constants[x]] = x
grablog("pointer grab constants: %s", GRAB_CONSTANTS)
grablog("detail constants: %s", DETAIL_CONSTANTS)

#these properties are not handled, and we don't want to spam the log file
#whenever an app decides to change them:
PROPERTIES_IGNORED = os.environ.get("XPRA_X11_PROPERTIES_IGNORED", "_NET_WM_OPAQUE_REGION").split(",")
#make it easier to debug property changes, just add them here:
#ie: {"WM_PROTOCOLS" : ["atom"]}
X11_PROPERTIES_DEBUG = {}
PROPERTIES_DEBUG = [x.strip() for x in os.environ.get("XPRA_WINDOW_PROPERTIES_DEBUG", "").split(",")]


def sanestr(s):
    return (s or "").strip("\0").replace("\0", " ")


class CoreX11WindowModel(WindowModelStub):
    """
        The utility superclass for all GTK2 / X11 window models,
        it wraps an X11 window (the "client-window").
        Defines the common properties and signals,
        sets up the composite helper so we get the damage events.
        The x11_property_handlers sync X11 window properties into Python objects,
        the py_property_handlers do it in the other direction.
    """
    __common_properties__ = {
        #the actual X11 client window
        "client-window": (gobject.TYPE_PYOBJECT,
                "gtk.gdk.Window representing the client toplevel", "",
                gobject.PARAM_READABLE),
        #the X11 window id
        "xid": (gobject.TYPE_INT,
                "X11 window id", "",
                -1, 65535, -1,
                gobject.PARAM_READABLE),
        #FIXME: this is an ugly virtual property
        "geometry": (gobject.TYPE_PYOBJECT,
                "current coordinates (x, y, w, h, border) for the window", "",
                gobject.PARAM_READABLE),
        #bits per pixel
        "depth": (gobject.TYPE_INT,
                "window bit depth", "",
                -1, 64, -1,
                gobject.PARAM_READABLE),
        #if the window depth is 32 bit
        "has-alpha": (gobject.TYPE_BOOLEAN,
                "Does the window use transparency", "",
                False,
                gobject.PARAM_READABLE),
        #from WM_CLIENT_MACHINE
        "client-machine": (gobject.TYPE_PYOBJECT,
                "Host where client process is running", "",
                gobject.PARAM_READABLE),
        #from _NET_WM_PID
        "pid": (gobject.TYPE_INT,
                "PID of owning process", "",
                -1, 65535, -1,
                gobject.PARAM_READABLE),
        #from _NET_WM_NAME or WM_NAME
        "title": (gobject.TYPE_PYOBJECT,
                "Window title (unicode or None)", "",
                gobject.PARAM_READABLE),
        #from WM_WINDOW_ROLE
        "role" : (gobject.TYPE_PYOBJECT,
                "The window's role (ICCCM session management)", "",
                gobject.PARAM_READABLE),
        #from WM_PROTOCOLS via XGetWMProtocols
        "protocols": (gobject.TYPE_PYOBJECT,
                "Supported WM protocols", "",
                gobject.PARAM_READABLE),
        #from WM_COMMAND
        "command": (gobject.TYPE_PYOBJECT,
                "Command used to start or restart the client", "",
                gobject.PARAM_READABLE),
        #from WM_CLASS via getClassHint
        "class-instance": (gobject.TYPE_PYOBJECT,
                "Classic X 'class' and 'instance'", "",
                gobject.PARAM_READABLE),
        #ShapeNotify events will populate this using XShapeQueryExtents
        "shape": (gobject.TYPE_PYOBJECT,
                "Window XShape data", "",
                gobject.PARAM_READABLE),
        #synced to "_NET_FRAME_EXTENTS"
        "frame": (gobject.TYPE_PYOBJECT,
                "Size of the window frame, as per _NET_FRAME_EXTENTS", "",
                gobject.PARAM_READWRITE),
        #synced to "_NET_WM_ALLOWED_ACTIONS"
        "allowed-actions": (gobject.TYPE_PYOBJECT,
                "Supported WM actions", "",
                gobject.PARAM_READWRITE),
           }

    __common_signals__ = {
        #signals we emit:
        "unmanaged"                     : one_arg_signal,
        "raised"                        : one_arg_signal,
        "initiate-moveresize"           : one_arg_signal,
        "grab"                          : one_arg_signal,
        "ungrab"                        : one_arg_signal,
        "bell"                          : one_arg_signal,
        "client-contents-changed"       : one_arg_signal,
        "motion"                        : one_arg_signal,
        #x11 events we catch (and often re-emit as something else):
        "xpra-property-notify-event"    : one_arg_signal,
        "xpra-xkb-event"                : one_arg_signal,
        "xpra-shape-event"              : one_arg_signal,
        "xpra-configure-event"          : one_arg_signal,
        "xpra-unmap-event"              : one_arg_signal,
        "xpra-client-message-event"     : one_arg_signal,
        "xpra-focus-in-event"           : one_arg_signal,
        "xpra-focus-out-event"          : one_arg_signal,
        "xpra-motion-event"             : one_arg_signal,
        }

    #things that we expose:
    _property_names         = ["xid", "depth", "has-alpha", "client-machine", "pid", "title", "role", "command", "shape", "class-instance", "protocols"]
    #exposed and changing (should be watched for notify signals):
    _dynamic_property_names = ["title", "command", "shape", "class-instance", "protocols"]
    #should not be exported to the clients:
    _internal_property_names = ["frame", "allowed-actions"]
    _initial_x11_properties = ["_NET_WM_PID", "WM_CLIENT_MACHINE",
                               "WM_NAME", "_NET_WM_NAME",        #_NET_WM_NAME is redundant, as it calls the same handler as "WM_NAME"
                               "WM_PROTOCOLS", "WM_CLASS", "WM_WINDOW_ROLE"]
    _DEFAULT_NET_WM_ALLOWED_ACTIONS = []
    _MODELTYPE = "Core"
    _scrub_x11_properties       = [
                              "WM_STATE",
                              #"_NET_WM_STATE",    # "..it should leave the property in place when it is shutting down"
                              "_NET_FRAME_EXTENTS", "_NET_WM_ALLOWED_ACTIONS"]

    def __init__(self, client_window):
        log("new window %#x", client_window.xid)
        super(CoreX11WindowModel, self).__init__()
        self.xid = get_xwindow(client_window)
        self.client_window = client_window
        self.client_window_saved_events = self.client_window.get_events()
        self._composite = None
        self._damage_forward_handle = None
        self._setup_done = False
        self._kill_count = 0
        self._internal_set_property("client-window", client_window)


    #########################################
    # Setup and teardown
    #########################################

    def call_setup(self):
        """
            Call this method to prepare the window:
            * makes sure it still exists
              (by querying its geometry which may raise an XError)
            * setup composite redirection
            * calls setup
            The difficulty comes from X11 errors and synchronization:
            we want to catch errors and undo what we've done.
            The mix of GTK and pure-X11 calls is not helping.
        """
        try:
            with xsync:
                geom = X11Window.geometry_with_border(self.xid)
                if geom is None:
                    raise Unmanageable("window %#x disappeared already" % self.xid)
                self._internal_set_property("geometry", geom[:4])
                self._read_initial_X11_properties()
        except XError as e:
            raise Unmanageable(e)
        add_event_receiver(self.client_window, self)
        # Keith Packard says that composite state is undefined following a
        # reparent, so I'm not sure doing this here in the superclass,
        # before we reparent, actually works... let's wait and see.
        try:
            self._composite = CompositeHelper(self.client_window)
            with xsync:
                self._composite.setup()
                if X11Window.displayHasXShape():
                    X11Window.XShapeSelectInput(self.xid)
        except Exception as e:
            remove_event_receiver(self.client_window, self)
            log("%s %#x does not support compositing: %s", self._MODELTYPE, self.xid, e)
            with xswallow:
                self._composite.destroy()
            self._composite = None
            if isinstance(e, Unmanageable):
                raise
            raise Unmanageable(e)
        #compositing is now enabled,
        #from now on we must call setup_failed to clean things up
        self._managed = True
        try:
            with xsync:
                self.setup()
        except XError as e:
            try:
                with xsync:
                    self.setup_failed(e)
            except Exception as ex:
                log.error("error in cleanup handler: %s", ex)
            raise Unmanageable(e)
        self._setup_done = True

    def setup_failed(self, e):
        log("cannot manage %s %#x: %s", self._MODELTYPE, self.xid, e)
        self.do_unmanaged(False)

    def setup(self):
        # Start listening for important events.
        self.client_window.set_events(self.client_window_saved_events | ADDMASK)
        self._damage_forward_handle = self._composite.connect("contents-changed", self._forward_contents_changed)
        self._setup_property_sync()


    def unmanage(self, exiting=False):
        if self._managed:
            self.emit("unmanaged", exiting)

    def do_unmanaged(self, wm_exiting):
        if not self._managed:
            return
        self._managed = False
        log("%s.do_unmanaged(%s) damage_forward_handle=%s, composite=%s", self._MODELTYPE, wm_exiting, self._damage_forward_handle, self._composite)
        remove_event_receiver(self.client_window, self)
        glib.idle_add(self.managed_disconnect)
        if self._composite:
            if self._damage_forward_handle:
                self._composite.disconnect(self._damage_forward_handle)
                self._damage_forward_handle = None
            self._composite.destroy()
            self._composite = None
            self._scrub_x11()


    #########################################
    # Damage / Composite
    #########################################

    def acknowledge_changes(self):
        c = self._composite
        assert c, "composite window destroyed outside the UI thread?"
        c.acknowledge_changes()

    def _forward_contents_changed(self, _obj, event):
        if self._managed:
            self.emit("client-contents-changed", event)

    def uses_XShm(self):
        c = self._composite
        return c and c.get_xshm_handle() is not None

    def get_image(self, x, y, width, height):
        return self._composite.get_image(x, y, width, height)


    def _setup_property_sync(self):
        metalog("setup_property_sync()")
        #python properties which trigger an X11 property to be updated:
        for prop, cb in self._py_property_handlers.items():
            self.connect("notify::%s" % prop, cb)
        #initial sync:
        for cb in self._py_property_handlers.values():
            cb(self)
        #this one is special, and overriden in BaseWindow too:
        self.managed_connect("notify::protocols", self._update_can_focus)

    def _update_can_focus(self, *_args):
        can_focus = "WM_TAKE_FOCUS" in self.get_property("protocols")
        self._updateprop("can-focus", can_focus)

    def _read_initial_X11_properties(self):
        """ This is called within an XSync context,
            so that X11 calls can raise XErrors,
            pure GTK calls are not allowed. (they would trap the X11 error and crash!)
            Calling _updateprop is safe, because setup has not completed yet,
            so the property update will not fire notify()
        """
        metalog("read_initial_X11_properties() core")
        #immutable ones:
        depth = X11Window.get_depth(self.xid)
        metalog("initial X11 properties: xid=%#x, depth=%i", self.xid, depth)
        self._updateprop("depth", depth)
        self._updateprop("xid", self.xid)
        self._updateprop("has-alpha", depth==32)
        self._updateprop("allowed-actions", self._DEFAULT_NET_WM_ALLOWED_ACTIONS)
        self._updateprop("shape", self._read_xshape())
        #note: some of those are technically mutable,
        #but we don't export them as "dynamic" properties, so this won't be propagated
        #maybe we want to catch errors parsing _NET_WM_ICON ?
        metalog("initial X11_properties: querying %s", self._initial_x11_properties)
        #to make sure we don't call the same handler twice which is pointless
        #(the same handler may handle more than one X11 property)
        handlers = set()
        for mutable in self._initial_x11_properties:
            handler = self._x11_property_handlers.get(mutable)
            if not handler:
                log.error("BUG: unknown initial X11 property: %s", mutable)
            elif handler not in handlers:
                handlers.add(handler)
                handler(self)

    def _scrub_x11(self):
        metalog("scrub_x11() x11 properties=%s", self._scrub_x11_properties)
        if not self._scrub_x11_properties:
            return
        with xswallow:
            for prop in self._scrub_x11_properties:
                X11Window.XDeleteProperty(self.xid, prop)


    #########################################
    # XShape
    #########################################

    def _read_xshape(self, x=0, y=0):
        if not X11Window.displayHasXShape() or not XSHAPE:
            return {}
        extents = X11Window.XShapeQueryExtents(self.xid)
        if not extents:
            shapelog("read_shape for window %#x: no extents", self.xid)
            return {}
        #w,h = X11Window.getGeometry(xid)[2:4]
        shapelog("read_shape for window %#x: extents=%s", self.xid, extents)
        bextents = extents[0]
        cextents = extents[1]
        if bextents[0]==0 and cextents[0]==0:
            shapelog("read_shape for window %#x: none enabled", self.xid)
            return {}
        v = {
             "x"                : x,
             "y"                : y,
             "Bounding.extents" : bextents,
             "Clip.extents"     : cextents,
             }
        for kind in SHAPE_KIND.keys():
            kind_name = SHAPE_KIND[kind]
            rectangles = X11Window.XShapeGetRectangles(self.xid, kind)
            v[kind_name+".rectangles"] = rectangles
        shapelog("_read_shape()=%s", v)
        return v


    ################################
    # Property reading
    ################################

    def get_dimensions(self):
        #just extracts the size from the geometry:
        return self.get_property("geometry")[2:4]

    def get_geometry(self):
        return self.get_property("geometry")[:4]


    #########################################
    # Python objects synced to X11 properties
    #########################################

    def prop_set(self, key, ptype, value):
        prop_set(self.client_window, key, ptype, value)


    def _sync_allowed_actions(self, *_args):
        actions = self.get_property("allowed-actions") or []
        metalog("sync_allowed_actions: setting _NET_WM_ALLOWED_ACTIONS=%s on %#x", actions, self.xid)
        with xswallow:
            prop_set(self.client_window, "_NET_WM_ALLOWED_ACTIONS", ["atom"], actions)
    def _handle_frame_changed(self, *_args):
        #legacy name for _sync_frame() called from Wm
        self._sync_frame()
    def _sync_frame(self, *_args):
        v = self.get_property("frame")
        framelog("sync_frame: frame(%#x)=%s", self.xid, v)
        if not v and (not self.is_OR() and not self.is_tray()):
            root = self.client_window.get_screen().get_root_window()
            v = prop_get(root, "DEFAULT_NET_FRAME_EXTENTS", ["u32"], ignore_errors=True)
        if not v:
            #default for OR, or if we don't have any other value:
            v = (0, 0, 0, 0)
        framelog("sync_frame: setting _NET_FRAME_EXTENTS=%s on %#x", v, self.xid)
        with xswallow:
            prop_set(self.client_window, "_NET_FRAME_EXTENTS", ["u32"], v)

    _py_property_handlers = {
        "allowed-actions"    : _sync_allowed_actions,
        "frame"              : _sync_frame,
        }


    #########################################
    # X11 properties synced to Python objects
    #########################################

    def prop_get(self, key, ptype, ignore_errors=None, raise_xerrors=False):
        """
            Get an X11 property from the client window,
            using the automatic type conversion code from prop.py
            Ignores property errors during setup_client.
        """
        if ignore_errors is None and (not self._setup_done or not self._managed):
            ignore_errors = True
        return prop_get(self.client_window, key, ptype, ignore_errors=bool(ignore_errors), raise_xerrors=raise_xerrors)


    def do_xpra_property_notify_event(self, event):
        #X11: PropertyNotify
        assert event.window is self.client_window
        self._handle_property_change(str(event.atom))

    def _handle_property_change(self, name):
        #ie: _handle_property_change("_NET_WM_NAME")
        metalog("Property changed on %#x: %s", self.xid, name)
        x11proptype = X11_PROPERTIES_DEBUG.get(name)
        if x11proptype is not None:
            metalog.info("%s=%s", name, self.prop_get(name, x11proptype, True, False))
        if name in PROPERTIES_IGNORED:
            return
        handler = self._x11_property_handlers.get(name)
        if handler:
            handler(self)

    #specific properties:
    def _handle_pid_change(self):
        pid = self.prop_get("_NET_WM_PID", "u32") or -1
        metalog("_NET_WM_PID=%s", pid)
        self._updateprop("pid", pid)

    def _handle_client_machine_change(self):
        client_machine = self.prop_get("WM_CLIENT_MACHINE", "latin1")
        metalog("WM_CLIENT_MACHINE=%s", client_machine)
        self._updateprop("client-machine", client_machine)

    def _handle_wm_name_change(self):
        name = self.prop_get("_NET_WM_NAME", "utf8", True)
        metalog("_NET_WM_NAME=%s", name)
        if name is None:
            name = self.prop_get("WM_NAME", "latin1", True)
            metalog("WM_NAME=%s", name)
        if self._updateprop("title", sanestr(name)):
            metalog("wm_name changed")

    def _handle_role_change(self):
        role = self.prop_get("WM_WINDOW_ROLE", "latin1")
        metalog("WM_WINDOW_ROLE=%s", role)
        self._updateprop("role", role)

    def _handle_protocols_change(self):
        with xsync:
            protocols = X11Window.XGetWMProtocols(self.xid)
        metalog("WM_PROTOCOLS=%s", protocols)
        self._updateprop("protocols", protocols)

    def _handle_command_change(self):
        command = self.prop_get("WM_COMMAND", "latin1")
        metalog("WM_COMMAND=%s", command)
        if command:
            command = command.strip("\0")
        self._updateprop("command", command)

    def _handle_class_change(self):
        with xswallow:
            class_instance = X11Window.getClassHint(self.xid)
            metalog("WM_CLASS=%s", class_instance)
            self._updateprop("class-instance", class_instance)

    #these handlers must not generate X11 errors (must use XSync)
    _x11_property_handlers = {
        "_NET_WM_PID"       : _handle_pid_change,
        "WM_CLIENT_MACHINE" : _handle_client_machine_change,
        "WM_NAME"           : _handle_wm_name_change,
        "_NET_WM_NAME"      : _handle_wm_name_change,
        "WM_WINDOW_ROLE"    : _handle_role_change,
        "WM_PROTOCOLS"      : _handle_protocols_change,
        "WM_COMMAND"        : _handle_command_change,
        "WM_CLASS"          : _handle_class_change,
        }


    #########################################
    # X11 Events
    #########################################

    def do_xpra_unmap_event(self, _event):
        self.unmanage()

    def do_xpra_destroy_event(self, event):
        if event.delivered_to is self.client_window:
            # This is somewhat redundant with the unmap signal, because if you
            # destroy a mapped window, then a UnmapNotify is always generated.
            # However, this allows us to catch the destruction of unmapped
            # ("iconified") windows, and also catch any mistakes we might have
            # made with unmap heuristics.  I love the smell of XDestroyWindow in
            # the morning.  It makes for simple code:
            self.unmanage()


    def process_client_message_event(self, event):
        # FIXME
        # Need to listen for:
        #   _NET_CURRENT_DESKTOP
        #   _NET_WM_PING responses
        # and maybe:
        #   _NET_RESTACK_WINDOW
        #   _NET_WM_STATE (more fully)
        if event.message_type=="_NET_CLOSE_WINDOW":
            log.info("_NET_CLOSE_WINDOW received by %s", self)
            self.request_close()
            return True
        elif event.message_type=="_NET_REQUEST_FRAME_EXTENTS":
            framelog("_NET_REQUEST_FRAME_EXTENTS")
            self._handle_frame_changed()
            return True
        elif event.message_type=="_NET_MOVERESIZE_WINDOW":
            #this is overriden in WindowModel, skipped everywhere else:
            geomlog("_NET_MOVERESIZE_WINDOW skipped on %s (data=%s)", self, event.data)
            return True
        #not handled:
        return False

    def do_xpra_configure_event(self, event):
        if self.client_window is None or not self._managed:
            return
        #shouldn't the border width always be 0?
        geom = (event.x, event.y, event.width, event.height)
        geomlog("CoreX11WindowModel.do_xpra_configure_event(%s) client_window=%#x, new geometry=%s", event, self.xid, geom)
        self._updateprop("geometry", geom)


    def do_xpra_shape_event(self, event):
        shapelog("shape event: %s, kind=%s", event, SHAPE_KIND.get(event.kind, event.kind))
        cur_shape = self.get_property("shape")
        if cur_shape and cur_shape.get("serial", 0)>=event.serial:
            shapelog("same or older xshape serial no: %#x (current=%#x)", event.serial, cur_shape.get("serial", 0))
            return
        #remove serial before comparing dicts:
        try:
            cur_shape["serial"]
        except:
            pass
        #read new xshape:
        with xswallow:
            #should we pass the x and y offsets here?
            #v = self._read_xshape(event.x, event.y)
            if event.shaped:
                v = self._read_xshape()
            else:
                v = {}
            if cur_shape==v:
                shapelog("xshape unchanged")
                return
            v["serial"] = int(event.serial)
            shapelog("xshape updated with serial %#x", event.serial)
            self._internal_set_property("shape", v)


    def do_xpra_xkb_event(self, event):
        #X11: XKBNotify
        log("WindowModel.do_xpra_xkb_event(%r)" % event)
        if event.subtype!="bell":
            log.error("WindowModel.do_xpra_xkb_event(%r) unknown event type: %s" % (event, event.type))
            return
        event.window_model = self
        self.emit("bell", event)

    def do_xpra_client_message_event(self, event):
        #X11: ClientMessage
        log("do_xpra_client_message_event(%s)", event)
        if not event.data or len(event.data)!=5:
            log.warn("invalid event data: %s", event.data)
            return
        if not self.process_client_message_event(event):
            log.warn("do_xpra_client_message_event(%s) not handled", event)


    def do_xpra_focus_in_event(self, event):
        #X11: FocusIn
        grablog("focus_in_event(%s) mode=%s, detail=%s",
            event, GRAB_CONSTANTS.get(event.mode), DETAIL_CONSTANTS.get(event.detail, event.detail))
        if event.mode==NotifyNormal and event.detail==NotifyNonlinearVirtual:
            self.emit("raised", event)
        else:
            self.may_emit_grab(event)

    def do_xpra_focus_out_event(self, event):
        #X11: FocusOut
        grablog("focus_out_event(%s) mode=%s, detail=%s",
            event, GRAB_CONSTANTS.get(event.mode), DETAIL_CONSTANTS.get(event.detail, event.detail))
        self.may_emit_grab(event)

    def may_emit_grab(self, event):
        if event.mode==NotifyGrab:
            grablog("emitting grab on %s", self)
            self.emit("grab", event)
        if event.mode==NotifyUngrab:
            grablog("emitting ungrab on %s", self)
            self.emit("ungrab", event)


    def do_xpra_motion_event(self, event):
        self.emit("motion", event)


    ################################
    # Actions
    ################################

    def raise_window(self):
        self.client_window.raise_()

    def set_active(self):
        root = self.client_window.get_screen().get_root_window()
        prop_set(root, "_NET_ACTIVE_WINDOW", "u32", self.xid)


    ################################
    # Killing clients:
    ################################

    def request_close(self):
        if "WM_DELETE_WINDOW" in self.get_property("protocols"):
            with xswallow:
                send_wm_delete_window(self.client_window)
        else:
            title = self.get_property("title")
            xid = self.get_property("xid")
            if FORCE_QUIT:
                log.warn("window %#x ('%s') does not support WM_DELETE_WINDOW... using force_quit", xid, title)
                # You don't wanna play ball?  Then no more Mr. Nice Guy!
                self.force_quit()
            else:
                log.warn("window %#x ('%s') cannot be closed,", xid, title)
                log.warn(" it does not support WM_DELETE_WINDOW")
                log.warn(" and FORCE_QUIT is disabled")

    def force_quit(self):
        pid = self.get_property("pid")
        machine = self.get_property("client-machine")
        from socket import gethostname
        localhost = gethostname()
        log("force_quit() pid=%s, machine=%s, localhost=%s", pid, machine, localhost)
        def XKill():
            with xswallow:
                X11Window.XKillClient(self.xid)
        if pid > 0 and machine is not None and machine == localhost:
            if pid==os.getpid():
                log.warn("force_quit() refusing to kill ourselves!")
                return
            if self._kill_count==0:
                #first time around: just send a SIGINT and hope for the best
                try:
                    os.kill(pid, signal.SIGINT)
                except OSError:
                    log.warn("failed to kill(SIGINT) client with pid %s", pid)
            else:
                #the more brutal way: SIGKILL + XKill
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    log.warn("failed to kill(SIGKILL) client with pid %s", pid)
                XKill()
            self._kill_count += 1
            return
        XKill()
