# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final
from collections.abc import Callable, Sequence

from xpra.os_util import gi_import
from xpra.util.env import first_time
from xpra.common import WORKSPACE_UNSET, WORKSPACE_ALL
from xpra.x11.common import _NET_WM_STATE_ADD, _NET_WM_STATE_REMOVE, _NET_WM_STATE_TOGGLE, STATE_STRING
from xpra.x11.error import xsync, xlog
from xpra.x11.models.core import CoreX11WindowModel, Above, RESTACKING_STR
from xpra.x11.bindings.core import constants
from xpra.x11.bindings.window import X11WindowBindings
from xpra.server.window.content_guesser import guess_content_type, get_content_type_properties, GUESS_CONTENT
from xpra.util.background_worker import add_work_item
from xpra.log import Logger

log = Logger("x11", "window")
workspacelog = Logger("x11", "window", "workspace")
metalog = Logger("x11", "window", "metadata")

GObject = gi_import("GObject")

X11Window = X11WindowBindings()


def get_pyatom(value: int):
    with xsync:
        return X11Window.get_atom_name(value)


WithdrawnState: Final[int] = constants["WithdrawnState"]
IconicState: Final[int] = constants["IconicState"]
NormalState: Final[int] = constants["NormalState"]
WM_STATE_NAME: dict[int, str] = {
    IconicState: "Iconic",
    NormalState: "Normal",
    WithdrawnState: "Withdrawn",
}

# add user-friendly workspace logging:
WORKSPACE_STR: dict[int, str] = {
    WORKSPACE_UNSET: "UNSET",
    WORKSPACE_ALL: "ALL",
}


def workspacestr(w) -> str:
    return WORKSPACE_STR.get(w, str(w))


