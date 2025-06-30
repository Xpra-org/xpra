# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
from socket import gethostname
from typing import Any, Final
from collections.abc import Callable, Sequence

from xpra.os_util import gi_import
from xpra.util.env import envbool, envint, first_time
from xpra.util.io import get_proc_cmdline
from xpra.x11.common import Unmanageable
from xpra.gtk.gobject import one_arg_signal, n_arg_signal
from xpra.gtk.error import XError, xsync, xswallow, xlog
from xpra.codecs.image import ImageWrapper
from xpra.platform.posix.proc import get_parent_pid
from xpra.x11.bindings.window import X11WindowBindings, constants, SHAPE_KIND
from xpra.x11.bindings.res import ResBindings
from xpra.x11.bindings.send_wm import send_wm_delete_window
from xpra.x11.models.model_stub import WindowModelStub
from xpra.x11.gtk.composite import CompositeHelper
from xpra.x11.gtk.prop import prop_get, prop_set, prop_del, prop_type_get, PYTHON_TYPES
from xpra.x11.gtk.bindings import add_event_receiver, remove_event_receiver, get_pywindow
from xpra.log import Logger

log = Logger("x11", "window")
metalog = Logger("x11", "window", "metadata")
shapelog = Logger("x11", "window", "shape")
grablog = Logger("x11", "window", "grab")
framelog = Logger("x11", "window", "frame")
geomlog = Logger("x11", "window", "geometry")

GObject = gi_import("GObject")
GLib = gi_import("GLib")

X11Window = X11WindowBindings()

XRes = ResBindings()
if not XRes.check_xres():
    log.warn("Warning: X Resource Extension missing or too old")
    XRes = None

if get_parent_pid is None:
    log("proc.get_parent_pid is not available")

FORCE_QUIT = envbool("XPRA_FORCE_QUIT", True)
XSHAPE = envbool("XPRA_XSHAPE", True)
FRAME_EXTENTS = envbool("XPRA_FRAME_EXTENTS", True)
OPAQUE_REGION = envbool("XPRA_OPAQUE_REGION", True)
DELETE_DESTROY = envbool("XPRA_DELETE_DESTROY", False)
DELETE_KILL_PID = envbool("XPRA_DELETE_KILL_PID", True)
DELETE_XKILL = envbool("XPRA_DELETE_XKILL", True)

CurrentTime: Final[int] = constants["CurrentTime"]

# Re-stacking:
Above = 0
Below = 1
TopIf = 2
BottomIf = 3
Opposite = 4
RESTACKING_STR: dict[int, str] = {
    Above: "Above",
    Below: "Below",
    TopIf: "TopIf",
    BottomIf: "BottomIf",
    Opposite: "Opposite",
}

# grab stuff:
NotifyNormal: Final[int] = constants["NotifyNormal"]
NotifyGrab: Final[int] = constants["NotifyGrab"]
NotifyUngrab: Final[int] = constants["NotifyUngrab"]
NotifyWhileGrabbed: Final[int] = constants["NotifyWhileGrabbed"]
NotifyNonlinearVirtual: Final[int] = constants["NotifyNonlinearVirtual"]
GRAB_CONSTANTS: dict[int, str] = {
    NotifyNormal: "NotifyNormal",
    NotifyGrab: "NotifyGrab",
    NotifyUngrab: "NotifyUngrab",
    NotifyWhileGrabbed: "NotifyWhileGrabbed",
}
DETAIL_CONSTANTS: dict[int, str] = {}
for dconst in (
        "NotifyAncestor", "NotifyVirtual", "NotifyInferior",
        "NotifyNonlinear", "NotifyNonlinearVirtual", "NotifyPointer",
        "NotifyPointerRoot", "NotifyDetailNone",
):
    DETAIL_CONSTANTS[constants[dconst]] = dconst
grablog("pointer grab constants: %s", GRAB_CONSTANTS)
grablog("detail constants: %s", DETAIL_CONSTANTS)

# these properties are not handled, and we don't want to spam the log file
# whenever an app decides to change them:
PROPERTIES_IGNORED = [x for x in os.environ.get("XPRA_X11_PROPERTIES_IGNORED", "").split(",") if x]
# make it easier to debug property changes, just add them here:
# ie: {"WM_PROTOCOLS" : ["atom"]}
X11_PROPERTIES_DEBUG: dict[str, Any] = {}
PROPERTIES_DEBUG = [
    prop_debug.strip()
    for prop_debug in os.environ.get("XPRA_WINDOW_PROPERTIES_DEBUG", "").split(",")
]
X11PROPERTY_SYNC = envbool("XPRA_X11PROPERTY_SYNC", True)
X11PROPERTY_SYNC_BLOCKLIST = os.environ.get("XPRA_X11PROPERTY_SYNC_BLOCKLIST",
                                            "_GTK,WM_,_NET,Xdnd").split(",")
