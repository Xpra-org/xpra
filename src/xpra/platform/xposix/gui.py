# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import struct
import binascii

from xpra.log import Logger
log = Logger("posix")
eventlog = Logger("posix", "events")
screenlog = Logger("posix", "screen")
dbuslog = Logger("posix", "dbus")
traylog = Logger("posix", "menu")
menulog = Logger("posix", "menu")
mouselog = Logger("posix", "mouse")

from xpra.os_util import strtobytes, bytestostr
from xpra.util import iround, envbool, csv
from xpra.gtk_common.gobject_compat import get_xid, is_gtk3

try:
    from xpra.x11.bindings.window_bindings import X11WindowBindings
    from xpra.x11.bindings.xi2_bindings import X11XI2Bindings   #@UnresolvedImport
except Exception as e:
    log.error("no X11 bindings", exc_info=True)
    X11WindowBindings = None
    X11XI2Bindings = None

device_bell = None
GTK_MENUS = envbool("XPRA_GTK_MENUS", False)
RANDR_DPI = envbool("XPRA_RANDR_DPI", True)
XSETTINGS_DPI = envbool("XPRA_XSETTINGS_DPI", True)
USE_NATIVE_TRAY = envbool("XPRA_USE_NATIVE_TRAY", True)


def hexstr(v):
    return binascii.hexlify(strtobytes(v))


def get_native_system_tray_classes():
    c = []
    if USE_NATIVE_TRAY:
        try:
            from xpra.platform.xposix.appindicator_tray import AppindicatorTray, can_use_appindicator
            if can_use_appindicator():
                c.append(AppindicatorTray)
        except Exception as e:
            traylog("cannot load appindicator tray: %s", e)
    return c

def get_wm_name():
    wm_name = os.environ.get("XDG_CURRENT_DESKTOP", "")
    try:
        wm_check = _get_X11_root_property("_NET_SUPPORTING_WM_CHECK", "WINDOW")
        if wm_check:
            xid = struct.unpack("=I", wm_check)[0]
            traylog("_NET_SUPPORTING_WM_CHECK window=%#x", xid)
            wm_name = _get_X11_window_property(xid, "_NET_WM_NAME", "UTF8_STRING")
            traylog("_NET_WM_NAME=%s", wm_name)
    except Exception as e:
        traylog.error("Error accessing window manager information:")
        traylog.error(" %s", e)
    return wm_name

def get_native_tray_classes():
    #could restrict to only DEs that have a broken system tray like "GNOME Shell"?
    if has_gtk_menu_support():  #and wm_name=="GNOME Shell":
        try:
            from xpra.platform.xposix.gtkmenu_tray import GTKMenuTray
            traylog("using GTKMenuTray for '%s' window manager", get_wm_name() or "unknown")
            return [GTKMenuTray]
        except Exception as e:
            traylog("cannot load gtk menu tray: %s", e)
    return get_native_system_tray_classes()


def get_native_notifier_classes():
    ncs = []
    try:
        from xpra.client.notifications.dbus_notifier import DBUS_Notifier_factory
        ncs.append(DBUS_Notifier_factory)
    except Exception as e:
        dbuslog("cannot load dbus notifier: %s", e)
    try:
        from xpra.client.notifications.pynotify_notifier import PyNotify_Notifier
        ncs.append(PyNotify_Notifier)
    except Exception as e:
        log("cannot load pynotify notifier: %s", e)
    return ncs


def get_session_type():
    return os.environ.get("XDG_SESSION_TYPE", "")


