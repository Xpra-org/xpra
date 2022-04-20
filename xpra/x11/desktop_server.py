# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2016-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket
from collections import namedtuple
from gi.repository import GObject, Gdk, Gio, GLib

from xpra.os_util import get_generic_os_name, load_binary_file
from xpra.scripts.config import FALSE_OPTIONS
from xpra.util import updict, log_screen_sizes, envbool, csv
from xpra.platform.paths import get_icon, get_icon_filename
from xpra.platform.gui import get_wm_name
from xpra.server import server_features
from xpra.server.mixins.window_server import WindowsMixin
from xpra.gtk_common.gobject_util import one_arg_signal, no_arg_signal
from xpra.gtk_common.error import XError
from xpra.gtk_common.gtk_util import get_screen_sizes, get_root_size
from xpra.x11.vfb_util import parse_resolution
from xpra.x11.models.model_stub import WindowModelStub
from xpra.x11.gtk_x11.gdk_bindings import (
    add_catchall_receiver, remove_catchall_receiver,
    add_event_receiver,          #@UnresolvedImport
   )
from xpra.x11.bindings.window_bindings import X11WindowBindings #@UnresolvedImport
from xpra.x11.xroot_props import XRootPropWatcher
from xpra.x11.gtk_x11.window_damage import WindowDamageHandler
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings #@UnresolvedImport
from xpra.x11.bindings.randr_bindings import RandRBindings #@UnresolvedImport
from xpra.x11.x11_server_base import X11ServerBase, mouselog
from xpra.rectangle import rectangle  #@UnresolvedImport
from xpra.gtk_common.error import xsync, xlog
from xpra.log import Logger

log = Logger("server")

X11Window = X11WindowBindings()
X11Keyboard = X11KeyboardBindings()
RandR = RandRBindings()

windowlog = Logger("server", "window")
geomlog = Logger("server", "window", "geometry")
metadatalog = Logger("x11", "metadata")
screenlog = Logger("screen")
iconlog = Logger("icon")

MODIFY_GSETTINGS = envbool("XPRA_MODIFY_GSETTINGS", True)
MULTI_MONITORS = envbool("XPRA_DESKTOP_MULTI_MONITORS", True)

MIN_SIZE = 640, 350
MAX_SIZE = 8192, 8192


class DesktopModel(WindowModelStub, WindowDamageHandler):
    __common_gsignals__ = {}
    __common_gsignals__.update(WindowDamageHandler.__common_gsignals__)
    __common_gsignals__.update({
                         "resized"                  : no_arg_signal,
                         "client-contents-changed"  : one_arg_signal,
                         })

    __gproperties__ = {
        "iconic": (GObject.TYPE_BOOLEAN,
                   "ICCCM 'iconic' state -- any sort of 'not on desktop'.", "",
                   False,
                   GObject.ParamFlags.READWRITE),
        "focused": (GObject.TYPE_BOOLEAN,
                       "Is the window focused", "",
                       False,
                       GObject.ParamFlags.READWRITE),
        "size-hints": (GObject.TYPE_PYOBJECT,
                       "Client hints on constraining its size", "",
                       GObject.ParamFlags.READABLE),
        "wm-name": (GObject.TYPE_PYOBJECT,
                       "The name of the window manager or session manager", "",
                       GObject.ParamFlags.READABLE),
        "icons": (GObject.TYPE_PYOBJECT,
                       "The icon of the window manager or session manager", "",
                       GObject.ParamFlags.READABLE),
        }

    _property_names         = [
        "client-machine", "window-type",
        "shadow", "size-hints", "class-instance",
        "focused", "title", "depth", "icons",
        "content-type",
        "set-initial-position",
        ]
    _dynamic_property_names = ["size-hints", "title", "icons"]

    def __init__(self):
        display = Gdk.Display.get_default()
        screen = display.get_screen(0)
        root = screen.get_root_window()
        WindowDamageHandler.__init__(self, root)
        WindowModelStub.__init__(self)
        self.update_icon()
        self.resize_timer = None
        self.resize_value = None

    def setup(self):
        WindowDamageHandler.setup(self)
        self._depth = X11Window.get_depth(self.client_window.get_xid())
        self._managed = True
        self._setup_done = True

    def unmanage(self, exiting=False):
        WindowDamageHandler.destroy(self)
        WindowModelStub.unmanage(self, exiting)
        self.cancel_resize_timer()
        self._managed = False

    def update_wm_name(self):
        try:
            wm_name = get_wm_name()     #pylint: disable=assignment-from-none
        except Exception:
            wm_name = ""
        iconlog("update_wm_name() wm-name=%s", wm_name)
        return self._updateprop("wm-name", wm_name)

    def update_icon(self):
        icons = None
        try:
            wm_name = get_wm_name()     #pylint: disable=assignment-from-none
            if not wm_name:
                return
            icon_name = get_icon_filename(wm_name.lower()+".png")
            from PIL import Image
            img = Image.open(icon_name)
            iconlog("Image(%s)=%s", icon_name, img)
            if img:
                icon_data = load_binary_file(icon_name)
                assert icon_data
                w, h = img.size
                icon = (w, h, "png", icon_data)
                icons = (icon,)
        except Exception:
            iconlog("failed to return window icon", exc_info=True)
        self._updateprop("icons", icons)

    def uses_XShm(self):
        return bool(self._xshm_handle)

    def get_default_window_icon(self, _size):
        icon_name = get_generic_os_name()+".png"
        icon = get_icon(icon_name)
        if not icon:
            return None
        return icon.get_width(), icon.get_height(), "RGBA", icon.get_pixels()

    def get_title(self):
        return get_wm_name() or "xpra desktop"

    def get_property(self, prop):
        if prop=="depth":
            return self._depth
        if prop=="title":
            return self.get_title()
        if prop=="client-machine":
            return socket.gethostname()
        if prop=="window-type":
            return ["NORMAL"]
        if prop=="shadow":
            return True
        if prop=="class-instance":
            return ("xpra-desktop", "Xpra-Desktop")
        if prop=="content-type":
            return "desktop"
        if prop=="set-initial-position":
            return False
        return GObject.GObject.get_property(self, prop)

    def do_xpra_damage_event(self, event):
        self.emit("client-contents-changed", event)


    def resize(self, w, h):
        geomlog("resize(%i, %i)", w, h)
        if not RandR.has_randr():
            geomlog.error("Error: cannot honour resize request,")
            geomlog.error(" no RandR support on this display")
            return
        #FIXME: small race if the user resizes with randr,
        #at the same time as he resizes the window..
        self.resize_value = (w, h)
        if not self.resize_timer:
            self.resize_timer = GLib.timeout_add(250, self.do_resize)

    def do_resize(self):
        raise NotImplementedError

    def cancel_resize_timer(self):
        rt = self.resize_timer
        if rt:
            self.resize_timer = None
            GLib.source_remove(rt)