SHAPE_DELAY = envint("XPRA_SHAPE_DELAY", 100)


def sanestr(s: str) -> str:
    return s.strip("\0").replace("\0", " ")


class CoreX11WindowModel(WindowModelStub):
    """
        The utility superclass for all GTK / X11 window models,
        it wraps an X11 window (the "client-window").
        Defines the common properties and signals,
        sets up the composite helper, so we get the damage events.
        The x11_property_handlers sync X11 window properties into Python objects,
        the py_property_handlers do it in the other direction.
    """
    __common_properties__ = {
        # the X11 window id
        "xid": (
            GObject.TYPE_INT,
            "X11 window id", "",
            -1, 65535, -1,
            GObject.ParamFlags.READABLE,
        ),
        "parent": (
            GObject.TYPE_PYOBJECT,
            "parent window id", "",
            GObject.ParamFlags.READABLE,
        ),
        # FIXME: this is an ugly virtual property
        "geometry": (
            GObject.TYPE_PYOBJECT,
            "current coordinates (x, y, w, h, border) for the window", "",
            GObject.ParamFlags.READABLE,
        ),
        # bits per pixel
        "depth": (
            GObject.TYPE_INT,
            "window bit depth", "",
            -1, 64, -1,
            GObject.ParamFlags.READABLE,
        ),
        # if the window depth is 32 bit
        "has-alpha": (
            GObject.TYPE_BOOLEAN,
            "Does the window use transparency", "",
            False,
            GObject.ParamFlags.READABLE,
        ),
        # from WM_CLIENT_MACHINE
        "client-machine": (
            GObject.TYPE_PYOBJECT,
            "Host where client process is running", "",
            GObject.ParamFlags.READABLE,
        ),
        # from XResGetClientPid
        "pid": (
            GObject.TYPE_INT,
            "PID of owning process", "",
            -1, 65535, -1,
            GObject.ParamFlags.READABLE,
        ),
        "ppid": (
            GObject.TYPE_INT,
            "PID of parent process", "",
            -1, 65535, -1,
            GObject.ParamFlags.READABLE,
        ),
        # from _NET_WM_PID
        "wm-pid": (
            GObject.TYPE_INT,
            "PID of owning process", "",
            -1, 65535, -1,
            GObject.ParamFlags.READABLE,
        ),
        # from _NET_WM_NAME or WM_NAME
        "title": (
            GObject.TYPE_PYOBJECT,
            "Window title (unicode or None)", "",
            GObject.ParamFlags.READABLE,
        ),
        # from WM_WINDOW_ROLE
        "role": (
            GObject.TYPE_PYOBJECT,
            "The window's role (ICCCM session management)", "",
            GObject.ParamFlags.READABLE,
        ),
        # from WM_PROTOCOLS via XGetWMProtocols
        "protocols": (
            GObject.TYPE_PYOBJECT,
            "Supported WM protocols", "",
            GObject.ParamFlags.READABLE,
        ),
        # from WM_COMMAND
        "command": (
            GObject.TYPE_PYOBJECT,
            "Command used to start or restart the client", "",
            GObject.ParamFlags.READABLE,
        ),
        # from WM_CLASS via getClassHint
        "class-instance": (
            GObject.TYPE_PYOBJECT,
            "Classic X 'class' and 'instance'", "",
            GObject.ParamFlags.READABLE,
        ),
        # ShapeNotify events will populate this using XShapeQueryExtents
        "shape": (
            GObject.TYPE_PYOBJECT,
            "Window XShape data", "",
            GObject.ParamFlags.READABLE,
        ),
        # synced to "_NET_FRAME_EXTENTS"
        "frame": (
            GObject.TYPE_PYOBJECT,
            "Size of the window frame, as per _NET_FRAME_EXTENTS", "",
            GObject.ParamFlags.READWRITE,
        ),
        # synced to "_NET_WM_ALLOWED_ACTIONS"
        "allowed-actions": (
            GObject.TYPE_PYOBJECT,
            "Supported WM actions", "",
            GObject.ParamFlags.READWRITE,
        ),
        # synced to "_NET_WM_OPAQUE_REGION"
        "opaque-region": (
            GObject.TYPE_PYOBJECT,
            "Compositor can assume that there is no transparency for this region", "",
            GObject.ParamFlags.READWRITE,
        ),
    }

    __common_signals__ = {
        # signals we emit:
        "unmanaged": one_arg_signal,
        "restack": n_arg_signal(2),
        "initiate-moveresize": one_arg_signal,
        "grab": one_arg_signal,
        "ungrab": one_arg_signal,
        "bell": one_arg_signal,
        "client-contents-changed": one_arg_signal,
        "motion": one_arg_signal,
        # x11 events we catch (and often re-emit as something else):
        "x11-property-notify-event": one_arg_signal,
        "x11-xkb-event": one_arg_signal,
        "x11-shape-event": one_arg_signal,
        "x11-configure-event": one_arg_signal,
        "x11-unmap-event": one_arg_signal,
        "x11-client-message-event": one_arg_signal,
        "x11-focus-in-event": one_arg_signal,
        "x11-focus-out-event": one_arg_signal,
        "x11-motion-event": one_arg_signal,
        "x11-property-changed": one_arg_signal,
    }

    # things that we expose:
    _property_names = [
        "xid", "depth", "has-alpha",
        "parent",
        "client-machine", "pid", "ppid", "wm-pid",
        "title", "role",
        "command", "shape",
        "class-instance", "protocols",
        "opaque-region",
    ]
    # exposed and changing (should be watched for notify signals):
    _dynamic_property_names = [
        "title", "command", "shape", "class-instance", "protocols", "opaque-region",
    ]
    # should not be exported to the clients:
    _internal_property_names = [
        "frame", "allowed-actions",
    ]
    _initial_x11_properties = [
        "_NET_WM_PID", "WM_CLIENT_MACHINE",
        # _NET_WM_NAME is redundant, as it calls the same handler as "WM_NAME"
        "WM_NAME", "_NET_WM_NAME",
        "WM_PROTOCOLS", "WM_CLASS", "WM_WINDOW_ROLE",
        "_NET_WM_OPAQUE_REGION",
        "WM_COMMAND",
    ]
    _DEFAULT_NET_WM_ALLOWED_ACTIONS: list[str] = []
    _MODELTYPE = "Core"
    _scrub_x11_properties = [
        "WM_STATE",
        # "_NET_WM_STATE",    # "..it should leave the property in place when it is shutting down"
        "_NET_FRAME_EXTENTS", "_NET_WM_ALLOWED_ACTIONS",
    ]

    def __init__(self, xid: int):
        super().__init__()
        if not isinstance(xid, int):
            raise TypeError(f"xid must be an int, not a {type(xid)}")
        log("new window %#x", xid)
        self.xid: int = xid
        self._composite: CompositeHelper | None = None
        self._damage_forward_handle = None
        self._setup_done = False
        self._kill_count = 0
        self._shape_timer = 0
        self._shape_timer_serial = 0

    def __repr__(self) -> str:  # pylint: disable=arguments-differ
        try:
            classname = type(self).__name__
            return f"{classname}({self.xid:x})"
        except AttributeError:
            return repr(self)

    #########################################
    # Setup and teardown
    #########################################

    def call_setup(self) -> None:
        """
            Call this method to prepare the window:
            * makes sure it still exists
              (by querying its geometry which may raise an XError)
            * setup composite redirection
            * calls `setup`
            The difficulty comes from X11 errors and synchronization:
            we want to catch errors and undo what we've done.
            The mix of GTK and pure-X11 calls is not helping.
        """
        try:
            with xsync:
                geom = X11Window.geometry_with_border(self.xid)
                if geom is None:
                    raise Unmanageable(f"window {self.xid:x} disappeared already")
                self._internal_set_property("geometry", geom[:4])
                self._read_initial_X11_properties()
        except XError as e:
            log("failed to manage %#x", self.xid, exc_info=True)
            raise Unmanageable(e) from e
        add_event_receiver(self.xid, self)
        # Keith Packard says that composite state is undefined following a
        # reparent, so I'm not sure doing this here in the superclass,
        # before we reparent, actually works... let's wait and see.
        try:
            self._composite = CompositeHelper(self.xid)
            with xsync:
                self._composite.setup()
                if X11Window.displayHasXShape():
                    X11Window.XShapeSelectInput(self.xid)
        except Exception as e:
            remove_event_receiver(self.xid, self)
            log("%s %#x does not support compositing: %s", self._MODELTYPE, self.xid, e)
            with xswallow:
                self._composite.destroy()
            self._composite = None
            if isinstance(e, Unmanageable):
                raise
            raise Unmanageable(e) from e
        # compositing is now enabled,
        # from now on we must call setup_failed to clean things up
        self._managed = True
        try:
            with xsync:
                self.setup()
        except XError as e:
            log("failed to setup %#x", self.xid, exc_info=True)
            try:
                with xsync:
                    self.setup_failed(e)
            except Exception:
                log.error(f"Error in cleanup handler for window {self.xid:x}", exc_info=True)
            raise Unmanageable(e) from None
        self._setup_done = True

    def setup_failed(self, e) -> None:
        log("cannot manage %s %#x: %s", self._MODELTYPE, self.xid, e)
        self.do_unmanaged(False)

    def setup(self) -> None:
        # Start listening for important events.
        X11Window.addDefaultEvents(self.xid)
        self._damage_forward_handle = self._composite.connect("contents-changed", self._forward_contents_changed)
        self._setup_property_sync()

    def unmanage(self, exiting=False) -> None:
        if self._managed:
            self.emit("unmanaged", exiting)

    def do_unmanaged(self, wm_exiting) -> None:
        if not self._managed:
            return
        self._managed = False
        log("%s.do_unmanaged(%s) damage_forward_handle=%s, composite=%s",
            self._MODELTYPE, wm_exiting, self._damage_forward_handle, self._composite)
        remove_event_receiver(self.xid, self)
        self.managed_disconnect()
        if self._composite:
            if self._damage_forward_handle:
                self._composite.disconnect(self._damage_forward_handle)
                self._damage_forward_handle = None
            self._composite.destroy()
            self._composite = None
            self._scrub_x11()
            self.xid = 0

    #########################################
    # Damage / Composite
    #########################################

    def acknowledge_changes(self) -> None:
        if not self._managed:
            return
        c = self._composite
        if not c:
            raise RuntimeError("composite window destroyed outside the UI thread?")
        c.acknowledge_changes()

    def _forward_contents_changed(self, _obj, event) -> None:
        if self._managed:
            self.emit("client-contents-changed", event)

    def uses_xshm(self) -> bool:
        c = self._composite
        return bool(c) and c.has_xshm()

    def get_image(self, x: int, y: int, width: int, height: int) -> ImageWrapper:
        return self._composite.get_image(x, y, width, height)

    def _setup_property_sync(self) -> None:
        metalog("setup_property_sync()")
        # python properties which trigger an X11 property to be updated:
        for prop, cb in self._py_property_handlers.items():
            self.connect(f"notify::{prop}", cb)
        # initial sync:
        for cb in self._py_property_handlers.values():
            cb(self)
        # this one is special, and overridden in BaseWindow too:
        self.managed_connect("notify::protocols", self._update_can_focus)

    def _update_can_focus(self, *_args) -> None:
        can_focus = "WM_TAKE_FOCUS" in self.get_property("protocols")
        self._updateprop("can-focus", can_focus)

    def _read_initial_X11_properties(self) -> None:
        """ This is called within an XSync context,
            so that X11 calls can raise XErrors,
            pure GTK calls are not allowed. (they would trap the X11 error and crash!)
            Calling _updateprop is safe, because setup has not completed yet,
            so the property update will not fire notify()
        """
        metalog("read_initial_X11_properties() core")
        # immutable ones:
        depth = X11Window.get_depth(self.xid)
        pid = XRes.get_pid(self.xid) if XRes else -1
        ppid = get_parent_pid(pid) if pid and get_parent_pid else 0
        parent = X11Window.getParent(self.xid)
        if parent == X11Window.get_root_xid():
            parent = 0
        metalog("initial X11 properties: xid=%#x, parent=%#x, depth=%i, pid=%i, ppid=%i",
                self.xid, parent, depth, pid, ppid)
        self._updateprop("depth", depth)
        self._updateprop("xid", self.xid)
        self._updateprop("pid", pid)
        self._updateprop("ppid", ppid)
        self._updateprop("has-alpha", depth == 32)
        self._updateprop("allowed-actions", self._DEFAULT_NET_WM_ALLOWED_ACTIONS)
        self._updateprop("shape", self._read_xshape())
        self._updateprop("parent", get_pywindow(parent))
        # note: some of those are technically mutable,
        # but we don't export them as "dynamic" properties, so this won't be propagated
        # maybe we want to catch errors parsing _NET_WM_ICON ?
        metalog("initial X11_properties: querying %s", self._initial_x11_properties)
        # to make sure we don't call the same handler twice which is pointless
        # (the same handler may handle more than one X11 property)
        handlers = set()
        for mutable in self._initial_x11_properties:
            handler = self._x11_property_handlers.get(mutable)
            if not handler:
                log.error(f"Error: unknown initial X11 property: {mutable!r}")
            elif handler not in handlers:
                handlers.add(handler)
                try:
                    handler(self)
                except XError:
                    log("handler %s failed", handler, exc_info=True)
                    # these will be caught in call_setup()
                    raise
                except Exception:
                    # try to continue:
                    log.error("Error parsing initial property {mutable!r}", exc_info=True)

    def _scrub_x11(self) -> None:
        metalog("scrub_x11() x11 properties=%s", self._scrub_x11_properties)
        if not self._scrub_x11_properties:
            return
        with xswallow:
            for prop in self._scrub_x11_properties:
                X11Window.XDeleteProperty(self.xid, prop)

    #########################################
    # XShape
    #########################################

    def read_xshape(self):
        shapelog("read_xshape()")
        self._shape_timer = 0
        cur_shape = self.get_property("shape") or {}
        # remove serial before comparing dicts:
        cur_shape.pop("serial", None)
        # read new xshape:
        with xlog:
            # should we pass the x and y offsets here?
            # v = self._read_xshape(event.x, event.y)
            v = self._read_xshape()
            if cur_shape == v:
                shapelog("xshape unchanged")
                return
            v["serial"] = int(self._shape_timer_serial)
            shapelog("xshape updated with serial %#x", self._shape_timer_serial)
            self._internal_set_property("shape", v)

    def _read_xshape(self, x: int = 0, y: int = 0) -> dict[str, Any]:
        if not X11Window.displayHasXShape() or not XSHAPE:
            return {}
        extents = X11Window.XShapeQueryExtents(self.xid)
        if not extents:
            shapelog("read_shape for window %#x: no extents", self.xid)
            return {}
        # w,h = X11Window.getGeometry(xid)[2:4]
        shapelog("read_shape for window %#x: extents=%s", self.xid, extents)
        bextents = extents[0]
        cextents = extents[1]
        if bextents[0] == 0 and cextents[0] == 0:
            shapelog("read_shape for window %#x: none enabled", self.xid)
            return {}
        v = {
            "x": x,
            "y": y,
            "Bounding.extents": bextents,
            "Clip.extents": cextents,
        }
        for kind, kind_name in SHAPE_KIND.items():  # @UndefinedVariable
            rectangles = X11Window.XShapeGetRectangles(self.xid, kind)
            v[kind_name + ".rectangles"] = rectangles
        shapelog("_read_shape()=%s", v)
        return v

    ################################
    # Property reading
    ################################

    def get_dimensions(self):
        # just extracts the size from the geometry:
        return self.get_property("geometry")[2:4]

    def get_geometry(self):
        return self.get_property("geometry")[:4]

    #########################################
    # Python objects synced to X11 properties
    #########################################

    def _sync_allowed_actions(self, *_args) -> None:
        actions = self.get_property("allowed-actions") or []
        metalog("sync_allowed_actions: setting _NET_WM_ALLOWED_ACTIONS=%s on %#x", actions, self.xid)
        with xswallow:
            self.prop_set("_NET_WM_ALLOWED_ACTIONS", ["atom"], actions)

    def _handle_frame_changed(self, *_args) -> None:
        # legacy name for _sync_frame() called from Wm
        self._sync_frame()

    def _sync_frame(self, *_args) -> None:
        if not FRAME_EXTENTS:
            return
        v = self.get_property("frame")
        framelog("sync_frame: frame(%#x)=%s", self.xid, v)
        if not v and (not self.is_OR() and not self.is_tray()):
            v = self.root_prop_get("DEFAULT_NET_FRAME_EXTENTS", ["u32"])
        if not v:
            # default for OR, or if we don't have any other value:
            v = (0, 0, 0, 0)
        framelog("sync_frame: setting _NET_FRAME_EXTENTS=%s on %#x", v, self.xid)
        with xswallow:
            self.prop_set("_NET_FRAME_EXTENTS", ["u32"], v)

    _py_property_handlers: dict[str, Callable] = {
        "allowed-actions": _sync_allowed_actions,
        "frame": _sync_frame,
    }

    #########################################
    # X11 properties synced to Python objects
    #########################################

    def prop_get(self, key, ptype, ignore_errors: bool | None = None, raise_xerrors=False) -> object:
        """
            Get an X11 property from the client window,
            using the automatic type conversion code from prop.py
            Ignores property errors during setup_client.
        """
        if ignore_errors is None and (not self._setup_done or not self._managed):
            ignore_errors = True
        return prop_get(self.xid, key, ptype, ignore_errors=bool(ignore_errors), raise_xerrors=raise_xerrors)

    def prop_del(self, key: str) -> None:
        prop_del(self.xid, key)

    def prop_set(self, key: str, ptype, value) -> None:
        prop_set(self.xid, key, ptype, value)

    def root_prop_get(self, key: str, ptype, ignore_errors=True) -> object:
        return prop_get(X11Window.get_root_xid(), key, ptype, ignore_errors=ignore_errors)

    def root_prop_set(self, key: str, ptype, value) -> None:
        prop_set(X11Window.get_root_xid(), key, ptype, value)

    def do_x11_property_notify_event(self, event) -> None:
        # X11: PropertyNotify
        assert event.window == self.xid
        self._handle_property_change(str(event.atom))

    def _handle_property_change(self, name: str) -> None:
        # ie: _handle_property_change("_NET_WM_NAME")
        metalog("Property changed on %#x: %s", self.xid, name)
        x11proptype = X11_PROPERTIES_DEBUG.get(name)
        if x11proptype is not None:
            metalog.info("%s=%s", name, self.prop_get(name, x11proptype, True, False))
        if name in PROPERTIES_IGNORED:
            return
        if X11PROPERTY_SYNC and not any(name.startswith(x) for x in X11PROPERTY_SYNC_BLOCKLIST):
            try:
                with xsync:
                    prop_type = prop_type_get(self.xid, name)
                    metalog("_handle_property_change(%s) property type=%s", name, prop_type)
                    if prop_type:
                        dtype, dformat = prop_type
                        ptype = PYTHON_TYPES.get(dtype, "")
                        if ptype:
                            value = self.prop_get(name, ptype, ignore_errors=True)
                            if value is None:
                                # retry using scalar type:
                                scalar = (ptype,)
                                value = self.prop_get(name, scalar, ignore_errors=True)
                            metalog("_handle_property_change(%s) value=%s", name, value)
                            if value is not None:
                                self.emit("x11-property-changed", (name, ptype, dformat, value))
                                return
            except Exception:
                metalog("_handle_property_change(%s)", name, exc_info=True)
            self.emit("x11-property-changed", (name, "", 0, ""))
        handler = self._x11_property_handlers.get(name)
        if handler:
            try:
                with xsync:
                    handler(self)
            except XError as e:
                log("_handle_property_change", exc_info=True)
                log.error("Error processing property change for '%s'", name)
                log.error(" on window %#x", self.xid)
                log.estr(e)

    # specific properties:
    def _handle_pid_change(self) -> None:
        pid = self.prop_get("_NET_WM_PID", "u32") or -1
        metalog("_NET_WM_PID=%s", pid)
        self._updateprop("wm-pid", pid)

    def _handle_client_machine_change(self) -> None:
        client_machine = self.prop_get("WM_CLIENT_MACHINE", "latin1") or ""
        metalog("WM_CLIENT_MACHINE=%s", client_machine)
        self._updateprop("client-machine", client_machine)

    def _handle_wm_name_change(self) -> None:
        name = self.prop_get("_NET_WM_NAME", "utf8", True)
        metalog("_NET_WM_NAME=%s", name)
        if name is None:
            name = self.prop_get("WM_NAME", "latin1", True) or ""
            metalog("WM_NAME=%s", name)
        if self._updateprop("title", sanestr(str(name) or "")):
            metalog("wm_name changed")

    def _handle_role_change(self) -> None:
        role = self.prop_get("WM_WINDOW_ROLE", "latin1") or ""
        metalog("WM_WINDOW_ROLE=%s", role)
        self._updateprop("role", role)

    def _handle_protocols_change(self) -> None:
        with xsync:
            protocols = X11Window.XGetWMProtocols(self.xid)
        metalog("WM_PROTOCOLS=%s", protocols)
        self._updateprop("protocols", protocols)

    def _handle_command_change(self) -> None:
        command = self.prop_get("WM_COMMAND", "latin1")
        metalog("WM_COMMAND=%s", command)
        if command:
            command = command.strip("\0")
        else:
            pid = self.get_property("pid")
            command = " ".join(get_proc_cmdline(pid))
        self._updateprop("command", command)

    def _handle_class_change(self) -> None:
        class_instance = X11Window.getClassHint(self.xid)
        if class_instance:
            class_instance = tuple(v.decode("latin1") for v in class_instance)
        metalog("WM_CLASS=%s", class_instance)
        self._updateprop("class-instance", class_instance or ())

    def _handle_opaque_region_change(self) -> None:
        rectangles = []
        v: Sequence[int] = tuple(self.prop_get("_NET_WM_OPAQUE_REGION", ["u32"]) or [])
        if OPAQUE_REGION and len(v) % 4 == 0:
            while v:
                rvalues = tuple((coord if coord < 2 ** 32 else -1) for coord in v[:4])
                rectangles.append(rvalues)
                v = v[4:]
        metalog("_NET_WM_OPAQUE_REGION(%s)=%s (OPAQUE_REGION=%s)", v, rectangles, OPAQUE_REGION)
        self._updateprop("opaque-region", tuple(rectangles))

    # these handlers must not generate X11 errors (must use XSync)
    _x11_property_handlers: dict[str, Callable] = {
        "_NET_WM_PID": _handle_pid_change,
        "WM_CLIENT_MACHINE": _handle_client_machine_change,
        "WM_NAME": _handle_wm_name_change,
        "_NET_WM_NAME": _handle_wm_name_change,
        "WM_WINDOW_ROLE": _handle_role_change,
        "WM_PROTOCOLS": _handle_protocols_change,
        "WM_COMMAND": _handle_command_change,
        "WM_CLASS": _handle_class_change,
        "_NET_WM_OPAQUE_REGION": _handle_opaque_region_change,
    }

    #########################################
    # X11 Events
    #########################################

    def do_x11_unmap_event(self, event) -> None:
        log("do_x11_unmap_event(%s) xid=%s, ", event, self.xid)
        self.unmanage()

    def do_x11_destroy_event(self, event) -> None:
        log("do_x11_destroy_event(%s) xid=%s, ", event, self.xid)
        if event.delivered_to == self.xid:
            # This is somewhat redundant with the unmap signal, because if you
            # destroy a mapped window, then a UnmapNotify is always generated.
            # However, this allows us to catch the destruction of unmapped
            # ("iconified") windows, and also catch any mistakes we might have
            # made with unmap heuristics.  I love the smell of XDestroyWindow in
            # the morning.  It makes for simple code:
            self.unmanage()

    def process_client_message_event(self, event) -> bool:
        # FIXME
        # Need to listen for:
        #   _NET_CURRENT_DESKTOP
        #   _NET_WM_PING responses
        # and maybe:
        #   _NET_RESTACK_WINDOW
        #   _NET_WM_STATE (more fully)
        if event.message_type == "_NET_CLOSE_WINDOW":
            log.info("_NET_CLOSE_WINDOW received by %s", self)
            self.request_close()
            return True
        if event.message_type == "_NET_REQUEST_FRAME_EXTENTS":
            framelog("_NET_REQUEST_FRAME_EXTENTS")
            self._handle_frame_changed()
            return True
        if event.message_type == "_NET_MOVERESIZE_WINDOW":
            # this is overridden in WindowModel, skipped everywhere else:
            geomlog("_NET_MOVERESIZE_WINDOW skipped on %s (data=%s)", self, event.data)
            return True
        if event.message_type == "":
            log("empty message type: %s", event)
            exid = event.window
            if first_time(f"empty-x11-window-message-type-{exid:x}"):
                log.warn(f"Warning: empty message type received for window {exid:x}")
                log.warn(" %s", event)
                log.warn(" further messages will be silently ignored")
            return True
        # not handled:
        return False

    def do_x11_configure_event(self, event) -> None:
        if not self._managed:
            return
        # shouldn't the border width always be 0?
        geom = (event.x, event.y, event.width, event.height)
        geomlog("CoreX11WindowModel.do_x11_configure_event(%s) xid=%#x, new geometry=%s",
                event, self.xid, geom)
        self._updateprop("geometry", geom)

    def do_x11_shape_event(self, event) -> None:
        shapelog("shape event: %s, kind=%s, timer=%s",
                 event, SHAPE_KIND.get(event.kind, event.kind), self._shape_timer)
        cur_shape = self.get_property("shape")
        if not event.shaped and not cur_shape:
            shapelog("no shape")
            return
        serial = event.serial
        if cur_shape and cur_shape.get("serial", 0) >= serial:
            shapelog("same or older xshape serial no: %#x (current=%#x)", serial, cur_shape.get("serial", 0))
            return
        if not self._shape_timer:
            self._shape_timer = GLib.timeout_add(SHAPE_DELAY, self.read_xshape)
        self._shape_timer_serial = max(self._shape_timer_serial, serial)

    def do_x11_xkb_event(self, event) -> None:
        # X11: XKBNotify
        log("WindowModel.do_x11_xkb_event(%r)", event)
        if event.subtype != "bell":
            log("WindowModel.do_x11_xkb_event(%r)", event, exc_info=True)
            log.error("Error: unknown xkb event type: %s", event.type)
            return
        event.window_model = self
        self.emit("bell", event)

    def do_x11_client_message_event(self, event) -> None:
        # X11: ClientMessage
        log("do_x11_client_message_event(%s)", event)
        if not event.data or len(event.data) != 5:
            log.warn("invalid event data: %s", event.data)
            return
        if not self.process_client_message_event(event):
            log.warn("do_x11_client_message_event(%s) not handled", event)

    def do_x11_focus_in_event(self, event) -> None:
        # X11: FocusIn
        grablog("focus_in_event(%s) mode=%s, detail=%s",
                event, GRAB_CONSTANTS.get(event.mode), DETAIL_CONSTANTS.get(event.detail, event.detail))
        if event.mode == NotifyNormal and event.detail == NotifyNonlinearVirtual:
            self.emit("restack", Above, 0)
        else:
            self.may_emit_grab(event)

    def do_x11_focus_out_event(self, event) -> None:
        # X11: FocusOut
        grablog("focus_out_event(%s) mode=%s, detail=%s",
                event, GRAB_CONSTANTS.get(event.mode), DETAIL_CONSTANTS.get(event.detail, event.detail))
        self.may_emit_grab(event)

    def may_emit_grab(self, event) -> None:
        if event.mode == NotifyGrab:
            grablog("emitting grab on %s", self)
            self.emit("grab", event)
        if event.mode == NotifyUngrab:
            grablog("emitting ungrab on %s", self)
            self.emit("ungrab", event)

    def do_x11_motion_event(self, event) -> None:
        self.emit("motion", event)

    ################################
    # Actions
    ################################

    def raise_window(self) -> None:
        X11Window.XRaiseWindow(self.xid)

    def set_active(self) -> None:
        self.root_prop_set("_NET_ACTIVE_WINDOW", "u32", self.xid)

    ################################
    # Killing clients:
    ################################

    def request_close(self) -> bool:
        if "WM_DELETE_WINDOW" in self.get_property("protocols"):
            self.send_delete()
            return True
        title = self.get_property("title")
        xid = self.get_property("xid")
        if FORCE_QUIT:
            log.info("window %#x ('%s') does not support WM_DELETE_WINDOW", xid, title)
            log.info(" using force quit")
            # You don't want to play ball?  Then no more Mr. Nice Guy!
            self.force_quit()
            return True
        log.warn("window %#x ('%s') cannot be closed,", xid, title)
        log.warn(" it does not support WM_DELETE_WINDOW")
        log.warn(" and FORCE_QUIT is disabled")
        return False

    def send_delete(self) -> None:
        with xswallow:
            now = X11Window.get_server_time(self.xid)
            send_wm_delete_window(self.xid, timestamp=now)

    def XKill(self) -> None:
        with xswallow:
            X11Window.XKillClient(self.xid)

    def force_quit(self) -> None:
        if DELETE_DESTROY:
            with xlog:
                X11Window.DestroyWindow(self.xid)
                return
        machine = self.get_property("client-machine")
        pid = self.get_property("pid")
        if pid <= 0:
            # we could fall back to _NET_WM_PID
            # but that would be unsafe
            log.warn("Warning: cannot terminate window %#x, no pid found", self.xid)
            if machine:
                log.warn(" WM_CLIENT_MACHINE=%s", machine)
            pid = self.get_property("wm-pid")
            if pid > 0:
                log.warn(" _NET_WM_PID=%s", pid)
        if pid == os.getpid():
            log.warn("Warning: force_quit is refusing to kill ourselves!")
            return
        localhost = gethostname()
        log("force_quit() pid=%s, machine=%s, localhost=%s", pid, machine, localhost)
        if DELETE_KILL_PID and pid and machine is not None and machine == localhost:
            if self._kill_count == 0:
                # first time around: just send a SIGINT and hope for the best
                try:
                    os.kill(pid, signal.SIGINT)
                except OSError as e:
                    log.warn("Warning: failed to kill(SIGINT) client with pid %s", pid)
                    log.warn(" %s", e)
            else:
                # the more brutal way: SIGKILL + XKill
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError as e:
                    log.warn("Warning: failed to kill(SIGKILL) client with pid %s", pid)
                    log.warn(" %s", e)
                self.XKill()
            self._kill_count += 1
            return
        if DELETE_XKILL:
            self.XKill()