#we duplicate some of the code found in gtk_x11.prop ...
#which is still better than having dependencies on that GTK2 code
def _get_X11_window_property(xid, name, req_type):
    try:
        from xpra.gtk_common.error import xsync
        from xpra.x11.bindings.window_bindings import PropertyError #@UnresolvedImport
        try:
            X11Window = X11WindowBindings()
            with xsync:
                prop = X11Window.XGetWindowProperty(xid, name, req_type)
            log("_get_X11_window_property(%#x, %s, %s)=%s, len=%s", xid, name, req_type, type(prop), len(prop or []))
            return prop
        except PropertyError as e:
            log("_get_X11_window_property(%#x, %s, %s): %s", xid, name, req_type, e)
    except Exception as e:
        log.warn("failed to get X11 window property %s on window %#x: %s", name, xid, e)
        log("get_X11_window_property%s", (xid, name, req_type), exc_info=True)
    return None
def _get_X11_root_property(name, req_type):
    try:
        X11Window = X11WindowBindings()
        root_xid = X11Window.getDefaultRootWindow()
        return _get_X11_window_property(root_xid, name, req_type)
    except Exception as e:
        log.warn("Warning: failed to get X11 root property '%s'", name)
        log.warn(" %s", e)
    return None


def _set_gtk_x11_window_menu(add, wid, window, menus, application_action_callback=None, window_action_callback=None):
    from xpra.x11.dbus.menu import setup_dbus_window_menu
    from xpra.x11.gtk_x11.prop import prop_set, prop_del
    window_props = setup_dbus_window_menu(add, wid, menus, application_action_callback, window_action_callback)
    #window_props may contains X11 window properties we have to clear or set
    if not window_props:
        return
    if not window:
        #window has already been closed
        #(but we still want to call setup_dbus_window_menu above to ensure we clear things up!)
        return
    menulog("will set/remove the following window properties for wid=%i: %s", wid, window_props)
    try:
        from xpra.gtk_common.error import xsync
        with xsync:
            for k,v in window_props.items():
                if v is None:
                    prop_del(window, k)
                else:
                    vtype, value = v
                    prop_set(window, k, vtype, value)
    except Exception as e:
        menulog.error("Error setting menu window properties:")
        menulog.error(" %s", e)


_has_gtk_menu_support = None
def has_gtk_menu_support():
    global _has_gtk_menu_support
    if not GTK_MENUS:
        _has_gtk_menu_support = False
    if _has_gtk_menu_support is not None:
        return _has_gtk_menu_support
    try:
        from xpra.gtk_common.gtk_util import get_default_root_window
        from xpra.x11.dbus.menu import has_gtk_menu_support
        root = get_default_root_window()
        _has_gtk_menu_support = has_gtk_menu_support(root)
        menulog("has_gtk_menu_support(%s)=%s", root, _has_gtk_menu_support)
    except Exception as e:
        menulog("cannot enable gtk-x11 menu support: %s", e)
        _has_gtk_menu_support = False
    return _has_gtk_menu_support

def get_menu_support_function():
    if has_gtk_menu_support():
        return _set_gtk_x11_window_menu
    return None


def _get_xsettings():
    try:
        X11Window = X11WindowBindings()
        selection = "_XSETTINGS_S0"
        owner = X11Window.XGetSelectionOwner(selection)
        if not owner:
            return None
        XSETTINGS = "_XSETTINGS_SETTINGS"
        data = X11Window.XGetWindowProperty(owner, XSETTINGS, XSETTINGS)
        if not data:
            return None
        from xpra.x11.xsettings_prop import get_settings
        return get_settings(X11Window.get_display_name(), data)
    except Exception as e:
        log("_get_xsettings error: %s", e)
    return None

def _get_xsettings_dict():
    d = {}
    v = _get_xsettings()
    if v:
        _, values = v
        for setting_type, prop_name, value, _ in values:
            d[bytestostr(prop_name)] = (setting_type, value)
    return d


def _get_xsettings_dpi():
    if XSETTINGS_DPI:
        from xpra.x11.xsettings_prop import XSettingsTypeInteger
        d = _get_xsettings_dict()
        for k,div in {
            "Xft.dpi"         : 1,
            "Xft/DPI"         : 1024,
            "gnome.Xft/DPI"   : 1024,
            #"Gdk/UnscaledDPI" : 1024, ??
            }.items():
            if k in d:
                value_type, value = d.get(k)
                if value_type==XSettingsTypeInteger:
                    screenlog("_get_xsettings_dpi() found %s=%s", k, value)
                    return max(10, min(1000, value/div))
    return -1