class ScreenDesktopModel(DesktopModel):
    """
    A desktop model covering the entire screen as a single window.
    """
    __gsignals__ = dict(DesktopModel.__common_gsignals__)
    _property_names         = DesktopModel._property_names+["xid"]
    _dynamic_property_names = ["size-hints", "title", "icons"]

    def __init__(self, resize_exact=False):
        super().__init__()
        self.resize_exact = resize_exact

    def __repr__(self):
        return "ScreenDesktopModel(%#x)" % self.client_window.get_xid()


    def setup(self):
        super().setup()
        screen = self.client_window.get_screen()
        screen.connect("size-changed", self._screen_size_changed)
        self.update_size_hints(screen)


    def get_geometry(self):
        return self.client_window.get_geometry()[:4]

    def get_dimensions(self):
        return self.client_window.get_geometry()[2:4]


    def get_property(self, prop):
        if prop=="xid":
            return int(self.client_window.get_xid())
        return super().get_property(prop)


    def do_resize(self):
        self.resize_timer = None
        rw, rh = self.resize_value
        try:
            with xsync:
                ow, oh = RandR.get_screen_size()
            w, h = self.set_screen_size(rw, rh, False)
            if (ow, oh) == (w, h):
                #this is already the resolution we have,
                #but the client has other ideas,
                #so tell the client we ain't budging:
                self.emit("resized")
        except Exception as e:
            geomlog("do_resize() %ix%i", rw, rh, exc_info=True)
            geomlog.error("Error: failed to resize desktop display to %ix%i:", rw, rh)
            geomlog.error(" %s", str(e) or type(e))

    def _screen_size_changed(self, screen):
        w, h = screen.get_width(), screen.get_height()
        screenlog("screen size changed: new size %ix%i", w, h)
        screenlog("root window geometry=%s", self.client_window.get_geometry())
        self.invalidate_pixmap()
        self.update_size_hints(screen)
        self.emit("resized")

    def update_size_hints(self, screen):
        w, h = screen.get_width(), screen.get_height()
        screenlog("screen dimensions: %ix%i", w, h)
        size_hints = {}
        def use_fixed_size():
            size = w, h
            size_hints.update({
                "maximum-size"  : size,
                "minimum-size"  : size,
                "base-size"     : size,
                })
        if RandR.has_randr():
            if self.resize_exact:
                #assume resize_exact is enabled
                #no size restrictions
                size_hints = {}
            else:
                try:
                    with xsync:
                        screen_sizes = RandR.get_xrr_screen_sizes()
                except XError:
                    screenlog("failed to query screen sizes", exc_info=True)
                else:
                    if not screen_sizes:
                        use_fixed_size()
                    else:
                        #find the maximum size supported:
                        max_size = {}
                        for tw, th in screen_sizes:
                            max_size[tw*th] = (tw, th)
                        max_pixels = sorted(max_size.keys())[-1]
                        size_hints["maximum-size"] = max_size[max_pixels]
                        #find the best increment we can use:
                        inc_hits = {}
                        #we should also figure out what the potential increments are,
                        #rather than hardcoding them here:
                        INC_VALUES = (16, 32, 64, 128, 256)
                        for inc in INC_VALUES:
                            hits = 0
                            for tsize in screen_sizes:
                                tw, th = tsize
                                if (tw+inc, th+inc) in screen_sizes:
                                    hits += 1
                            inc_hits[inc] = hits
                        screenlog("size increment hits: %s", inc_hits)
                        max_hits = max(inc_hits.values())
                        if max_hits>16:
                            #find the first increment value matching the max hits
                            for inc in INC_VALUES:
                                if inc_hits[inc]==max_hits:
                                    break
                            #TODO: also get these values from the screen sizes:
                            size_hints.update({
                                "base-size"             : (640, 640),
                                "minimum-size"          : (640, 640),
                                "increment"             : (128, 128),
                                "minimum-aspect-ratio"  : (1, 3),
                                "maximum-aspect-ratio"  : (3, 1),
                                })
        else:
            use_fixed_size()
        screenlog("size-hints=%s", size_hints)
        self._updateprop("size-hints", size_hints)

