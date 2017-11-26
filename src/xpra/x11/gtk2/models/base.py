# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import WORKSPACE_UNSET, WORKSPACE_ALL
from xpra.x11.gtk_x11.prop import prop_set, prop_get
from xpra.x11.gtk2.models.core import CoreX11WindowModel, gobject, xswallow, gdk
from xpra.x11.bindings.window_bindings import X11WindowBindings, constants      #@UnresolvedImport
from xpra.x11.gtk2.gdk_bindings import get_pywindow, get_pyatom                 #@UnresolvedImport

from xpra.log import Logger
log = Logger("x11", "window")
workspacelog = Logger("x11", "window", "workspace")
metalog = Logger("x11", "window", "metadata")
geomlog = Logger("x11", "window", "geometry")
menulog = Logger("x11", "window", "menu")


dbus_helper = None
MENU_FORWARDING = os.environ.get("XPRA_MENU_FORWARDING", "1")=="1"
if MENU_FORWARDING:
    try:
        from xpra import dbus
        assert dbus
    except ImportError as e:
        log("this build does not include the dbus module, no menu forwarding")
        del e
    else:
        try:
            from xpra.dbus.helper import DBusHelper
            dbus_helper = DBusHelper()
            from xpra.dbus.gtk_menuactions import query_actions, query_menu, ACTIONS, MENUS
        except Exception as e:
            log.warn("Warning: menu forwarding is disabled:")
            log.warn(" cannot load dbus helper: %s", e)
            del e
            MENU_FORWARDING = False


X11Window = X11WindowBindings()

#_NET_WM_STATE:
_NET_WM_STATE_REMOVE = 0
_NET_WM_STATE_ADD    = 1
_NET_WM_STATE_TOGGLE = 2
STATE_STRING = {
            _NET_WM_STATE_REMOVE    : "REMOVE",
            _NET_WM_STATE_ADD       : "ADD",
            _NET_WM_STATE_TOGGLE    : "TOGGLE",
                }
IconicState = constants["IconicState"]
NormalState = constants["NormalState"]
ICONIC_STATE_STRING = {
                       IconicState  : "Iconic",
                       NormalState  : "Normal",
                       }

#add user friendly workspace logging:
WORKSPACE_STR = {WORKSPACE_UNSET    : "UNSET",
                 WORKSPACE_ALL      : "ALL"}
def workspacestr(w):
    return WORKSPACE_STR.get(w, w)