class BaseWindowModel(CoreX11WindowModel):
    """
        Extends CoreX11WindowModel to add properties
        that we find on real X11 windows (as opposed to trays).
        Also wraps access to _NET_WM_STATE using simpler gobject booleans.
    """
    __common_properties__ = CoreX11WindowModel.__common_properties__.copy()
    __common_properties__ |= {
        # from WM_TRANSIENT_FOR
        "transient-for": (
            GObject.TYPE_PYOBJECT,
            "Transient for (or None)", "",
            GObject.ParamFlags.READABLE,
        ),
        # from _NET_WM_WINDOW_OPACITY
        "opacity": (
            GObject.TYPE_INT64,
            "Opacity", "",
            -1, 0xffffffff, -1,
            GObject.ParamFlags.READABLE,
        ),
        # from WM_HINTS.window_group
        "group-leader": (
            GObject.TYPE_INT,
            "Window group leader", "",
            -1, 65535, -1,
            GObject.ParamFlags.READABLE,
        ),
        # from WM_HINTS.urgency or _NET_WM_STATE
        "attention-requested": (
            GObject.TYPE_BOOLEAN,
            "Urgency hint from client, or us", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        # from WM_HINTS.input or WM_TAKE_FOCUS
        "can-focus": (
            GObject.TYPE_BOOLEAN,
            "Does this window ever accept keyboard input?", "",
            True,
            GObject.ParamFlags.READWRITE,
        ),
        # from _NET_WM_BYPASS_COMPOSITOR
        "bypass-compositor": (
            GObject.TYPE_INT,
            "hint that the window would benefit from running uncomposited ", "",
            0, 2, 0,
            GObject.ParamFlags.READABLE,
        ),
        # from _NET_WM_FULLSCREEN_MONITORS
        "fullscreen-monitors": (
            GObject.TYPE_PYOBJECT,
            "tuple of 4 monitor indices indicating the top, bottom, left, and right edges"
            " of the window when the fullscreen state is enabled", "",
            GObject.ParamFlags.READABLE,
        ),
        # from _NET_WM_STRUT_PARTIAL or _NET_WM_STRUT
        "strut": (
            GObject.TYPE_PYOBJECT,
            "Struts requested by window, or None", "",
            GObject.ParamFlags.READABLE,
        ),
        # for our own use:
        "content-type": (
            GObject.TYPE_PYOBJECT,
            "What type of content is shown in this window", "",
            GObject.ParamFlags.READABLE,
        ),
        # from _XPRA_QUALITY
        "quality": (
            GObject.TYPE_INT,
            "Quality", "",
            -1, 100, -1,
            GObject.ParamFlags.READABLE,
        ),
        # from _XPRA_SPEED
        "speed": (
            GObject.TYPE_INT,
            "Speed", "",
            -1, 100, -1,
            GObject.ParamFlags.READABLE,
        ),
        # from _XPRA_ENCODING
        "encoding": (
            GObject.TYPE_PYOBJECT,
            "Encoding", "",
            GObject.ParamFlags.READABLE,
        ),
        # from _NET_WM_DESKTOP
        "workspace": (
            GObject.TYPE_UINT,
            "The workspace this window is on", "",
            0, 2 ** 32 - 1, WORKSPACE_UNSET,
            GObject.ParamFlags.READWRITE,
        ),
        # set initially only by the window model class
        # (derived from XGetWindowAttributes.override_redirect)
        "override-redirect": (
            GObject.TYPE_BOOLEAN,
            "Is the window of type override-redirect", "",
            False,
            GObject.ParamFlags.READABLE,
        ),
        # from _NET_WM_WINDOW_TYPE
        "window-type": (
            GObject.TYPE_PYOBJECT,
            "Window type",
            "NB, most preferred comes first, then fallbacks",
            GObject.ParamFlags.READABLE,
        ),
        # this value is synced to "_NET_WM_STATE":
        "state": (
            GObject.TYPE_PYOBJECT,
            "State, as per _NET_WM_STATE", "",
            GObject.ParamFlags.READABLE,
        ),
        # all the attributes below are virtual attributes from WM_STATE:
        "modal": (
            GObject.TYPE_PYOBJECT,
            "Modal", "",
            GObject.ParamFlags.READWRITE,
        ),
        "fullscreen": (
            GObject.TYPE_BOOLEAN,
            "Fullscreen-ness of window", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "focused": (
            GObject.TYPE_BOOLEAN,
            "Is the window focused", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "maximized": (
            GObject.TYPE_BOOLEAN,
            "Is the window maximized", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "above": (
            GObject.TYPE_BOOLEAN,
            "Is the window on top of most windows", "",
            False,
            GObject.ParamFlags.READWRITE),
        "below": (
            GObject.TYPE_BOOLEAN,
            "Is the window below most windows", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "shaded": (
            GObject.TYPE_BOOLEAN,
            "Is the window shaded", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "skip-taskbar": (
            GObject.TYPE_BOOLEAN,
            "Should the window be included on a taskbar", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "skip-pager": (
            GObject.TYPE_BOOLEAN,
            "Should the window be included on a pager", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "sticky": (
            GObject.TYPE_BOOLEAN,
            "Is the window's position fixed on the screen", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
    }
    _property_names = CoreX11WindowModel._property_names + [
        "transient-for", "fullscreen-monitors", "bypass-compositor",
        "group-leader", "window-type", "workspace", "strut", "opacity",
        "content-type",
        # virtual attributes:
        "fullscreen", "focused", "maximized", "above", "below", "shaded",
        "skip-taskbar", "skip-pager", "sticky",
    ]
    _dynamic_property_names = CoreX11WindowModel._dynamic_property_names + [
        "attention-requested", "content-type",
        "window-type", "workspace", "opacity",
        "fullscreen", "focused", "maximized", "above", "below", "shaded",
        "skip-taskbar", "skip-pager", "sticky",
        "quality", "speed", "encoding",
    ]
    _internal_property_names = CoreX11WindowModel._internal_property_names + ["state"]
    _initial_x11_properties = CoreX11WindowModel._initial_x11_properties + [
        "WM_TRANSIENT_FOR",
        "_NET_WM_WINDOW_TYPE",
        "_NET_WM_DESKTOP",
        "_NET_WM_FULLSCREEN_MONITORS",
        "_NET_WM_BYPASS_COMPOSITOR",
        "_NET_WM_STRUT",
        # redundant as it uses the same handler as _NET_WM_STRUT:
        "_NET_WM_STRUT_PARTIAL",
        "_NET_WM_WINDOW_OPACITY",
        "WM_HINTS",
        "_XPRA_CONTENT_TYPE",
        "_XPRA_QUALITY",
        "_XPRA_SPEED",
        "_XPRA_ENCODING",
    ]
    _DEFAULT_NET_WM_ALLOWED_ACTIONS: list[str] = [
        f"_NET_WM_ACTION_{x}" for x in (
            "CLOSE", "MOVE", "RESIZE", "FULLSCREEN",
            "MINIMIZE", "SHADE", "STICK",
            "MAXIMIZE_HORZ", "MAXIMIZE_VERT",
            "CHANGE_DESKTOP", "ABOVE", "BELOW",
        )
    ]
    _MODELTYPE = "Base"

    def __init__(self, xid: int):
        super().__init__(xid)
        self.last_unmap_serial = 0
        self._input_field = True  # The WM_HINTS input field
        if GUESS_CONTENT:
            # watch for changes to properties that are used to derive the content-type:
            for x in get_content_type_properties():
                if x in self.get_dynamic_property_names():
                    self.connect(f"notify::{x}", self._content_type_related_property_change)

    def serial_after_last_unmap(self, serial) -> bool:
        # "The serial member is set from the serial number reported in the protocol
        # but expanded from the 16-bit least-significant bits to a full 32-bit value"
        if serial > self.last_unmap_serial:
            return True
        # the serial can wrap around:
        if self.last_unmap_serial - serial >= 2 ** 15:
            return True
        return False

    def _read_initial_X11_properties(self) -> None:
        metalog("%s.read_initial_X11_properties()", self._MODELTYPE)
        wm_state = tuple(self._read_wm_state())
        self._updateprop("state", wm_state)
        self._gproperties["iconic"] = "_NET_WM_STATE_HIDDEN" in wm_state
        super()._read_initial_X11_properties()
        self._update_content_type()

    def _guess_window_type(self) -> str:
        # query the X11 property directly,
        # in case the python property isn't set yet
        if not self.is_OR():
            transient_for = self.prop_get("WM_TRANSIENT_FOR", "window")
            if transient_for:
                # EWMH says that even if it's transient-for, we MUST check to
                # see if it's override-redirect (and if so treat as NORMAL).
                # But we wouldn't be here if this was override-redirect.
                # (OverrideRedirectWindowModel overrides this method)
                return "_NET_WM_WINDOW_TYPE_DIALOG"
        return "_NET_WM_WINDOW_TYPE_NORMAL"

    ################################
    # Actions
    ################################

    def move_to_workspace(self, workspace: int) -> None:
        # we send a message to ourselves, we could also just update the property
        current = self.get_property("workspace")
        if current == workspace:
            workspacelog("move_to_workspace(%s) unchanged", workspacestr(workspace))
            return
        workspacelog("move_to_workspace(%s) current=%s", workspacestr(workspace), workspacestr(current))
        with xlog:
            if workspace == WORKSPACE_UNSET:
                workspacelog("removing _NET_WM_DESKTOP property from window %#x", self.xid)
                self.prop_del("_NET_WM_DESKTOP")
            else:
                workspacelog("setting _NET_WM_DESKTOP=%s on window %#x", workspacestr(workspace), self.xid)
                self.prop_set("_NET_WM_DESKTOP", "u32", workspace)

    #########################################
    # Python objects synced to X11 properties
    #########################################

    def _sync_state(self, *_args) -> None:
        state = self.get_property("state")
        if "_NET_WM_STATE_HIDDEN" in state and "_NET_WM_STATE_FOCUSED" in state:
            # a window should not be focused and hidden at the same time:
            state = set(state)
            state.remove("_NET_WM_STATE_HIDDEN")
            state = tuple(state)
        metalog("sync_state: setting _NET_WM_STATE=%s on %#x", state, self.xid)
        with xlog:
            self.prop_set("_NET_WM_STATE", ["atom"], state)

    def set_wm_state(self, state: int) -> None:
        metalog("set_wm_state(%s)", state)
        with xlog:
            self.prop_set("WM_STATE", "state", state)

    def _sync_iconic(self, *_args) -> None:
        if self.get("iconic"):
            self.set_wm_state(IconicState)
            self._state_update(add=("_NET_WM_STATE_HIDDEN", ), remove=("_NET_WM_STATE_FOCUSED", ))
        else:
            self.set_wm_state(NormalState)
            self._state_update(remove=("_NET_WM_STATE_HIDDEN", ))

    _py_property_handlers: dict[str, Callable] = dict(CoreX11WindowModel._py_property_handlers)
    _py_property_handlers |= {
        "state": _sync_state,
        "iconic": _sync_iconic,
    }

    #########################################
    # X11 properties synced to Python objects
    #########################################

    def _handle_transient_for_change(self) -> None:
        transient_for = self.prop_get("WM_TRANSIENT_FOR", "window") or 0
        metalog("WM_TRANSIENT_FOR=%#x", transient_for)
        # `transient-for` may be None
        self._updateprop("transient-for", transient_for)

    def _handle_window_type_change(self) -> None:
        window_types = self.prop_get("_NET_WM_WINDOW_TYPE", ["atom"])
        metalog("_NET_WM_WINDOW_TYPE=%s", window_types)
        if not window_types:
            window_type = self._guess_window_type()
            metalog("guessed window type=%s", window_type)
            # atom = Gdk.Atom.intern(window_type, False)
            window_types = [window_type]
        # normalize them (hide _NET_WM_WINDOW_TYPE prefix):
        window_types = [str(wt).replace("_NET_WM_WINDOW_TYPE_", "").replace("_NET_WM_TYPE_", "") for wt in window_types]
        self._updateprop("window-type", window_types)

    def _handle_workspace_change(self) -> None:
        workspace = self.prop_get("_NET_WM_DESKTOP", "u32", True)
        if workspace is None:
            workspace = WORKSPACE_UNSET
        workspacelog("_NET_WM_DESKTOP=%s for window %#x", workspacestr(workspace), self.xid)
        self._updateprop("workspace", workspace)

    def _handle_fullscreen_monitors_change(self) -> None:
        fsm = self.prop_get("_NET_WM_FULLSCREEN_MONITORS", ["u32"], True)
        metalog("_NET_WM_FULLSCREEN_MONITORS=%s", fsm)
        self._updateprop("fullscreen-monitors", tuple(fsm or ()))

    def _handle_bypass_compositor_change(self) -> None:
        bypass = self.prop_get("_NET_WM_BYPASS_COMPOSITOR", "u32", True) or 0
        metalog("_NET_WM_BYPASS_COMPOSITOR=%s", bypass)
        self._updateprop("bypass-compositor", bypass)

    def _handle_wm_strut_change(self) -> None:
        strut = self.prop_get("_NET_WM_STRUT_PARTIAL", "strut-partial")
        metalog("_NET_WM_STRUT_PARTIAL=%s", strut)
        if strut is None:
            strut = self.prop_get("_NET_WM_STRUT", "strut")
            metalog("_NET_WM_STRUT=%s", strut)
        value = {} if not strut else strut.todict()
        self._updateprop("strut", value)

    def _handle_opacity_change(self) -> None:
        opacity = self.prop_get("_NET_WM_WINDOW_OPACITY", "u32", True) or -1
        metalog("_NET_WM_WINDOW_OPACITY=%s", opacity)
        self._updateprop("opacity", opacity)

    def _handle_wm_hints_change(self) -> None:
        with xsync:
            wm_hints = X11Window.getWMHints(self.xid)
        metalog("getWMHints(%#x)=%s", self.xid, wm_hints)
        if wm_hints is None:
            return
        # GdkWindow or None
        group_leader = 0
        if "window_group" in wm_hints:
            group_leader = wm_hints.get("window_group", 0)
        self._updateprop("group-leader", group_leader)
        self._updateprop("attention-requested", wm_hints.get("urgency", False))
        _input = wm_hints.get("input")
        metalog("wm_hints.input = %s", _input)
        # we only set this value once:
        # (input_field always starts as True, and we then set it to an int)
        if self._input_field is True and _input is not None:
            # keep the value as an int to differentiate from the start value:
            self._input_field = int(_input)
            self._update_can_focus()

    def _update_can_focus(self, *_args) -> None:
        can_focus = bool(self._input_field) or "WM_TAKE_FOCUS" in self.get_property("protocols")
        self._updateprop("can-focus", can_focus)

    def _content_type_related_property_change(self, *_args) -> None:
        self._update_content_type()

    def _handle_xpra_content_type_change(self) -> None:
        self._update_content_type()

    def _update_content_type(self) -> None:
        # watch for changes to properties that are used to derive the content-type:
        content_type = self.prop_get("_XPRA_CONTENT_TYPE", "latin1", True) or ""
        # the _XPRA_CONTENT_TYPE property takes precedence
        if not content_type and GUESS_CONTENT:
            # guess_content_type can take a while as it will load the xdg menu data
            # so call it as a work item.
            # multiple callers can be added to the sequential work queue,
            # the menu loader also has a lock.
            add_work_item(self.guess_content_type)
        metalog("_update_content_type() %s", content_type)
        self._updateprop("content-type", content_type)

    def guess_content_type(self) -> None:
        content_type = guess_content_type(self)
        if not content_type and self.is_tray():
            content_type = "picture"
        metalog(f"guess_content_type() {content_type=}")
        self._updateprop("content-type", content_type)

    def _handle_xpra_quality_change(self) -> None:
        quality = self.prop_get("_XPRA_QUALITY", "u32", True) or -1
        metalog("quality=%s", quality)
        self._updateprop("quality", max(-1, min(100, quality)))

    def _handle_xpra_speed_change(self) -> None:
        speed = self.prop_get("_XPRA_SPEED", "u32", True) or -1
        metalog("speed=%s", speed)
        self._updateprop("speed", max(-1, min(100, speed)))

    def _handle_xpra_encoding_change(self) -> None:
        encoding = self.prop_get("_XPRA_ENCODING", "latin1", True) or ""
        metalog("encoding=%s", encoding)
        self._updateprop("encoding", encoding)

    _x11_property_handlers: dict[str, Callable] = CoreX11WindowModel._x11_property_handlers.copy()
    _x11_property_handlers |= {
        "WM_TRANSIENT_FOR": _handle_transient_for_change,
        "_NET_WM_WINDOW_TYPE": _handle_window_type_change,
        "_NET_WM_DESKTOP": _handle_workspace_change,
        "_NET_WM_FULLSCREEN_MONITORS": _handle_fullscreen_monitors_change,
        "_NET_WM_BYPASS_COMPOSITOR": _handle_bypass_compositor_change,
        "_NET_WM_STRUT": _handle_wm_strut_change,
        "_NET_WM_STRUT_PARTIAL": _handle_wm_strut_change,
        "_NET_WM_WINDOW_OPACITY": _handle_opacity_change,
        "WM_HINTS": _handle_wm_hints_change,
        "_XPRA_CONTENT_TYPE": _handle_xpra_content_type_change,
        "_XPRA_QUALITY": _handle_xpra_quality_change,
        "_XPRA_SPEED": _handle_xpra_speed_change,
        "_XPRA_ENCODING": _handle_xpra_encoding_change,
    }

    #########################################
    # _NET_WM_STATE
    #########################################
    # A few words about _NET_WM_STATE are in order.  Basically, it is a set of
    # flags.  Clients are allowed to set the initial value of this X property
    # to anything they like, when their window is first mapped; after that,
    # though, only the window manager is allowed to touch this property.  So
    # we store its value (or at least, our idea as to its value, the X server
    # in principle could disagree) as the "state" property.  There are
    # basically two things we need to accomplish:
    #   1) Whenever our property is modified, we mirror that modification into
    #      the X server.  This is done by connecting to our own notify::state
    #      signal.
    #   2) As a more user-friendly interface to these state flags, we provide
    #      several boolean properties like "attention-requested".
    #      These are virtual boolean variables; they are actually backed
    #      directly by the "state" property, and reading/writing them in fact
    #      accesses the "state" set directly.  This is done by overriding
    #      do_set_property and do_get_property.
    _state_properties: dict[str, Sequence[str]] = {
        "attention-requested": ("_NET_WM_STATE_DEMANDS_ATTENTION",),
        "fullscreen": ("_NET_WM_STATE_FULLSCREEN",),
        "maximized": ("_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"),
        "shaded": ("_NET_WM_STATE_SHADED",),
        "above": ("_NET_WM_STATE_ABOVE",),
        "below": ("_NET_WM_STATE_BELOW",),
        "sticky": ("_NET_WM_STATE_STICKY",),
        "skip-taskbar": ("_NET_WM_STATE_SKIP_TASKBAR",),
        "skip-pager": ("_NET_WM_STATE_SKIP_PAGER",),
        "modal": ("_NET_WM_STATE_MODAL",),
        "focused": ("_NET_WM_STATE_FOCUSED",),
    }
    _state_properties_reversed = {}
    for k, states in tuple(_state_properties.items()):
        for x in states:
            _state_properties_reversed[x] = k

    def _state_update(self, add=(), remove=()) -> None:
        curr = set(self.get_property("state"))
        was = set(curr)
        added = set(add) - curr
        curr |= added
        removed = set(remove) & curr
        curr -= removed
        metalog("state_update(%s, %s) was=%s, added=%s, removed=%s, new state=%s",
                add, remove, was, added, removed, curr)
        if added or removed:
            # note: _sync_state will update _NET_WM_STATE here:
            self._internal_set_property("state", tuple(curr))
            self._state_notify(added | removed)

    def _state_notify(self, state_names: set[str]) -> None:
        notify_props: set[str] = set()
        for x in state_names:
            if x in self._state_properties_reversed:
                notify_props.add(self._state_properties_reversed[x])
        metalog("state notify(%s)=%s", state_names, notify_props)
        for x in tuple(notify_props):
            self.notify(x)

    def _state_isset(self, state_name: str) -> bool:
        return state_name in self.get_property("state")

    def _read_wm_state(self) -> list[str]:
        wm_state = self.prop_get("_NET_WM_STATE", ["atom"])
        metalog("read _NET_WM_STATE=%s", wm_state)
        return wm_state or []

    def do_set_property(self, pspec, value) -> None:
        # intercept state properties to route via update_state()
        if pspec.name in self._state_properties:
            # virtual property for WM_STATE:
            self.update_wm_state(pspec.name, bool(value))
            return
        super().do_set_property(pspec, value)

    def do_get_property(self, pspec) -> object:
        # intercept state properties to route via get_wm_state()
        if pspec.name in self._state_properties:
            # virtual property for WM_STATE:
            return self.get_wm_state(pspec.name)
        return super().do_get_property(pspec)

    def update_wm_state(self, prop: str, b: bool) -> None:
        state_names = self._state_properties.get(prop)
        if not state_names:
            raise ValueError(f"invalid window state {prop}")
        if b:
            self._state_update(add=state_names)
        else:
            self._state_update(remove=state_names)

    def get_wm_state(self, prop: str) -> bool:
        state_names = self._state_properties.get(prop)
        if not state_names:
            raise ValueError(f"invalid window state {prop}")
        # this is a virtual property for WM_STATE:
        # return True if any is set (only relevant for maximized)
        return any(self._state_isset(x) for x in state_names)

    #########################################
    # X11 Events
    #########################################

    def process_client_message_event(self, event) -> bool:
        # FIXME
        # Need to listen for:
        #   _NET_CURRENT_DESKTOP
        #   _NET_WM_PING responses
        # and maybe:
        #   _NET_WM_STATE (more fully)

        if event.message_type == "_NET_WM_STATE":
            def update_wm_state(prop: str) -> None:
                current = self.get_property(prop)
                mode = event.data[0]
                if mode == _NET_WM_STATE_ADD:
                    v = True
                elif mode == _NET_WM_STATE_REMOVE:
                    v = False
                elif mode == _NET_WM_STATE_TOGGLE:
                    v = not bool(current)
                else:
                    log.warn(f"Warning: invalid mode for _NET_WM_STATE: {mode}")
                    return
                log("process_client_message_event(%s) window %s=%s after %s (current state=%s)",
                    event, prop, v, STATE_STRING.get(mode, mode), current)
                if v != current:
                    self.update_wm_state(prop, v)

            atom1 = get_pyatom(event.data[1])
            log("_NET_WM_STATE: %s", atom1)
            if atom1 == "_NET_WM_STATE_FULLSCREEN":
                update_wm_state("fullscreen")
            elif atom1 == "_NET_WM_STATE_ABOVE":
                update_wm_state("above")
            elif atom1 == "_NET_WM_STATE_BELOW":
                update_wm_state("below")
            elif atom1 == "_NET_WM_STATE_SHADED":
                update_wm_state("shaded")
            elif atom1 == "_NET_WM_STATE_STICKY":
                update_wm_state("sticky")
            elif atom1 == "_NET_WM_STATE_SKIP_TASKBAR":
                update_wm_state("skip-taskbar")
            elif atom1 == "_NET_WM_STATE_SKIP_PAGER":
                update_wm_state("skip-pager")
                get_pyatom(event.data[2])
            elif atom1 in ("_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"):
                atom2 = get_pyatom(event.data[2])
                # we only have one state for both, so we require both to be set:
                if atom1 != atom2 and atom2 in ("_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"):
                    update_wm_state("maximized")
            elif atom1 == "_NET_WM_STATE_HIDDEN":
                log("ignoring 'HIDDEN' _NET_WM_STATE: %s", event)
                # we don't honour those because they make little sense, see:
                # https://mail.gnome.org/archives/wm-spec-list/2005-May/msg00004.html
            elif atom1 == "_NET_WM_STATE_MODAL":
                update_wm_state("modal")
            elif atom1 == "_NET_WM_STATE_DEMANDS_ATTENTION":
                update_wm_state("attention-requested")
            elif atom1 == "_KDE_NET_WM_STATE_SKIP_SWITCHER":
                if first_time(f"KDE-WM_STATE-{self.xid}"):
                    log.info(f"invalid KDE specific request {atom1} ignored, will not be logged again")
            else:
                log.info(f"Unhandled _NET_WM_STATE request: {atom1!r}")
                log.info(f" event {event!r}")
            return True
        if event.message_type == "WM_CHANGE_STATE":
            iconic = event.data[0]
            log("WM_CHANGE_STATE: %s, serial=%s, last unmap serial=%#x",
                WM_STATE_NAME.get(iconic, iconic), event.serial, self.last_unmap_serial)
            valid = iconic in (IconicState, NormalState)
            if valid and self.serial_after_last_unmap(event.serial) and not self.is_OR() and not self.is_tray():
                self._updateprop("iconic", iconic == IconicState)
            return True
        if event.message_type == "_NET_WM_MOVERESIZE":
            log("_NET_WM_MOVERESIZE: %s", event)
            self.emit("initiate-moveresize", event)
            return True
        if event.message_type == "_NET_ACTIVE_WINDOW":
            # to filter based on the source indication:
            # ACTIVE_WINDOW_SOURCE = tuple(int(x)
            #                              for x in os.environ.get("XPRA_ACTIVE_WINDOW_SOURCE", "0,1").split(","))
            # if event.data[0] in ACTIVE_WINDOW_SOURCE:
            log("_NET_ACTIVE_WINDOW: %s", event)
            self.set_active()
            self.emit("restack", Above, 0)
            return True
        if event.message_type == "_NET_WM_DESKTOP":
            workspace = int(event.data[0])
            # query the workspace count on the root window
            # since we cannot access Wm from here…
            from xpra.x11.common import get_number_of_desktops
            ndesktops = get_number_of_desktops()
            workspacelog("received _NET_WM_DESKTOP: workspace=%s, number of desktops=%s",
                         workspacestr(workspace), ndesktops)
            if ndesktops == 0:
                self.move_to_workspace(0)
            elif ndesktops > 0 and (workspace in (WORKSPACE_UNSET, WORKSPACE_ALL) or 0 <= workspace < ndesktops):
                self.move_to_workspace(workspace)
            else:
                workspacelog.warn("invalid _NET_WM_DESKTOP request: workspace=%s, number of desktops=%s",
                                  workspacestr(workspace), ndesktops)
            return True
        if event.message_type == "_NET_WM_FULLSCREEN_MONITORS":
            log("_NET_WM_FULLSCREEN_MONITORS: %s", event)
            # TODO: we should validate the indexes instead of copying them blindly!
            # TODO: keep track of source indication so we can forward that to the client
            N = 16  # FIXME: this is an arbitrary limit
            monitors = list(event.data[:4])
            if not all(0 <= x < N for x in monitors):
                log.warn("Warning: invalid list of _NET_WM_FULLSCREEN_MONITORS:%s - ignored", event.data)
                return False
            log("_NET_WM_FULLSCREEN_MONITORS: monitors=%s", monitors)
            self.prop_set("_NET_WM_FULLSCREEN_MONITORS", ["u32"], monitors)
            return True
        if event.message_type == "_NET_RESTACK_WINDOW":
            source = {1: "application", 2: "pager"}.get(event.data[0], "default (%s)" % event.data[0])
            sibling_window = event.data[1]
            log("%s sent to window %#x for sibling %#x from %s with detail=%s",
                event.message_type, event.window, sibling_window, source,
                RESTACKING_STR.get(event.detail, event.detail))
            self.emit("restack", event.detail, sibling_window)
            return True
        # TODO: maybe we should process _NET_MOVERESIZE_WINDOW here?
        # it may make sense to apply it to the client_window
        # whereas the code in WindowModel assumes there is a corral window
        # not handled:
        return super().process_client_message_event(event)