GObject.type_register(ScreenDesktopModel)


MonitorDamageNotify = namedtuple("MonitorDamageNotify", "x,y,width,height")


class MonitorDesktopModel(DesktopModel):
    """
    A desktop model representing a single monitor
    """
    __gsignals__ = dict(DesktopModel.__common_gsignals__)

    #bump the number of receivers,
    #because we add all the monitor models as receivers for the root window:
    MAX_RECEIVERS = 20

    def __repr__(self):
        return "MonitorDesktopModel(%s : %s)" % (self.name, self.monitor_geometry)

    def __init__(self, monitor):
        super().__init__()
        self.init(monitor)

    def init(self, monitor):
        self.name = monitor.get("name", "")
        self.resize_delta = 0, 0
        x = monitor.get("x", 0)
        y = monitor.get("y", 0)
        width = monitor.get("width", 0)
        height = monitor.get("height", 0)
        self.monitor_geometry = (x, y, width, height)
        self._updateprop("size-hints", {
            "minimum-size"          : MIN_SIZE,
            "maximum-size"          : MAX_SIZE,
            })

    def get_title(self):
        title = get_wm_name()  # pylint: disable=assignment-from-none
        if self.name:
            if not title:
                return self.name
            title += " on %s" % self.name
        return title

    def get_geometry(self):
        return self.monitor_geometry

    def get_dimensions(self):
        return self.monitor_geometry[2:4]


    def get_definition(self):
        x, y, width, height = self.monitor_geometry
        return {
            "x"         : x,
            "y"         : y,
            "width"     : width,
            "height"    : height,
            "name"      : self.name,
            }


    def do_xpra_damage_event(self, event):
        #ie: <X11:DamageNotify {'send_event': '0', 'serial': '0x4da', 'delivered_to': '0x56e', 'window': '0x56e',
        #                       'damage': '2097157', 'x': '313', 'y': '174', 'width': '6', 'height': '13'}>)
        damaged_area = rectangle(event.x, event.y, event.width, event.height)
        x, y, width, height = self.monitor_geometry
        monitor_damaged_area = damaged_area.intersection(x, y, width, height)
        if monitor_damaged_area:
            #use an event relative to this monitor's coordinates:
            mod_event = MonitorDamageNotify(monitor_damaged_area.x-x, monitor_damaged_area.y-y,
                                            monitor_damaged_area.width, monitor_damaged_area.height)
            self.emit("client-contents-changed", mod_event)

    def get_image(self, x, y, width, height):
        #adjust the coordinates with the monitor's position:
        mx, my = self.monitor_geometry[:2]
        image = super().get_image(mx+x, my+y, width, height)
        if image:
            image.set_target_x(x)
            image.set_target_y(y)
        return image


    def do_resize(self):
        self.resize_timer = None
        saved_width = self.monitor.get("width", 0)
        saved_height = self.monitor.get("height", 0)
        width, height = self.resize_value
        self.monitor.update({
            "width" : width,
            "height" : height,
            })
        self.resize_delta = width-saved_width, height-saved_height
        x = self.monitor.get("x", 0)
        y = self.monitor.get("y", 0)
        self.monitor_geometry = (x, y, width, height)
        self.emit("resized")