class BaseWindowModel(CoreX11WindowModel):
    """
        Extends CoreX11WindowModel to add properties
        that we find on real X11 windows (as opposed to trays).
        Also wraps access to _NET_WM_STATE using simpler gobject booleans.
    """
    __common_properties__ = CoreX11WindowModel.__common_properties__.copy()
    __common_properties__.update({
        #from WM_TRANSIENT_FOR
        "transient-for": (gobject.TYPE_PYOBJECT,
                          "Transient for (or None)", "",
                          gobject.PARAM_READABLE),
        #from _NET_WM_WINDOW_OPACITY
        "opacity": (gobject.TYPE_INT64,
                "Opacity", "",
                -1, 0xffffffff, -1,
                gobject.PARAM_READABLE),
        #from WM_HINTS.window_group
        "group-leader": (gobject.TYPE_PYOBJECT,
                         "Window group leader as a pair: (xid, gdk window)", "",
                         gobject.PARAM_READABLE),
        #from WM_HINTS.urgency or _NET_WM_STATE
        "attention-requested": (gobject.TYPE_BOOLEAN,
                                "Urgency hint from client, or us", "",
                                False,
                                gobject.PARAM_READWRITE),
        #from WM_HINTS.input or WM_TAKE_FOCUS
        "can-focus": (gobject.TYPE_BOOLEAN,
                      "Does this window ever accept keyboard input?", "",
                      True,
                      gobject.PARAM_READWRITE),
        #from _NET_WM_BYPASS_COMPOSITOR
        "bypass-compositor": (gobject.TYPE_INT,
                       "hint that the window would benefit from running uncomposited ", "",
                       0, 2, 0,
                       gobject.PARAM_READABLE),
        #from _NET_WM_FULLSCREEN_MONITORS
        "fullscreen-monitors": (gobject.TYPE_PYOBJECT,
                         "List of 4 monitor indices indicating the top, bottom, left, and right edges of the window when the fullscreen state is enabled", "",
                         gobject.PARAM_READABLE),
        #from _NET_WM_STRUT_PARTIAL or _NET_WM_STRUT
        "strut": (gobject.TYPE_PYOBJECT,
                  "Struts requested by window, or None", "",
                  gobject.PARAM_READABLE),
        #from _GTK_*MENU*
        "menu": (gobject.TYPE_PYOBJECT,
                  "Application menu, or None", "",
                  gobject.PARAM_READABLE),
        #from _NET_WM_DESKTOP
        "workspace": (gobject.TYPE_UINT,
                "The workspace this window is on", "",
                0, 2**32-1, WORKSPACE_UNSET,
                gobject.PARAM_READWRITE),
        #set initially only by the window model class
        #(derived from XGetWindowAttributes.override_redirect)
        "override-redirect": (gobject.TYPE_BOOLEAN,
                       "Is the window of type override-redirect", "",
                       False,
                       gobject.PARAM_READABLE),
        #from _NET_WM_WINDOW_TYPE
        "window-type": (gobject.TYPE_PYOBJECT,
                        "Window type",
                        "NB, most preferred comes first, then fallbacks",
                        gobject.PARAM_READABLE),
        #this value is synced to "_NET_WM_STATE":
        "state": (gobject.TYPE_PYOBJECT,
                  "State, as per _NET_WM_STATE", "",
                  gobject.PARAM_READABLE),
        #all the attributes below are virtual attributes from WM_STATE:
        "modal": (gobject.TYPE_PYOBJECT,
                          "Modal (boolean)", "",
                          gobject.PARAM_READWRITE),
        "fullscreen": (gobject.TYPE_BOOLEAN,
                       "Fullscreen-ness of window", "",
                       False,
                       gobject.PARAM_READWRITE),
        "focused": (gobject.TYPE_BOOLEAN,
                       "Is the window focused", "",
                       False,
                       gobject.PARAM_READWRITE),
        "maximized": (gobject.TYPE_BOOLEAN,
                       "Is the window maximized", "",
                       False,
                       gobject.PARAM_READWRITE),
        "above": (gobject.TYPE_BOOLEAN,
                       "Is the window on top of most windows", "",
                       False,
                       gobject.PARAM_READWRITE),
        "below": (gobject.TYPE_BOOLEAN,
                       "Is the window below most windows", "",
                       False,
                       gobject.PARAM_READWRITE),
        "shaded": (gobject.TYPE_BOOLEAN,
                       "Is the window shaded", "",
                       False,
                       gobject.PARAM_READWRITE),
        "skip-taskbar": (gobject.TYPE_BOOLEAN,
                       "Should the window be included on a taskbar", "",
                       False,
                       gobject.PARAM_READWRITE),
        "skip-pager": (gobject.TYPE_BOOLEAN,
                       "Should the window be included on a pager", "",
                       False,
                       gobject.PARAM_READWRITE),
        "sticky": (gobject.TYPE_BOOLEAN,
                       "Is the window's position fixed on the screen", "",
                       False,
                       gobject.PARAM_READWRITE),
        })
    _property_names = CoreX11WindowModel._property_names + [
                      "transient-for", "fullscreen-monitors", "bypass-compositor", "group-leader", "window-type", "workspace", "strut", "opacity",
                      "menu",
                      #virtual attributes:
                      "fullscreen", "focused", "maximized", "above", "below", "shaded", "skip-taskbar", "skip-pager", "sticky"]
    _dynamic_property_names = CoreX11WindowModel._dynamic_property_names + [
                              "attention-requested",
                              "menu", "workspace", "opacity",
                              "fullscreen", "focused", "maximized", "above", "below", "shaded", "skip-taskbar", "skip-pager", "sticky"]
    _internal_property_names = CoreX11WindowModel._internal_property_names+["state"]
    _initial_x11_properties = CoreX11WindowModel._initial_x11_properties + [
                              "WM_TRANSIENT_FOR",
                              "_NET_WM_WINDOW_TYPE",
                              "_NET_WM_DESKTOP",
                              "_NET_WM_FULLSCREEN_MONITORS",
                              "_NET_WM_BYPASS_COMPOSITOR",
                              "_NET_WM_STRUT",
                              "_NET_WM_STRUT_PARTIAL",      #redundant as it uses the same handler as _NET_WM_STRUT
                              "_NET_WM_WINDOW_OPACITY",
                              "WM_HINTS",
                              "_GTK_APP_MENU_OBJECT_PATH",
                              #redundant as they use the same function as _GTK_APP_MENU_OBJECT_PATH:
                              #(but the code will make sure we only call it once during setup)
                              "_GTK_APPLICATION_ID",
                              "_GTK_UNIQUE_BUS_NAME",
                              "_GTK_APPLICATION_OBJECT_PATH",
                              "_GTK_APP_MENU_OBJECT_PATH",
                              "_GTK_WINDOW_OBJECT_PATH",
                              ]
    _DEFAULT_NET_WM_ALLOWED_ACTIONS = ["_NET_WM_ACTION_%s" % x for x in (
        "CLOSE", "MOVE", "RESIZE", "FULLSCREEN",
        "MINIMIZE", "SHADE", "STICK",
        "MAXIMIZE_HORZ", "MAXIMIZE_VERT",
        "CHANGE_DESKTOP", "ABOVE", "BELOW")]
    _MODELTYPE = "Base"

    def __init__(self, client_window):
        super(BaseWindowModel, self).__init__(client_window)
        self.last_unmap_serial = 0
        self._input_field = True            # The WM_HINTS input field

    def serial_after_last_unmap(self, serial):
        #"The serial member is set from the serial number reported in the protocol
        # but expanded from the 16-bit least-significant bits to a full 32-bit value"
        if serial>self.last_unmap_serial:
            return True
        #the serial can wrap around:
        if self.last_unmap_serial-serial>=2**15:
            return True
        return False


    def _read_initial_X11_properties(self):
        metalog("%s.read_initial_X11_properties()", self._MODELTYPE)
        self._updateprop("state", frozenset(self._read_wm_state()))
        super(BaseWindowModel, self)._read_initial_X11_properties()

    def _guess_window_type(self):
        #query the X11 property directly,
        #in case the python property isn't set yet
        if not self.is_OR():
            transient_for = self.prop_get("WM_TRANSIENT_FOR", "window")
            if transient_for is not None:
                # EWMH says that even if it's transient-for, we MUST check to
                # see if it's override-redirect (and if so treat as NORMAL).
                # But we wouldn't be here if this was override-redirect.
                # (OverrideRedirectWindowModel overrides this method)
                return "_NET_WM_WINDOW_TYPE_DIALOG"
        return "_NET_WM_WINDOW_TYPE_NORMAL"


    ################################
    # Actions
    ################################

    def move_to_workspace(self, workspace):
        #we send a message to ourselves, we could also just update the property
        current = self.get_property("workspace")
        if current==workspace:
            workspacelog("move_to_workspace(%s) unchanged", workspacestr(workspace))
            return
        workspacelog("move_to_workspace(%s) current=%s", workspacestr(workspace), workspacestr(current))
        with xswallow:
            if workspace==WORKSPACE_UNSET:
                workspacelog("removing _NET_WM_DESKTOP property from window %#x", self.xid)
                X11Window.XDeleteProperty(self.xid, "_NET_WM_DESKTOP")
            else:
                workspacelog("setting _NET_WM_DESKTOP=%s on window %#x", workspacestr(workspace), self.xid)
                prop_set(self.client_window, "_NET_WM_DESKTOP", "u32", workspace)


    #########################################
    # Python objects synced to X11 properties
    #########################################

    def _sync_state(self, *_args):
        state = self.get_property("state")
        metalog("sync_state: setting _NET_WM_STATE=%s on %#x", state, self.xid)
        with xswallow:
            prop_set(self.client_window, "_NET_WM_STATE", ["atom"], state)

    def _sync_iconic(self, *_args):
        def set_state(state):
            log("_handle_iconic_update: set_state(%s)", state)
            with xswallow:
                prop_set(self.client_window, "WM_STATE", "state", state)

        if self.get("iconic"):
            set_state(IconicState)
            self._state_add("_NET_WM_STATE_HIDDEN")
        else:
            set_state(NormalState)
            self._state_remove("_NET_WM_STATE_HIDDEN")


    _py_property_handlers = dict(CoreX11WindowModel._py_property_handlers)
    _py_property_handlers.update({
        "state"         : _sync_state,
        "iconic"        : _sync_iconic,
        })


    #########################################
    # X11 properties synced to Python objects
    #########################################

    def _handle_transient_for_change(self):
        transient_for = self.prop_get("WM_TRANSIENT_FOR", "window")
        metalog("WM_TRANSIENT_FOR=%s", transient_for)
        # May be None
        self._updateprop("transient-for", transient_for)

    def _handle_window_type_change(self):
        window_types = self.prop_get("_NET_WM_WINDOW_TYPE", ["atom"])
        metalog("_NET_WM_WINDOW_TYPE=%s", window_types)
        if not window_types:
            window_type = self._guess_window_type()
            metalog("guessed window type=%s", window_type)
            window_types = [gdk.atom_intern(window_type)]
        #normalize them (hide _NET_WM_WINDOW_TYPE prefix):
        window_types = [str(wt).replace("_NET_WM_WINDOW_TYPE_", "").replace("_NET_WM_TYPE_", "") for wt in window_types]
        self._updateprop("window-type", window_types)

    def _handle_workspace_change(self):
        workspace = self.prop_get("_NET_WM_DESKTOP", "u32", True)
        if workspace is None:
            workspace = WORKSPACE_UNSET
        workspacelog("_NET_WM_DESKTOP=%s for window %#x", workspacestr(workspace), self.xid)
        self._updateprop("workspace", workspace)

    def _handle_fullscreen_monitors_change(self):
        fsm = self.prop_get("_NET_WM_FULLSCREEN_MONITORS", ["u32"], True)
        metalog("_NET_WM_FULLSCREEN_MONITORS=%s", fsm)
        self._updateprop("fullscreen-monitors", fsm)

    def _handle_bypass_compositor_change(self):
        bypass = self.prop_get("_NET_WM_BYPASS_COMPOSITOR", "u32", True) or 0
        metalog("_NET_WM_BYPASS_COMPOSITOR=%s", bypass)
        self._updateprop("bypass-compositor", bypass)

    def _handle_wm_strut_change(self):
        strut = self.prop_get("_NET_WM_STRUT_PARTIAL", "strut-partial")
        metalog("_NET_WM_STRUT_PARTIAL=%s", strut)
        if strut is None:
            strut = self.prop_get("_NET_WM_STRUT", "strut")
            metalog("_NET_WM_STRUT=%s", strut)
        # Might be None:
        self._updateprop("strut", strut)

    def _handle_opacity_change(self):
        opacity = self.prop_get("_NET_WM_WINDOW_OPACITY", "u32", True) or -1
        metalog("_NET_WM_WINDOW_OPACITY=%s", opacity)
        self._updateprop("opacity", opacity)

    def _handle_wm_hints_change(self):
        with xswallow:
            wm_hints = X11Window.getWMHints(self.xid)
        if wm_hints is None:
            return
        # GdkWindow or None
        group_leader = None
        if "window_group" in wm_hints:
            xid = wm_hints.get("window_group")
            try:
                group_leader = xid, get_pywindow(xid)
            except:
                group_leader = xid, None
        self._updateprop("group-leader", group_leader)
        self._updateprop("attention-requested", wm_hints.get("urgency", False))
        _input = wm_hints.get("input")
        metalog("wm_hints.input = %s", _input)
        #we only set this value once:
        #(input_field always starts as True, and we then set it to an int)
        if self._input_field is True and _input is not None:
            #keep the value as an int to differentiate from the start value:
            self._input_field = int(_input)
            self._update_can_focus()

    def _update_can_focus(self, *_args):
        can_focus = bool(self._input_field) or "WM_TAKE_FOCUS" in self.get_property("protocols")
        self._updateprop("can-focus", can_focus)


    def _get_x11_menu_properties(self):
        props = {}
        for k,x11name in {
            "application-id"    : "_GTK_APPLICATION_ID",            #ie: org.gnome.baobab
            "bus-name"          : "_GTK_UNIQUE_BUS_NAME",           #ie: :1.745
            "application-path"  : "_GTK_APPLICATION_OBJECT_PATH",   #ie: /org/gnome/baobab
            "app-menu-path"     : "_GTK_APP_MENU_OBJECT_PATH",      #ie: /org/gnome/baobab/menus/appmenu
            "window-path"       : "_GTK_WINDOW_OBJECT_PATH",        #ie: /org/gnome/baobab/window/1
            }.items():
            v = self.prop_get(x11name, "utf8", ignore_errors=True, raise_xerrors=False)
            menulog("%s=%s", x11name, v)
            if v:
                props[k] = v
        return props

    def _handle_gtk_app_menu_change(self):
        def nomenu(*_args):
            self._updateprop("menu", {})
        if not MENU_FORWARDING:
            nomenu()
        props = self._get_x11_menu_properties()
        if len(props)<5:        #incomplete
            nomenu()
            return
        menulog("gtk menu properties: %s", props)
        app_id      = props["application-id"]
        bus_name    = props["bus-name"]
        app_path    = props["application-path"]
        menu_path   = props["app-menu-path"]
        window_path = props["window-path"]
        def updatemenu(k, v):
            """ Updates the 'menu' property if the value has changed.
                Sets the 'enabled' flag if all the required properties are present.
            """
            menu = self._gproperties.get("menu") or {}
            cv = menu.get(k)
            if cv==v:
                return
            if v is None:
                try:
                    del menu[k]
                except:
                    pass
            else:
                menu[k] = v
            enabled = all(menu.get(x) for x in ("application-id", "application-actions", "window-actions", "window-menu"))
            menu["enabled"] = enabled
            menulog("menu(%s)=%s", self, menu)
            self._internal_set_property("menu", menu)
        updatemenu("application-id", app_id)
        def app_actions_cb(actions):
            menulog("application-actions=%s", actions)
            updatemenu("application-actions", actions)
        def app_actions_err(err):
            menulog.error("Error: failed to query %s at %s:", ACTIONS, app_path)
            menulog.error(" %s", err)
            updatemenu("application-actions", None)
        query_actions(bus_name, app_path, app_actions_cb, app_actions_err)
        def window_actions_cb(actions):
            menulog("window-actions", actions)
            updatemenu("window-actions", actions)
        def window_actions_err(err):
            menulog.error("Error: failed to query %s at %s:", ACTIONS, window_path)
            menulog.error(" %s", err)
            updatemenu("window-actions", None)
        query_actions(bus_name, window_path, window_actions_cb, window_actions_err)
        def menu_cb(menu):
            menulog("window-menu", menu)
            updatemenu("window-menu", menu)
        def menu_err(err):
            menulog.error("Error: failed to query %s at %s:", MENUS, menu_path)
            menulog.error(" %s", err)
            updatemenu("window-menu", None)
        query_menu(bus_name, menu_path, menu_cb, menu_err)

    def activate_menu(self, action_type, action, state, pdata):
        #locate the service and call it:
        from xpra.dbus.gtk_menuactions import get_actions_interface
        props = self._get_x11_menu_properties()
        menulog("activate_menu%s properties=%s", (action_type, action, state, pdata), props)
        if not props:
            raise Exception("no menu defined for %s" % self)
        bus_name    = props.get("bus-name")
        if not bus_name:
            raise Exception("no bus name defined for %s" % self)
        if action_type=="application":
            path = "application-path"
        elif action_type=="window":
            path = "window-path"
        else:
            raise Exception("unknown action type for menu: %s" % action_type)
        object_path = props.get(path)
        if not object_path:
            raise Exception("no object path property %s" % path)
        actions_iface = get_actions_interface(bus_name, object_path)
        actions_iface.Activate(action, state, pdata)


    _x11_property_handlers = CoreX11WindowModel._x11_property_handlers.copy()
    _x11_property_handlers.update({
        "WM_TRANSIENT_FOR"              : _handle_transient_for_change,
        "_NET_WM_WINDOW_TYPE"           : _handle_window_type_change,
        "_NET_WM_DESKTOP"               : _handle_workspace_change,
        "_NET_WM_FULLSCREEN_MONITORS"   : _handle_fullscreen_monitors_change,
        "_NET_WM_BYPASS_COMPOSITOR"     : _handle_bypass_compositor_change,
        "_NET_WM_STRUT"                 : _handle_wm_strut_change,
        "_NET_WM_STRUT_PARTIAL"         : _handle_wm_strut_change,
        "_NET_WM_WINDOW_OPACITY"        : _handle_opacity_change,
        "WM_HINTS"                      : _handle_wm_hints_change,
        "_GTK_APPLICATION_ID"           : _handle_gtk_app_menu_change,
        "_GTK_UNIQUE_BUS_NAME"          : _handle_gtk_app_menu_change,
        "_GTK_APPLICATION_OBJECT_PATH"  : _handle_gtk_app_menu_change,
        "_GTK_APP_MENU_OBJECT_PATH"     : _handle_gtk_app_menu_change,
        "_GTK_WINDOW_OBJECT_PATH"       : _handle_gtk_app_menu_change,
        })


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
    _state_properties = {
        "attention-requested"   : ("_NET_WM_STATE_DEMANDS_ATTENTION", ),
        "fullscreen"            : ("_NET_WM_STATE_FULLSCREEN", ),
        "maximized"             : ("_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"),
        "shaded"                : ("_NET_WM_STATE_SHADED", ),
        "above"                 : ("_NET_WM_STATE_ABOVE", ),
        "below"                 : ("_NET_WM_STATE_BELOW", ),
        "sticky"                : ("_NET_WM_STATE_STICKY", ),
        "skip-taskbar"          : ("_NET_WM_STATE_SKIP_TASKBAR", ),
        "skip-pager"            : ("_NET_WM_STATE_SKIP_PAGER", ),
        "modal"                 : ("_NET_WM_STATE_MODAL", ),
        "focused"               : ("_NET_WM_STATE_FOCUSED", ),
        }
    _state_properties_reversed = {}
    for k, states in _state_properties.iteritems():
        for x in states:
            _state_properties_reversed[x] = k

    def _state_add(self, *state_names):
        curr = set(self.get_property("state"))
        add = [s for s in state_names if s not in curr]
        if add:
            for x in add:
                curr.add(x)
            #note: _sync_state will update _NET_WM_STATE here:
            self._internal_set_property("state", frozenset(curr))
            self._state_notify(add)

    def _state_remove(self, *state_names):
        curr = set(self.get_property("state"))
        discard = [s for s in state_names if s in curr]
        if discard:
            for x in discard:
                curr.discard(x)
            #note: _sync_state will update _NET_WM_STATE here:
            self._internal_set_property("state", frozenset(curr))
            self._state_notify(discard)

    def _state_notify(self, state_names):
        notify_props = set()
        for x in state_names:
            if x in self._state_properties_reversed:
                notify_props.add(self._state_properties_reversed[x])
        for x in tuple(notify_props):
            self.notify(x)

    def _state_isset(self, state_name):
        return state_name in self.get_property("state")

    def _read_wm_state(self):
        wm_state = self.prop_get("_NET_WM_STATE", ["atom"])
        metalog("read _NET_WM_STATE=%s", wm_state)
        return wm_state or []


    def do_set_property(self, pspec, value):
        #intercept state properties to route via update_state()
        if pspec.name in self._state_properties:
            #virtual property for WM_STATE:
            self.update_state(pspec.name, value)
            return
        super(BaseWindowModel, self).do_set_property(pspec, value)

    def do_get_property(self, pspec):
        #intercept state properties to route via get_wm_state()
        if pspec.name in self._state_properties:
            #virtual property for WM_STATE:
            return self.get_wm_state(pspec.name)
        return super(BaseWindowModel, self).do_get_property(pspec)


    def update_wm_state(self, prop, b):
        state_names = self._state_properties.get(prop)
        assert state_names, "invalid window state %s" % prop
        if b:
            self._state_add(*state_names)
        else:
            self._state_remove(*state_names)

    def get_wm_state(self, prop):
        state_names = self._state_properties.get(prop)
        assert state_names, "invalid window state %s" % prop
        #this is a virtual property for WM_STATE:
        #return True if any is set (only relevant for maximized)
        for x in state_names:
            if self._state_isset(x):
                return True
        return False


    #########################################
    # X11 Events
    #########################################

    def process_client_message_event(self, event):
        # FIXME
        # Need to listen for:
        #   _NET_CURRENT_DESKTOP
        #   _NET_WM_PING responses
        # and maybe:
        #   _NET_RESTACK_WINDOW
        #   _NET_WM_STATE (more fully)

        if event.message_type=="_NET_WM_STATE":
            def update_wm_state(prop):
                current = self.get_property(prop)
                mode = event.data[0]
                if mode==_NET_WM_STATE_ADD:
                    v = True
                elif mode==_NET_WM_STATE_REMOVE:
                    v = False
                elif mode==_NET_WM_STATE_TOGGLE:
                    v = not bool(current)
                else:
                    log.warn("invalid mode for _NET_WM_STATE: %s", mode)
                    return
                log("process_client_message_event(%s) window %s=%s after %s (current state=%s)", event, prop, v, STATE_STRING.get(mode, mode), current)
                if v!=current:
                    self.update_wm_state(prop, v)
            atom1 = get_pyatom(event.window, event.data[1])
            log("_NET_WM_STATE: %s", atom1)
            if atom1=="_NET_WM_STATE_FULLSCREEN":
                update_wm_state("fullscreen")
            elif atom1=="_NET_WM_STATE_ABOVE":
                update_wm_state("above")
            elif atom1=="_NET_WM_STATE_BELOW":
                update_wm_state("below")
            elif atom1=="_NET_WM_STATE_SHADED":
                update_wm_state("shaded")
            elif atom1=="_NET_WM_STATE_STICKY":
                update_wm_state("sticky")
            elif atom1=="_NET_WM_STATE_SKIP_TASKBAR":
                update_wm_state("skip-taskbar")
            elif atom1=="_NET_WM_STATE_SKIP_PAGER":
                update_wm_state("skip-pager")
                get_pyatom(event.window, event.data[2])
            elif atom1 in ("_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"):
                atom2 = get_pyatom(event.window, event.data[2])
                #we only have one state for both, so we require both to be set:
                if atom1!=atom2 and atom2 in ("_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"):
                    update_wm_state("maximized")
            elif atom1=="_NET_WM_STATE_HIDDEN":
                log("ignoring 'HIDDEN' _NET_WM_STATE: %s", event)
                #we don't honour those because they make little sense, see:
                #https://mail.gnome.org/archives/wm-spec-list/2005-May/msg00004.html
            elif atom1=="_NET_WM_STATE_MODAL":
                update_wm_state("modal")
            elif atom1=="_NET_WM_STATE_DEMANDS_ATTENTION":
                update_wm_state("attention-requested")
            else:
                log.info("Unhandled _NET_WM_STATE request: '%s'", event, atom1)
                log.info(" event%s", event)
            return True
        elif event.message_type=="WM_CHANGE_STATE":
            iconic = event.data[0]
            log("WM_CHANGE_STATE: %s, serial=%s, last unmap serial=%#x", ICONIC_STATE_STRING.get(iconic, iconic), event.serial, self.last_unmap_serial)
            if iconic in (IconicState, NormalState) and self.serial_after_last_unmap(event.serial) and not self.is_OR() and not self.is_tray():
                self._updateprop("iconic", iconic==IconicState)
            return True
        elif event.message_type=="_NET_WM_MOVERESIZE":
            log("_NET_WM_MOVERESIZE: %s", event)
            self.emit("initiate-moveresize", event)
            return True
        elif event.message_type=="_NET_ACTIVE_WINDOW" and event.data[0] in (0, 1):
            log("_NET_ACTIVE_WINDOW: %s", event)
            self.set_active()
            self.emit("raised", event)
            return True
        elif event.message_type=="_NET_WM_DESKTOP":
            workspace = int(event.data[0])
            #query the workspace count on the root window
            #since we cannot access Wm from here..
            root = self.client_window.get_screen().get_root_window()
            ndesktops = prop_get(root, "_NET_NUMBER_OF_DESKTOPS", "u32", ignore_errors=True)
            workspacelog("received _NET_WM_DESKTOP: workspace=%s, number of desktops=%s", workspacestr(workspace), ndesktops)
            if ndesktops>0 and (workspace in (WORKSPACE_UNSET, WORKSPACE_ALL) or (workspace>=0 and workspace<ndesktops)):
                self.move_to_workspace(workspace)
            else:
                workspacelog.warn("invalid _NET_WM_DESKTOP request: workspace=%s, number of desktops=%s", workspacestr(workspace), ndesktops)
            return True
        elif event.message_type=="_NET_WM_FULLSCREEN_MONITORS":
            log("_NET_WM_FULLSCREEN_MONITORS: %s", event)
            #TODO: we should validate the indexes instead of copying them blindly!
            #TODO: keep track of source indication so we can forward that to the client
            m1, m2, m3, m4 = event.data[0], event.data[1], event.data[2], event.data[3]
            N = 16      #FIXME: arbitrary limit
            if m1<0 or m1>=N or m2<0 or m2>=N or m3<0 or m3>=N or m4<0 or m4>=N:
                log.warn("invalid list of _NET_WM_FULLSCREEN_MONITORS - ignored")
                return
            monitors = [m1, m2, m3, m4]
            log("_NET_WM_FULLSCREEN_MONITORS: monitors=%s", monitors)
            prop_set(self.client_window, "_NET_WM_FULLSCREEN_MONITORS", ["u32"], monitors)
            return True
        #TODO: maybe we should process _NET_MOVERESIZE_WINDOW here?
        # it may make sense to apply it to the client_window
        # whereas the code in WindowModel assumes there is a corral window
        #not handled:
        return CoreX11WindowModel.process_client_message_event(self, event)