def _get_randr_dpi():
    if RANDR_DPI:
        try:
            from xpra.x11.bindings.randr_bindings import RandRBindings  #@UnresolvedImport
            randr_bindings = RandRBindings()
            wmm, hmm = randr_bindings.get_screen_size_mm()
            w, h =  randr_bindings.get_screen_size()
            dpix = iround(w * 25.4 / wmm)
            dpiy = iround(h * 25.4 / hmm)
            screenlog("xdpi=%s, ydpi=%s - size-mm=%ix%i, size=%ix%i", dpix, dpiy, wmm, hmm, w, h)
            return dpix, dpiy
        except Exception as e:
            screenlog.warn("failed to get dpi: %s", e)
    return -1, -1

def get_xdpi():
    dpi = _get_xsettings_dpi()
    if dpi>0:
        return dpi
    return _get_randr_dpi()[0]

def get_ydpi():
    dpi = _get_xsettings_dpi()
    if dpi>0:
        return dpi
    return _get_randr_dpi()[1]


def get_icc_info():
    try:
        data = _get_X11_root_property("_ICC_PROFILE", "CARDINAL")
        if data:
            screenlog("_ICC_PROFILE=%s (%s)", type(data), len(data))
            version = _get_X11_root_property("_ICC_PROFILE_IN_X_VERSION", "CARDINAL")
            screenlog("get_icc_info() found _ICC_PROFILE_IN_X_VERSION=%s, _ICC_PROFILE=%s", hexstr(version or ""), hexstr(data))
            icc = {
                    "source"    : "_ICC_PROFILE",
                    "data"      : data,
                    }
            if version:
                try:
                    version = ord(version)
                except:
                    pass
                icc["version"] = version
            return icc
    except Exception as e:
        screenlog.error("Error: cannot access _ICC_PROFILE X11 window property")
        screenlog.error(" %s", e)
        screenlog("get_icc_info()", exc_info=True)
    return {}


def get_antialias_info():
    info = {}
    try:
        from xpra.x11.xsettings_prop import XSettingsTypeInteger, XSettingsTypeString
        d = _get_xsettings_dict()
        for prop_name, name in {"Xft/Antialias"    : "enabled",
                                "Xft/Hinting"      : "hinting"}.items():
            if prop_name in d:
                value_type, value = d.get(prop_name)
                if value_type==XSettingsTypeInteger and value>0:
                    info[name] = bool(value)
        def get_contrast(value):
            #win32 API uses numerical values:
            #(this is my best guess at translating the X11 names)
            return {"hintnone"      : 0,
                    "hintslight"    : 1000,
                    "hintmedium"    : 1600,
                    "hintfull"      : 2200}.get(value)
        for prop_name, name, convert in (
                                         ("Xft/HintStyle",  "hintstyle",    str),
                                         ("Xft/HintStyle",  "contrast",     get_contrast),
                                         ("Xft/RGBA",       "orientation",  lambda x : str(x).upper())
                                         ):
            if prop_name in d:
                value_type, value = d.get(prop_name)
                if value_type==XSettingsTypeString:
                    cval = convert(value)
                    if cval is not None:
                        info[name] = cval
    except Exception as e:
        screenlog.warn("failed to get antialias info from xsettings: %s", e)
    screenlog("get_antialias_info()=%s", info)
    return info


def get_current_desktop():
    v = -1
    d = None
    try:
        d = _get_X11_root_property("_NET_CURRENT_DESKTOP", "CARDINAL")
        if d:
            v = struct.unpack("=I", d)[0]
    except Exception as e:
        log.warn("failed to get current desktop: %s", e)
    log("get_current_desktop() %s=%s", hexstr(d or ""), v)
    return v