GObject.type_register(MonitorDesktopModel)


DESKTOPSERVER_BASES = [GObject.GObject]
if server_features.rfb:
    from xpra.server.rfb.rfb_server import RFBServer
    DESKTOPSERVER_BASES.append(RFBServer)
DESKTOPSERVER_BASES.append(X11ServerBase)
DESKTOPSERVER_BASES = tuple(DESKTOPSERVER_BASES)
DesktopServerBaseClass = type('DesktopServerBaseClass', DESKTOPSERVER_BASES, {})
log("DesktopServerBaseClass%s", DESKTOPSERVER_BASES)


class XpraDesktopServer(DesktopServerBaseClass):
    """
        A server class for RFB / VNC-like desktop displays,
        used with the "start-desktop" subcommand.
    """
    __gsignals__ = {
        "xpra-xkb-event"        : one_arg_signal,
        "xpra-cursor-event"     : one_arg_signal,
        "xpra-motion-event"     : one_arg_signal,
        }

    def __init__(self):
        X11ServerBase.__init__(self)
        for c in DESKTOPSERVER_BASES:
            if c!=X11ServerBase:
                c.__init__(self)
        self.session_type = "desktop"
        self.multi_monitors = False
        if MULTI_MONITORS:
            with xlog:
                self.multi_monitors = RandR.is_dummy16()
        self.gsettings_modified = {}
        self.root_prop_watcher = None

    def init(self, opts):
        for c in DESKTOPSERVER_BASES:
            if c!=GObject.GObject:
                c.init(self, opts)

    def server_init(self):
        X11ServerBase.server_init(self)
        from xpra.x11.vfb_util import set_initial_resolution, DEFAULT_DESKTOP_VFB_RESOLUTIONS
        screenlog("server_init() randr=%s, multi-monitors=%s, initial-resolutions=%s, default-resolutions=%s",
                       self.randr, self.multi_monitors, self.initial_resolutions, DEFAULT_DESKTOP_VFB_RESOLUTIONS)
        if not self.randr or self.initial_resolutions==():
            return
        res = self.initial_resolutions or DEFAULT_DESKTOP_VFB_RESOLUTIONS
        if not self.multi_monitors and len(res)>1:
            log.warn("Warning: cannot set vfb resolution to %s", res)
            log.warn(" multi monitor mode is not enabled")
            log.warn(" using %r", res[0])
            res = (res[0], )
        with xlog:
            set_initial_resolution(res)

    def x11_init(self):
        X11ServerBase.x11_init(self)
        display = Gdk.Display.get_default()
        assert display.get_n_screens()==1
        screen = display.get_screen(0)
        root = screen.get_root_window()
        add_event_receiver(root, self)
        add_catchall_receiver("xpra-motion-event", self)
        add_catchall_receiver("xpra-xkb-event", self)
        with xlog:
            X11Keyboard.selectBellNotification(True)
        if MODIFY_GSETTINGS:
            self.modify_gsettings()
        self.root_prop_watcher = XRootPropWatcher(["WINDOW_MANAGER", "_NET_SUPPORTING_WM_CHECK"], root)
        self.root_prop_watcher.connect("root-prop-changed", self.root_prop_changed)

    def root_prop_changed(self, watcher, prop):
        iconlog("root_prop_changed(%s, %s)", watcher, prop)
        for window in self._id_to_window.values():
            window.update_wm_name()
            window.update_icon()


    def modify_gsettings(self):
        #try to suspend animations:
        self.gsettings_modified = self.do_modify_gsettings({
            "org.mate.interface" : ("gtk-enable-animations", "enable-animations"),
            "org.gnome.desktop.interface" : ("enable-animations",),
            "com.deepin.wrap.gnome.desktop.interface" : ("enable-animations",),
            })

    def do_modify_gsettings(self, defs, value=False):
        modified = {}
        schemas = Gio.Settings.list_schemas()
        for schema, attributes in defs.items():
            if schema not in schemas:
                continue
            try:
                s = Gio.Settings.new(schema)
                restore = []
                for attribute in attributes:
                    v = s.get_boolean(attribute)
                    if v:
                        s.set_boolean(attribute, value)
                        restore.append(attribute)
                if restore:
                    modified[schema] = restore
            except Exception as e:
                log("error accessing schema '%s' and attributes %s", schema, attributes, exc_info=True)
                log.error("Error accessing schema '%s' and attributes %s:", schema, csv(attributes))
                log.error(" %s", e)
        return modified

    def do_cleanup(self):
        remove_catchall_receiver("xpra-motion-event", self)
        X11ServerBase.do_cleanup(self)
        if MODIFY_GSETTINGS:
            self.restore_gsettings()
        rpw = self.root_prop_watcher
        if rpw:
            self.root_prop_watcher = None
            rpw.cleanup()

    def restore_gsettings(self):
        self.do_modify_gsettings(self.gsettings_modified, True)

    def notify_dpi_warning(self, body):
        """ ignore DPI warnings in desktop mode """

    def print_screen_info(self):
        super().print_screen_info()
        root_w, root_h = get_root_size()
        log.info(" initial resolution: %ix%i", root_w, root_h)
        sss = get_screen_sizes()
        log_screen_sizes(root_w, root_h, sss)

    def parse_screen_info(self, ss):
        return self.do_parse_screen_info(ss, ss.desktop_mode_size)

    def do_screen_changed(self, screen):
        if self.multi_monitors:
            #TODO: update monitors
            pass

    def get_best_screen_size(self, desired_w, desired_h, bigger=False):
        return self.do_get_best_screen_size(desired_w, desired_h, bigger)

    def configure_best_screen_size(self):
        """ for the first client, honour desktop_mode_size if set """
        root_w, root_h = self.root_window.get_geometry()[2:4]
        if not self.randr:
            screenlog("configure_best_screen_size() no randr")
            return root_w, root_h
        sss = tuple(x for x in self._server_sources.values() if x.ui_client)
        if len(sss)!=1:
            screenlog.info("screen used by %i clients:", len(sss))
            return root_w, root_h
        ss = sss[0]
        requested_size = ss.desktop_mode_size
        if not requested_size:
            screenlog("configure_best_screen_size() client did not request a specific desktop mode size")
            return root_w, root_h
        w, h = requested_size
        screenlog("client requested desktop mode resolution is %sx%s (current server resolution is %sx%s)",
                  w, h, root_w, root_h)
        if w<=0 or h<=0 or w>=32768 or h>=32768:
            screenlog("configure_best_screen_size() client requested an invalid desktop mode size: %s", requested_size)
            return root_w, root_h
        return self.set_screen_size(w, h, ss.screen_resize_bigger)

    def resize(self, w, h):
        if self.multi_monitors:
            import traceback
            traceback.print_stack()
            return
        geomlog("resize(%i, %i)", w, h)
        if not RandR.has_randr():
            geomlog.error("Error: cannot honour resize request,")
            geomlog.error(" no RandR support on this display")
            return
        #FIXME: small race if the user resizes with randr,
        #at the same time as he resizes the window..
        self.resize_value = (w, h)
        if not self.resize_timer:
            self.resize_timer = self.timeout_add(250, self.do_resize)

    def do_resize(self):
        self.resize_timer = None
        rw, rh = self.resize_value
        try:
            with xsync:
                ow, oh = RandR.get_screen_size()
            w, h = self.set_screen_size(rw, rh, False)
            if (ow, oh) == (w, h):
                #this is already the resolution we have,
                #but the client has other ideas,
                #so tell the client we ain't budging:
                for win in self._window_to_id.keys():
                    win.emit("resized")
        except Exception as e:
            geomlog("do_resize() %ix%i", rw, rh, exc_info=True)
            geomlog.error("Error: failed to resize desktop display to %ix%i:", rw, rh)
            geomlog.error(" %s", str(e) or type(e))


    def set_desktop_geometry_attributes(self, w, h):
        #geometry is not synced with the client's for desktop servers
        pass


    def get_server_mode(self):
        return "X11 desktop"

    def make_hello(self, source):
        capabilities = super().make_hello(source)
        if source.wants_features:
            capabilities.update({
                                 "pointer.grabs"    : True,
                                 "desktop"          : True,
                                 "multi-monitors"   : self.multi_monitors,
                                 "monitors"         : self.get_monitor_config(),
                                 "monitors.min-size" : MIN_SIZE,
                                 "monitors.max-size" : MAX_SIZE,
                                 })
            updict(capabilities, "window", {
                "decorations"            : True,
                "states"                 : ["iconified", "focused"],
                })
            capabilities["screen_sizes"] = get_screen_sizes()
        return capabilities


    def load_existing_windows(self):
        if self.multi_monitors:
            with xlog:
                monitors = RandR.get_monitor_properties()
                for i, monitor in monitors.items():
                    self.add_monitor_model(i+1, monitor)
                return
        #legacy mode: just a single window
        with xsync:
            model = ScreenDesktopModel(self.randr_exact_size)
            model.setup()
            screenlog("adding root window model %s", model)
            super().do_add_new_window_common(1, model)
            model.managed_connect("client-contents-changed", self._contents_changed)
            model.managed_connect("resized", self.send_updated_screen_size)

    def send_updated_screen_size(self, model):
        #the vfb has been resized
        wid = self._window_to_id[model]
        x, y, w, h = model.get_geometry()
        geomlog("send_updated_screen_size(%s) geometry=%s", model, (x, y, w, h))
        for ss in self.window_sources():
            ss.resize_window(wid, model, w, h)
            ss.damage(wid, model, 0, 0, w, h)


    def add_monitor_model(self, wid, monitor):
        model = MonitorDesktopModel(monitor)
        model.setup()
        screenlog("adding monitor model %s", model)
        super().do_add_new_window_common(wid, model)
        model.managed_connect("client-contents-changed", self._contents_changed)
        model.managed_connect("resized", self.monitor_resized)
        return model

    def monitor_resized(self, model):
        delta_x, delta_y = model.resize_delta
        rwid = self._window_to_id[model]
        screenlog("monitor_resized(%s) delta=%s, wid=%i", model, (delta_x, delta_y), rwid)
        #we adjust the position of monitors after this one,
        #assuming that they are defined left to right!
        #first the models:
        self._adjust_monitors(rwid, delta_x, delta_y)
        self.reconfigure_monitors()

    def reconfigure_monitors(self):
        #now we can do the virtual crtcs, outputs and monitors
        defs = self.get_monitor_config()
        screenlog("reconfigure_monitors() definitions=%s", defs)
        self.apply_monitor_config(defs)
        #and tell the client:
        self.setting_changed("monitors", defs)

    def validate_monitors(self):
        for model in self._id_to_window.values():
            x, y, width, height = model.get_geometry()
            if x+width>=MAX_SIZE[0] or y+height>=MAX_SIZE[1]:
                new_x, new_y = 0, 0
                mdef = model.get_definition()
                mdef.update({
                    "x"         : new_x,
                    "y"         : new_y,
                    })
                model.init(mdef)

    def _adjust_monitors(self, after_wid, delta_x, delta_y):
        models = dict((wid, model) for wid, model in self._id_to_window.items() if wid>after_wid)
        screenlog("adjust_monitors(%i, %i, %i) models=%s", after_wid, delta_x, delta_y, models)
        if (delta_x==0 and delta_y==0) or not models:
            return
        for wid, model in models.items():
            self._adjust_monitor(model, delta_x, delta_y)

    def _adjust_monitor(self, model, delta_x, delta_y):
        screenlog("adjust_monitors(%s, %i, %i)", model, delta_x, delta_y)
        if (delta_x==0 and delta_y==0):
            return
        x, y = model.get_geometry()[:2]
        new_x = max(0, x+delta_x)
        new_y = max(0, y+delta_y)
        if new_x!=x or new_y!=y:
            screenlog("adjusting monitor %s from %s to %s",
                      model, (x, y), (new_x, new_y))
            mdef = model.get_definition()
            mdef.update({
                "x"         : new_x,
                "y"         : new_y,
                })
            model.init(mdef)

    def get_monitor_config(self):
        monitor_defs = {}
        for wid, model in self._id_to_window.items():
            monitor = model.get_definition()
            i = wid-1
            monitor["index"] = i
            monitor_defs[i] = monitor
        return monitor_defs

    def apply_monitor_config(self, monitor_defs):
        with xsync:
            RandR.set_crtc_config(monitor_defs)

    def _process_configure_monitor(self, proto, packet):
        assert self.multi_monitors, "received a 'configure-monitor' packet but the feature is not enabled!"
        action = packet[1]
        if action=="remove":
            identifier = packet[2]
            value = packet[3]
            if identifier=="wid":
                wid = value
            elif identifier=="index":
                #index is zero-based
                wid = value+1
            else:
                raise ValueError("unsupported monitor identifier %r" % identifier)
            model = self._id_to_window.get(wid)
            screenlog("removing %s %i : %s", identifier, value, model)
            assert model, "monitor %r not found" % wid
            assert len(self._id_to_window)>1, "cannot remove the last monitor"
            delta_x = -model.get_definition().get("width", 0)
            delta_y = 0 #model.monitor.get("width", 0)
            model.unmanage()
            rwid = self._remove_window(model)
            #adjust the position of the other monitors:
            self._adjust_monitors(rwid, delta_x, delta_y)
            self.reconfigure_monitors()
            return
        if action=="add":
            assert len(self._id_to_window)<16, "already too many monitors: %i" % len(self._id_to_window)
            resolution = packet[2]
            if isinstance(resolution, str):
                resolution = parse_resolution(resolution)
            assert isinstance(resolution, (tuple, list)) and len(resolution)==2
            width, height = resolution
            assert isinstance(width, int) and isinstance(height, int)
            assert (width, height)>=MIN_SIZE and (width, height)<=MAX_SIZE
            #find the wid to use:
            #prefer just incrementing the wid, but we cannot go higher than 16
            def rightof(wid):
                mdef = self._id_to_window[wid].get_definition()
                x = mdef.get("x", 0)+mdef.get("width", 0)
                y = mdef.get("y", 0) #+monitor.get("height", 0)
                return x, y
            wid = self._max_window_id
            x = y = 0
            if wid<16:
                #since we're just appending,
                #just place to the right of the last monitor:
                last = max(self._id_to_window)
                x, y = rightof(last)
            else:
                #find a gap we can use in the window ids before 16:
                prev = None
                for wid in range(16):
                    if wid not in self._id_to_window:
                        break
                    prev = wid
                assert wid<=16
                if prev:
                    x, y = rightof(prev)
                self._adjust_monitors(wid-1, width, 0)
            #ensure no monitors end up too far to the right or bottom:
            #(better have them overlap - though we could do something smarter here)
            self.validate_monitors()
            #now we can add our new monitor:
            xdpi = self.xdpi or self.dpi or 96
            ydpi = self.ydpi or self.dpi or 96
            wmm = round(width * 25.4 / xdpi)
            hmm = round(height * 25.4 / ydpi)
            index = wid-1
            monitor = {
                "index"     : index,
                "name"      : "VFB-%i" % index,
                "x"         : x,
                "y"         : y,
                "width"     : width,
                "height"    : height,
                "mm-width"  : wmm,
                "mm-height" : hmm,
                }
            with xsync:
                model = self.add_monitor_model(wid, monitor)
            self.reconfigure_monitors()
            #send it to the clients:
            for ss in self._server_sources.values():
                if not isinstance(ss, WindowsMixin):
                    continue
                self.send_new_monitor(model, ss)
            self.refresh_all_windows()
            return
        raise ValueError("unsupported 'configure-monitor' action %r" % action)


    def send_initial_windows(self, ss, sharing=False):
        windowlog("send_initial_windows(%s, %s) will send: %s", ss, sharing, self._id_to_window)
        for model in self._id_to_window.values():
            self.send_new_monitor(model, ss, sharing)

    def send_new_monitor(self, model, ss, sharing=False):
        x, y, w, h = model.get_geometry()
        wid = self._window_to_id[model]
        wprops = self.client_properties.get(wid, {}).get(ss.uuid)
        ss.new_window("new-window", wid, model, x, y, w, h, wprops)
        wid = self._window_to_id[model]
        ss.damage(wid, model, 0, 0, w, h)


    def _lost_window(self, window, wm_exiting=False):
        pass

    def _contents_changed(self, window, event):
        log("contents changed on %s: %s", window, event)
        self.refresh_window_area(window, event.x, event.y, event.width, event.height)


    def _set_window_state(self, proto, wid, window, new_window_state):
        if not new_window_state:
            return []
        metadatalog("set_window_state%s", (proto, wid, window, new_window_state))
        changes = []
        #boolean: but not a wm_state and renamed in the model... (iconic vs iconified!)
        iconified = new_window_state.get("iconified")
        if iconified is not None:
            if window._updateprop("iconic", iconified):
                changes.append("iconified")
        focused = new_window_state.get("focused")
        if focused is not None:
            if window._updateprop("focused", focused):
                changes.append("focused")
        return changes


    def get_window_position(self, _window):
        #we export the whole desktop as a window:
        return 0, 0


    def _process_map_window(self, proto, packet):
        wid, x, y, w, h = packet[1:6]
        window = self._id_to_window.get(wid)
        if not window:
            windowlog("cannot map window %s: already removed!", wid)
            return
        geomlog("client mapped window %s - %s, at: %s", wid, window, (x, y, w, h))
        self._window_mapped_at(proto, wid, window, (x, y, w, h))
        if len(packet)>=8:
            self._set_window_state(proto, wid, window, packet[7])
        if len(packet)>=7:
            self._set_client_properties(proto, wid, window, packet[6])
        self.refresh_window_area(window, 0, 0, w, h)


    def _process_unmap_window(self, proto, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if not window:
            log("cannot map window %s: already removed!", wid)
            return
        if len(packet)>=4:
            #optional window_state added in 0.15 to update flags
            #during iconification events:
            self._set_window_state(proto, wid, window, packet[3])
        assert not window.is_OR()
        self._window_mapped_at(proto, wid, window)
        #TODO: handle inconification?
        #iconified = len(packet)>=3 and bool(packet[2])


    def _process_configure_window(self, proto, packet):
        wid, x, y, w, h = packet[1:6]
        if len(packet)>=13 and server_features.input_devices and not self.readonly:
            pwid = packet[10]
            pointer = packet[11]
            modifiers = packet[12]
            if self._process_mouse_common(proto, pwid, pointer):
                self._update_modifiers(proto, wid, modifiers)
        #some "configure-window" packets are only meant for metadata updates:
        skip_geometry = len(packet)>=10 and packet[9]
        window = self._id_to_window.get(wid)
        if not window:
            geomlog("cannot map window %s: already removed!", wid)
            return
        damage = False
        if len(packet)>=9:
            damage = bool(self._set_window_state(proto, wid, window, packet[8]))
        if not skip_geometry and not self.readonly:
            owx, owy, oww, owh = window.get_geometry()
            geomlog("_process_configure_window(%s) old window geometry: %s", packet[1:], (owx, owy, oww, owh))
            if oww!=w or owh!=h:
                window.resize(w, h)
        if len(packet)>=7:
            cprops = packet[6]
            if cprops:
                metadatalog("window client properties updates: %s", cprops)
                self._set_client_properties(proto, wid, window, cprops)
        self._window_mapped_at(proto, wid, window, (x, y, w, h))
        if damage:
            self.refresh_window_area(window, 0, 0, w, h)


    def _adjust_pointer(self, proto, wid, pointer):
        window = self._id_to_window.get(wid)
        if not window:
            self.suspend_cursor(proto)
            return None
        pointer = super()._adjust_pointer(proto, wid, pointer)
        #maybe the pointer is off-screen:
        ww, wh = window.get_dimensions()
        x, y = pointer[:2]
        if x<0 or x>=ww or y<0 or y>=wh:
            self.suspend_cursor(proto)
            return None
        self.restore_cursor(proto)
        return pointer

    def _move_pointer(self, wid, pos, *args):
        if wid>=0:
            window = self._id_to_window.get(wid)
            if not window:
                mouselog("_move_pointer(%s, %s) invalid window id", wid, pos)
                return
        with xsync:
            X11ServerBase._move_pointer(self, wid, pos, -1, *args)


    def _process_close_window(self, proto, packet):
        #disconnect?
        pass


    def _process_desktop_size(self, proto, packet):
        pass
    def calculate_workarea(self, w, h):
        pass


    def make_dbus_server(self):
        from xpra.x11.dbus.x11_dbus_server import X11_DBUS_Server
        self.dbus_server = X11_DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))


    def show_all_windows(self):
        log.warn("Warning: show_all_windows not implemented for desktop server")


    def do_make_screenshot_packet(self):
        log("grabbing screenshot")
        regions = []
        offset_x, offset_y = 0, 0
        for wid in reversed(sorted(self._id_to_window.keys())):
            window = self._id_to_window.get(wid)
            log("screenshot: window(%s)=%s", wid, window)
            if window is None:
                continue
            if not window.is_managed():
                log("screenshot: window %s is not/no longer managed", wid)
                continue
            x, y, w, h = window.get_geometry()
            log("screenshot: geometry(%s)=%s", window, (x, y, w, h))
            try:
                with xsync:
                    img = window.get_image(0, 0, w, h)
            except Exception:
                log.warn("screenshot: window %s could not be captured", wid)
                continue
            if img is None:
                log.warn("screenshot: no pixels for window %s", wid)
                continue
            log("screenshot: image=%s, size=%s", img, img.get_size())
            if img.get_pixel_format() not in ("RGB", "RGBA", "XRGB", "BGRX", "ARGB", "BGRA"):
                log.warn("window pixels for window %s using an unexpected rgb format: %s", wid, img.get_pixel_format())
                continue
            regions.append((wid, offset_x+x, offset_y+y, img))
            #tile them horizontally:
            offset_x += w
            offset_y += 0
        return self.make_screenshot_packet_from_regions(regions)


    def init_packet_handlers(self):
        super().init_packet_handlers()
        self.add_packet_handlers({
            "configure-monitor"       : self._process_configure_monitor,
            })

GObject.type_register(XpraDesktopServer)