def get_workarea():
    try:
        d = get_current_desktop()
        if d<0:
            return None
        workarea = _get_X11_root_property("_NET_WORKAREA", "CARDINAL")
        if not workarea:
            return None
        screenlog("get_workarea()=%s, len=%s", type(workarea), len(workarea))
        #workarea comes as a list of 4 CARDINAL dimensions (x,y,w,h), one for each desktop
        if len(workarea)<(d+1)*4*4:
            screenlog.warn("get_workarea() invalid _NET_WORKAREA value")
        else:
            cur_workarea = workarea[d*4*4:(d+1)*4*4]
            v = struct.unpack("=IIII", cur_workarea)
            screenlog("get_workarea() %s=%s", hexstr(cur_workarea), v)
            return v
    except Exception as e:
        screenlog.warn("failed to get workarea: %s", e)
    return None


def get_number_of_desktops():
    v = 1
    d = None
    try:
        d = _get_X11_root_property("_NET_NUMBER_OF_DESKTOPS", "CARDINAL")
        if d:
            v = struct.unpack("=I", d)[0]
    except Exception as e:
        screenlog.warn("failed to get number of desktop: %s", e)
    v = max(1, v)
    screenlog("get_number_of_desktops() %s=%s", hexstr(d or ""), v)
    return v

def get_desktop_names():
    v = ["Main"]
    d = None
    try:
        d = _get_X11_root_property("_NET_DESKTOP_NAMES", "UTF8_STRING")
        if d:
            v = d.split(b"\0")
            if len(v)>1 and v[-1]=="":
                v = v[:-1]
    except Exception as e:
        screenlog.warn("failed to get desktop names: %s", e)
    screenlog("get_desktop_names() %s=%s", hexstr(d or ""), v)
    return v


def get_vrefresh():
    try:
        from xpra.x11.bindings.randr_bindings import RandRBindings      #@UnresolvedImport
        randr = RandRBindings()
        v = randr.get_vrefresh()
    except Exception as e:
        screenlog.warn("failed to get VREFRESH: %s", e)
        v = -1
    screenlog("get_vrefresh()=%s", v)
    return v


def _get_xresources():
    try:
        from xpra.x11.gtk_x11.prop import prop_get
        import gtk.gdk
        root = gtk.gdk.get_default_root_window()
        v = prop_get(root, "RESOURCE_MANAGER", "latin1", ignore_errors=True)
        log("RESOURCE_MANAGER=%s", v)
        if v is None:
            return None
        value = v.decode("utf-8")
        #parse the resources into a dict:
        values={}
        options = value.split("\n")
        for option in options:
            if not option:
                continue
            parts = option.split(":\t", 1)
            if len(parts)!=2:
                log("skipped invalid option: '%s'", option)
                continue
            values[parts[0]] = parts[1]
        return values
    except Exception as e:
        log("_get_xresources error: %s", e)
    return None

def get_cursor_size():
    d = _get_xresources() or {}
    try:
        return int(d.get("Xcursor.size", 0))
    except:
        return -1


def _get_xsettings_int(name, default_value):
    d = _get_xsettings_dict()
    if name not in d:
        return default_value
    value_type, value = d.get(name)
    from xpra.x11.xsettings_prop import XSettingsTypeInteger
    if value_type!=XSettingsTypeInteger:
        return default_value
    return value

def get_double_click_time():
    return _get_xsettings_int("Net/DoubleClickTime", -1)

def get_double_click_distance():
    v = _get_xsettings_int("Net/DoubleClickDistance", -1)
    return v, v

def get_window_frame_sizes():
    #for X11, have to create a window and then check the
    #_NET_FRAME_EXTENTS value after sending a _NET_REQUEST_FRAME_EXTENTS message,
    #so this is done in the gtk client instead of here...
    return {}


def system_bell(window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
    from xpra.gtk_common.error import XError
    global device_bell
    if device_bell is False:
        #failed already
        return False
    def x11_bell():
        global device_bell
        if device_bell is None:
            #try to load it:
            from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings       #@UnresolvedImport
            device_bell = X11KeyboardBindings().device_bell
        device_bell(get_xid(window), device, bell_class, bell_id, percent, bell_name)
    try:
        from xpra.gtk_common.error import xsync
        with xsync:
            x11_bell()
        return  True
    except XError as e:
        log.error("error using device_bell: %s, switching native X11 bell support off", e)
        device_bell = False
        return False


def _send_client_message(window, message_type, *values):
    try:
        from xpra.x11.gtk2 import gdk_display_source
        assert gdk_display_source
        from xpra.x11.bindings.window_bindings import constants #@UnresolvedImport
        X11Window = X11WindowBindings()
        root_xid = X11Window.getDefaultRootWindow()
        if window:
            xid = get_xid(window)
        else:
            xid = root_xid
        SubstructureNotifyMask = constants["SubstructureNotifyMask"]
        SubstructureRedirectMask = constants["SubstructureRedirectMask"]
        event_mask = SubstructureNotifyMask | SubstructureRedirectMask
        X11Window.sendClientMessage(root_xid, xid, False, event_mask, message_type, *values)
    except Exception as e:
        log.warn("failed to send client message '%s' with values=%s: %s", message_type, values, e)

def show_desktop(b):
    _send_client_message(None, "_NET_SHOWING_DESKTOP", int(bool(b)))

def set_fullscreen_monitors(window, fsm, source_indication=0):
    if type(fsm) not in (tuple, list):
        log.warn("invalid type for fullscreen-monitors: %s", type(fsm))
        return
    if len(fsm)!=4:
        log.warn("invalid number of fullscreen-monitors: %s", len(fsm))
        return
    values = list(fsm)+[source_indication]
    _send_client_message(window, "_NET_WM_FULLSCREEN_MONITORS", *values)

def _toggle_wm_state(window, state, enabled):
    if enabled:
        action = 1  #"_NET_WM_STATE_ADD"
    else:
        action = 0  #"_NET_WM_STATE_REMOVE"
    _send_client_message(window, "_NET_WM_STATE", action, state)

def set_shaded(window, shaded):
    _toggle_wm_state(window, "_NET_WM_STATE_SHADED", shaded)



WINDOW_ADD_HOOKS = []
def add_window_hooks(window):
    global WINDOW_ADD_HOOKS
    for x in WINDOW_ADD_HOOKS:
        x(window)
    log("add_window_hooks(%s) added %s", window, WINDOW_ADD_HOOKS)

WINDOW_REMOVE_HOOKS = []
def remove_window_hooks(window):
    global WINDOW_REMOVE_HOOKS
    for x in WINDOW_REMOVE_HOOKS:
        x(window)
    log("remove_window_hooks(%s) added %s", window, WINDOW_REMOVE_HOOKS)


def get_info():
    from xpra.platform.gui import get_info_base
    i = get_info_base()
    s = _get_xsettings()
    if s:
        serial, values = s
        xi = {"serial"  : serial}
        for _,name,value,_ in values:
            xi[bytestostr(name)] = value
        i["xsettings"] = xi
    i.setdefault("dpi", {
                         "xsettings"    : _get_xsettings_dpi(),
                         "randr"        : _get_randr_dpi()
                         })
    return i


class XI2_Window(object):
    def __init__(self, window):
        log("XI2_Window(%s)", window)
        self.XI2 = X11XI2Bindings()
        self.X11Window = X11WindowBindings()
        self.window = window
        self.xid = window.get_window().xid
        self.windows = ()
        window.connect("configure-event", self.configured)
        self.configured()
        #replace event handlers with XI2 version:
        self.do_motion_notify_event = window.do_motion_notify_event
        window.do_motion_notify_event = self.noop
        window.do_button_press_event = self.noop
        window.do_button_release_event = self.noop
        window.do_scroll_event = self.noop
        window.connect("destroy", self.cleanup)

    def noop(self, *args):
        pass

    def cleanup(self, *args):
        for window in self.windows:
            self.XI2.disconnect(window)
        self.windows = []
        self.window = None

    def configured(self, *args):
        self.windows = self.get_parent_windows(self.xid)
        for window in self.windows:
            self.XI2.connect(window, "XI_Motion", self.do_xi_motion)
            self.XI2.connect(window, "XI_ButtonPress", self.do_xi_button)
            self.XI2.connect(window, "XI_ButtonRelease", self.do_xi_button)

    def get_parent_windows(self, oxid):
        windows = [oxid]
        root = self.X11Window.getDefaultRootWindow()
        xid = oxid
        while True:
            xid = self.X11Window.getParent(xid)
            if xid==0 or xid==root:
                break
            windows.append(xid)
        log("get_parent_windows(%#x)=%s", oxid, csv(hex(x) for x in windows))
        return windows


    def do_xi_button(self, event):
        window = self.window
        client = window._client
        if client.readonly:
            return
        if client.server_input_devices=="xi":
            #skip synthetic scroll events for two-finger scroll,
            #as the server should synthesize them from the motion events 
            #those have the same serial:
            matching_motion = self.XI2.find_event("XI_Motion", event.serial)
            #maybe we need more to distinguish?
            if matching_motion:
                return
        button = event.detail
        depressed = (event.name == "XI_ButtonPress")
        args = self.get_pointer_extra_args(event)
        window._button_action(button, event, depressed, *args)

    def do_xi_motion(self, event):
        window = self.window
        if window.moveresize_event:
            window.motion_moveresize(event)
            self.do_motion_notify_event(event)
            return
        if window._client.readonly:
            return
        #find the motion events in the xi2 event list:
        pointer, modifiers, buttons = window._pointer_modifiers(event)
        wid = self.window.get_mouse_event_wid(*pointer)
        mouselog("do_motion_notify_event(%s) wid=%s / focus=%s / window wid=%i, device=%s, pointer=%s, modifiers=%s, buttons=%s", event, wid, window._client._focused, self.window._id, event.device, pointer, modifiers, buttons)
        packet = ["pointer-position", wid, pointer, modifiers, buttons] + self.get_pointer_extra_args(event)
        window._client.send_mouse_position(packet)

    def get_pointer_extra_args(self, event):
        def intscaled(f):
            return int(f*1000000), 1000000
        def dictscaled(v):
            return dict((k,intscaled(v)) for k,v in v.items())
        raw_valuators = {}
        raw_event_name = event.name.replace("XI_", "XI_Raw")    #ie: XI_Motion -> XI_RawMotion
        raw = self.XI2.find_event(raw_event_name, event.serial)
        #mouselog("raw(%s)=%s", raw_event_name, raw)
        if raw:
            raw_valuators = raw.raw_valuators
        args = [event.device]
        for x in ("x", "y", "x_root", "y_root"):
            args.append(intscaled(getattr(event, x)))
        for v in [event.valuators, raw_valuators]:
            args.append(dictscaled(v))
        return args


class ClientExtras(object):
    def __init__(self, client, opts):
        self.client = client
        self._xsettings_watcher = None
        self._root_props_watcher = None
        self.system_bus = None
        self.upower_resuming_match = None
        self.upower_sleeping_match = None
        self.login1_match = None
        self.x11_filter = None
        if client.xsettings_enabled:
            self.setup_xprops()
        if client.input_devices=="xi":
            #this would trigger warnings with our temporary opengl windows:
            #only enable it after we have connected:
            self.client.after_handshake(self.setup_xi)
        self.setup_dbus_signals()

    def ready(self):
        pass

    def init_x11_filter(self):
        if self.x11_filter:
            return
        try:
            from xpra.x11.gtk2.gdk_bindings import init_x11_filter  #@UnresolvedImport
            self.x11_filter = init_x11_filter()
            log("x11_filter=%s", self.x11_filter)
        except:
            self.x11_filter = None

    def cleanup(self):
        log("cleanup() xsettings_watcher=%s, root_props_watcher=%s", self._xsettings_watcher, self._root_props_watcher)
        if self.x11_filter:
            from xpra.x11.gtk2.gdk_bindings import cleanup_x11_filter   #@UnresolvedImport
            self.x11_filter = None
            cleanup_x11_filter()
        if self._xsettings_watcher:
            self._xsettings_watcher.cleanup()
            self._xsettings_watcher = None
        if self._root_props_watcher:
            self._root_props_watcher.cleanup()
            self._root_props_watcher = None
        if self.system_bus:
            bus = self.system_bus
            log("cleanup() system bus=%s, matches: %s", bus, (self.upower_resuming_match, self.upower_sleeping_match, self.login1_match))
            self.system_bus = None
            if self.upower_resuming_match:
                bus._clean_up_signal_match(self.upower_resuming_match)
            if self.upower_sleeping_match:
                bus._clean_up_signal_match(self.upower_sleeping_match)
            if self.login1_match:
                bus._clean_up_signal_match(self.login1_match)
        global WINDOW_METHOD_OVERRIDES
        WINDOW_METHOD_OVERRIDES = {}

    def resuming_callback(self, *args):
        eventlog("resuming_callback%s", args)
        self.client.resume()

    def sleeping_callback(self, *args):
        eventlog("sleeping_callback%s", args)
        self.client.suspend()


    def setup_dbus_signals(self):
        try:
            import xpra.dbus
            assert xpra.dbus
        except ImportError as e:
            dbuslog("setup_dbus_signals()", exc_info=True)
            dbuslog.info("dbus support is not installed")
            dbuslog.info(" no support for power events")
            return
        try:
            from xpra.dbus.common import init_system_bus
            bus = init_system_bus()
            self.system_bus = bus
            dbuslog("setup_dbus_signals() system bus=%s", bus)
        except Exception as e:
            dbuslog("setup_dbus_signals()", exc_info=True)
            dbuslog.error("Error setting up dbus signals:")
            dbuslog.error(" %s", e)
            return

        #the UPower signals:
        try:
            bus_name    = 'org.freedesktop.UPower'
            dbuslog("bus has owner(%s)=%s", bus_name, bus.name_has_owner(bus_name))
            iface_name  = 'org.freedesktop.UPower'
            self.upower_resuming_match = bus.add_signal_receiver(self.resuming_callback, 'Resuming', iface_name, bus_name)
            self.upower_sleeping_match = bus.add_signal_receiver(self.sleeping_callback, 'Sleeping', iface_name, bus_name)
            dbuslog("listening for 'Resuming' and 'Sleeping' signals on %s", iface_name)
        except Exception as e:
            dbuslog("failed to setup UPower event listener: %s", e)

        #the "logind" signals:
        try:
            bus_name    = 'org.freedesktop.login1'
            dbuslog("bus has owner(%s)=%s", bus_name, bus.name_has_owner(bus_name))
            def sleep_event_handler(suspend):
                if suspend:
                    self.sleeping_callback()
                else:
                    self.resuming_callback()
            iface_name  = 'org.freedesktop.login1.Manager'
            self.login1_match = bus.add_signal_receiver(sleep_event_handler, 'PrepareForSleep', iface_name, bus_name)
            dbuslog("listening for 'PrepareForSleep' signal on %s", iface_name)
        except Exception as e:
            dbuslog("failed to setup login1 event listener: %s", e)

    def setup_xprops(self):
        #wait for handshake to complete:
        self.client.after_handshake(self.do_setup_xprops)

    def do_setup_xprops(self, *args):
        log("do_setup_xprops(%s)", args)
        if is_gtk3():
            log("x11 root properties and XSETTINGS are not supported yet with GTK3")
            return
        ROOT_PROPS = ["RESOURCE_MANAGER", "_NET_WORKAREA", "_NET_CURRENT_DESKTOP"]
        try:
            self.init_x11_filter()
            from xpra.x11.xsettings import XSettingsWatcher
            from xpra.x11.xroot_props import XRootPropWatcher
            if self._xsettings_watcher is None:
                self._xsettings_watcher = XSettingsWatcher()
                self._xsettings_watcher.connect("xsettings-changed", self._handle_xsettings_changed)
                self._handle_xsettings_changed()
            if self._root_props_watcher is None:
                self._root_props_watcher = XRootPropWatcher(ROOT_PROPS)
                self._root_props_watcher.connect("root-prop-changed", self._handle_root_prop_changed)
                #ensure we get the initial value:
                self._root_props_watcher.do_notify("RESOURCE_MANAGER")
        except ImportError as e:
            log.error("failed to load X11 properties/settings bindings: %s - root window properties will not be propagated", e)


    def do_xi_devices_changed(self, event):
        log("do_xi_devices_changed(%s)", event)
        XI2 = X11XI2Bindings()
        devices = XI2.get_devices()
        if devices:
            self.client.send_input_devices("xi", devices)

    def setup_xi(self):
        if self.client.server_input_devices!="xi":
            log.info("server does not support xi input devices")
        try:
            from xpra.gtk_common.error import xsync
            with xsync:
                assert X11WindowBindings, "no X11 window bindings"
                assert X11XI2Bindings, "no XI2 window bindings"
                X11XI2Bindings().gdk_inject()
                self.init_x11_filter()
                XI2 = X11XI2Bindings()
                XI2.select_xi2_events()
                if self.client.server_input_devices:
                    XI2.connect(0, "XI_HierarchyChanged", self.do_xi_devices_changed)
                    devices = XI2.get_devices()
                    if devices:
                        self.client.send_input_devices("xi", devices)
        except Exception as e:
            log("enable_xi2()", exc_info=True)
            log.error("Error: cannot enable XI2 events")
            log.error(" %s", e)
        else:
            #register our enhanced event handlers:
            self.add_xi2_method_overrides()

    def add_xi2_method_overrides(self):
        global WINDOW_ADD_HOOKS
        WINDOW_ADD_HOOKS = [XI2_Window]


    def _get_xsettings(self):
        try:
            return self._xsettings_watcher.get_settings()
        except:
            log.error("failed to get XSETTINGS", exc_info=True)
        return None

    def _handle_xsettings_changed(self, *args):
        settings = self._get_xsettings()
        log("xsettings_changed new value=%s", settings)
        if settings is not None:
            self.client.send("server-settings", {"xsettings-blob": settings})

    def get_resource_manager(self):
        try:
            import gtk.gdk
            root = gtk.gdk.get_default_root_window()
            from xpra.x11.gtk_x11.prop import prop_get
            value = prop_get(root, "RESOURCE_MANAGER", "latin1", ignore_errors=True)
            if value is not None:
                return value.encode("utf-8")
        except:
            log.error("failed to get RESOURCE_MANAGER", exc_info=True)
        return None

    def _handle_root_prop_changed(self, obj, prop):
        log("root_prop_changed(%s, %s)", obj, prop)
        if prop=="RESOURCE_MANAGER":
            rm = self.get_resource_manager()
            if rm is not None:
                self.client.send("server-settings", {"resource-manager" : rm})
        elif prop=="_NET_WORKAREA":
            self.client.screen_size_changed("from %s event" % self._root_props_watcher)
        elif prop=="_NET_CURRENT_DESKTOP":
            self.client.workspace_changed("from %s event" % self._root_props_watcher)
        elif prop in ("_NET_DESKTOP_NAMES", "_NET_NUMBER_OF_DESKTOPS"):
            self.client.desktops_changed("from %s event" % self._root_props_watcher)
        else:
            log.error("unknown property %s", prop)


def main():
    try:
        from xpra.x11.gtk2 import gdk_display_source
        assert gdk_display_source
    except:
        pass
    from xpra.platform.gui import main
    main()


if __name__ == "__main__":
    sys.exit(main())
